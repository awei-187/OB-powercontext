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

"""Native seekdb process-restart tests, plus a separately reported SQLite regression.

The native case requires pylibseekdb. SQLite does not validate the seekdb SQL.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import Engine, event

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory import (
    CapabilityNotSupportedError,
    EmbeddingProfile,
    MemoryEntryInput,
    MemorySearchRequest,
)
from powercontext.builtin.inference import EmbeddingResult
from powercontext.builtin.persistence.seekdb import SeekDBConfig
from powercontext.builtin.persistence.seekdb.memory_index import SeekDBMemoryIndex
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import BuiltinConfig, open_builtin_contexts
from powercontext.builtin.tags import MemoryEntryTagTarget, TagFilter

PROFILE = EmbeddingProfile(profile_id="restart-test", model="test", dimension=3, distance="l2", normalization="unit")


class Embedding:
    profile = PROFILE

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        return EmbeddingResult(
            vectors=tuple((1.0, 0.0, 0.0) if "alpha" in t.lower() else (0.0, 1.0, 0.0) for t in texts)
        )


def config(root: Path, backend: str) -> BuiltinConfig:
    database = (
        SeekDBConfig(path=root / "native")
        if backend == "seekdb"
        else SQLiteConfig(url=f"sqlite+aiosqlite:///{root / 'sqlite.db'}")
    )
    return BuiltinConfig(database=database)


def identities(result) -> list[dict[str, object]]:
    return [
        {
            "memory": hit.memory_ref.model_dump(mode="json"),
            "entry": hit.entry_id,
            "version": hit.entry_version_id,
            "text": hit.text,
            "channels": list(hit.matched_by),
        }
        for hit in result.hits
    ]


async def seed(root: Path, backend: str) -> None:
    saved: dict[str, object] = {}
    async with open_builtin_contexts(config(root, backend), embedding_model=Embedding()) as contexts:
        for scope in ("project", "other'雪;--"):
            memory = (await contexts.get(scope)).artifacts.memory
            first = await memory.remember(
                memory=None,
                entries=(MemoryEntryInput(kind="fact", text=f"Alpha original {scope}."),),
                mode="append",
            )
            assert first is not None
            second = await memory.remember(
                memory=first,
                entries=(MemoryEntryInput(kind="fact", text=f"Beta lexical {scope}."),),
                mode="append",
            )
            assert second is not None
            unchanged = await memory.search("alpha", memories=(second,), mode="hybrid", limit=1)
            assert unchanged.hits[0].text == f"Alpha original {scope}."
            assert unchanged.hits[0].memory_ref == second.as_ref()
            with pytest.raises(CapabilityNotSupportedError):
                await memory.search("alpha", memories=(first,), mode="hybrid")
            alpha = next(entry for entry in await memory.entries(second) if entry.text.startswith("Alpha"))
            revised = await memory.remember(
                memory=second,
                entries=(MemoryEntryInput(kind="fact", text=f"Alpha revised {scope}.\n精确正文", entry=alpha),),
                mode="append",
            )
            assert revised is not None
            current = next(entry for entry in await memory.entries(revised) if entry.entry_id == alpha.entry_id)
            assert current.entry_version_id != alpha.entry_version_id
            inactive = await memory.forget(revised, entries=(current,))
            assert (await memory.search("alpha", memories=(inactive,), mode="hybrid")).hits == ()
            restored = await memory.reactivate(inactive, entries=(current,))
            hit = (await memory.search("alpha", memories=(restored,), mode="hybrid", limit=1)).hits[0]
            assert hit.entry_version_id == current.entry_version_id
            assert hit.memory_ref == restored.as_ref()
            assert hit.matched_by == ("fts", "vector")
            target = MemoryEntryTagTarget(artifact_id=restored.artifact_id, entry_id=current.entry_id)
            empty = await contexts.records.get_tags(scope, target)
            await contexts.records.replace_tags(scope, target, ("selected'雪", "shared"), expected_etag=empty.etag)
            saved[scope] = {
                "head": restored.as_ref().model_dump(mode="json"),
                "hit": identities(await memory.search("alpha", memories=(restored,), mode="hybrid", limit=1)),
            }

        memory = (await contexts.get("ties")).artifacts.memory
        tied = await memory.remember(
            memory=None,
            entries=tuple(MemoryEntryInput(kind="fact", text=f"Alpha tied record {number}.") for number in range(45)),
            mode="append",
        )
        assert tied is not None
        saved["ties"] = tied.as_ref().model_dump(mode="json")
    (root / "saved.json").write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")


async def verify(root: Path, backend: str) -> None:
    saved = json.loads((root / "saved.json").read_text(encoding="utf-8"))
    async with open_builtin_contexts(config(root, backend), embedding_model=Embedding()) as contexts:
        for scope in ("project", "other'雪;--"):
            memory = (await contexts.get(scope)).artifacts.memory
            head = await memory.revision(ArtifactRef.model_validate(saved[scope]["head"]))
            for _ in range(3):
                result = await memory.search("alpha", memories=(head,), mode="hybrid", limit=1)
                assert identities(result) == saved[scope]["hit"]
                expanded = await memory.expand(result.hits)
                assert expanded[0].text == result.hits[0].text
                assert expanded[0].entry_version_id == result.hits[0].entry_version_id
            for match in ("all", "any"):
                tagged = await memory.search(
                    "alpha",
                    memories=(head,),
                    mode="hybrid",
                    limit=1,
                    tag_filter=TagFilter.model_validate({"tags": ("selected'雪", "shared"), "match": match}),
                )
                assert identities(tagged) == saved[scope]["hit"]
            empty = await memory.search(
                "alpha", memories=(head,), mode="hybrid", tag_filter=TagFilter(tags=("missing",))
            )
            assert empty.hits == ()
            for mode in ("fts", "vector"):
                result = await memory.search("beta", memories=(head,), mode=mode)
                assert result.hits[0].text == f"Beta lexical {scope}."

        memory = (await contexts.get("ties")).artifacts.memory
        tied = await memory.revision(ArtifactRef.model_validate(saved["ties"]))
        first = identities(await memory.search("alpha", memories=(tied,), mode="hybrid", limit=10))
        assert len(first) == 10
        assert len({hit["entry"] for hit in first}) == 10
        for _ in range(5):
            assert identities(await memory.search("alpha", memories=(tied,), mode="hybrid", limit=10)) == first
        if backend == "seekdb":
            await verify_native_sql(contexts, tied.as_ref())


async def verify_native_sql(contexts, tied: ArtifactRef) -> None:
    index = SeekDBMemoryIndex(PROFILE)
    for tag_filter in (None, TagFilter(tags=("missing",))):
        statements: list[tuple[str, object]] = []

        def record(_connection, _cursor, statement, parameters, _context, _executemany, captured=statements) -> None:
            captured.append((statement, parameters))

        event.listen(Engine, "before_cursor_execute", record)
        try:
            async with contexts.database.transaction() as connection:
                result = await index.search(
                    connection,
                    "ties",
                    MemorySearchRequest(
                        query="alpha",
                        analyzed_query="alpha",
                        memories=(tied,),
                        candidate_limit=2,
                        mode="hybrid",
                        query_vector=(1.0, 0.0, 0.0),
                        embedding_profile=PROFILE,
                        tag_filter=tag_filter,
                    ),
                )
        finally:
            event.remove(Engine, "before_cursor_execute", record)
        native = [(sql, params) for sql, params in statements if "AGAINST" in sql.upper() or "l2_distance" in sql]
        assert len(native) == 1
        sql, parameters = native[0]
        assert "AGAINST" in sql.upper() and "l2_distance" in sql
        expected = 2 if tag_filter is None else 0
        assert len(result.fts) == len(result.vector) == expected
        async with contexts.database.transaction() as connection:
            plan = "\n".join(
                str(row[0]) for row in (await connection.exec_driver_sql(f"EXPLAIN {sql}", parameters)).all()
            )
        assert "TEXT RETRIEVAL SCAN" in plan
        assert "VECTOR INDEX" in plan


@pytest.mark.parametrize("backend", ["sqlite", "seekdb"])
def test_hybrid_persists_across_process_restart_and_isolates_scopes(tmp_path: Path, backend: str) -> None:
    if backend == "seekdb" and importlib.util.find_spec("pylibseekdb") is None:
        pytest.skip("Native seekdb requires pylibseekdb on a supported platform; SQLite is a separate regression only")
    for phase in ("seed", "verify"):
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), phase, str(tmp_path), backend],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=180,
        )
        assert result.returncode == 0, result.stdout + result.stderr


if __name__ == "__main__":
    asyncio.run((seed if sys.argv[1] == "seed" else verify)(Path(sys.argv[2]), sys.argv[3]))
