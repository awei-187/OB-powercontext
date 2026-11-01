"""Native count workers consume mixed CSV/Pi observations across OS restarts."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import subprocess
import sys
from importlib import import_module
from pathlib import Path

import pytest
from pydantic import AnyHttpUrl

from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    PrepareContextRequest,
    open_builtin_runtime,
)
from powercontext.builtin.runtime.config import InferenceConfig, RuntimeConfig
from powercontext.sources import ConnectorBinding, SourceDefinitionRegistry, SourceObservation, manifest_for_definition
from powercontext.sources.csv_rows import CSV_ROW_SOURCE_DEFINITION, CSVDocumentInput, CSVRowInput, parse_csv_document
from powercontext.sources.pi_session import PI_EVENT_SOURCE_DEFINITION, PiEventInput
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY
from tests.e2e.test_integrated_features import reconstruct, run_connector, write_session

checks = import_module("competition.challenges.processing-01-count-trigger.acceptance.checks")


def settings(directory: Path, family: str, port: int) -> BuiltinConfig:
    return BuiltinConfig(
        database=SQLiteConfig(url=f"sqlite+aiosqlite:///{directory / 'mixed.db'}"),
        inference=InferenceConfig(
            generation_model="openai-chat:gpt-4o-mini",
            generation_base_url=AnyHttpUrl(f"http://127.0.0.1:{port}/v1"),
            embedding_model="openai:count-test-embedding",
            embedding_base_url=AnyHttpUrl(f"http://127.0.0.1:{port}/v1"),
            embedding_dimension=2,
            embedding_profile_id="count-test",
        ),
        runtime=RuntimeConfig(
            artifact_processing_families=(family,),
            artifact_processing_worker_timeout_seconds=30,
            memory_worker_timeout_seconds=30,
            topic_memory_worker_timeout_seconds=30,
            memory_source_count_threshold=3 if family == "memory" else None,
            topic_memory_source_count_threshold=3 if family == "topic-memory" else None,
        ),
    )


def generation(directory, scope, family):
    with sqlite3.connect(directory / "mixed.db") as connection:
        return connection.execute(
            "SELECT requested_generation, handled_generation FROM pc_artifact_processing_intents "
            "WHERE scope_id=? AND binding_name=?",
            (scope, family + "-source-window"),
        ).fetchone()


async def submit_row(runtime, registry, scope, word, key="1"):
    from powercontext.builtin.runtime import SubmitSourceObservation
    from powercontext.sources import project_source_for_transport

    row = parse_csv_document(
        CSVDocumentInput(
            document_id="shared", primary_key="id", content=f"id,z,a\n{key},CountEvidence {word},001\n".encode()
        )
    )[0]
    observation = project_source_for_transport(registry, await registry.resolve(row))
    first = await runtime.ingestion.submit(SubmitSourceObservation(scope_id=scope, observation=observation))
    for _ in range(3):
        repeated = await runtime.ingestion.submit(SubmitSourceObservation(scope_id=scope, observation=observation))
        assert repeated.source_ref == first.source_ref
    return checks.ref_key(first.source_ref)


def binding(scope):
    return ConnectorBinding(
        scope_id=scope, binding_id="mixed", connector_name="pi-session-history", connector_version="1"
    )


async def seed(runtime, registry, directory, state, family):
    for word in ("amber", "violet"):
        scope = await checks.scope(runtime, word)
        ref = await submit_row(runtime, registry, scope, word)
        path = directory / f"{word}.jsonl"
        write_session(path, word)
        # First delivery has only the root; numeric event is appended after restart.
        path.write_text("\n".join(path.read_text(encoding="utf-8").splitlines()[:2]) + "\n", encoding="utf-8")
        result = await run_connector(runtime, registry, binding(scope), path)
        assert len(result.items) == 1 and result.items[0].source_ref is not None
        state[word] = {
            "scope": scope,
            "refs": [ref, checks.ref_key(result.items[0].source_ref)],
            "checkpoint": result.committed_checkpoint,
        }
        assert (await run_connector(runtime, registry, binding(scope), path)).items == ()
        await checks.stay_refs(runtime, scope, family, set())


async def replay(runtime, registry, directory, state):
    for word in ("amber", "violet"):
        scope = state[word]["scope"]
        assert (await runtime.ingestion.checkpoint(binding(scope))).checkpoint == state[word]["checkpoint"]
        assert await submit_row(runtime, registry, scope, word) == tuple(state[word]["refs"][0])
        assert (await run_connector(runtime, registry, binding(scope), directory / f"{word}.jsonl")).items == ()


async def resume(runtime, registry, directory, state, family):
    await replay(runtime, registry, directory, state)
    for word in ("amber", "violet"):
        await checks.stay_refs(runtime, state[word]["scope"], family, set())
    scope = state["amber"]["scope"]
    write_session(directory / "amber.jsonl", "amber")
    result = await run_connector(runtime, registry, binding(scope), directory / "amber.jsonl")
    assert len(result.items) == 1 and result.items[0].source_ref is not None
    state["amber"]["refs"].append(checks.ref_key(result.items[0].source_ref))
    state["amber"]["checkpoint"] = result.committed_checkpoint
    expected = {tuple(ref) for ref in state["amber"]["refs"]}
    await checks.wait_refs(runtime, scope, family, expected)
    await checks.stay_refs(runtime, scope, family, expected)
    await checks.stay_refs(runtime, state["violet"]["scope"], family, set())
    assert generation(directory, scope, family) == (1, 1)
    if family == "memory":
        pack = await reconstruct(
            runtime.context.for_scope(scope), PrepareContextRequest(query="CountEvidence", max_bytes=16000)
        )
        assert pack.items
        (directory / "native.pack").write_bytes(pack.to_bytes())


async def final(runtime, registry, directory, state, family):
    from powercontext.builtin.runtime.context_pack import ContextPack

    await replay(runtime, registry, directory, state)
    amber = state["amber"]["scope"]
    expected = {tuple(ref) for ref in state["amber"]["refs"]}
    await checks.stay_refs(runtime, amber, family, expected)
    assert generation(directory, amber, family) == (1, 1)
    # One new row is below threshold after the successful cursor; old rows cannot count again.
    await submit_row(runtime, registry, amber, "amber", "2")
    violet = state["violet"]["scope"]
    added = await submit_row(runtime, registry, violet, "violet", "2")
    state["violet"]["refs"].append(added)
    await checks.wait_refs(runtime, violet, family, {tuple(ref) for ref in state["violet"]["refs"]})
    await checks.stay_refs(runtime, violet, family, {tuple(ref) for ref in state["violet"]["refs"]})
    await checks.stay_refs(runtime, amber, family, expected)
    assert generation(directory, amber, family) == generation(directory, violet, family) == (1, 1)
    if family == "memory":
        old = ContextPack.from_bytes((directory / "native.pack").read_bytes())
        assert (
            await reconstruct(
                runtime.context.for_scope(amber), PrepareContextRequest(query="CountEvidence", max_bytes=16000), old
            )
            == old
        )


async def readback(runtime, registry, state, phase):
    for word in ("amber", "violet"):
        # Read through the real Runtime's context with its configured hybrid retrieval profile.
        async with runtime._context(state[word]["scope"]) as context:
            entries = await context.sources.journal.entries()
            expected_count = len(state[word]["refs"]) + int(phase == "final" and word == "amber")
            assert len(entries) == expected_count
            for entry in entries:
                assert isinstance(entry.source, SourceObservation)
                definition = (
                    CSV_ROW_SOURCE_DEFINITION if entry.source.source_type == "csv-row" else PI_EVENT_SOURCE_DEFINITION
                )
                item = await registry.read(definition.source_class.model_validate(entry.source.payload))
                if isinstance(item, CSVRowInput):
                    value = entry.source.projection(TEXT_EVIDENCE_PROJECTION_KEY)
                    assert isinstance(value, dict) and isinstance(value["metadata"], dict)
                    row = value["metadata"]["row"]
                    assert isinstance(row, dict)
                    assert list(row) == ["id", "z", "a"] and row["a"] == "001"
                else:
                    assert isinstance(item, PiEventInput)
                    if item.event_id == "numeric":
                        number = item.record["message"]["details"]["integer"]
                        assert type(number) is int and number == 10**100


async def worker(directory, family, phase, port):
    config = settings(directory, family, port)
    registry = SourceDefinitionRegistry((CSV_ROW_SOURCE_DEFINITION, PI_EVENT_SOURCE_DEFINITION))
    state_path = directory / "count-state.json"
    state = {} if phase == "seed" else json.loads(state_path.read_text(encoding="utf-8"))
    async with open_builtin_runtime(config) as runtime:
        for definition in (CSV_ROW_SOURCE_DEFINITION, PI_EVENT_SOURCE_DEFINITION):
            await runtime.ingestion.register(manifest_for_definition(definition))
        await {"seed": seed, "resume": resume, "final": final}[phase](runtime, registry, directory, state, family)
        await readback(runtime, registry, state, phase)
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(
        json.dumps({
            "phase": phase,
            "family": family,
            "source_counts": {word: len(state[word]["refs"]) for word in state},
        })
    )


@pytest.mark.parametrize("family", ["memory", "topic-memory"])
def test_mixed_captured_sources_count_after_restart_without_replay_or_scope_leak(tmp_path, monkeypatch, family):
    with checks.provider(monkeypatch) as server:
        for phase in ("seed", "resume", "final"):
            result = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), str(tmp_path), family, phase, str(server.server_port)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=180,
                check=False,
            )
            assert result.returncode == 0, result.stdout + result.stderr
            print(result.stdout.strip())
        assert server.generation_calls > 0


if __name__ == "__main__":
    asyncio.run(worker(Path(sys.argv[1]), sys.argv[2], sys.argv[3], int(sys.argv[4])))
