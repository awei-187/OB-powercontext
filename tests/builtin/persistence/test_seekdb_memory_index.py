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

"""Statement-budget and adapter tests; these do not certify native index plans."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects.mysql import dialect
from sqlalchemy.ext.asyncio import AsyncConnection

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory import (
    CapabilityNotSupportedError,
    EmbeddingProfile,
    MemorySearchRequest,
)
from powercontext.builtin.artifacts.memory.fusion import fuse_rankings
from powercontext.builtin.persistence.oceanbase.memory_index import OceanBaseMemoryFTSIndex, OceanBaseMemoryVectorIndex
from powercontext.builtin.persistence.seekdb.memory_index import SeekDBMemoryIndex
from powercontext.builtin.tags import TagFilter

PROFILE = EmbeddingProfile(profile_id="seekdb-test", model="test", dimension=3, distance="l2", normalization="unit")
MEMORY = ArtifactRef(family="memory", artifact_id="memory", revision=9)


def request(**changes: Any) -> MemorySearchRequest:
    return MemorySearchRequest.model_validate({
        "query": "raw alpha",
        "analyzed_query": "alpha",
        "memories": (MEMORY,),
        "candidate_limit": 2,
        "mode": "hybrid",
        "query_vector": (1.0, 0.0, 0.0),
        "embedding_profile": PROFILE,
        **changes,
    })


def row(channel: str, entry_id: str, *, artifact_id: str = "memory") -> dict[str, object]:
    return {
        "channel": channel,
        "memory_artifact_id": artifact_id,
        "head_revision": 1,
        "entry_id": entry_id,
        "entry_version_id": entry_id + "-version",
        "text": "Exact body: 中文\n" + entry_id,
        "distance": 0.2 if channel == "vector" else None,
    }


class Result:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def mappings(self) -> Result:
        return self

    def all(self) -> list[dict[str, object]]:
        return self.rows


def connection_with(rows: list[dict[str, object]]) -> AsyncMock:
    connection = AsyncMock(spec=AsyncConnection)
    connection.execute.return_value = Result(rows)
    return connection


@pytest.fixture
def index(monkeypatch: pytest.MonkeyPatch) -> SeekDBMemoryIndex:
    result = SeekDBMemoryIndex(PROFILE)
    # Only isolate the candidate adapter here; native tests exercise real checks.
    monkeypatch.setattr(result, "vector_complete", AsyncMock(return_value=True))
    return result


@pytest.mark.asyncio
async def test_one_statement_preserves_both_rankings_and_fuses_current_identity(index: SeekDBMemoryIndex) -> None:
    connection = connection_with([row("fts", "b"), row("fts", "a"), row("vector", "a"), row("vector", "c")])
    channels = await index.search(cast(AsyncConnection, connection), "scope", request())

    assert connection.execute.await_count == 1
    assert [hit.entry_id for hit in channels.fts] == ["b", "a"]
    assert [hit.entry_id for hit in channels.vector] == ["a", "c"]
    assert all(hit.memory_ref == MEMORY for hit in (*channels.fts, *channels.vector))
    hits = fuse_rankings(fts=channels.fts, vector=channels.vector, limit=3)
    assert [hit.entry_id for hit in hits] == ["a", "b", "c"]
    assert hits[0].matched_by == ("fts", "vector")
    assert hits[0].text == "Exact body: 中文\na"
    assert len({(hit.memory_ref.artifact_id, hit.entry_id, hit.entry_version_id) for hit in hits}) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("channels", [(), ("fts",), ("vector",), ("fts", "vector")])
async def test_empty_or_one_sided_results_do_not_issue_fallback_queries(index: SeekDBMemoryIndex, channels) -> None:
    connection = connection_with([row(channel, "a") for channel in channels])
    result = await index.search(cast(AsyncConnection, connection), "scope", request())
    assert len(result.fts) == ("fts" in channels)
    assert len(result.vector) == ("vector" in channels)
    assert connection.execute.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("match", ["all", "any"])
@pytest.mark.parametrize("candidate_limit", [1, 32, 217])
async def test_filters_limits_and_hostile_values_are_bound_in_both_branches(
    index: SeekDBMemoryIndex, match: str, candidate_limit: int
) -> None:
    hostile = "雪'\\:x); DROP TABLE pc_memory_entry_heads; --"
    memories = (MEMORY, ArtifactRef(family="memory", artifact_id=hostile, revision=1))
    tag_filter = TagFilter.model_validate({"tags": (hostile, "second"), "match": match})
    connection = connection_with([])
    await index.search(
        cast(AsyncConnection, connection),
        hostile,
        request(analyzed_query=hostile, memories=memories, candidate_limit=candidate_limit, tag_filter=tag_filter),
    )
    statement, parameters = connection.execute.call_args.args
    compiled = statement.params(**parameters).compile(dialect=dialect(), compile_kwargs={"render_postcompile": True})
    sql = str(compiled)
    assert hostile not in sql
    assert compiled.params["scope_id"] == hostile
    assert compiled.params["query"] == hostile
    assert compiled.params["memory_artifact_ids_2"] == hostile
    assert compiled.params["tag_minimum"] == (2 if match == "all" else 1)
    assert compiled.params["candidate_limit"] == candidate_limit
    assert sql.count("LIMIT %s") == 2
    assert sql.count("scope_id = %s") == 2
    assert sql.count("memory_artifact_id IN") == 2
    assert sql.count("tag_key_hash IN") == 2
    assert sql.count("tag_key IN") == 2
    assert "tags.scope_id = f.scope_id" in sql
    assert "tags.scope_id = m.scope_id" in sql
    assert "UNION ALL" in sql
    assert "AGAINST" in sql and "APPROXIMATE" in sql and "l2_distance" in sql
    assert "head_revision =" not in sql


@pytest.mark.asyncio
async def test_unfiltered_statement_has_channel_limits_and_stable_outer_order(index: SeekDBMemoryIndex) -> None:
    connection = connection_with([])
    await index.search(cast(AsyncConnection, connection), "scope", request())
    statement, parameters = connection.execute.call_args.args
    sql = str(statement)
    assert "pc_artifact_tags" not in sql
    assert sql.count("LIMIT :candidate_limit") == 2
    assert sql.index("LIMIT :candidate_limit") < sql.index("UNION ALL")
    assert sql.rfind("LIMIT :candidate_limit") > sql.index("UNION ALL")
    assert sql.endswith("ORDER BY channel, fts_score DESC, distance, memory_artifact_id, entry_id, entry_version_id")
    assert parameters["query"] == "alpha"
    assert parameters["query_vector"] == (1.0, 0.0, 0.0)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["fts", "vector"])
async def test_single_channels_keep_existing_strategy(index: SeekDBMemoryIndex, mode: str, monkeypatch) -> None:
    from powercontext.builtin.artifacts.memory import MemorySearchChannels

    fts = AsyncMock(return_value=MemorySearchChannels())
    vector = AsyncMock(return_value=MemorySearchChannels())
    monkeypatch.setattr(OceanBaseMemoryFTSIndex, "search", fts)
    monkeypatch.setattr(OceanBaseMemoryVectorIndex, "search", vector)
    connection = connection_with([])
    current = request(mode=mode)
    assert await index.search(cast(AsyncConnection, connection), "scope", current) == MemorySearchChannels()
    fts.assert_awaited_once_with(connection, "scope", current)
    vector.assert_awaited_once_with(connection, "scope", current)
    connection.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"query_vector": None}, {"embedding_profile": None}])
async def test_missing_embedding_rejected_before_any_candidate_query(index: SeekDBMemoryIndex, changes) -> None:
    connection = connection_with([])
    with pytest.raises(CapabilityNotSupportedError, match="embedding-profile"):
        await index.search(cast(AsyncConnection, connection), "scope", request(**changes))
    connection.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_incomplete_projection_rejected_without_candidate_query(index: SeekDBMemoryIndex, monkeypatch) -> None:
    monkeypatch.setattr(index, "vector_complete", AsyncMock(return_value=False))
    connection = connection_with([])
    with pytest.raises(CapabilityNotSupportedError, match="vector"):
        await index.search(cast(AsyncConnection, connection), "scope", request())
    connection.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_head_error_propagates_without_candidate_query(index: SeekDBMemoryIndex, monkeypatch) -> None:
    error = CapabilityNotSupportedError("head")
    monkeypatch.setattr(index, "vector_complete", AsyncMock(side_effect=error))
    connection = connection_with([])
    with pytest.raises(CapabilityNotSupportedError) as caught:
        await index.search(cast(AsyncConnection, connection), "scope", request())
    assert caught.value is error
    connection.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_database_error_is_not_hidden_by_two_query_fallback(index: SeekDBMemoryIndex) -> None:
    error = RuntimeError("native query failed")
    connection = connection_with([])
    connection.execute.side_effect = error
    with pytest.raises(RuntimeError) as caught:
        await index.search(cast(AsyncConnection, connection), "scope", request())
    assert caught.value is error
    assert connection.execute.await_count == 1
