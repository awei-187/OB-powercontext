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

"""Real SQLite evidence and citation readback across separate Python processes."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.artifacts.memory.models import MemoryCitation
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    GetMemoryEntryRequest,
    SearchMemoryRequest,
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
from powercontext.sources.csv_rows import (
    CSV_ROW_SOURCE_DEFINITION,
    CSVDocumentInput,
    CSVRowInput,
    CSVRowSource,
    parse_csv_document,
)
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY


class RowPipeline:
    async def extract(self, request, /) -> tuple[MemoryEntryInput, ...]:
        return tuple(
            MemoryEntryInput(
                kind="csv-row", text=source.projection(TEXT_EVIDENCE_PROJECTION_KEY)["content"], sources=(source,)
            )
            for source in request.sources
        )


async def ingest(directory: Path, config: BuiltinConfig) -> None:
    registry = SourceDefinitionRegistry((CSV_ROW_SOURCE_DEFINITION,))
    expected = []
    async with open_builtin_runtime(config) as runtime:
        assert runtime.scopes is not None
        await runtime.ingestion.register(manifest_for_definition(CSV_ROW_SOURCE_DEFINITION))
        for index in range(2):
            scope = await runtime.scopes.create(
                ScopeDraft(title=f"CSV {index}", summary="Rows", idempotency_key=str(index))
            )
            rows = parse_csv_document(
                CSVDocumentInput(
                    document_id="document:/雪", primary_key=" id ", content=(directory / f"{index}.csv").read_bytes()
                )
            )
            observations = [project_source_for_transport(registry, await registry.resolve(row)) for row in rows]
            # Repeat in a different order; stable observations must not create duplicate journal entries.
            for observation in [*observations, *reversed(observations)]:
                await runtime.ingestion.submit(
                    SubmitSourceObservation(scope_id=scope.scope_id, observation=observation)
                )
            expected.append({"scope_id": scope.scope_id, "rows": [row.model_dump(mode="json") for row in rows]})
    (directory / "expected.json").write_text(json.dumps(expected, ensure_ascii=False), encoding="utf-8")


async def retrieve(directory: Path, config: BuiltinConfig) -> None:
    expected = json.loads((directory / "expected.json").read_text(encoding="utf-8"))
    registry = SourceDefinitionRegistry((CSV_ROW_SOURCE_DEFINITION,))
    async with open_builtin_contexts(config) as contexts:
        for scope in expected:
            entries = await (await contexts.get(scope["scope_id"])).sources.journal.entries()
            assert len(entries) == len(scope["rows"])
            expected_by_key = {row["primary_key_value"]: row for row in scope["rows"]}
            for entry in entries:
                assert isinstance(entry.source, SourceObservation)
                source = CSVRowSource.model_validate(entry.source.payload)
                row = await registry.read(source)
                assert isinstance(row, CSVRowInput)
                assert row.model_dump(mode="json") == expected_by_key[row.primary_key_value]
                assert entry.source.projection(TEXT_EVIDENCE_PROJECTION_KEY) == registry.project(
                    source, TEXT_EVIDENCE_PROJECTION_KEY
                )
                # Dictionary equality cannot detect RFC 8785's recursive key sorting.
                evidence = entry.source.projection(TEXT_EVIDENCE_PROJECTION_KEY)
                assert isinstance(evidence, dict) and isinstance(evidence["metadata"], dict)
                mapping = evidence["metadata"]["row"]
                assert isinstance(mapping, dict)
                assert list(mapping) == list(row.columns)
                projected = registry.project(entry.source, TEXT_EVIDENCE_PROJECTION_KEY)
                assert isinstance(projected, dict) and isinstance(projected["metadata"], dict)
                projected_row = projected["metadata"]["row"]
                assert isinstance(projected_row, dict)
                assert list(projected_row) == list(row.columns)

    citations = []
    async with open_builtin_runtime(config, candidate_pipeline=RowPipeline()) as runtime:
        for index, scope in enumerate(expected):
            memory = runtime.memory.for_scope(scope["scope_id"])
            processed = 0
            for _ in range(len(scope["rows"]) + 1):
                result = await memory.flush()
                if not result.processed:
                    break
                processed += result.source_count
            assert processed == len(scope["rows"])
            own_query, other_query = (
                ("Zephyrharbor", "Moonlitdelta") if index == 0 else ("Moonlitdelta", "Zephyrharbor")
            )
            assert not (await memory.search(SearchMemoryRequest(query=other_query, mode="fts"))).hits
            hits = (await memory.search(SearchMemoryRequest(query=own_query, mode="fts", limit=10))).hits
            assert len(hits) == 1
            hit = hits[0]
            citation = MemoryCitation(
                memory_ref=hit.memory_ref, entry_id=hit.entry_id, entry_version_id=hit.entry_version_id
            )
            result = await memory.get(GetMemoryEntryRequest(citation=citation))
            row = scope["rows"][0]
            mapping = dict(zip(row["columns"], row["values"], strict=True))
            assert result.entry.text == json.dumps(mapping, ensure_ascii=False, separators=(",", ":"))
            assert result.entry.sources[0].source_type == "csv-row"
            citations.append({
                "scope_id": scope["scope_id"],
                "citation": citation.model_dump(mode="json"),
                "text": result.entry.text,
            })
    (directory / "citations.json").write_text(json.dumps(citations, ensure_ascii=False), encoding="utf-8")


async def read_citations(directory: Path, config: BuiltinConfig) -> None:
    citations = json.loads((directory / "citations.json").read_text(encoding="utf-8"))
    async with open_builtin_runtime(config) as runtime:
        for saved in citations:
            entry = await runtime.memory.for_scope(saved["scope_id"]).get(
                GetMemoryEntryRequest(citation=MemoryCitation.model_validate(saved["citation"]))
            )
            assert entry.entry.text == saved["text"]


def test_rows_survive_process_restart_without_csv_files_and_remain_scope_isolated(tmp_path: Path) -> None:
    for index, name in enumerate(("Zephyrharbor", "Moonlitdelta")):
        (tmp_path / f"{index}.csv").write_bytes(
            f'\ufeff" id ",z,a,empty\r\n" key:/% ",{name},"雪\r\n\r\n""quoted""",\r\n002,false,001,\r\n'.encode()
        )
    for stage in ("ingest", "retrieve", "citations"):
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), stage, str(tmp_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=90,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        if stage == "ingest":
            for index in range(2):
                (tmp_path / f"{index}.csv").unlink()


if __name__ == "__main__":
    directory = Path(sys.argv[2])
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{directory / 'rows.db'}"))
    operation = {"ingest": ingest, "retrieve": retrieve, "citations": read_citations}[sys.argv[1]]
    asyncio.run(operation(directory, config))
