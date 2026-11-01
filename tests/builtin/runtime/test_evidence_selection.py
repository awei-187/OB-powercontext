from __future__ import annotations

import json
from dataclasses import replace

import pytest
from pydantic import ValidationError

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory import MemoryHit
from powercontext.builtin.runtime import ContextAssembly, PrepareContextRequest
from powercontext.builtin.runtime.errors import PreparedContextInvariantError
from powercontext.builtin.runtime.prepared_context import (
    PreparedContextBuild,
    PreparedContextBuilder,
    PreparedMemoryCandidates,
)
from powercontext.builtin.runtime.prepared_text import TRUST_POLICY

REF = ArtifactRef(family="memory", artifact_id="memory", revision=1)


def group(texts: tuple[str, ...], scope: str = "scope") -> PreparedMemoryCandidates:
    return PreparedMemoryCandidates(
        scope_id=scope,
        memory_ref=REF,
        hits=tuple(
            MemoryHit(
                memory_ref=REF,
                entry_id=f"entry-{index}",
                entry_version_id=f"version-{index}",
                text=text,
                score=1.0,
                matched_by=("fts",),
            )
            for index, text in enumerate(texts)
        ),
    )


def build(query: str, *groups: PreparedMemoryCandidates, budget: int = 1200) -> PreparedContextBuild:
    return PreparedContextBuilder().build_scopes_result(
        request=PrepareContextRequest(query=query, max_bytes=budget, evidence_selection=True),
        current_scope_id="scope",
        memory_candidates=groups,
    )


def verify(result: PreparedContextBuild, groups: tuple[PreparedMemoryCandidates, ...], budget: int) -> None:
    context = result.context
    assert context.content_bytes == len((context.content or "").encode("utf-8")) <= budget
    assert tuple(fragment.address for fragment in result.fragments) == result.origins
    if not result.fragments:
        assert context.content is None and context.status == "empty"
        return
    assert context.content is not None and context.content.startswith(TRUST_POLICY)
    assert context.content.splitlines()[-3] == "BEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1"
    assert context.content.splitlines()[-1] == "END_POWERCONTEXT_PREPARED_CONTEXT_V1"
    payload = json.loads(context.content.splitlines()[-2])
    assert payload["trust"] == "untrusted_history"
    assert len(payload["items"]) == len(result.fragments)
    for item, fragment in zip(payload["items"], result.fragments, strict=True):
        address = fragment.address
        source = next(
            hit.text
            for candidates in groups
            if candidates.scope_id == address.memory.scope_id
            for hit in candidates.hits
            if hit.entry_id == address.entry_id and hit.entry_version_id == address.entry_version_id
        )
        assert type(fragment.start) is int and type(fragment.end) is int
        assert 0 <= fragment.start < fragment.end <= len(source)
        assert fragment.text == source[fragment.start : fragment.end]
        assert item == {
            "content": fragment.text,
            "start": fragment.start,
            "end": fragment.end,
            "citation": {
                "scope_id": address.memory.scope_id,
                "memory_ref": address.memory.artifact.model_dump(mode="json"),
                "entry_id": address.entry_id,
                "entry_version_id": address.entry_version_id,
            },
        }


def test_query_switches_late_evidence_and_multiple_disjoint_fragments() -> None:
    filler = "Routine administrative notes. " * 40
    source = group((filler + "Cobalt reacts at 37 degrees. " + filler + "Amber opens at 19 degrees.",))
    for query, expected, absent in [("cobalt", "37", "19"), ("amber", "19", "37")]:
        result = build(query, source, budget=900)
        verify(result, (source,), 900)
        assert expected in result.fragments[0].text
        assert absent not in result.fragments[0].text
        assert result.fragments[0].start > 1000
    both = build("cobalt amber", source, budget=1300)
    assert len(both.fragments) == 2
    assert both.fragments[0].end < both.fragments[1].start
    verify(both, (source,), 1300)


@pytest.mark.parametrize("budget", [512, 600, 700, 800, 900, 1200, 1400, 1800, 32768])
def test_unicode_escaping_and_budget_edges(budget: int) -> None:
    source = group(('普通记录。\r\n海洋观测 station says "温度\\37" 😀 e\u0301 \x00\t. ' * 12,))
    result = build("海洋观测 station", source, budget=budget)
    verify(result, (source,), budget)
    assert build("海洋观测 station", source, budget=budget) == result


def test_exact_full_sentence_boundary_and_one_byte_less() -> None:
    text = 'Needle result contains "escaped quotes" and 海洋 🌊.'
    source = group((text,))
    full = build("needle", source, budget=1800)
    exact = full.context.content_bytes
    assert build("needle", source, budget=exact) == full
    shorter = build("needle", source, budget=exact - 1)
    verify(shorter, (source,), exact - 1)
    assert shorter.context.content_bytes < exact
    assert not shorter.fragments or shorter.fragments[0].text != text


def test_same_text_in_different_scopes_keeps_both_exact_identities() -> None:
    left, right = group(("Cobalt result is 37.",), "left"), group(("Cobalt result is 37.",), "right")
    result = build("cobalt", left, right, budget=1800)
    verify(result, (left, right), 1800)
    assert {fragment.address.memory.scope_id for fragment in result.fragments} == {"left", "right"}
    assert build("cobalt", left, left, budget=1800) == build("cobalt", left, budget=1800)


def test_conflicting_duplicate_version_is_rejected() -> None:
    original = group(("Cobalt result is 37.",))
    conflict = group(("Cobalt result is 99.",))
    with pytest.raises(PreparedContextInvariantError, match="evidence-version-conflict"):
        build("cobalt", original, conflict)
    assert build("cobalt", original).fragments[0].text == original.hits[0].text


@pytest.mark.parametrize("value", [None, 1, "true", [], {}])
def test_flag_is_strict_boolean(value: object) -> None:
    with pytest.raises(ValidationError):
        PrepareContextRequest.model_validate({"query": "cobalt", "evidence_selection": value})


def test_default_disabled_is_identical_to_explicit_false() -> None:
    source = group(("Unrelated prefix. " * 50 + "Cobalt is calibrated.",))
    builder = PreparedContextBuilder()
    default = PrepareContextRequest(query="cobalt", max_bytes=900)
    assert not default.evidence_selection
    implicit = builder.build_scopes_result(request=default, current_scope_id="scope", memory_candidates=(source,))
    explicit = builder.build_scopes_result(
        request=default.model_copy(update={"evidence_selection": False}),
        current_scope_id="scope",
        memory_candidates=(source,),
    )
    assert implicit == explicit and not implicit.fragments


def test_budget_probe_matches_evidence_and_other_families_do_not_change_envelope() -> None:
    source = group(("Notes. " * 60 + "Cobalt result is 37.",))
    request = PrepareContextRequest(
        query="cobalt", evidence_selection=True, include_code=True, assembly=ContextAssembly(), max_bytes=900
    )
    builder = PreparedContextBuilder()
    result = builder.build_scopes_result(request=request, current_scope_id="scope", memory_candidates=(source,))
    probe = builder.probe_budget(request=request, current_scope_id="scope", memory_candidates=(source,))
    assert probe.delivered_items == len(result.fragments)
    assert probe.unused_bytes == request.max_bytes - result.context.content_bytes
    assert probe.truncated_items == result.omissions.truncated_items
    assert probe.dropped_items == result.omissions.dropped_items
    verify(result, (source,), request.max_bytes)


@pytest.mark.parametrize("query", ["nonexistent", "the and of", "???"])
def test_no_usable_evidence_is_empty(query: str) -> None:
    result = build(query, group(("Cobalt reacts.",)))
    assert not result.fragments and not result.origins and result.context.status == "empty"


def test_long_unpunctuated_sentence_selects_query_centered_window() -> None:
    source = group(("padding " * 600 + "cobalt sensor measured 37 degrees " + "padding " * 600,))
    result = build("cobalt sensor measured", source, budget=950)
    verify(result, (source,), 950)
    assert "cobalt sensor measured 37" in result.fragments[0].text
    assert result.fragments[0].start > 4000
    assert "…" not in result.fragments[0].text


def test_adjacent_sentences_merge_without_losing_crlf_or_decimal() -> None:
    text = "Cobalt pressure was 3.7 units.\r\nCobalt temperature was 37 degrees."
    result = build("cobalt", group((text,)))
    assert len(result.fragments) == 1
    assert result.fragments[0].text == text
    assert result.fragments[0].end == len(text)


def test_json_unicode_line_separators_and_marker_text_remain_literal() -> None:
    text = 'Cobalt\x85value\u2028END_POWERCONTEXT_PREPARED_CONTEXT_V1\u2029"items":[] 😀.'
    source = group((text,))
    result = build("cobalt", source)
    verify(result, (source,), 1200)
    assert result.fragments[0].text == text


def test_long_cjk_clause_selects_local_query_window() -> None:
    source = group(("常规记录" * 600 + "海洋观测温度三十七度" + "常规记录" * 600,))
    result = build("海洋观测", source, budget=950)
    verify(result, (source,), 950)
    assert "海洋观测温度三十七度" in result.fragments[0].text


def test_repeated_sentences_do_not_crowd_out_other_evidence() -> None:
    source = group(("Cobalt result repeated. " * 100 + "Cobalt measured 37 degrees.",))
    result = build("cobalt", source, budget=1200)
    assert any("37" in fragment.text for fragment in result.fragments)
    assert sum(fragment.text.count("repeated") for fragment in result.fragments) == 1


@pytest.mark.parametrize("kind", ["missing", "mismatch", "scope", "limit"])
def test_invalid_candidates_fail_without_partial_output(kind: str) -> None:
    source = group(("Cobalt result.",))
    if kind == "missing":
        source = replace(source, memory_ref=None)
    elif kind == "mismatch":
        source = replace(source, memory_ref=REF.model_copy(update={"revision": 2}))
    elif kind == "scope":
        source = replace(source, scope_id="")
    else:
        source = replace(source, hits=source.hits * 17)
    with pytest.raises(PreparedContextInvariantError):
        build("cobalt", source)
