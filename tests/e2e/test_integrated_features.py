"""Four-feature acceptance through real SQLite, HTTP and separate OS processes."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

import httpx
import pytest
import typing_extensions

from powercontext.builtin.artifacts.memory import HTTPMemoryReranker, MemoryEntryInput
from powercontext.builtin.artifacts.memory.models import MemoryCitation
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    CommitConnectorCheckpoint,
    GetMemoryEntryRequest,
    PrepareContextRequest,
    SearchMemoryRequest,
    SubmitSourceObservation,
    open_builtin_contexts,
    open_builtin_runtime,
)
from powercontext.builtin.runtime.context_pack import ContextPack, ContextPackDelta, apply_context_pack_delta
from powercontext.builtin.scope import ScopeDraft
from powercontext.sources import (
    ConnectorBinding,
    SourceDefinitionRegistry,
    SourceObservation,
    manifest_for_definition,
    project_source_for_transport,
)
from powercontext.sources.connectors import ConnectorLifecycle
from powercontext.sources.csv_rows import CSV_ROW_SOURCE_DEFINITION, CSVDocumentInput, CSVRowInput, parse_csv_document
from powercontext.sources.pi_session import PI_EVENT_SOURCE_DEFINITION, PiEventInput, PiSessionConnector
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY


class EvidencePipeline:
    async def extract(self, request, /) -> tuple[MemoryEntryInput, ...]:
        return tuple(
            MemoryEntryInput(
                kind="evidence", text=source.projection(TEXT_EVIDENCE_PROJECTION_KEY)["content"], sources=(source,)
            )
            for source in request.sources
        )


def write_session(path: Path, word: str, *, append: bool = False) -> None:
    records = [
        {"type": "session", "version": 3, "id": "shared-session"},
        {
            "type": "message",
            "id": "root",
            "parentId": None,
            "message": {"role": "user", "content": f"integrated {word} Pi root"},
        },
        {
            "type": "message",
            "id": "numeric",
            "parentId": "root",
            "message": {
                "role": "assistant",
                "content": f"integrated {word} Pi numeric",
                "details": {"integer": 10**100},
            },
        },
    ]
    if append:
        records.append({
            "type": "message",
            "id": "tail",
            "parentId": "numeric",
            "message": {"role": "user", "content": f"integrated {word} Pi appended"},
        })
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


async def run_connector(runtime, registry, binding, path):
    # These adapters call the real ingestion/checkpoint APIs; no project class is mocked.
    class Sink:
        async def submit(self, binding, item_id, definition_name, value, /):
            observation = project_source_for_transport(registry, await registry.resolve(value))
            result = await runtime.ingestion.submit(
                SubmitSourceObservation(scope_id=binding.scope_id, observation=observation)
            )
            return result.source_ref

    class Checkpoints:
        async def load(self, binding, /):
            return (await runtime.ingestion.checkpoint(binding)).checkpoint

        async def save(self, binding, checkpoint, /, *, expected):
            await runtime.ingestion.commit(
                CommitConnectorCheckpoint(binding=binding, checkpoint=checkpoint, expected=expected)
            )

    return await ConnectorLifecycle(sink=Sink(), checkpoints=Checkpoints()).run(PiSessionConnector(path), binding)


async def reconstruct(context, request, base=None):
    expected = await context.prepare(request)
    delivery = await context.prepare_incremental(request, base)
    if base is None:
        assert isinstance(delivery, ContextPack)
        received = ContextPack.from_bytes(delivery.to_bytes())
    else:
        assert isinstance(delivery, ContextPackDelta)
        received = apply_context_pack_delta(base, ContextPackDelta.from_bytes(delivery.to_bytes()))
    assert b"".join(received.items) == (expected.content or "").encode()
    return received


async def verify_persisted_evidence(config, registry, state, phase):
    async with open_builtin_contexts(config) as contexts:
        for word in ("amber", "violet"):
            entries = await (await contexts.get(state[word]["scope"])).sources.journal.entries()
            assert len(entries) == (4 if word == "amber" and phase != "seed" else 3)
            for entry in entries:
                assert isinstance(entry.source, SourceObservation)
                definition = (
                    CSV_ROW_SOURCE_DEFINITION if entry.source.source_type == "csv-row" else PI_EVENT_SOURCE_DEFINITION
                )
                readback = await registry.read(definition.source_class.model_validate(entry.source.payload))
                if isinstance(readback, CSVRowInput):
                    evidence = entry.source.projection(TEXT_EVIDENCE_PROJECTION_KEY)
                    assert isinstance(evidence, dict) and isinstance(evidence["metadata"], dict)
                    row_mapping = evidence["metadata"]["row"]
                    assert isinstance(row_mapping, dict)
                    assert list(row_mapping) == ["id", "z", "a"] and row_mapping["a"] == "001"
                else:
                    assert isinstance(readback, PiEventInput)
                    if readback.event_id == "numeric":
                        number = readback.record["message"]["details"]["integer"]
                        assert type(number) is int and number == 10**100


async def ingest_evidence(runtime, registry, binding, directory, word, phase):
    scope_id = binding.scope_id
    row = parse_csv_document(
        CSVDocumentInput(
            document_id="shared-csv",
            primary_key="id",
            content=f"id,z,a\n1,integrated {word} CSV,001\n".encode(),
        )
    )[0]
    observation = project_source_for_transport(registry, await registry.resolve(row))
    for _ in range(2):
        await runtime.ingestion.submit(SubmitSourceObservation(scope_id=scope_id, observation=observation))
    if phase != "final":
        first = await run_connector(runtime, registry, binding, directory / f"{word}.jsonl")
        assert len(first.items) == (2 if phase == "seed" else 0)
        assert (await run_connector(runtime, registry, binding, directory / f"{word}.jsonl")).items == ()
        if phase == "resume" and word == "amber":
            write_session(directory / f"{word}.jsonl", word, append=True)
            assert len((await run_connector(runtime, registry, binding, directory / f"{word}.jsonl")).items) == 1
            assert (await run_connector(runtime, registry, binding, directory / f"{word}.jsonl")).items == ()


async def scenario(directory: Path, phase: str, endpoint: str, requests: list[dict[str, Any]]) -> None:
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{directory / 'combined.db'}"))
    registry = SourceDefinitionRegistry((CSV_ROW_SOURCE_DEFINITION, PI_EVENT_SOURCE_DEFINITION))
    state_path = directory / "state.json"
    state = {} if phase == "seed" else json.loads(state_path.read_text(encoding="utf-8"))
    async with httpx.AsyncClient(
        trust_env=False,
        timeout=10,
        headers={"Authorization": "Bearer local-test"},
        auth=httpx.DigestAuth("unused", "unused"),
    ) as client:
        reranker = HTTPMemoryReranker(endpoint, client=client, batch_size=2)
        async with open_builtin_runtime(
            config, candidate_pipeline=EvidencePipeline(), memory_reranker=reranker
        ) as runtime:
            assert runtime.scopes is not None
            for definition in (CSV_ROW_SOURCE_DEFINITION, PI_EVENT_SOURCE_DEFINITION):
                await runtime.ingestion.register(manifest_for_definition(definition))
            for word in ("amber", "violet"):
                if phase == "seed":
                    scope = await runtime.scopes.create(ScopeDraft(title=word, summary=word, idempotency_key=word))
                    state[word] = {"scope": scope.scope_id}
                    write_session(directory / f"{word}.jsonl", word)
                scope_id = state[word]["scope"]
                binding = ConnectorBinding(
                    scope_id=scope_id, binding_id="pi", connector_name="pi-session-history", connector_version="1"
                )
                assert (
                    phase == "seed"
                    or (await runtime.ingestion.checkpoint(binding)).checkpoint == state[word]["checkpoint"]
                )
                await ingest_evidence(runtime, registry, binding, directory, word, phase)
                memory = runtime.memory.for_scope(scope_id)
                while (await memory.flush()).processed:
                    pass
                start = len(requests)
                page = await memory.search(SearchMemoryRequest(query="integrated", mode="fts", limit=8))
                assert page.rerank is not None
                batches = requests[start:]
                count = len(page.rerank.candidate_hits)
                assert page.rerank.usage.requests == len(batches) == (count + 1) // 2
                assert sorted(c["rank"] for batch in batches for c in batch["candidates"]) == list(range(1, count + 1))
                assert "Pi" in page.hits[0].text
                other = "violet" if word == "amber" else "amber"
                assert all(word in hit.text and other not in hit.text for hit in page.hits)
                assert any("CSV" in hit.text for hit in page.hits)
                for hit in page.hits:
                    citation = MemoryCitation(
                        memory_ref=hit.memory_ref, entry_id=hit.entry_id, entry_version_id=hit.entry_version_id
                    )
                    assert (await memory.get(GetMemoryEntryRequest(citation=citation))).entry.text == hit.text
                if phase == "seed":
                    state[word]["citations"] = [
                        {
                            "citation": MemoryCitation(
                                memory_ref=h.memory_ref, entry_id=h.entry_id, entry_version_id=h.entry_version_id
                            ).model_dump(mode="json"),
                            "text": h.text,
                        }
                        for h in page.hits
                    ]
                else:
                    for saved in state[word]["citations"]:
                        assert (
                            await memory.get(
                                GetMemoryEntryRequest(citation=MemoryCitation.model_validate(saved["citation"]))
                            )
                        ).entry.text == saved["text"]
                request = PrepareContextRequest(query="integrated", max_bytes=16000)
                context = runtime.context.for_scope(scope_id)
                pack_path = directory / f"{word}.pack"
                base = None if phase == "seed" else ContextPack.from_bytes(pack_path.read_bytes())
                pack = await reconstruct(context, request, base)
                assert phase != "resume" or word != "amber" or pack != base
                assert phase != "final" or pack == base
                assert word.encode() in b"".join(pack.items) and other.encode() not in b"".join(pack.items)
                assert await reconstruct(context, request, pack) == pack
                pack_path.write_bytes(pack.to_bytes())
                if phase != "seed":
                    foreign = ContextPack.from_bytes((directory / f"{other}.pack").read_bytes())
                    assert await reconstruct(context, request, foreign) == pack

                async def deny(_ids):
                    raise PermissionError("scope denied")  # noqa: TRY003

                with pytest.raises(PermissionError):
                    await context.prepare_incremental(request, pack, authorize_scopes=deny)
                state[word]["checkpoint"] = (await runtime.ingestion.checkpoint(binding)).checkpoint
                assert state[word]["checkpoint"] is not None
        assert not client.is_closed
    await verify_persisted_evidence(config, registry, state, phase)
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(
        json.dumps({
            "phase": phase,
            "http_requests": len(requests),
            "sqlite": str(directory / "combined.db"),
            "module": __import__("powercontext").__file__,
        })
    )


def worker(directory: Path, phase: str) -> None:
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            assert self.headers["Authorization"] == "Bearer local-test"
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            payload = json.dumps({
                "scores": [
                    {"rank": c["rank"], "score": (100 if "Pi" in c["text"] else 10) - c["rank"]}
                    for c in body["candidates"]
                ]
            }).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        @typing_extensions.override
        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        asyncio.run(scenario(directory, phase, f"http://127.0.0.1:{server.server_port}/rank", requests))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_four_features_share_sqlite_across_processes_without_scope_or_identity_loss(tmp_path: Path) -> None:
    for phase in ("seed", "resume", "final"):
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), str(tmp_path), phase],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=90,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        print(result.stdout.strip())
        if phase == "resume":
            for word in ("amber", "violet"):
                (tmp_path / f"{word}.jsonl").write_bytes(b"provider no longer available")


if __name__ == "__main__":
    worker(Path(sys.argv[1]), sys.argv[2])
