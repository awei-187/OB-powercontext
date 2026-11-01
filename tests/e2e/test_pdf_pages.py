# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

"""Actual PDF ingestion, SQLite restart, scoped retrieval and historical citation readback."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import cast

from powercontext.artifacts import MemoryCitation
from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    GetMemoryEntryRequest,
    RememberMemoryRequest,
    SubmitSourceObservation,
    open_builtin_contexts,
    open_builtin_runtime,
)
from powercontext.builtin.scope import ScopeDraft
from powercontext.sources import (
    SourceDefinitionRegistry,
    SourceObservation,
    manifest_for_definition,
    project_source_for_transport,
)
from powercontext.sources.pdf_pages import (
    PDF_PAGE_SOURCE_DEFINITION,
    PDFDocumentInput,
    parse_pdf_document,
    search_pdf_pages,
)
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY
from tests.pdf_fixtures import pdf_bytes


class PagePipeline:
    async def extract(self, request, /):
        return tuple(
            MemoryEntryInput(
                kind="source-evidence",
                text=source.projection(TEXT_EVIDENCE_PROJECTION_KEY)["content"],
                sources=(source,),
            )
            for source in request.sources
        )


async def ingest(directory: Path, config: BuiltinConfig) -> None:
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    expected = []
    async with open_builtin_runtime(config) as runtime:
        assert runtime.scopes is not None
        await runtime.ingestion.register(manifest_for_definition(PDF_PAGE_SOURCE_DEFINITION))
        for index in range(2):
            scope = await runtime.scopes.create(ScopeDraft(title="PDFs", summary="Pages", idempotency_key=str(index)))
            pages = parse_pdf_document(
                PDFDocumentInput(document_id="annual-report", content=(directory / f"{index}.pdf").read_bytes())
            )
            observations = [project_source_for_transport(registry, await registry.resolve(page)) for page in pages]
            for observation in [*observations, *reversed(observations)]:
                await runtime.ingestion.submit(
                    SubmitSourceObservation(scope_id=scope.scope_id, observation=observation)
                )
            expected.append({
                "scope_id": scope.scope_id,
                "pages": {
                    observation.name: observation.projection(TEXT_EVIDENCE_PROJECTION_KEY)
                    for observation in observations
                },
            })
    (directory / "expected.json").write_text(json.dumps(expected), encoding="utf-8")


async def retrieve(directory: Path, config: BuiltinConfig) -> None:
    expected = json.loads((directory / "expected.json").read_text(encoding="utf-8"))
    async with open_builtin_contexts(config) as contexts:
        for scope in expected:
            journal = await (await contexts.get(scope["scope_id"])).sources.journal.entries()
            assert len(journal) == len(scope["pages"])
            assert {
                item.source.name: cast(SourceObservation, item.source).projection(TEXT_EVIDENCE_PROJECTION_KEY)
                for item in journal
            } == scope["pages"]
    saved = []
    async with open_builtin_runtime(config, candidate_pipeline=PagePipeline()) as runtime:
        for index, scope in enumerate(expected):
            memory = runtime.memory.for_scope(scope["scope_id"])
            for _ in range(10):
                if not (await memory.flush()).processed:
                    break
            else:
                raise AssertionError("PDF processing did not drain")  # noqa: TRY003
            # A highly relevant Memory without a PDF source is not a page citation.
            await memory.remember(
                RememberMemoryRequest(entries=(MemoryEntryInput(kind="note", text="quartz revenue 999999"),))
            )
            own, other = ("quartz", "sapphire") if index == 0 else ("sapphire", "quartz")
            assert await search_pdf_pages(memory, other, 20) == ()
            citations = await search_pdf_pages(memory, own, 20)
            assert len(citations) == 2  # equal text on separate physical pages is distinct evidence
            assert len(await search_pdf_pages(memory, own, 1)) == 1
            assert await search_pdf_pages(memory, own, 0) == ()
            assert await search_pdf_pages(memory, "unfindableterm", 20) == ()
            locations = set()
            for citation in citations:
                entry = (await memory.get(GetMemoryEntryRequest(citation=citation))).entry
                assert len(entry.sources) == 1 and entry.sources[0].source_type == "pdf-page"
                evidence = scope["pages"][entry.sources[0].source_id]
                assert entry.text == evidence["content"].strip()
                locations.add(evidence["metadata"]["page_number"])
                saved.append({
                    "scope_id": scope["scope_id"],
                    "citation": citation.model_dump(mode="json"),
                    "text": entry.text,
                })
            assert locations == {1, 3}
            # Synonym retrieval must return the actual proceedings page, although
            # this question uses 'lawsuit' and the PDF uses 'litigation'.
            legal = await search_pdf_pages(memory, "What lawsuits are pending?", 3)
            assert legal
            legal_texts = [(await memory.get(GetMemoryEntryRequest(citation=c))).entry.text for c in legal]
            assert any("litigation" in text for text in legal_texts)
    (directory / "citations.json").write_text(json.dumps(saved), encoding="utf-8")


async def revise(directory: Path, config: BuiltinConfig) -> None:
    expected = json.loads((directory / "expected.json").read_text(encoding="utf-8"))
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    pages = parse_pdf_document(
        PDFDocumentInput(
            document_id="annual-report", content=pdf_bytes("quartz Revenue 777 revised", title="revision 2")
        )
    )
    async with open_builtin_runtime(config, candidate_pipeline=PagePipeline()) as runtime:
        for page in pages:
            await runtime.ingestion.submit(
                SubmitSourceObservation(
                    scope_id=expected[0]["scope_id"],
                    observation=project_source_for_transport(registry, await registry.resolve(page)),
                )
            )
        memory = runtime.memory.for_scope(expected[0]["scope_id"])
        assert (await memory.flush()).processed
        assert len(await search_pdf_pages(memory, "quartz", 20)) == 3


async def read_citations(directory: Path, config: BuiltinConfig) -> None:
    saved = json.loads((directory / "citations.json").read_text(encoding="utf-8"))
    async with open_builtin_runtime(config) as runtime:
        for item in saved:
            entry = await runtime.memory.for_scope(item["scope_id"]).get(
                GetMemoryEntryRequest(citation=MemoryCitation.model_validate(item["citation"]))
            )
            assert entry.entry.text == item["text"]


def test_real_pdfs_survive_process_restart_scope_switch_and_revision(tmp_path):
    for index, marker in enumerate(("quartz", "sapphire")):
        text = f"{marker} Revenue 1,234.50\nTable year 2024 2023\nCost (80) (90)"
        (tmp_path / f"{index}.pdf").write_bytes(
            pdf_bytes(text, "", text, "Legal proceedings\nPending litigation is material.")
        )
    for stage in ("ingest", "retrieve", "revise", "citations"):
        result = subprocess.run(
            [sys.executable, "-m", "tests.e2e.test_pdf_pages", stage, str(tmp_path)],
            cwd=Path(__file__).parents[2],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=90,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        if stage == "ingest":
            for index in range(2):
                (tmp_path / f"{index}.pdf").unlink()


async def test_financial_statement_pages_outrank_narrative_mentions(tmp_path):
    # The requested metric need not occur verbatim on its supporting statements.
    # These are real text streams parsed from PDF bytes, then persisted natively.
    texts = [
        f"Note {index}: financial policy\nOperating income and depreciation and amortization are discussed here.\n"
        "See the consolidated statement of cash flows and the income statement.\n"
        "Management considers EBITDA and capital expenditure trends."
        "\nConsolidated Statement of Income 12\nConsolidated Statement of Cash Flows - fiscal years"
        for index in range(30)
    ]
    texts.extend([
        "Consolidated Statement of Income\nNorthwind Inc.\nYear 2025 2024\n"
        "Net sales 1000 900\nOperating profit 250 200",
        "Consolidated Statement of Cash Flows\nNorthwind Inc.\nOperating Activities\n"
        "Depreciation 50 40\nAmortization 10 9",
    ])
    pages = parse_pdf_document(PDFDocumentInput(document_id="Northwind_2025", content=pdf_bytes(*texts)))
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'statements.db'}"))
    async with open_builtin_runtime(config, candidate_pipeline=PagePipeline()) as runtime:
        assert runtime.scopes is not None
        scope = await runtime.scopes.create(
            ScopeDraft(title="Financial report", summary="Pages", idempotency_key="report")
        )
        await runtime.ingestion.register(manifest_for_definition(PDF_PAGE_SOURCE_DEFINITION))
        locations = {}
        for page in pages:
            observation = project_source_for_transport(registry, await registry.resolve(page))
            locations[observation.name] = page.page_number
            await runtime.ingestion.submit(SubmitSourceObservation(scope_id=scope.scope_id, observation=observation))
        memory = runtime.memory.for_scope(scope.scope_id)
        for _ in range(len(pages) + 1):
            if not (await memory.flush()).processed:
                break
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope.scope_id)
        citations = await search_pdf_pages(
            memory, "What is Northwind's EBITDA from operating income and D&A in 2025?", 5
        )
        found = set()
        for citation in citations:
            entry = (await memory.get(GetMemoryEntryRequest(citation=citation))).entry
            found.add(locations[entry.sources[0].source_id])
        assert {31, 32} <= found


if __name__ == "__main__":
    directory = Path(sys.argv[2])
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{directory / 'pdf.db'}"))
    operation = {"ingest": ingest, "retrieve": retrieve, "revise": revise, "citations": read_citations}[sys.argv[1]]
    asyncio.run(operation(directory, config))
