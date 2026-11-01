"""SQLite-backed incremental delivery across mutations, scopes, and restarts."""

from __future__ import annotations

import asyncio
import gzip
import json

import pytest

from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    GetMemoryEntryRequest,
    PrepareContextRequest,
    RememberMemoryRequest,
    RetireMemoryEntryRequest,
    ReviseMemoryEntryRequest,
    open_builtin_runtime,
)
from powercontext.builtin.runtime.application import ScopedContextApplication
from powercontext.builtin.runtime.context_pack import (
    ContextPack,
    ContextPackDelta,
    ContextPackError,
    apply_context_pack_delta,
)
from powercontext.builtin.scope import ScopeDraft, ScopeNotFoundError


async def _reconstruct(context: ScopedContextApplication, request: PrepareContextRequest, base: ContextPack | None):
    expected = await context.prepare(request)
    value = await context.prepare_incremental(request, base)
    if base is None:
        assert isinstance(value, ContextPack)
        result = ContextPack.from_bytes(value.to_bytes())
    else:
        assert isinstance(value, ContextPackDelta)
        result = apply_context_pack_delta(
            ContextPack.from_bytes(base.to_bytes()), ContextPackDelta.from_bytes(value.to_bytes())
        )
    assert b"".join(result.items) == (expected.content or "").encode()
    assert len(b"".join(result.items)) <= request.max_bytes
    return result


def test_persisted_runtime_mutations_scope_budget_and_recovery(tmp_path):
    async def scenario():
        config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'delta.db'}"))
        request = PrepareContextRequest(query="orchard", max_bytes=4096)
        async with open_builtin_runtime(config) as runtime:
            assert runtime.scopes is not None
            scope = await runtime.scopes.create(ScopeDraft(title="Orchard", summary="A", idempotency_key="a"))
            other = await runtime.scopes.create(ScopeDraft(title="Other", summary="B", idempotency_key="b"))
            context = runtime.context.for_scope(scope.scope_id)
            memory = runtime.memory.for_scope(scope.scope_id)
            empty = await _reconstruct(context, request, None)
            assert empty.items == ()
            created = await memory.remember(
                RememberMemoryRequest(entries=(MemoryEntryInput(kind="fact", text="orchard apples 海洋🙂"),))
            )
            assert created.entry is not None
            base = await _reconstruct(context, request, empty)
            assert b"orchard apples" in b"".join(base.items)
            await runtime.memory.for_scope(other.scope_id).remember(
                RememberMemoryRequest(
                    entries=(MemoryEntryInput(kind="fact", text="orchard secret from another scope"),)
                )
            )
            base = await _reconstruct(context, request, base)
            assert b"secret" not in b"".join(base.items)
            unchanged = await context.prepare_incremental(request, base)
            assert isinstance(unchanged, ContextPackDelta)
            assert unchanged.appended == () and unchanged.target_digest == base.digest
            revised = await memory.revise(
                ReviseMemoryEntryRequest(citation=created.entry.citation, kind="fact", text="orchard pears 海洋🙂")
            )
            assert revised.entry is not None
            base = await _reconstruct(context, request, base)
            assert b"orchard pears" in b"".join(base.items)
            assert b"orchard apples" not in b"".join(base.items)
            historical = await memory.get(GetMemoryEntryRequest(citation=created.entry.citation))
            assert historical.entry.text == "orchard apples 海洋🙂"
            await memory.retire(RetireMemoryEntryRequest(citation=revised.entry.citation))
            base = await _reconstruct(context, request, base)
            assert base.items == ()
            await memory.remember(
                RememberMemoryRequest(
                    entries=(MemoryEntryInput(kind="fact", text="orchard restored " + "海洋🙂" * 200),)
                )
            )
            base = await _reconstruct(context, request, base)
            (tmp_path / "base.json").write_bytes(base.to_bytes())

        async with open_builtin_runtime(config) as runtime:
            context = runtime.context.for_scope(scope.scope_id)
            restored = ContextPack.from_bytes((tmp_path / "base.json").read_bytes())
            assert await _reconstruct(context, request, restored) == restored
            for budget in (512, 700, 1024, 4096, 32768):
                restored = await _reconstruct(
                    context, PrepareContextRequest(query="orchard", max_bytes=budget), restored
                )
            no_match = await _reconstruct(context, PrepareContextRequest(query="unfindableterm"), restored)
            assert no_match.items == ()
            # A caller may supply any valid content pack. It never changes scope selection.
            other_base = await _reconstruct(runtime.context.for_scope(other.scope_id), request, None)
            rebuilt = await _reconstruct(context, request, other_base)
            assert b"secret" not in b"".join(rebuilt.items)
            delta = await context.prepare_incremental(request, other_base)
            assert isinstance(delta, ContextPackDelta)
            with pytest.raises(ContextPackError):
                apply_context_pack_delta(ContextPack.build(()), delta)
            fresh = await _reconstruct(context, request, None)
            assert fresh == rebuilt

            async def deny(_scope_ids):
                raise PermissionError("scope-denied")

            with pytest.raises(PermissionError):
                await context.prepare_incremental(request, authorize_scopes=deny)
            with pytest.raises(ScopeNotFoundError):
                await runtime.context.for_scope("missing").prepare_incremental(request)

    asyncio.run(scenario())


def test_observational_cost_with_public_sample(tmp_path):
    """Local two-turn smoke measurement; NOT the unavailable official 40-round workload."""
    from pathlib import Path

    async def scenario():
        sample_path = (
            Path(__file__).parents[2] / "competition/challenges/context-02-incremental-pack/workload/public/turns.json"
        )
        sample = json.loads(sample_path.read_text(encoding="utf-8"))
        async with open_builtin_runtime(BuiltinConfig()) as runtime:
            assert runtime.scopes is not None
            scope = await runtime.scopes.create(ScopeDraft(title="Cost", summary="Local smoke", idempotency_key="cost"))
            memory = runtime.memory.for_scope(scope.scope_id)
            context = runtime.context.for_scope(scope.scope_id)
            request = PrepareContextRequest(query=sample["query"], max_bytes=4096)
            base = None
            raw_bytes = full_bytes = incremental_bytes = gzip_bytes = 0
            distinct = set()
            for turn in range(20):
                if turn in (0, 10):
                    await memory.remember(
                        RememberMemoryRequest(
                            entries=(
                                MemoryEntryInput(kind="conversation-turn", text=sample["turns"][turn // 10]["text"]),
                            )
                        )
                    )
                ordinary = await context.prepare(request)
                assert ordinary.content
                raw = ordinary.content.encode()
                distinct.add(raw)
                sent = await context.prepare_incremental(request, base)
                incremental_bytes += len(sent.to_bytes())
                if isinstance(sent, ContextPack):
                    base = ContextPack.from_bytes(sent.to_bytes())
                else:
                    assert base is not None
                    base = apply_context_pack_delta(base, ContextPackDelta.from_bytes(sent.to_bytes()))
                assert b"".join(base.items) == raw
                raw_bytes += len(raw)
                full_bytes += len(base.to_bytes())
                gzip_bytes += len(gzip.compress(raw, compresslevel=9, mtime=0))
            result = {
                "workload": "local-20-round-two-public-turn-smoke-not-official-cost-gate",
                "distinct_contexts": len(distinct),
                "raw_full_bytes": raw_bytes,
                "full_v1_pack_bytes": full_bytes,
                "incremental_bytes": incremental_bytes,
                "gzip_bytes": gzip_bytes,
                "raw_saving": 1 - incremental_bytes / raw_bytes,
                "pack_saving": 1 - incremental_bytes / full_bytes,
                "gzip_saving": 1 - incremental_bytes / gzip_bytes,
            }
            print(json.dumps(result, sort_keys=True))
            assert len(distinct) == 2

    asyncio.run(scenario())
