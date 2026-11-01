# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

"""PDF evidence selection independent of physical order and heading word order."""

import asyncio
import json
from pathlib import Path

import pytest

from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    GetMemoryEntryRequest,
    SubmitSourceObservation,
    open_builtin_runtime,
)
from powercontext.builtin.scope import ScopeDraft
from powercontext.sources import SourceDefinitionRegistry, manifest_for_definition, project_source_for_transport
from powercontext.sources.pdf_pages import (
    PDF_PAGE_SOURCE_DEFINITION,
    PDFDocumentInput,
    parse_pdf_document,
    search_pdf_pages,
)
from tests.e2e.test_pdf_pages import PagePipeline
from tests.pdf_fixtures import pdf_bytes


async def _capture(directory, documents):
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{directory / 'reports.db'}"))
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    captured = {}
    async with open_builtin_runtime(config, candidate_pipeline=PagePipeline()) as runtime:
        assert runtime.scopes is not None
        scope = await runtime.scopes.create(ScopeDraft(title="Reports", summary="PDF pages", idempotency_key="reports"))
        await runtime.ingestion.register(manifest_for_definition(PDF_PAGE_SOURCE_DEFINITION))
        for name, texts in documents.items():
            raw = texts if isinstance(texts, bytes) else pdf_bytes(*texts)
            for page in parse_pdf_document(PDFDocumentInput(document_id=name, content=raw)):
                observation = project_source_for_transport(registry, await registry.resolve(page))
                captured[observation.name] = page
                await runtime.ingestion.submit(
                    SubmitSourceObservation(scope_id=scope.scope_id, observation=observation)
                )
        memory = runtime.memory.for_scope(scope.scope_id)
        for _ in range(len(captured) + 1):
            if not (await memory.flush()).processed:
                break
        else:
            pytest.fail("PDF ingestion did not drain")
    return config, scope.scope_id, captured


async def _locations(config, scope_id, captured, question, limit):
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope_id)
        citations = await search_pdf_pages(memory, question, limit)
        locations = []
        for citation in citations:
            entry = (await memory.get(GetMemoryEntryRequest(citation=citation))).entry
            assert len(entry.sources) == 1 and entry.sources[0].source_type == "pdf-page"
            page = captured[entry.sources[0].source_id]
            assert entry.text == f"{page.document_id}\n{page.text}".strip()
            locations.append((page.document_id, page.page_number))
        assert len(locations) == len(set(locations)) <= limit
        return locations


@pytest.mark.parametrize(
    ("heading", "topic"),
    [
        ("INCOME STATEMENTS", "income"),
        ("CASH FLOWS STATEMENTS", "cash flow"),
        ("CONDENSED CONSOLIDATED INCOME STATEMENTS", "income"),
        ("CONSOLIDATED CASH FLOW STATEMENTS", "cash flow"),
    ],
)
async def test_statement_titles_allow_subject_before_statement(tmp_path, heading, topic):
    narrative = (
        "Accounting policies\nNet income and cash flow figures for 2037 are discussed in the annual report.\n"
        "See the consolidated income statement and consolidated cash flow statement for complete figures."
    )
    texts = [narrative] * 35
    texts[18] = (
        f"{heading}\n(In millions)\nYear ended 2037 2036\nRevenue 1200 1100\nOperating income 300 280\n"
        "Depreciation 40 35\nAmortization 10 9\nCash from operations 350 324"
    )
    config, scope, captured = await _capture(tmp_path, {"JUNIPER_2037_10K": texts})
    found = await _locations(
        config, scope, captured, f"Find Juniper consolidated {topic} statement with the 2037 figures.", 5
    )
    assert ("JUNIPER_2037_10K", 19) in found


@pytest.mark.parametrize(("printed", "position"), [(37, 6), (108, 29), (204, 11)])
async def test_printed_footer_is_not_a_physical_page_offset(tmp_path, printed, position):
    texts = [
        f"Annual report 2037\nPrinted page references are listed in this table.\n"
        f"Production unit {printed} revenue 2300\nDetails of inventory accounting and annual reporting.\n{n + 1000}"
        for n in range(40)
    ]
    texts[position - 1] = (
        "Inventories\nRaw materials 817\nFinished goods 623\n"
        + "Operational policies follow established accounting practice. " * 50
        + f"\n{printed}"
    )
    config, scope, captured = await _capture(tmp_path, {"JUNIPER_2037_10K": texts})
    found = await _locations(
        config, scope, captured, f"What table appears on printed page {printed} of Juniper's 2037 annual report?", 1
    )
    assert found == [("JUNIPER_2037_10K", position)]


@pytest.mark.parametrize(
    ("question", "target"),
    [
        ("How much cash was returned to Juniper's stockholders?", 28),
        ("Show Juniper cash distributions to shareholders during 2037.", 28),
        ("What discretionary cash remained for Juniper after investment in fixed assets?", 29),
        ("Find Juniper operating cash less capital spending in 2037.", 29),
    ],
)
async def test_cash_payout_and_investment_paraphrases(tmp_path, question, target):
    texts = [
        f"Annual report 2037\nShareholders and stockholders met during the year.\n"
        f"Management discussed cash investment, fixed assets, capital spending and operating cash.\n"
        f"The discretionary program and returned payments were discussed in policy number {n}."
        for n in range(30)
    ]
    texts[27] = (
        "Consolidated Statement of Cash Flows (continued)\n2037 2036\nFinancing Activities\n"
        "Cash dividends paid 731 701\nRepurchases of common stock 422 388\nDebt repaid 104 97"
    )
    texts[28] = (
        "Free Cash Flow\n2037 2036\nNet cash provided by operating activities 4817 4412\n"
        "Capital expenditures (1203) (1094)\nProceeds from asset sales 94 87\nFree cash flow 3708 3405"
    )
    config, scope, captured = await _capture(tmp_path, {"JUNIPER_2037_10K": texts})
    found = await _locations(config, scope, captured, question, 5)
    assert ("JUNIPER_2037_10K", target) in found


async def test_a_topic_shaped_document_id_does_not_become_an_issuer_filter(tmp_path):
    config, scope, captured = await _capture(
        tmp_path,
        {
            "INVENTORY_2037": ["Inventory policy summary. The report does not contain category balances."],
            "JUNIPER_2037_10K": ["Inventories by category\nRaw materials 817\nWork in process 143\nFinished goods 623"],
        },
    )
    found = await _locations(
        config, scope, captured, "Show inventory by category including raw materials and finished goods.", 5
    )
    assert ("JUNIPER_2037_10K", 1) in found


async def test_long_multitopic_question_keeps_each_explicit_statement(tmp_path):
    texts = [
        f"Management discussion {n}\n"
        "The analyst defines unadjusted EBITDA as operating income plus depreciation and amortization. "
        "EBITDA less capex and EBITDA margin are discussed in USD millions. "
        "The figures should rely on the statement of cash flows and the income statement. "
        "Capital expenditure and operating income were evaluated from an investment perspective."
        for n in range(35)
    ]
    texts[12] = (
        "Consolidated Statement of Income\nJuniper\n2037 2036\nRevenue 5200 4900\n"
        "Cost of sales 2400 2300\nOperating profit 2800 2600\nNet income 1800 1700"
    )
    texts[26] = (
        "Consolidated Statement of Cash Flows\n2037 2036\nOperating activities\n"
        "Depreciation 200 180\nAmortization 50 40\nCapital spending (300) (250)"
    )
    config, scope, captured = await _capture(tmp_path, {"JUNIPER_2037_10K": texts})
    question = (
        "What is Juniper's unadjusted EBITDA less capex for 2037? Define EBITDA as operating income plus "
        "depreciation and amortization. Answer in USD millions using the perspective of an investment analyst "
        "and relying on the details shown in the statement of cash flows and the income statement."
    )
    found = await _locations(config, scope, captured, question, 20)
    assert {("JUNIPER_2037_10K", 13), ("JUNIPER_2037_10K", 27)} <= set(found)


@pytest.fixture(scope="module")
def public_statement_corpus(tmp_path_factory):
    public = Path(__file__).parents[2] / "competition/challenges/source-03-pdf-retrieval/workload/public"
    case = json.loads((public / "cases.json").read_text(encoding="utf-8"))["cases"][0]
    corpus = asyncio.run(
        _capture(
            tmp_path_factory.mktemp("original-public-questions"),
            {case["document_id"]: (public / case["file"]).read_bytes()},
        )
    )
    return corpus, case


@pytest.mark.parametrize("question_index", [3, 4])
async def test_original_long_public_questions_retain_both_statements(public_statement_corpus, question_index):
    (config, scope, captured), case = public_statement_corpus
    # These complete statement pages were read directly from the original PDF;
    # they are supporting sections, not FinanceBench annotated answer locations.
    sections = {62: "Operating Profit", 64: "Depreciation and amortization"}
    for number, phrase in sections.items():
        assert any(page.page_number == number and phrase in page.text for page in captured.values())
    found = await _locations(config, scope, captured, case["questions"][question_index]["question"], 20)
    assert {(case["document_id"], number) for number in sections} <= set(found)
