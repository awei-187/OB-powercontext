# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

"""Real PDF candidate competition, document discrimination and restart regression."""

import asyncio
import json
import time
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
from tests.pdf_fixtures import pdf_bytes


async def _ingest(directory):
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{directory / 'competition.db'}"))
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    corpora = []
    async with open_builtin_runtime(config, candidate_pipeline=PagePipeline()) as runtime:
        assert runtime.scopes is not None
        await runtime.ingestion.register(manifest_for_definition(PDF_PAGE_SOURCE_DEFINITION))
        for variant in range(2):
            scope = await runtime.scopes.create(
                ScopeDraft(title="Multiple PDFs", summary="Candidate competition", idempotency_key=str(variant))
            )
            captured, targets = {}, {}
            for company, position in [("Amber Meridian", 17), ("Violet Harbor", 93)]:
                if variant:
                    position = 121 - position
                label = company.upper().replace(" ", "_") + "_2034_10K"
                texts = ["Annual operating narrative. Internal controls have been assessed."] * 120
                # The cover names the issuer; the target page only has its captured
                # document ID. Native analysis keeps that ID as one underscore token.
                texts[0] = company + "\nAnnual report 2034"
                texts[position - 1] = (
                    "Inventories\nRaw materials 821\nWork-in-process 146\nFinished goods 593\nTotal 1560\n"
                    + "Operational policies follow established accounting practice. " * 60
                )
                targets[company] = (label, position)
                raw = pdf_bytes(*texts)
                (directory / f"{label}-{variant}.pdf").write_bytes(raw)
                for page in parse_pdf_document(PDFDocumentInput(document_id=label, content=raw)):
                    observation = project_source_for_transport(registry, await registry.resolve(page))
                    captured[observation.name] = page
                    await runtime.ingestion.submit(
                        SubmitSourceObservation(scope_id=scope.scope_id, observation=observation)
                    )
            for company in ("Silver", "Copper", "Bronze"):
                raw = pdf_bytes(*[
                    f"{company} inventories by category {number}\n"
                    "Raw materials 91\nWork-in-process 23\nFinished goods 45"
                    for number in range(40)
                ])
                for page in parse_pdf_document(PDFDocumentInput(document_id=f"{company}_2034_10K", content=raw)):
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
                pytest.fail("native ingestion failed to drain")
            corpora.append((scope.scope_id, captured, targets))
    return config, corpora, directory


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    return asyncio.run(_ingest(tmp_path_factory.mktemp("multiple-reports")))


class TraceMemory:
    def __init__(self, memory):
        self.memory = memory
        self.calls = []

    async def search(self, request):
        result = await self.memory.search(request)
        self.calls.append({"query": request.query, "limit": request.limit, "hits": len(result.hits)})
        return result

    async def get(self, request):
        return await self.memory.get(request)


@pytest.mark.parametrize("variant", [0, 1])
@pytest.mark.parametrize("companies", [("Amber Meridian",), ("Violet Harbor",), ("Amber Meridian", "Violet Harbor")])
def test_named_reports_survive_competing_short_tables(corpus, variant, companies):
    async def check():
        config, corpora, directory = corpus
        scope_id, captured, targets = corpora[variant]
        question = (
            f"For {' and '.join(companies)}, show inventories by category, including raw materials and finished goods."
        )
        async with open_builtin_runtime(config) as runtime:
            memory = TraceMemory(runtime.memory.for_scope(scope_id))
            start = time.perf_counter()
            citations = await search_pdf_pages(cast(ScopedMemoryApplication, memory), question, limit=20)
            locations = []
            for citation in citations:
                entry = (await memory.get(GetMemoryEntryRequest(citation=citation))).entry
                assert len(entry.sources) == 1
                page = captured[entry.sources[0].source_id]
                assert entry.text == f"{page.document_id}\n{page.text}".strip()
                locations.append((page.document_id, page.page_number))
            assert 0 < len(locations) == len(set(locations)) <= 20
            assert all(targets[company] in locations for company in companies)
            assert {label for label, _ in locations} <= {targets[company][0] for company in companies}
            assert len(memory.calls) <= 24
            assert max(call["limit"] for call in memory.calls) <= 512
            assert sum(call["limit"] for call in memory.calls) <= 24 * 80
            with (directory / "queries.jsonl").open("a", encoding="utf-8") as output:
                output.write(
                    json.dumps({
                        "question": question,
                        "variant": variant,
                        "locations": locations,
                        "calls": memory.calls,
                        "seconds": time.perf_counter() - start,
                    })
                    + "\n"
                )

    asyncio.run(check())


@pytest.mark.parametrize("question", ["Show inventories by category.", "For annual report 2034, show raw materials."])
def test_generic_words_do_not_select_an_issuer(corpus, question):
    async def check():
        config, corpora, _ = corpus
        scope_id, captured, _ = corpora[0]
        async with open_builtin_runtime(config) as runtime:
            memory = runtime.memory.for_scope(scope_id)
            citations = await search_pdf_pages(memory, question, limit=20)
            labels = set()
            for citation in citations:
                entry = (await memory.get(GetMemoryEntryRequest(citation=citation))).entry
                labels.add(captured[entry.sources[0].source_id].document_id)
            assert len(labels) > 1

    asyncio.run(check())
