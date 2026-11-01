"""Provider-failure retries compose with durable evidence and lifecycle deltas."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from powercontext.artifacts import MemoryCitation
from powercontext.builtin.artifacts.memory import EmbeddingProfile, MemoryEntryInput
from powercontext.builtin.inference import EmbeddingResult, InferenceUsage
from powercontext.builtin.inference.coalescing import CoalescingEmbeddingModel
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    CaptureSource,
    GetMemoryEntryRequest,
    PrepareContextRequest,
    RememberMemoryRequest,
    SearchMemoryRequest,
    open_builtin_runtime,
)
from powercontext.builtin.runtime.context_pack import ContextPack
from powercontext.builtin.runtime.source_lifecycle import SourceLifecycleEvent
from powercontext.builtin.scope import ScopeDraft
from tests.e2e.test_integrated_evidence_delta import delivery

GOOD = "Cobalt stable evidence retains exact original text."
BAD = "Cobalt recovery evidence receives a valid vector on retry."


class RecoveryProvider:
    profile = EmbeddingProfile(profile_id="contract-integration", model="offline", dimension=2)

    def __init__(self, initial_failure):
        self.failure_pending = initial_failure
        self.calls = []

    async def embed(self, texts, /):
        self.calls.append(texts)
        if self.failure_pending and BAD in texts:
            self.failure_pending = False
            raise RuntimeError("offline embedding provider unavailable")  # noqa: TRY003
        return EmbeddingResult(
            vectors=tuple((0.0, 2.0) if text == BAD else (3.0, 4.0) for text in texts),
            usage=InferenceUsage(requests=3, input_tokens=7, output_tokens=2),
        )


async def remember(runtime, scope, text):
    result = await runtime.memory.for_scope(scope).remember(
        RememberMemoryRequest(entries=(MemoryEntryInput(kind="fact", text=text),))
    )
    assert result.entry is not None
    return result.entry


async def seed(runtime, model, provider, directory):
    primed = await model.embed((GOOD, GOOD))
    assert primed.vectors == ((3.0, 4.0), (3.0, 4.0))
    assert primed.usage == InferenceUsage(requests=3, input_tokens=7, output_tokens=2)
    # A provider exception, not a successful zero vector, is a retryable cache miss.
    with pytest.raises(RuntimeError, match="offline embedding provider unavailable"):
        await model.embed((BAD,))
    assert (await model.embed((GOOD, GOOD))).usage.requests == 0
    scopes = []
    for label in ("alpha", "beta"):
        scopes.append(
            (await runtime.scopes.create(ScopeDraft(title=label, summary=label, idempotency_key=label))).scope_id
        )
    first, other = await asyncio.gather(*(remember(runtime, scope, GOOD) for scope in scopes))
    recovered = await remember(runtime, scopes[0], BAD)
    assert provider.calls == [(GOOD,), (BAD,), (BAD,)]
    cached = await model.embed((BAD, GOOD, BAD))
    assert cached.vectors == ((0.0, 2.0), (3.0, 4.0), (0.0, 2.0))
    assert cached.usage.requests == 0
    lc = runtime.lifecycle.for_scope(scopes[0])
    support = await runtime.sources.for_scope(scopes[0]).capture(
        CaptureSource(source_id="retry-support", content=BAD, metadata={})
    )
    await lc.register_source("retry-source", support.source_ref, revision=1)
    await lc.register_memory("retry-memory", recovered.citation, parents=("retry-source",), policy="all")
    request = PrepareContextRequest(query="cobalt", max_bytes=4096, evidence_selection=True)
    base, fragments = await delivery(runtime, scopes[0], request, None, {scopes[0]})
    assert {fragment["citation"]["entry_id"] for fragment in fragments} == {
        first.citation.entry_id,
        recovered.citation.entry_id,
    }
    await lc.apply(
        SourceLifecycleEvent(node_id="retry-source", revision=1, sequence=1, available=False, reason="withdraw")
    )
    base, fragments = await delivery(runtime, scopes[0], request, base, {scopes[0]})
    assert {fragment["citation"]["entry_id"] for fragment in fragments} == {first.citation.entry_id}
    _, separate = await delivery(runtime, scopes[1], request, base, {scopes[1]})
    assert {fragment["citation"]["entry_id"] for fragment in separate} == {other.citation.entry_id}
    (directory / "receiver.pack").write_bytes(base.to_bytes())
    return {"scopes": scopes, "recovered": recovered.citation.model_dump(mode="json")}


async def resume(runtime, model, provider, directory, state):
    scope, other = state["scopes"]
    result = await runtime.memory.for_scope(scope).search(SearchMemoryRequest(query="cobalt", mode="vector"))
    assert [hit.text for hit in result.hits] == [GOOD]
    assert provider.calls == [("cobalt",)]
    assert (await model.embed_query(("cobalt", "cobalt"))).usage.requests == 0
    lc = runtime.lifecycle.for_scope(scope)
    event = SourceLifecycleEvent(node_id="retry-source", revision=1, sequence=2, available=True, reason="restore")
    active = await lc.apply(event)
    head = (await runtime.memory.for_scope(scope).list(include_inactive=True)).memory_ref
    assert await lc.apply(event) == active
    assert (await runtime.memory.for_scope(scope).list(include_inactive=True)).memory_ref == head
    request = PrepareContextRequest(query="cobalt", max_bytes=4096, evidence_selection=True)
    old = ContextPack.from_bytes((directory / "receiver.pack").read_bytes())
    new, fragments = await delivery(runtime, scope, request, old, {scope})
    assert new != old and len(fragments) == 2
    _, separate = await delivery(runtime, other, request, new, {other})
    assert len(separate) == 1 and BAD not in separate[0]["content"]
    original = await runtime.memory.for_scope(scope).get(
        GetMemoryEntryRequest(citation=MemoryCitation.model_validate(state["recovered"]))
    )
    assert original.entry.text == BAD
    # Native Memory retains active projections, while reactivation rebuilds the inactive entry's projection.
    assert provider.calls == [("cobalt",), (BAD,)], provider.calls
    assert (await model.embed((BAD, BAD))).usage.requests == 0
    assert provider.calls == [("cobalt",), (BAD,)]


async def worker(directory, phase):
    provider = RecoveryProvider(initial_failure=phase == "seed")
    model = CoalescingEmbeddingModel(provider, coalesce_ms=0)
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{directory / 'contract.db'}"))
    path = directory / "state.json"
    async with open_builtin_runtime(config, embedding_model=model) as runtime:
        if phase == "seed":
            state = await seed(runtime, model, provider, directory)
            path.write_text(json.dumps(state), encoding="utf-8")
        else:
            await resume(runtime, model, provider, directory, json.loads(path.read_text(encoding="utf-8")))


def test_provider_failure_retry_composes_with_scope_lifecycle_and_evidence_delta_on_restart(tmp_path):
    for phase in ("seed", "resume"):
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), str(tmp_path), phase],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr


def test_memory_unit_validation_does_not_change_wrapper_success_cache(tmp_path):
    class ZeroProvider:
        profile = EmbeddingProfile(profile_id="memory-zero-boundary", model="offline", dimension=2)

        def __init__(self):
            self.calls = []

        async def embed(self, texts, /):
            self.calls.append(texts)
            return EmbeddingResult(vectors=((0.0, 0.0),) * len(texts), usage=InferenceUsage(requests=1))

    async def scenario():
        provider = ZeroProvider()
        model = CoalescingEmbeddingModel(provider, coalesce_ms=0)
        first = await model.embed((GOOD,))
        assert first.vectors == ((0.0, 0.0),) and first.usage.requests == 1
        config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'boundary.db'}"))
        async with open_builtin_runtime(config, embedding_model=model) as runtime:
            assert runtime.scopes is not None
            scope = (
                await runtime.scopes.create(
                    ScopeDraft(title="boundary", summary="boundary", idempotency_key="boundary")
                )
            ).scope_id
            with pytest.raises(ValueError, match="non-zero norm"):
                await remember(runtime, scope, GOOD)
        cached = await model.embed((GOOD, GOOD))
        assert cached.vectors == ((0.0, 0.0), (0.0, 0.0))
        assert cached.usage.requests == 0
        assert provider.calls == [(GOOD,)]

    asyncio.run(scenario())


if __name__ == "__main__":
    asyncio.run(worker(Path(sys.argv[1]), sys.argv[2]))
