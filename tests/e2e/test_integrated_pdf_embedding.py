"""Real PDF evidence survives selective embedding caching and scoped SQLite reopen."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

from powercontext.artifacts import MemoryCitation
from powercontext.builtin.artifacts.memory import EmbeddingProfile
from powercontext.builtin.inference import EmbeddingResult, InferenceUsage
from powercontext.builtin.inference.coalescing import CoalescingEmbeddingModel
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    GetMemoryEntryRequest,
    PrepareContextRequest,
    SubmitSourceObservation,
    open_builtin_runtime,
)
from powercontext.builtin.runtime.context_pack import ContextPack
from powercontext.builtin.scope import ScopeDraft
from powercontext.sources import SourceDefinitionRegistry, manifest_for_definition, project_source_for_transport
from powercontext.sources.observations import SourceObservation
from powercontext.sources.pdf_pages import (
    PDF_PAGE_SOURCE_DEFINITION,
    PDFDocumentInput,
    parse_pdf_document,
    search_pdf_pages,
)
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY
from tests.e2e.test_integrated_evidence_delta import delivery
from tests.e2e.test_pdf_pages import PagePipeline
from tests.pdf_fixtures import pdf_bytes


class Provider:
    profile = EmbeddingProfile(profile_id="pdf-integration", model="offline", dimension=2)

    def __init__(self):
        self.calls = []
        self.invalid = None

    async def embed(self, texts, /):
        self.calls.append(texts)
        first = len(self.calls) == 1
        return EmbeddingResult(
            vectors=tuple((0.0, 0.0) if first and text == self.invalid else (3.0, 4.0) for text in texts),
            usage=InferenceUsage(requests=4, input_tokens=17, output_tokens=2),
        )


async def seed(runtime, model, provider, directory):
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    await runtime.ingestion.register(manifest_for_definition(PDF_PAGE_SOURCE_DEFINITION))
    pages = parse_pdf_document(
        PDFDocumentInput(document_id="new-report", content=pdf_bytes("Quartz Revenue 184.75", "Quartz Costs 83.24"))
    )
    observations = [project_source_for_transport(registry, await registry.resolve(page)) for page in pages]
    contents = []
    for item in observations:
        projection = item.projection(TEXT_EVIDENCE_PROJECTION_KEY)
        assert isinstance(projection, dict) and isinstance(projection["content"], str)
        # Native Memory canonicalizes surrounding whitespace before embedding a candidate.
        contents.append(projection["content"].strip())
    texts = tuple(contents)
    provider.invalid = texts[1]
    primed = await model.embed(texts)
    assert primed.vectors == ((3.0, 4.0), (0.0, 0.0))
    assert primed.usage == InferenceUsage(requests=4, input_tokens=17, output_tokens=2)
    assert (await model.embed((texts[0],))).usage.requests == 0
    state = []
    for label in ("first", "second"):
        scope = (await runtime.scopes.create(ScopeDraft(title=label, summary=label, idempotency_key=label))).scope_id
        for observation in [*observations, *observations]:
            await runtime.ingestion.submit(SubmitSourceObservation(scope_id=scope, observation=observation))
        memory = runtime.memory.for_scope(scope)
        for _ in range(5):
            if not (await memory.flush()).processed:
                break
        else:
            raise AssertionError("PDF processing did not drain")  # noqa: TRY003
        citations = await search_pdf_pages(memory, "Quartz", 20)
        assert len(citations) == 2
        request = PrepareContextRequest(query="Quartz", max_bytes=4096, evidence_selection=True)
        pack, fragments = await delivery(runtime, scope, request, None, {scope})
        assert {item["citation"]["entry_id"] for item in fragments} == {c.entry_id for c in citations}
        (directory / f"{label}.pack").write_bytes(pack.to_bytes())
        state.append({"scope": scope, "label": label, "citations": [c.model_dump(mode="json") for c in citations]})
    # The bad member refreshes once; its valid neighbor is reusable in both scopes.
    assert provider.calls == [texts, (texts[1],), ("Quartz",)], provider.calls
    assert (await model.embed(texts)).usage.requests == 0
    return state


async def resume(runtime, provider, directory, state):
    for item in state:
        scope = item["scope"]
        memory = runtime.memory.for_scope(scope)
        actual = await search_pdf_pages(memory, "Quartz", 20)
        expected = tuple(MemoryCitation.model_validate(c) for c in item["citations"])
        assert {c.entry_id for c in actual} == {c.entry_id for c in expected}
        async with runtime._context(scope) as context:
            journal = await context.sources.journal.entries()
        assert len(journal) == 2
        observations = {item.source.name: item.source for item in journal}
        pages = set()
        for citation in expected:
            entry = (await memory.get(GetMemoryEntryRequest(citation=citation))).entry
            assert entry is not None and len(entry.sources) == 1
            source = observations[entry.sources[0].source_id]
            assert isinstance(source, SourceObservation)
            projection = source.projection(TEXT_EVIDENCE_PROJECTION_KEY)
            assert isinstance(projection, dict) and isinstance(projection["metadata"], dict)
            assert isinstance(projection["content"], str)
            assert entry.text == projection["content"].strip()
            assert projection["metadata"]["document_id"] == "new-report"
            pages.add(projection["metadata"]["page_number"])
        assert pages == {1, 2}
        old = ContextPack.from_bytes((directory / f"{item['label']}.pack").read_bytes())
        new, fragments = await delivery(
            runtime, scope, PrepareContextRequest(query="Quartz", max_bytes=4096, evidence_selection=True), old, {scope}
        )
        assert new == old and len(fragments) == 2
    # Preparing context embeds its query once after reopening; stored page vectors are reused.
    assert provider.calls == [("Quartz",)]
    assert {c["entry_id"] for c in state[0]["citations"]}.isdisjoint(c["entry_id"] for c in state[1]["citations"])


async def worker(directory, phase):
    provider = Provider()
    model = CoalescingEmbeddingModel(provider, coalesce_ms=0)
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{directory / 'pdf.db'}"))
    path = directory / "state.json"
    async with open_builtin_runtime(config, embedding_model=model, candidate_pipeline=PagePipeline()) as runtime:
        if phase == "seed":
            path.write_text(json.dumps(await seed(runtime, model, provider, directory)), encoding="utf-8")
        else:
            await resume(runtime, provider, directory, json.loads(path.read_text(encoding="utf-8")))


def test_pdf_cache_recovery_scope_and_exact_evidence_delta_survive_process_restart(tmp_path):
    for phase in ("seed", "resume"):
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), str(tmp_path), phase],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=90,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr


if __name__ == "__main__":
    asyncio.run(worker(Path(sys.argv[1]), sys.argv[2]))
