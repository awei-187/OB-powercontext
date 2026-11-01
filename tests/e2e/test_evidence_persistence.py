"""Exercise exact citations across independent SQLite runtime processes."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from powercontext.artifacts import MemoryCitation
from powercontext.builtin.artifacts.memory import MemoryCandidateRequest, MemoryEntryInput
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    CaptureSource,
    GetMemoryEntryRequest,
    PrepareContextRequest,
    RetireMemoryEntryRequest,
    ReviseMemoryEntryRequest,
    SearchMemoryRequest,
    open_builtin_runtime,
)
from powercontext.builtin.runtime.prepared_context import PreparedContextBuilder, PreparedMemoryCandidates
from powercontext.builtin.scope import ScopeDraft
from powercontext.builtin.sources import ContentSource


class LiteralPipeline:
    async def extract(self, request: MemoryCandidateRequest, /) -> tuple[MemoryEntryInput, ...]:
        return tuple(
            MemoryEntryInput(kind="document", text=source.content, sources=(source,))
            for source in request.sources
            if isinstance(source, ContentSource)
        )


async def stage(directory: Path, action: str) -> None:  # noqa: C901 -- one persisted lifecycle, in five processes
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{directory / 'memory.db'}"))
    manifest = directory / "citations.json"
    async with open_builtin_runtime(config, candidate_pipeline=LiteralPipeline()) as runtime:
        assert runtime.scopes is not None
        if action == "seed":
            scopes = []
            for name in ("left", "right"):
                scope = await runtime.scopes.create(ScopeDraft(title=name, summary=name, idempotency_key=name))
                scopes.append(scope.scope_id)
                sources = runtime.sources.for_scope(scope.scope_id)
                for index, text in enumerate((
                    "Administrative notes. " * 80 + "Cobalt sensor measured 37 degrees. 海洋 😀",
                    "Maintenance notes. " * 80 + "Amber valve measured 19 degrees.",
                )):
                    request = CaptureSource(source_id=f"document-{index}", content=text, metadata={})
                    first = await sources.capture(request)
                    again = await sources.capture(request)
                    assert first == again
                memory = runtime.memory.for_scope(scope.scope_id)
                while (await memory.flush()).processed:
                    pass
                page = await memory.search(SearchMemoryRequest(query="cobalt", mode="fts"))
                assert len(page.hits) == 1
                assert not (await memory.flush()).processed
                assert (
                    await memory.search(SearchMemoryRequest(query="cobalt", mode="fts"))
                ).memory_ref == page.memory_ref
            manifest.write_text(json.dumps({"scopes": scopes}), encoding="utf-8")
            return

        saved = json.loads(manifest.read_text(encoding="utf-8"))
        if action == "read":
            records = []
            outputs = []
            for query in ("cobalt", "amber"):
                groups = []
                for scope_id in saved["scopes"]:
                    memory = runtime.memory.for_scope(scope_id)
                    page = await memory.search(SearchMemoryRequest(query=query, mode="fts"))
                    groups.append(PreparedMemoryCandidates(scope_id, page.memory_ref, page.hits))
                    prepared = await runtime.context.for_scope(scope_id).prepare(
                        PrepareContextRequest(query=query, max_bytes=1200, evidence_selection=True)
                    )
                    assert prepared.content is not None and query.capitalize() in prepared.content
                for budget in (512, 700, 900, 1200, 1800, 32768):
                    result = PreparedContextBuilder().build_scopes_result(
                        request=PrepareContextRequest(query=query, max_bytes=budget, evidence_selection=True),
                        current_scope_id=saved["scopes"][0],
                        memory_candidates=groups,
                    )
                    assert result.context.content_bytes == len((result.context.content or "").encode("utf-8")) <= budget
                    assert result.origins == tuple(fragment.address for fragment in result.fragments)
                    outputs.append(result.context.model_dump(mode="json"))
                    for fragment in result.fragments:
                        address = fragment.address
                        citation = MemoryCitation(
                            memory_ref=address.memory.artifact,
                            entry_id=address.entry_id,
                            entry_version_id=address.entry_version_id,
                        )
                        record = await runtime.memory.for_scope(address.memory.scope_id).get(
                            GetMemoryEntryRequest(citation=citation)
                        )
                        assert record.entry.text[fragment.start : fragment.end] == fragment.text
                        if budget == 1800:
                            records.append({
                                "scope_id": address.memory.scope_id,
                                "citation": citation.model_dump(mode="json"),
                                "start": fragment.start,
                                "end": fragment.end,
                                "text": fragment.text,
                            })
                    if budget >= 1800:
                        assert {fragment.address.memory.scope_id for fragment in result.fragments} == set(
                            saved["scopes"]
                        )
            if "records" in saved:
                assert saved["records"] == records
                assert saved["outputs"] == outputs
            saved["records"] = records
            saved["outputs"] = outputs
            manifest.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
            return

        if action == "mutate":
            for index, scope_id in enumerate(saved["scopes"]):
                memory = runtime.memory.for_scope(scope_id)
                old = next(record for record in saved["records"] if record["scope_id"] == scope_id)
                citation = MemoryCitation.model_validate(old["citation"])
                if index == 0:
                    await memory.revise(
                        ReviseMemoryEntryRequest(
                            citation=citation,
                            kind="document",
                            text="Cobalt sensor now measured 42 degrees.",
                        )
                    )
                else:
                    await memory.retire(RetireMemoryEntryRequest(citation=citation, reason="withdrawn"))
            return

        assert action == "verify"
        for old in saved["records"]:
            record = await runtime.memory.for_scope(old["scope_id"]).get(
                GetMemoryEntryRequest(citation=MemoryCitation.model_validate(old["citation"]))
            )
            assert record.entry.text[old["start"] : old["end"]] == old["text"]
        for index, scope_id in enumerate(saved["scopes"]):
            prepared = await runtime.context.for_scope(scope_id).prepare(
                PrepareContextRequest(query="cobalt", evidence_selection=True, max_bytes=1200)
            )
            if index == 0:
                assert prepared.content is not None
                items = json.loads(prepared.content.splitlines()[-2])["items"]
                assert [item["content"] for item in items] == ["Cobalt sensor now measured 42 degrees."]
            else:
                assert prepared.status == "empty"


def test_persistent_citations_scopes_idempotence_and_revision_restart(tmp_path: Path) -> None:
    for index, action in enumerate(("seed", "read", "read", "mutate", "verify")):
        environment = dict(os.environ, PYTHONHASHSEED=str(index + 1))
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), str(tmp_path), action],
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )
        assert completed.returncode == 0, f"{action}: {completed.stdout}\n{completed.stderr}"


if __name__ == "__main__":
    asyncio.run(stage(Path(sys.argv[1]), sys.argv[2]))
