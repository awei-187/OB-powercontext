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

"""Shared evidence aliases retain independent support at exact native identities."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import select

from powercontext.artifacts import MemoryCitation
from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.artifacts.topic_memory import (
    TopicMemoryContent,
    TopicMemoryDraft,
    TopicMemorySearchRequest,
    prepare_topic_memory_projection,
)
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.persistence.tables import TOPIC_MEMORY_ACTIVE_TOPICS_TABLE
from powercontext.builtin.persistence.topic_memory_index import topic_memory_lifecycle_eligible
from powercontext.builtin.runtime import (
    BuiltinConfig,
    ContextAssembly,
    ContextAssemblySection,
    GetMemoryEntryRequest,
    PrepareContextRequest,
    RememberMemoryRequest,
    SearchMemoryRequest,
    open_builtin_runtime,
)
from powercontext.builtin.runtime.source_lifecycle import SourceLifecycleError
from tests.e2e.test_source_lifecycle import Embeddings, create_memory, create_scope, create_source, transition


def config(path):
    return BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{path / 'aliases.db'}"))


async def memory_status(runtime, scope, original, available):
    memory = runtime.memory.for_scope(scope)
    page = await memory.list(include_inactive=True)
    states = {entry.entry.entry_id: entry.state for entry in page.entries}
    assert (states[original.entry_id] == "active") == available
    hits = (await memory.search(SearchMemoryRequest(query="aliasmarker", mode="fts"))).hits
    assert (original.entry_id in {hit.entry_id for hit in hits}) == available
    exact = await memory.get(GetMemoryEntryRequest(citation=original))
    assert exact.entry.text == "aliasmarker independent evidence"
    prepared = await runtime.context.for_scope(scope).prepare(
        PrepareContextRequest(
            query="aliasmarker",
            max_bytes=4096,
            assembly=ContextAssembly(sections=(ContextAssemblySection(family="memory", limit=8),)),
        )
    )
    # The equal-text but distinct entry is independently withdrawn throughout.
    assert ("aliasmarker independent evidence" in (prepared.content or "")) == available
    return page.memory_ref


async def memory_alias_stage(path: Path, stage: str, late: bool):
    metadata = path / "memory-alias-refs.json"
    async with open_builtin_runtime(config(path)) as runtime:
        if stage == "create":
            scope = await create_scope(runtime, "memory-aliases")
            for root in ("a", "b", "c"):
                await create_source(runtime, scope, root)
            lifecycle = runtime.lifecycle.for_scope(scope)
            original = await create_memory(runtime, scope, "aliasmarker independent evidence")
            duplicate = await runtime.memory.for_scope(scope).remember(
                RememberMemoryRequest(entries=(MemoryEntryInput(kind="fact", text="aliasmarker independent evidence"),))
            )
            assert duplicate.entry is None and duplicate.memory_ref == original.memory_ref
            # Same text with a different native identity must not become an alias.
            distinct_result = await runtime.memory.for_scope(scope).remember(
                RememberMemoryRequest(
                    entries=(MemoryEntryInput(kind="constraint", text="aliasmarker independent evidence"),)
                )
            )
            assert distinct_result.entry is not None
            distinct = distinct_result.entry.citation
            assert distinct.entry_id != original.entry_id
            await lifecycle.register_memory("distinct", distinct, parents=("c",), policy="all")
            await lifecycle.apply(transition("c"))
            # The same immutable entry can be cited from different Memory snapshots.
            current = next(
                item.citation
                for item in (await runtime.memory.for_scope(scope).list()).entries
                if item.entry.entry_id == original.entry_id
            )
            assert current.entry_version_id == original.entry_version_id
            assert current.memory_ref != original.memory_ref
            await lifecycle.register_memory("alias-b", current, parents=("b",), policy="all")
            if late:
                await lifecycle.apply(transition("a"))
            await lifecycle.register_memory("alias-a", original, parents=("a",), policy="all")
            await lifecycle.apply(transition("a"))
            before = await memory_status(runtime, scope, original, True)
            await lifecycle.apply(transition("a"))
            assert await memory_status(runtime, scope, original, True) == before
            assert await lifecycle.resolve("alias-b", purpose="generation") == current
            with pytest.raises(SourceLifecycleError):
                await lifecycle.resolve("alias-a", purpose="generation")
            metadata.write_text(json.dumps({"scope": scope, "ref": original.model_dump()}), encoding="utf-8")
            return
        stored = json.loads(metadata.read_text(encoding="utf-8"))
        scope = stored["scope"]
        original = MemoryCitation.model_validate(stored["ref"])
        lifecycle = runtime.lifecycle.for_scope(scope)
        if stage == "withdraw-all":
            await memory_status(runtime, scope, original, True)
            event = transition("b")
            await lifecycle.apply(event)
            before = await memory_status(runtime, scope, original, False)
        elif stage == "restore-one":
            await memory_status(runtime, scope, original, False)
            event = transition("a", 2, True)
            await lifecycle.apply(event)
            before = await memory_status(runtime, scope, original, True)
        else:
            event = transition("a", 2, True)
            before = await memory_status(runtime, scope, original, True)
        await lifecycle.apply(event)
        assert (await runtime.memory.for_scope(scope).list(include_inactive=True)).memory_ref == before


@pytest.mark.parametrize("late", [False, True])
def test_memory_aliases_process_restart_all_withdrawn_and_one_restored(tmp_path, late):
    for stage in ("create", "withdraw-all", "restore-one", "verify"):
        result = subprocess.run(
            [sys.executable, "-m", "tests.e2e.test_source_lifecycle_aliases", str(tmp_path), stage, str(int(late))],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr


def test_same_memory_identifiers_in_other_scope_do_not_supply_support(tmp_path):
    async def run():
        async with open_builtin_runtime(config(tmp_path)) as runtime:
            scopes = [await create_scope(runtime, name) for name in ("alpha", "beta")]
            # Deterministic input IDs create a genuine database identity collision
            # across scopes. No persistence or Runtime implementation is replaced.
            original_factory = runtime.lifecycle.contexts._id_factory
            runtime.lifecycle.contexts._id_factory = lambda namespace: (
                original_factory(namespace) if namespace == "memory" else f"same-{namespace}"
            )
            references = []
            for scope in scopes:
                for root in ("a", "b"):
                    await create_source(runtime, scope, root)
                ref = await create_memory(runtime, scope, "aliasmarker independent evidence")
                references.append(ref)
                lifecycle = runtime.lifecycle.for_scope(scope)
                await lifecycle.register_memory("alias-a", ref, parents=("a",), policy="all")
                await lifecycle.register_memory("alias-b", ref, parents=("b",), policy="all")
            assert references[0] == references[1]
            alpha, beta = scopes
            await runtime.lifecycle.for_scope(alpha).apply(transition("a"))
            await memory_status(runtime, alpha, references[0], True)
            await runtime.lifecycle.for_scope(alpha).apply(transition("b"))
            await memory_status(runtime, alpha, references[0], False)
            await memory_status(runtime, beta, references[1], True)
        async with open_builtin_runtime(config(tmp_path)) as runtime:
            await memory_status(runtime, alpha, references[0], False)
            await memory_status(runtime, beta, references[1], True)
            await runtime.lifecycle.for_scope(alpha).apply(transition("a", 2, True))
            await memory_status(runtime, alpha, references[0], True)
            await memory_status(runtime, beta, references[1], True)

    asyncio.run(run())


async def publish_topic(runtime, scope, artifact_id, *, previous=None):
    content = TopicMemoryContent(title="titlealias", summary="identical summary", detail="detailalias independent body")
    projection = prepare_topic_memory_projection(
        content,
        topic_embedding=(1.0, 0.0, 0.0),
        chunk_embeddings=((1.0, 0.0, 0.0),),
        embedding_profile=Embeddings.profile,
    )
    contexts = runtime.lifecycle.contexts
    async with contexts.database.transaction() as connection:
        repository = contexts.repositories.topic_memories
        if previous is None:
            result = await repository.publish_create(
                connection, scope, artifact_id, TopicMemoryDraft(content=content), projection
            )
        else:
            current = (await repository.get_exact(connection, scope, previous)).topic
            result = await repository.publish_revision(
                connection, scope, current, TopicMemoryDraft(content=content), projection
            )
        return result.topic.as_ref()


async def topic_channels(runtime, scope, expected):
    contexts = runtime.lifecycle.contexts
    async with contexts.database.transaction() as connection:
        # Execute the SQLAlchemy predicate used by OceanBase on the same real
        # rows as SQLite's native FTS/vector queries, including exact revisions.
        active = TOPIC_MEMORY_ACTIVE_TOPICS_TABLE
        rows = await connection.execute(
            select(active.c.artifact_id, active.c.revision).where(
                active.c.scope_id == scope, topic_memory_lifecycle_eligible(active)
            )
        )
        assert sorted(rows.tuples()) == sorted((ref.artifact_id, ref.revision) for ref in expected)
        for query, lexical_channel in (("titlealias", "topic_fts"), ("detailalias", "detail_fts")):
            channels = await contexts.repositories.topic_memories.index.search(
                connection,
                scope,
                TopicMemorySearchRequest(
                    query=query,
                    analyzed_query=query,
                    candidate_limit=1,
                    mode="hybrid",
                    query_vector=(1.0, 0.0, 0.0),
                    embedding_profile=Embeddings.profile,
                ),
            )
            for channel in (lexical_channel, "topic_vector", "detail_vector"):
                assert [hit.artifact_ref for hit in getattr(channels, channel)] == expected
            assert getattr(channels, lexical_channel + "_retrieved") == len(expected)


@pytest.mark.parametrize("late", [False, True])
def test_topic_alias_identity_scope_revision_and_channel_limits(tmp_path, late):
    async def run():
        async with open_builtin_runtime(config(tmp_path), embedding_model=Embeddings()) as runtime:
            scopes = [await create_scope(runtime, name) for name in ("alpha", "beta")]
            refs = []
            for scope in scopes:
                lifecycle = runtime.lifecycle.for_scope(scope)
                for root in ("a", "b", "old", "distinct"):
                    await create_source(runtime, scope, root)
                # Real Topic projections with deliberately identical IDs in two scopes.
                old = await publish_topic(runtime, scope, "same-native-id")
                await lifecycle.register_topic("old-revision", old, parents=("old",), policy="all")
                current = await publish_topic(runtime, scope, "same-native-id", previous=old)
                refs.append(current)
                await lifecycle.register_topic("alias-b", current, parents=("b",), policy="all")
                if late:
                    await lifecycle.apply(transition("a"))
                await lifecycle.register_topic("alias-a", current, parents=("a",), policy="all")
                # Same content and revision, but another artifact, must stay excluded.
                distinct = await publish_topic(runtime, scope, "different-native-id")
                await lifecycle.register_topic("distinct-topic", distinct, parents=("distinct",), policy="all")
                await lifecycle.apply(transition("distinct"))
                await lifecycle.apply(transition("a"))
                await topic_channels(runtime, scope, [current])
            assert refs[0] == refs[1]
            alpha, beta = scopes
            await runtime.lifecycle.for_scope(alpha).apply(transition("b"))
            # Active beta aliases and the active old revision must not rescue alpha.
            await topic_channels(runtime, alpha, [])
            await topic_channels(runtime, beta, [refs[1]])
        async with open_builtin_runtime(config(tmp_path), embedding_model=Embeddings()) as runtime:
            await topic_channels(runtime, alpha, [])
            await topic_channels(runtime, beta, [refs[1]])
            await runtime.lifecycle.for_scope(beta).apply(transition("b"))
            await topic_channels(runtime, beta, [])
            event = transition("a", 2, True)
            await runtime.lifecycle.for_scope(alpha).apply(event)
            await topic_channels(runtime, alpha, [refs[0]])
            await topic_channels(runtime, beta, [])
            await runtime.lifecycle.for_scope(alpha).apply(event)
            await topic_channels(runtime, alpha, [refs[0]])
            assert await runtime.lifecycle.for_scope(alpha).resolve("alias-a", purpose="generation") == refs[0]
            with pytest.raises(SourceLifecycleError):
                await runtime.lifecycle.for_scope(alpha).resolve("alias-b", purpose="generation")

    asyncio.run(run())


if __name__ == "__main__":
    asyncio.run(memory_alias_stage(Path(sys.argv[1]), sys.argv[2], bool(int(sys.argv[3]))))
