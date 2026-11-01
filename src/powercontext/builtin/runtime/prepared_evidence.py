"""Offline, query-driven selection of literal Memory passages.

Scoring sees only the request and its candidates. Rendering is part of selection:
every addition, merge, or shortened passage is measured with its exact citation.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from bisect import bisect_left, bisect_right
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from powercontext.artifacts import ArtifactAddress
from powercontext.builtin.runtime.errors import PreparedContextInvariantError
from powercontext.builtin.runtime.models import PrepareContextRequest, PreparedContext
from powercontext.builtin.runtime.prepared_text import TRUST_POLICY

if TYPE_CHECKING:
    from powercontext.builtin.runtime.prepared_context import (
        MemoryEntryAddress,
        PreparedContextBuild,
        PreparedMemoryCandidates,
    )

_BEGIN = "BEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1"
_END = "END_POWERCONTEXT_PREPARED_CONTEXT_V1"
_WORDS = re.compile(r"[^\W_]+", re.UNICODE)
_BOUNDARY = re.compile(r"[.!?]+[\"'\u2019\u201d)]*(?=\s|$)|[。！？]+|\n+")  # noqa: RUF001
_STOP = frozenset(
    "a an and are as at be been being by can could did do does for from had has have how "  # noqa: SIM905
    "in into is it its of on or that the their these they this those to was were what when "
    "where which who will with would".split()
)
_ABBREVIATIONS = frozenset({"dr", "mr", "mrs", "ms", "prof", "vs", "fig", "eq", "e.g", "i.e", "et al"})


@dataclass(frozen=True)
class EvidenceFragment:
    """An unchanged half-open Python character slice of one exact Memory version."""

    address: MemoryEntryAddress
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class _Document:
    address: MemoryEntryAddress
    text: str


@dataclass(frozen=True)
class _Passage:
    document: int
    start: int
    end: int
    score: float


def _terms(text: str) -> list[str]:
    terms = []
    for match in _WORDS.finditer(unicodedata.normalize("NFKC", text).casefold()):
        word = match.group()
        if word in _STOP:
            continue
        if any("\u3400" <= char <= "\u9fff" for char in word):
            # CJK queries need not contain whitespace or exactly match a whole clause.
            terms.extend(word[index : index + 2] for index in range(max(1, len(word) - 1)))
            continue
        if word.isascii() and word.isalpha():
            if len(word) > 5 and word.endswith("ies"):
                word = word[:-3] + "y"
            elif len(word) > 5 and word.endswith("ing"):
                word = word[:-3]
            elif len(word) > 4 and word.endswith("ed"):
                word = word[:-2]
            elif len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "is", "us")):
                word = word[:-1]
            if len(word) > 4 and word.endswith("e"):
                word = word[:-1]
        terms.append(word)
    return terms


def _sentences(text: str) -> list[tuple[int, int]]:
    spans = []
    start = 0
    for boundary in _BOUNDARY.finditer(text):
        end = boundary.end()
        if boundary.group().startswith("."):
            previous = text[start : boundary.start()].rsplit(maxsplit=1)
            word = previous[-1].casefold() if previous else ""
            if word in _ABBREVIATIONS or (len(word) == 1 and word.isalpha()):
                continue
        if text[start:end].strip():
            # Retain sentence-leading spaces: coordinates cover the literal source,
            # and adjacent sentences can later coalesce without losing characters.
            spans.append((start, end))
        start = end
    if text[start:].strip():
        spans.append((start, len(text)))
    return spans


def _documents(groups: Sequence[PreparedMemoryCandidates]) -> list[_Document]:
    from powercontext.builtin.runtime.prepared_context import MemoryEntryAddress

    documents = []
    seen: dict[tuple[str, str, str, int, str, str], str] = {}
    for group in groups:
        if group.hits and group.memory_ref is None:
            raise PreparedContextInvariantError("memory-ref-missing")
        for hit in group.hits:
            if hit.memory_ref != group.memory_ref:
                raise PreparedContextInvariantError("memory-ref-mismatch")
            if not hit.entry_id.strip() or not hit.entry_version_id.strip() or not hit.text.strip():
                continue
            if not group.scope_id.strip():
                raise PreparedContextInvariantError("evidence-scope-missing")
            address = MemoryEntryAddress(
                memory=ArtifactAddress(scope_id=group.scope_id, artifact=hit.memory_ref),
                entry_id=hit.entry_id,
                entry_version_id=hit.entry_version_id,
            )
            identity = (
                group.scope_id,
                hit.memory_ref.family,
                hit.memory_ref.artifact_id,
                hit.memory_ref.revision,
                hit.entry_id,
                hit.entry_version_id,
            )
            if identity in seen:
                if seen[identity] != hit.text:
                    raise PreparedContextInvariantError("evidence-version-conflict")
                continue
            seen[identity] = hit.text
            documents.append(_Document(address, hit.text))
    return documents


def _rank(query: str, documents: Sequence[_Document]) -> list[_Passage]:
    query_terms = set(_terms(query))
    if not query_terms:
        return []
    rows = []
    for index, doc in enumerate(documents):
        seen = set()
        for start, end in _sentences(doc.text):
            literal = doc.text[start:end].strip()
            if literal not in seen:
                rows.append((index, start, end))
                seen.add(literal)
    counts = [Counter(_terms(documents[index].text[start:end])) for index, start, end in rows]
    frequency = Counter(term for count in counts for term in count)
    weights = {term: math.log1p((len(rows) + 0.5) / (frequency[term] + 0.5)) for term in sorted(query_terms)}
    total_weight = sum(weights.values())
    average = sum(sum(count.values()) for count in counts) / max(1, len(counts))
    doc_terms = [set(_terms(doc.text)) for doc in documents]
    coverage = [sum(weights[term] for term in sorted(query_terms & terms)) / total_weight for terms in doc_terms]
    passages = []
    for (index, start, end), count in zip(rows, counts, strict=True):
        matched = sorted(query_terms & count.keys())
        if not matched:
            continue
        length = sum(count.values())
        lexical = sum(
            weights[term] * count[term] * 2.2 / (count[term] + 1.2 * (0.65 + 0.35 * length / max(1, average)))
            for term in matched
        )
        completeness = sum(weights[term] for term in matched) / total_weight
        score = lexical * (0.5 + completeness) * (0.5 + coverage[index])
        passages.append(_Passage(index, start, end, score))
    return passages


def _merge(passages: Sequence[_Passage], documents: Sequence[_Document]) -> list[_Passage]:
    merged: list[_Passage] = []
    for passage in sorted(passages, key=lambda item: (item.document, item.start, item.end)):
        if merged and merged[-1].document == passage.document:
            previous = merged[-1]
            gap = documents[passage.document].text[previous.end : passage.start]
            if passage.start <= previous.end or not gap.strip():
                merged[-1] = replace(previous, end=max(previous.end, passage.end), score=previous.score + passage.score)
                continue
        merged.append(passage)
    return merged


def _fragments(passages: Sequence[_Passage], documents: Sequence[_Document]) -> tuple[EvidenceFragment, ...]:
    return tuple(
        EvidenceFragment(
            documents[item.document].address, item.start, item.end, documents[item.document].text[item.start : item.end]
        )
        for item in passages
    )


def _render(fragments: Sequence[EvidenceFragment]) -> str:
    items = [
        {
            "citation": {
                "scope_id": fragment.address.memory.scope_id,
                "memory_ref": fragment.address.memory.artifact.model_dump(mode="json"),
                "entry_id": fragment.address.entry_id,
                "entry_version_id": fragment.address.entry_version_id,
            },
            "content": fragment.text,
            "start": fragment.start,
            "end": fragment.end,
        }
        for fragment in fragments
    ]
    body = json.dumps({"trust": "untrusted_history", "items": items}, ensure_ascii=False, separators=(",", ":"))
    # These Unicode separators are legal inside JSON strings but splitlines() treats
    # them as physical envelope boundaries. JSON escapes preserve the original text.
    for separator in ("\x85", "\u2028", "\u2029"):
        body = body.replace(separator, f"\\u{ord(separator):04x}")
    return f"{TRUST_POLICY}\n\n{_BEGIN}\n{body}\n{_END}"


def _size(passages: Sequence[_Passage], documents: Sequence[_Document]) -> int:
    return len(_render(_fragments(passages, documents)).encode("utf-8"))


def _shorten(
    passage: _Passage,
    selected: Sequence[_Passage],
    documents: Sequence[_Document],
    query: str,
    budget: int,
) -> _Passage | None:
    """Fit a query-centered literal window when a complete sentence cannot fit."""
    text = documents[passage.document].text
    query_terms = set(_terms(query))
    matches = []
    for match in _WORDS.finditer(text, passage.start, passage.end):
        word = match.group()
        if not query_terms.intersection(_terms(word)):
            continue
        if any("\u3400" <= char <= "\u9fff" for char in word):
            matches.extend(
                (match.start() + index, match.start() + index + 2)
                for index in range(len(word) - 1)
                if query_terms.intersection(_terms(word[index : index + 2]))
            )
        else:
            matches.append((match.start(), match.end()))
    if not matches:
        return None
    # Prefer the densest local query cluster, rather than always taking the prefix.
    positions = [match[0] for match in matches]
    anchor = max(
        matches,
        key=lambda item: bisect_right(positions, item[0] + 159) - bisect_left(positions, item[0] - 159),
    )
    lower, upper = 0, passage.end - passage.start
    best = None
    while lower <= upper:
        radius = (lower + upper) // 2
        start, end = max(passage.start, anchor[0] - radius), min(passage.end, anchor[1] + radius)
        candidate = replace(passage, start=start, end=end)
        if _size(_merge((*selected, candidate), documents), documents) <= budget:
            best = candidate
            lower = radius + 1
        else:
            upper = radius - 1
    return best


def select_evidence(request: PrepareContextRequest, groups: Sequence[PreparedMemoryCandidates]) -> PreparedContextBuild:
    # The public Builder owns these result types; import after its module is initialized.
    from powercontext.builtin.runtime.prepared_context import PreparedContextBuild, PreparedContextOmissions

    documents = _documents(groups)
    remaining = _rank(request.query, documents)
    selected: list[_Passage] = []
    truncated = 0
    while remaining:
        current_size = _size(selected, documents)
        choices = []
        for index, candidate in enumerate(remaining):
            merged = _merge((*selected, candidate), documents)
            size = _size(merged, documents)
            if size <= request.max_bytes:
                utility = candidate.score / math.sqrt(max(1, size - current_size))
                choices.append((utility, -index, index, merged))
        if not choices:
            break
        _, _, index, selected = max(choices, key=lambda choice: choice[:2])
        remaining.pop(index)

    # Complete sentences have priority over partial evidence. Try remaining high-scoring
    # sentences once; no ellipsis or other generated character enters an evidence slice.
    for candidate in sorted(remaining, key=lambda item: -item.score):
        shortened = _shorten(candidate, selected, documents, request.query, request.max_bytes)
        if shortened is not None:
            selected = _merge((*selected, shortened), documents)
            remaining.remove(candidate)
            truncated += 1
    fragments = _fragments(selected, documents)
    content = _render(fragments) if fragments else None
    context = PreparedContext(
        status="ready" if content is not None else "empty",
        content=content,
        content_bytes=len(content.encode("utf-8")) if content is not None else 0,
    )
    return PreparedContextBuild(
        context=context,
        origins=tuple(fragment.address for fragment in fragments),
        fragments=fragments,
        omissions=PreparedContextOmissions(
            truncated_items=truncated,
            dropped_items=len(remaining),
            dropped_no_fitting_truncation=len(remaining),
        ),
    )
