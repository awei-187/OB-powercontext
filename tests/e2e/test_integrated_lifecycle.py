"""Source lifecycle changes preserve count cursors and exact evidence deltas on restart."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from powercontext.artifacts import ArtifactRef, MemoryCitation
from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.records import ArtifactWrite
from powercontext.builtin.runtime import (
    GetMemoryEntryRequest,
    PrepareContextRequest,
    RememberMemoryRequest,
    SearchMemoryRequest,
    SearchTopicMemoryRequest,
    SubmitSourceObservation,
    open_builtin_runtime,
)
from powercontext.builtin.runtime.context_pack import ContextPack
from powercontext.builtin.runtime.processing_discovery import source_count_scopes
from powercontext.builtin.runtime.source_lifecycle import SourceLifecycleError, SourceLifecycleEvent
from powercontext.sources import (
    SourceDefinitionRegistry,
    SourceRef,
    manifest_for_definition,
    project_source_for_transport,
)
from powercontext.sources.csv_rows import CSV_ROW_SOURCE_DEFINITION, CSVDocumentInput, parse_csv_document
from powercontext.sources.pi_session import PI_EVENT_SOURCE_DEFINITION
from tests.e2e.test_integrated_count_sources import binding, checks, generation, settings
from tests.e2e.test_integrated_evidence_delta import delivery
from tests.e2e.test_integrated_features import run_connector, write_session

TEXT = ("Sapphire exact original evidence 雪. " * 6).strip()


async def row(runtime, registry, scope, key="1"):
    value = parse_csv_document(
        CSVDocumentInput(
            document_id="lifecycle", primary_key="id", content=f"id,text\n{key},CountEvidence sapphire\n".encode()
        )
    )[0]
    observation = project_source_for_transport(registry, await registry.resolve(value))
    return (await runtime.ingestion.submit(SubmitSourceObservation(scope_id=scope, observation=observation))).source_ref


async def seed(runtime, registry, directory, state, family):
    for label in ("alpha", "beta"):
        scope = await checks.scope(runtime, label)
        csv = await row(runtime, registry, scope)
        path = directory / f"{label}.jsonl"
        write_session(path, "sapphire")
        result = await run_connector(runtime, registry, binding(scope), path)
        pi_refs = [item.source_ref for item in result.items]
        assert len(pi_refs) == 2 and all(ref is not None for ref in pi_refs)
        expected = {checks.ref_key(ref) for ref in (csv, *pi_refs)}
        await checks.wait_refs(runtime, scope, family, expected)
        await checks.stay_refs(runtime, scope, family, expected)
        assert generation(directory, scope, family) == (1, 1)
        lc = runtime.lifecycle.for_scope(scope)
        assert pi_refs[0] is not None
        await lc.register_source("csv", csv, revision=1)
        await lc.register_source("pi", pi_refs[0], revision=1)
        memory = await runtime.memory.for_scope(scope).remember(
            RememberMemoryRequest(entries=(MemoryEntryInput(kind="fact", text=TEXT),))
        )
        assert memory.entry is not None
        citation = memory.entry.citation
        await lc.register_memory("csv-memory", citation, parents=("csv",), policy="all")
        await lc.register_memory("pi-memory", citation, parents=("pi",), policy="any")
        saved = await runtime.records.for_scope(scope).create_artifact(
            "topic-memory",
            ArtifactWrite(content={"title": "sapphire topic", "summary": "sapphire", "detail": "sapphire detail"}),
        )
        topic = ArtifactRef(family="topic-memory", artifact_id=saved.artifact_id, revision=saved.revision)
        await lc.register_topic("csv-topic", topic, parents=("csv-memory",), policy="all")
        # Manual writes contribute server-owned lineage in addition to the three worker-produced references.
        manual_sources = memory.entry.entry.sources if family == "memory" else saved.sources
        expected |= {checks.ref_key(ref) for ref in manual_sources}
        assert await checks.source_refs(runtime, scope, family) == expected
        state[label] = {
            "scope": scope,
            "csv": csv.model_dump(mode="json"),
            "citation": citation.model_dump(mode="json"),
            "topic": topic.model_dump(mode="json"),
            "native_refs": list(expected),
        }
        await visibility(runtime, directory, label, state[label], memory_visible=True, topic_visible=True)


async def visibility(runtime, directory, label, state, *, memory_visible, topic_visible):
    scope = state["scope"]
    citation = MemoryCitation.model_validate(state["citation"])
    found = await runtime.memory.for_scope(scope).search(SearchMemoryRequest(query="sapphire", mode="fts"))
    assert any(hit.entry_id == citation.entry_id for hit in found.hits) == memory_visible
    topics = await runtime.topic_memory.for_scope(scope).search(SearchTopicMemoryRequest(query="sapphire"))
    assert any(hit.artifact_ref.artifact_id == state["topic"]["artifact_id"] for hit in topics.hits) == topic_visible
    request = PrepareContextRequest(query="sapphire", evidence_selection=True, max_bytes=1800)
    path = directory / f"{label}.pack"
    base = ContextPack.from_bytes(path.read_bytes()) if path.exists() else None
    rebuilt, fragments = await delivery(runtime, scope, request, base, {scope})
    assert any(fragment["citation"]["entry_id"] == citation.entry_id for fragment in fragments) == memory_visible
    path.write_bytes(rebuilt.to_bytes())
    historical = await runtime.memory.for_scope(scope).get(GetMemoryEntryRequest(citation=citation))
    assert historical.entry.text == TEXT


async def counts(runtime, directory, state, family, pending):
    for label, item in state.items():
        scope = item["scope"]
        async with runtime._context(scope) as context:
            # Manual remember captures one additional content Source after the worker's cursor at three.
            assert len(await context.sources.journal.entries()) == 4 + (pending if label == "alpha" else 0)
        async with runtime.lifecycle.contexts.database.transaction() as connection:
            for threshold in (1, 3):
                eligible = await source_count_scopes(
                    connection, (scope,), binding_name=family + "-source-window", threshold=threshold
                )
                unconsumed = 1 + (pending if label == "alpha" else 0)
                assert bool(eligible) == (unconsumed >= threshold)
        assert generation(directory, scope, family) == (1, 1)


async def transitions(runtime, registry, directory, state, family, phase):
    scope = state["alpha"]["scope"]
    lc = runtime.lifecycle.for_scope(scope)
    for label, item in state.items():
        assert await row(runtime, registry, item["scope"]) == SourceRef.model_validate(item["csv"])
        assert (
            await run_connector(runtime, registry, binding(item["scope"]), directory / f"{label}.jsonl")
        ).items == ()
    await counts(runtime, directory, state, family, 0)
    restore = phase == "restore"
    order = ("pi", "csv") if restore else ("csv", "pi")
    for index, node in enumerate(order):
        event = SourceLifecycleEvent(
            node_id=node, revision=1, sequence=2 if restore else 1, available=restore, reason=phase
        )
        available = await lc.apply(event)
        head = (await runtime.memory.for_scope(scope).list(include_inactive=True)).memory_ref
        assert await lc.apply(event) == available
        assert (await runtime.memory.for_scope(scope).list(include_inactive=True)).memory_ref == head
        visible = restore or index == 0
        await visibility(
            runtime, directory, "alpha", state["alpha"], memory_visible=visible, topic_visible=restore and index == 1
        )
        await visibility(runtime, directory, "beta", state["beta"], memory_visible=True, topic_visible=True)
        await counts(runtime, directory, state, family, 0)
        if not restore or index == 0:
            with pytest.raises(SourceLifecycleError):
                await lc.resolve("csv-memory", purpose="generation")
        assert await lc.resolve("csv-memory", purpose="audit") == MemoryCitation.model_validate(
            state["alpha"]["citation"]
        )
    if restore:
        await row(runtime, registry, scope, "2")
        await checks.stay_refs(runtime, scope, family, {tuple(ref) for ref in state["alpha"]["native_refs"]})
        await counts(runtime, directory, state, family, 1)


async def worker(directory, family, phase, port):
    path = directory / "lifecycle-state.json"
    state = {} if phase == "seed" else json.loads(path.read_text(encoding="utf-8"))
    registry = SourceDefinitionRegistry((CSV_ROW_SOURCE_DEFINITION, PI_EVENT_SOURCE_DEFINITION))
    async with open_builtin_runtime(settings(directory, family, port)) as runtime:
        for definition in (CSV_ROW_SOURCE_DEFINITION, PI_EVENT_SOURCE_DEFINITION):
            await runtime.ingestion.register(manifest_for_definition(definition))
        if phase == "seed":
            await seed(runtime, registry, directory, state, family)
        else:
            await transitions(runtime, registry, directory, state, family, phase)
    path.write_text(json.dumps(state), encoding="utf-8")


@pytest.mark.parametrize("family", ["memory", "topic-memory"])
def test_lifecycle_preserves_native_count_and_selected_evidence_delta_after_restart(tmp_path, monkeypatch, family):
    with checks.provider(monkeypatch) as server:
        for phase in ("seed", "withdraw", "restore"):
            result = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), str(tmp_path), family, phase, str(server.server_port)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=180,
                check=False,
            )
            assert result.returncode == 0, result.stdout + result.stderr


if __name__ == "__main__":
    asyncio.run(worker(Path(sys.argv[1]), sys.argv[2], sys.argv[3], int(sys.argv[4])))
