# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

"""Report-derived quality regressions, not FinanceBench gold or score estimates."""

import asyncio
import json
import time
from pathlib import Path
from typing import cast

import pytest

from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    GetMemoryEntryRequest,
    ScopedMemoryApplication,
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


async def _ingest(directory):
    pdf = (
        Path(__file__).parents[2]
        / "competition/challenges/source-03-pdf-retrieval/workload/public/pdfs/PEPSICO_2022_10K.pdf"
    )
    pages = parse_pdf_document(PDFDocumentInput(document_id="public-quality-report", content=pdf.read_bytes()))
    assert len(pages) == 503
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{directory / 'quality.db'}"))
    captured = {}
    async with open_builtin_runtime(config, candidate_pipeline=PagePipeline()) as runtime:
        assert runtime.scopes is not None
        scope = await runtime.scopes.create(
            ScopeDraft(title="Quality", summary="Real pages", idempotency_key="quality")
        )
        await runtime.ingestion.register(manifest_for_definition(PDF_PAGE_SOURCE_DEFINITION))
        for page in pages:
            observation = project_source_for_transport(registry, await registry.resolve(page))
            captured[observation.name] = page
            await runtime.ingestion.submit(SubmitSourceObservation(scope_id=scope.scope_id, observation=observation))
        memory = runtime.memory.for_scope(scope.scope_id)
        for _ in range(len(pages) + 1):
            if not (await memory.flush()).processed:
                break
        else:
            pytest.fail("native ingestion did not drain")
    return config, scope.scope_id, captured, directory


@pytest.fixture(scope="module")
def quality_corpus(tmp_path_factory):
    return asyncio.run(_ingest(tmp_path_factory.mktemp("real-report-quality")))


class TraceMemory:
    """Transparent observer; every result comes from actual scoped Memory."""

    def __init__(self, memory):
        self.memory = memory
        self.calls = []

    async def search(self, request):
        start = time.perf_counter()
        response = await self.memory.search(request)
        self.calls.append({"query": request.query, "hits": len(response.hits), "seconds": time.perf_counter() - start})
        return response

    async def get(self, request):
        return await self.memory.get(request)


# Expectations come from directly reading the original report. Unlike the
# independent review prompts, these use different phrasing and an unrelated
# document ID. Non-target accounting subjects guard against expansion spillover.
@pytest.mark.parametrize(
    ("question", "anchors"),
    [
        ("Show raw materials, work in process and finished goods in the inventory balance.", {110: "Finished goods"}),
        (
            "Which inventory balances were reported, and what proportion was valued on a LIFO basis?",
            {110: "Inventories", 111: "LIFO"},
        ),
        ("How much were gross earnings before selling and administrative expenses in 2022?", {62: "Gross profit"}),
        ("Where are 2022 revenue and COGS presented together?", {62: "Cost of sales"}),
        ("What closing allowance covers uncollectible receivables?", {110: "Allowance, end of year"}),
        (
            "Show the doubtful accounts reserve beginning balance and closing balance.",
            {110: "Allowance, beginning of year"},
        ),
        ("Compare current asset totals with current liability totals in 2022.", {66: "Total Current Assets"}),
        ("Compare current assets totals with current liabilities totals in 2022.", {66: "Total Current Assets"}),
        ("How large were short-term and long-term debt balances at year end?", {66: "Long-Term Debt Obligations"}),
        (
            "What is the average remaining lease term, and the lease payments due in 2023?",
            {106: "Weighted-average remaining lease term"},
        ),
        ("How much did the company contribute to its savings plan in 2022?", {97: "Savings Plan"}),
        (
            "What fraction of employees were female and what fraction of management roles were held by women?",
            {13: "44%"},
        ),
        (
            "How large was the Celsius investment and what annual preferred dividend does it earn?",
            {101: "Celsius", 102: "5% annual dividend"},
        ),
        (
            "Compare cash dividends declared and cash dividends paid for 2022.",
            {65: "Cash dividends paid", 67: "Cash dividends declared"},
        ),
        ("Did the juice transaction qualify as discontinued operations?", {107: "discontinued operations"}),
        (
            "How much was spent on capital assets and how is operating cash reconciled to free cash flow?",
            {54: "Free Cash Flow"},
        ),
    ],
)
async def test_real_report_financial_paraphrases(quality_corpus, question, anchors):
    config, scope_id, captured, directory = quality_corpus
    for number, phrase in anchors.items():
        assert any(page.page_number == number and phrase in page.text for page in captured.values())
    start = time.perf_counter()
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope_id)
        trace = TraceMemory(memory)
        citations = await search_pdf_pages(cast(ScopedMemoryApplication, trace), question, 20)
        found = []
        for citation in citations:
            entry = (await memory.get(GetMemoryEntryRequest(citation=citation))).entry
            assert len(entry.sources) == 1
            page = captured[entry.sources[0].source_id]
            assert entry.text == f"{page.document_id}\n{page.text}".strip()
            found.append(page.page_number)
    with (directory / "queries.jsonl").open("a", encoding="utf-8") as output:
        output.write(
            json.dumps({
                "question": question,
                "anchors": anchors,
                "returned": found,
                "seconds": time.perf_counter() - start,
                "search_calls": trace.calls,
            })
            + "\n"
        )
    assert len(found) == len(set(found)) <= 20
    assert set(anchors) <= set(found)
