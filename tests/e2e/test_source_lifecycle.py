# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Real SQLite lifecycle transitions, recovery and exact evidence reads."""

from __future__ import annotations

import asyncio
import json
import random
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from powercontext.artifacts import ArtifactRef, MemoryCitation
from powercontext.builtin.artifacts.memory import EmbeddingProfile, MemoryEntryInput
from powercontext.builtin.artifacts.memory.errors import MemoryCapacityExceededError
from powercontext.builtin.inference import EmbeddingResult
from powercontext.builtin.persistence.memory import RelationalMemoryBackend
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.records import ArtifactWrite
from powercontext.builtin.runtime import (
    BuiltinConfig,
    CaptureSource,
    ContextAssembly,
    ContextAssemblySection,
    GetMemoryEntryRequest,
    PrepareContextRequest,
    RememberMemoryRequest,
    RetireMemoryEntryRequest,
    RuntimeConfig,
    SearchMemoryRequest,
    SearchTopicMemoryRequest,
    open_builtin_runtime,
)
from powercontext.builtin.runtime.source_lifecycle import SourceLifecycleError, SourceLifecycleEvent
from powercontext.builtin.scope import ScopeDraft
from powercontext.sources import SourceRef


def transition(node="source", sequence=1, available=False, reason="explicit withdrawal"):
    return SourceLifecycleEvent(node_id=node, revision=7, sequence=sequence, available=available, reason=reason)


async def create_scope(runtime, name):
    return (await runtime.scopes.create(ScopeDraft(title=name, summary=name, idempotency_key=name))).scope_id


async def create_source(runtime, scope, node="source"):
    receipt = await runtime.sources.for_scope(scope).capture(CaptureSource(source_id=node, content=node, metadata={}))
    await runtime.lifecycle.for_scope(scope).register_source(node, receipt.source_ref, revision=7)
    return receipt.source_ref


async def create_memory(runtime, scope, text="durable evidence"):
    result = await runtime.memory.for_scope(scope).remember(
        RememberMemoryRequest(entries=(MemoryEntryInput(kind="fact", text=text),))
    )
    return result.entry.citation


async def create_topic(runtime, scope, title="durable topic"):
    result = await runtime.records.for_scope(scope).create_artifact(
        "topic-memory", ArtifactWrite(content={"title": title, "summary": title, "detail": f"{title} evidence"})
    )
    return ArtifactRef(family="topic-memory", artifact_id=result.artifact_id, revision=result.revision)


async def seed(runtime, scope):
    source = await create_source(runtime, scope)
    citation = await create_memory(runtime, scope)
    topic = await create_topic(runtime, scope)
    service = runtime.lifecycle.for_scope(scope)
    await service.register_memory("memory", citation, parents=("source",), policy="all")
    await service.register_topic("topic", topic, parents=("memory",), policy="any")
    return source, citation, topic


async def assert_visible(runtime, scope, citation, topic, available):
    service = runtime.lifecycle.for_scope(scope)
    memory = runtime.memory.for_scope(scope)
    entries = await memory.list(include_inactive=True)
    assert (entries.entries[0].state == "active") == available
    assert bool((await memory.search(SearchMemoryRequest(query="durable", mode="fts"))).hits) == available
    assert (
        bool((await runtime.topic_memory.for_scope(scope).search(SearchTopicMemoryRequest(query="durable"))).hits)
        == available
    )
    for budget in (512, 1024, 4096):
        prepared = await runtime.context.for_scope(scope).prepare(
            PrepareContextRequest(
                query="durable",
                max_bytes=budget,
                assembly=ContextAssembly(
                    sections=(
                        ContextAssemblySection(family="memory", limit=4),
                        ContextAssemblySection(family="topic-memory", limit=4),
                    )
                ),
            )
        )
        assert len((prepared.content or "").encode()) <= budget
        if not available:
            assert "durable" not in (prepared.content or "")
        elif budget == 4096:
            assert "durable evidence" in prepared.content
            assert "durable topic" in prepared.content
    assert (await memory.get(GetMemoryEntryRequest(citation=citation))).entry.text == "durable evidence"
    assert (
        await runtime.records.for_scope(scope).get_artifact_revision(topic.family, topic.artifact_id, topic.revision)
    ).content["title"] == "durable topic"
    for node, ref in (("memory", citation), ("topic", topic)):
        assert await service.resolve(node, purpose="audit") == ref
        if available:
            assert await service.resolve(node, purpose="generation") == ref
        else:
            with pytest.raises(SourceLifecycleError):
                await service.resolve(node, purpose="generation")


@pytest.mark.parametrize(
    "field,value",
    [
        ("node_id", ""),
        ("node_id", " \t\n"),
        ("node_id", 3),
        ("node_id", b"x"),
        ("reason", ""),
        ("reason", "\u2003"),
        ("reason", None),
        ("revision", 0),
        ("revision", -1),
        ("revision", True),
        ("revision", 1.0),
        ("revision", "1"),
        ("sequence", 0),
        ("sequence", -1),
        ("sequence", False),
        ("sequence", 1.0),
        ("sequence", "1"),
        ("available", 0),
        ("available", 1),
        ("available", "false"),
        ("extra", "no"),
    ],
)
def test_strict_event_schema(field, value):
    payload = transition().model_dump()
    payload[field] = value
    with pytest.raises(ValidationError):
        SourceLifecycleEvent.model_validate(payload)


def test_registration_validation_and_idempotency(tmp_path):
    async def run():
        async with open_builtin_runtime(BuiltinConfig(database=SQLiteConfig())) as runtime:
            scope = await create_scope(runtime, "validation")
            source, citation, topic = await seed(runtime, scope)
            service = runtime.lifecycle.for_scope(scope)
            before = (await runtime.memory.for_scope(scope).list()).memory_ref
            await service.register_source("source", source, revision=7)
            await service.register_memory("memory", citation, parents=("source",), policy="all")
            await service.register_topic("topic", topic, parents=("memory",), policy="any")
            assert (await runtime.memory.for_scope(scope).list()).memory_ref == before
            for parents, policy in (
                ((), "all"),
                (("source", "source"), "any"),
                (("missing",), "all"),
                (("invalid",), "all"),
                (("source",), "ALL"),
                ("source", "all"),
            ):
                with pytest.raises(SourceLifecycleError):
                    await service.register_memory("invalid", citation, parents=parents, policy=policy)  # ty: ignore[invalid-argument-type] - malformed input
            for revision in (True, 0, -1, 7.0, "7", 8):
                with pytest.raises(SourceLifecycleError):
                    await service.register_source("source", source, revision=revision)  # ty: ignore[invalid-argument-type] - malformed input
            with pytest.raises(SourceLifecycleError):
                await service.register_source(
                    "missing", SourceRef(source_type="content", source_id="missing"), revision=7
                )
            with pytest.raises(SourceLifecycleError):
                await service.register_topic(
                    "missing",
                    ArtifactRef(family="topic-memory", artifact_id="missing", revision=1),
                    parents=("source",),
                    policy="all",
                )
            with pytest.raises(SourceLifecycleError):
                await service.register_memory(
                    "missing",
                    citation.model_copy(update={"entry_version_id": "missing"}),
                    parents=("source",),
                    policy="all",
                )
            other = await create_scope(runtime, "other")
            await create_source(runtime, other)
            with pytest.raises(SourceLifecycleError):
                await runtime.lifecycle.for_scope(other).register_memory(
                    "foreign", citation, parents=("source",), policy="all"
                )
            with pytest.raises(SourceLifecycleError):
                await service.register_memory("source", citation, parents=("memory",), policy="any")
            with pytest.raises(SourceLifecycleError):
                await service.resolve("missing", purpose="audit")
            with pytest.raises(SourceLifecycleError):
                await service.resolve("memory", purpose="unknown")
            with pytest.raises(SourceLifecycleError):
                await service.apply(transition("memory"))
            await service.apply(transition(sequence=10**30))
            with pytest.raises(SourceLifecycleError):
                await service.apply(transition(sequence=10**30, reason="changed reason"))
            await service.register_memory("memory", citation, parents=("source",), policy="all")
            assert await service.resolve("memory", purpose="audit") == citation
            await assert_visible(runtime, scope, citation, topic, False)

    asyncio.run(run())


def test_native_commit_failure_is_atomic_and_retryable(tmp_path, monkeypatch):
    async def run():
        config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'failure.db'}"))
        async with open_builtin_runtime(config) as runtime:
            scope = await create_scope(runtime, "failure")
            _, citation, topic = await seed(runtime, scope)
            before = (await runtime.memory.for_scope(scope).list()).memory_ref
            original = RelationalMemoryBackend._commit

            async def fail_after_write(self, connection, value):
                await original(self, connection, value)
                raise RuntimeError("injected after native SQL writes")  # noqa: TRY003

            with monkeypatch.context() as patch:
                patch.setattr(RelationalMemoryBackend, "_commit", fail_after_write)
                with pytest.raises(RuntimeError, match="injected"):
                    await runtime.lifecycle.for_scope(scope).apply(transition())
            assert (await runtime.memory.for_scope(scope).list()).memory_ref == before
            await assert_visible(runtime, scope, citation, topic, True)
        async with open_builtin_runtime(config) as runtime:
            service = runtime.lifecycle.for_scope(scope)
            assert await service.apply(transition()) == []
            await assert_visible(runtime, scope, citation, topic, False)
            before = (await runtime.memory.for_scope(scope).list(include_inactive=True)).memory_ref
            assert await service.apply(transition()) == []
            assert (await runtime.memory.for_scope(scope).list(include_inactive=True)).memory_ref == before
            assert await service.apply(transition(sequence=2, available=True)) == ["memory", "source", "topic"]
            await assert_visible(runtime, scope, citation, topic, True)

    asyncio.run(run())


def test_capacity_refusal_rolls_back_source_and_can_retry(tmp_path):
    async def run():
        config = BuiltinConfig(database=SQLiteConfig(), runtime=RuntimeConfig(memory_max_active_entries=1))
        async with open_builtin_runtime(config) as runtime:
            scope = await create_scope(runtime, "capacity")
            _, citation, topic = await seed(runtime, scope)
            service = runtime.lifecycle.for_scope(scope)
            await service.apply(transition())
            newcomer = await create_memory(runtime, scope, "independent survivor")
            before = (await runtime.memory.for_scope(scope).list()).memory_ref
            with pytest.raises(MemoryCapacityExceededError):
                await service.apply(transition(sequence=2, available=True))
            assert (await runtime.memory.for_scope(scope).list()).memory_ref == before
            with pytest.raises(SourceLifecycleError):
                await service.resolve("source", purpose="generation")
            await runtime.memory.for_scope(scope).retire(
                RetireMemoryEntryRequest(citation=newcomer, reason="free capacity")
            )
            await service.apply(transition(sequence=2, available=True))
            assert await service.resolve("memory", purpose="generation") == citation
            assert await service.resolve("topic", purpose="generation") == topic

    asyncio.run(run())


def test_registration_failure_does_not_reserve_node_or_retire_body(monkeypatch):
    async def run():
        async with open_builtin_runtime(BuiltinConfig(database=SQLiteConfig())) as runtime:
            scope = await create_scope(runtime, "registration-failure")
            await create_source(runtime, scope)
            lifecycle = runtime.lifecycle.for_scope(scope)
            await lifecycle.apply(transition())
            citation = await create_memory(runtime, scope)
            before = (await runtime.memory.for_scope(scope).list()).memory_ref
            original = RelationalMemoryBackend._commit

            async def fail_after_write(self, connection, value):
                await original(self, connection, value)
                raise RuntimeError("registration write interrupted")  # noqa: TRY003

            with monkeypatch.context() as patch:
                patch.setattr(RelationalMemoryBackend, "_commit", fail_after_write)
                with pytest.raises(RuntimeError, match="interrupted"):
                    await lifecycle.register_memory("late", citation, parents=("source",), policy="all")
            assert (await runtime.memory.for_scope(scope).list()).memory_ref == before
            with pytest.raises(SourceLifecycleError):
                await lifecycle.resolve("late", purpose="audit")
            await lifecycle.register_memory("late", citation, parents=("source",), policy="all")
            assert not (await runtime.memory.for_scope(scope).list()).entries
            await lifecycle.apply(transition(sequence=2, available=True))
            assert await lifecycle.resolve("late", purpose="generation") == citation

    asyncio.run(run())


@pytest.mark.parametrize("seed_value", [13, 83, 421])
def test_multilayer_dag_matches_independent_recursive_oracle(seed_value):  # noqa: C901 - whole graph scenario
    async def run():
        rng = random.Random(seed_value)  # noqa: S311 - deterministic test graph, not security
        async with open_builtin_runtime(BuiltinConfig(database=SQLiteConfig())) as runtime:
            scope = await create_scope(runtime, f"graph-{seed_value}")
            service = runtime.lifecycle.for_scope(scope)
            edges = {}
            references = {}
            root_state = {}
            sequences = {}
            for index in range(4):
                node = f"根-{index}"
                references[node] = await create_source(runtime, scope, node)
                root_state[node] = True
                sequences[node] = 0
            for index in range(16):
                node = f"derived-{index}"
                parents = tuple(rng.sample(list(references), k=min(3, len(references))))
                policy = "any" if index % 2 else "all"
                if index < 12:
                    ref = await create_memory(runtime, scope, f"uniquegraph{index} durable evidence")
                    await service.register_memory(node, ref, parents=parents, policy=policy)
                else:
                    ref = await create_topic(runtime, scope, f"uniquegraph{index}")
                    await service.register_topic(node, ref, parents=parents, policy=policy)
                edges[node] = (parents, policy)
                references[node] = ref

            def supported(node):
                if node in root_state:
                    return root_state[node]
                parents, policy = edges[node]
                values = [supported(parent) for parent in parents]
                return all(values) if policy == "all" else any(values)

            for step in range(16):
                root = list(root_state)[step % 4]
                root_state[root] = not root_state[root]
                sequences[root] += 1
                event = transition(root, sequences[root], root_state[root])
                expected = sorted(node for node in references if supported(node))
                assert await service.apply(event) == expected
                page = await runtime.memory.for_scope(scope).list(include_inactive=True)
                states = {entry.entry.entry_id: entry.state for entry in page.entries}
                for node, ref in references.items():
                    assert await service.resolve(node, purpose="audit") == ref
                    if isinstance(ref, MemoryCitation):
                        assert (states[ref.entry_id] == "active") == supported(node)
                    elif isinstance(ref, ArtifactRef):
                        index = int(node.split("-")[1])
                        result = await runtime.topic_memory.for_scope(scope).search(
                            SearchTopicMemoryRequest(query=f"uniquegraph{index}")
                        )
                        assert bool(result.hits) == supported(node)
                before = page.memory_ref
                assert await service.apply(event) == expected
                assert (await runtime.memory.for_scope(scope).list()).memory_ref == before

    asyncio.run(run())


class Embeddings:
    """Deterministic input vectors; all persistence and index execution is real."""

    profile = EmbeddingProfile(profile_id="lifecycle", model="local", dimension=3)

    async def embed(self, texts, /):
        return EmbeddingResult(vectors=tuple((1.0, 0.0, 0.0) for _ in texts))


@pytest.mark.parametrize("vector", [False, True])
def test_unavailable_topics_do_not_consume_candidate_budget(tmp_path, vector):
    async def run():
        config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'candidates.db'}"))
        embedding = Embeddings() if vector else None
        async with open_builtin_runtime(config, embedding_model=embedding) as runtime:
            scope = await create_scope(runtime, "candidates")
            await create_source(runtime, scope)
            await create_source(runtime, scope, "independent")
            service = runtime.lifecycle.for_scope(scope)
            for index in range(40):
                topic = await create_topic(runtime, scope, f"candidate durable {index}")
                await service.register_topic(f"topic-{index}", topic, parents=("source",), policy="all")
            survivor = await create_topic(runtime, scope, "candidate durable survivor")
            await service.register_topic("survivor", survivor, parents=("independent",), policy="all")
            await service.apply(transition())
        async with open_builtin_runtime(config, embedding_model=embedding) as runtime:
            result = await runtime.topic_memory.for_scope(scope).search(
                SearchTopicMemoryRequest(query="candidate durable", limit=1)
            )
            assert result.mode == ("hybrid" if vector else "fts")
            assert [hit.artifact_ref for hit in result.hits] == [survivor]
            for mode in ("fts", "vector", "hybrid") if vector else ("fts",):
                result = await runtime.lifecycle.contexts.search_topic_memories(
                    scope,
                    "candidate durable",
                    mode=mode,
                    limit=1,
                    query_vector=(1.0, 0.0, 0.0) if vector else None,
                    embedding_profile=Embeddings.profile if vector else None,
                )
                assert result.mode == mode
                assert [hit.artifact_ref for hit in result.hits] == [survivor]
            await runtime.lifecycle.for_scope(scope).apply(transition(sequence=2, available=True))
            result = await runtime.topic_memory.for_scope(scope).search(
                SearchTopicMemoryRequest(query="candidate durable", limit=20)
            )
            assert len(result.hits) == 20

    asyncio.run(run())


async def restart_stage(directory: Path, stage: str):
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{directory / 'restart.db'}"))
    metadata = directory / "refs.json"
    async with open_builtin_runtime(config) as runtime:
        if stage == "create":
            scopes = []
            for name in ("alpha", "beta"):
                scope = await create_scope(runtime, name)
                source, citation, topic = await seed(runtime, scope)
                scopes.append({
                    "scope": scope,
                    "source": source.model_dump(),
                    "citation": citation.model_dump(),
                    "topic": topic.model_dump(),
                })
            metadata.write_text(json.dumps(scopes), encoding="utf-8")
            return
        scopes = json.loads(metadata.read_text(encoding="utf-8"))
        alpha, beta = scopes
        service = runtime.lifecycle.for_scope(alpha["scope"])
        if stage == "withdraw":
            await service.apply(transition())
        elif stage == "restore":
            before = (await runtime.memory.for_scope(alpha["scope"]).list(include_inactive=True)).memory_ref
            await service.apply(transition())
            assert (await runtime.memory.for_scope(alpha["scope"]).list(include_inactive=True)).memory_ref == before
            await service.apply(transition(sequence=2, available=True))
        for item in (alpha, beta):
            await assert_visible(
                runtime,
                item["scope"],
                MemoryCitation.model_validate(item["citation"]),
                ArtifactRef.model_validate(item["topic"]),
                item == beta or stage == "restore",
            )


def test_real_process_restart_and_scope_isolation(tmp_path):
    for stage in ("create", "withdraw", "verify", "restore"):
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), str(tmp_path), stage],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr


if __name__ == "__main__":
    asyncio.run(restart_stage(Path(sys.argv[1]), sys.argv[2]))
