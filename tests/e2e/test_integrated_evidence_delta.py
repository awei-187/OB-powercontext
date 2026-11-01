"""Selected literal evidence retains its exact citations through Context Pack deltas."""

from __future__ import annotations

import asyncio
import json

import pytest

from powercontext.artifacts import MemoryCitation
from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    GetMemoryEntryRequest,
    PrepareContextRequest,
    RememberMemoryRequest,
    RetireMemoryEntryRequest,
    ReviseMemoryEntryRequest,
    SearchMemoryRequest,
    open_builtin_runtime,
)
from powercontext.builtin.runtime.context_pack import ContextPack, ContextPackDelta, apply_context_pack_delta
from powercontext.builtin.runtime.prepared_context import PreparedContextBuilder, PreparedMemoryCandidates
from powercontext.builtin.scope import ScopeDraft


def items(content):
    return [] if content is None else json.loads(content.splitlines()[-2])["items"]


async def verify_items(runtime, content, allowed_scopes):
    fragments = items(content)
    for fragment in fragments:
        identity = dict(fragment["citation"])
        scope = identity.pop("scope_id")
        assert scope in allowed_scopes
        citation = MemoryCitation.model_validate(identity)
        record = await runtime.memory.for_scope(scope).get(GetMemoryEntryRequest(citation=citation))
        start, end = fragment["start"], fragment["end"]
        assert type(start) is type(end) is int and 0 <= start < end <= len(record.entry.text)
        assert record.entry.text[start:end] == fragment["content"]
    return fragments


async def delivery(runtime, scope, request, base, allowed_scopes):
    ordinary = await runtime.context.for_scope(scope).prepare(request)
    wire = await runtime.context.for_scope(scope).prepare_incremental(request, base)
    assert wire.byte_count == len(wire.to_bytes())
    if base is None:
        assert isinstance(wire, ContextPack)
        rebuilt = ContextPack.from_bytes(wire.to_bytes())
    else:
        assert isinstance(wire, ContextPackDelta)
        rebuilt = apply_context_pack_delta(
            ContextPack.from_bytes(base.to_bytes()), ContextPackDelta.from_bytes(wire.to_bytes())
        )
    raw = b"".join(rebuilt.items)
    assert raw == (ordinary.content or "").encode("utf-8")
    assert ordinary.content_bytes == len(raw) <= request.max_bytes
    raw.decode("utf-8", errors="strict")
    # max_bytes bounds prepared content, not JSON/Base64 transport overhead.
    fragments = await verify_items(runtime, ordinary.content, allowed_scopes)
    return rebuilt, fragments


async def seed(runtime):
    assert runtime.scopes is not None
    scopes, citations = {}, {}
    for label in ("reference", "hidden", "reader"):
        scope = await runtime.scopes.create(
            ScopeDraft(
                title=label,
                summary=label,
                idempotency_key=label,
                context_references=(scopes["reference"],) if label == "reader" else (),
            )
        )
        scopes[label] = scope.scope_id
        text = (
            "Routine administrative material. " * 90
            + f"Cobalt sensor {label} measured 37 degrees 雪😀 e\u0301.\r\n"
            + "Routine maintenance material. " * 90
            + f'Amber valve {label} measured 19 degrees 中🧪 "quoted" \\ \x00. '
        )
        result = await runtime.memory.for_scope(scope.scope_id).remember(
            RememberMemoryRequest(entries=(MemoryEntryInput(kind="document", text=text),))
        )
        assert result.entry is not None
        citations[label] = result.entry.citation
    return scopes, citations


async def budgets_and_queries(runtime, scopes):
    base = None
    saved = []
    nonempty = set()
    for query in ("cobalt", "amber", "cobalt"):
        for budget in (512, 700, 900, 1400, 1800, 32768):
            request = PrepareContextRequest(query=query, max_bytes=budget, evidence_selection=True)
            base, fragments = await delivery(
                runtime, scopes["reader"], request, base, {scopes["reader"], scopes["reference"]}
            )
            assert b"hidden" not in b"".join(base.items)
            if fragments:
                nonempty.add(query)
                saved.extend(fragments)
            # Cross-check the Builder's public offsets/origins against its own exact rendered JSON.
            groups = []
            for scope in (scopes["reader"], scopes["reference"]):
                page = await runtime.memory.for_scope(scope).search(
                    SearchMemoryRequest(query=query, mode="fts", limit=8)
                )
                groups.append(PreparedMemoryCandidates(scope, page.memory_ref, page.hits))
            build = PreparedContextBuilder().build_scopes_result(
                request=request, current_scope_id=scopes["reader"], memory_candidates=groups
            )
            assert build.context.content_bytes == len((build.context.content or "").encode()) <= budget
            assert build.origins == tuple(fragment.address for fragment in build.fragments)
            rendered = items(build.context.content)
            assert len(rendered) == len(build.fragments)
            for fragment, item in zip(build.fragments, rendered, strict=True):
                assert (fragment.start, fragment.end, fragment.text) == (item["start"], item["end"], item["content"])
                assert item["citation"]["scope_id"] == fragment.address.memory.scope_id
    assert nonempty == {"cobalt", "amber"}
    assert any(item["start"] > 0 for item in saved)
    assert any(len(item["content"].encode()) > len(item["content"]) for item in saved)
    return base, saved


async def scope_and_flags(runtime, scopes, base):
    request = PrepareContextRequest(query="cobalt", max_bytes=1800, evidence_selection=True)
    hidden, _ = await delivery(runtime, scopes["hidden"], request, base, {scopes["hidden"]})
    clean, _ = await delivery(runtime, scopes["reader"], request, hidden, {scopes["reader"], scopes["reference"]})
    assert b"hidden" not in b"".join(clean.items)
    seen = []

    async def deny(ids):
        seen.append(ids)
        raise PermissionError("integration denied")  # noqa: TRY003

    with pytest.raises(PermissionError):
        await runtime.context.for_scope(scopes["reader"]).prepare_incremental(request, hidden, authorize_scopes=deny)
    assert seen == [(scopes["reader"], scopes["reference"])]
    default = PrepareContextRequest(query="cobalt", max_bytes=1800)
    explicit = PrepareContextRequest(query="cobalt", max_bytes=1800, evidence_selection=False)
    assert await runtime.context.for_scope(scopes["reader"]).prepare(default) == await runtime.context.for_scope(
        scopes["reader"]
    ).prepare(explicit)
    return clean


def test_selected_evidence_delta_preserves_utf8_budget_citations_and_restart_history(tmp_path):
    async def scenario():
        config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'evidence-delta.db'}"))
        request = PrepareContextRequest(query="cobalt", max_bytes=1800, evidence_selection=True)
        async with open_builtin_runtime(config) as runtime:
            scopes, citations = await seed(runtime)
            base, fragments = await budgets_and_queries(runtime, scopes)
            base = await scope_and_flags(runtime, scopes, base)
            (tmp_path / "receiver.pack").write_bytes(base.to_bytes())
        async with open_builtin_runtime(config) as runtime:
            restored = ContextPack.from_bytes((tmp_path / "receiver.pack").read_bytes())
            assert (
                await delivery(runtime, scopes["reader"], request, restored, {scopes["reader"], scopes["reference"]})
            )[0] == restored
            await runtime.memory.for_scope(scopes["reader"]).revise(
                ReviseMemoryEntryRequest(
                    citation=citations["reader"],
                    kind="document",
                    text="Cobalt sensor revised to 42 degrees 雪😀. Amber valve revised to 20 degrees.",
                )
            )
            await runtime.memory.for_scope(scopes["reference"]).retire(
                RetireMemoryEntryRequest(citation=citations["reference"], reason="integration test")
            )
            revised, current = await delivery(runtime, scopes["reader"], request, restored, {scopes["reader"]})
            assert current and revised != restored and b"42" in b"".join(revised.items)
            # Exact old references remain usable after revision/retirement and a fresh Runtime.
            for fragment in fragments:
                identity = dict(fragment["citation"])
                scope = identity.pop("scope_id")
                historical = await runtime.memory.for_scope(scope).get(
                    GetMemoryEntryRequest(citation=MemoryCitation.model_validate(identity))
                )
                assert historical.entry.text[fragment["start"] : fragment["end"]] == fragment["content"]
            assert (
                await delivery(
                    runtime,
                    scopes["reader"],
                    PrepareContextRequest(query="absentterm", evidence_selection=True),
                    revised,
                    {scopes["reader"]},
                )
            )[0].items == ()

    asyncio.run(scenario())
