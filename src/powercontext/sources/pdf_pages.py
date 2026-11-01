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

"""Complete physical PDF pages and offline retrieval of their exact Memory citations."""

from __future__ import annotations

import hashlib
import io
import json
import math
import re
from collections import Counter
from typing import TYPE_CHECKING, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from powercontext.artifacts import MemoryCitation
from powercontext.builtin.artifacts.search import analyze_fts_query
from powercontext.sources.definitions import SourceDefinition, SourceProjection
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

if TYPE_CHECKING:
    from pypdf import PageObject

    from powercontext.builtin.artifacts.memory.models import MemoryHit
    from powercontext.builtin.runtime import ScopedMemoryApplication


def _document_id(value: str) -> str:
    if not value.strip():
        raise ValueError("document_id must not be empty or whitespace-only")  # noqa: TRY003
    return value


class PDFDocumentInput(BaseModel):
    """The complete original PDF bytes, without path or network dependencies."""

    model_config = ConfigDict(frozen=True)
    document_id: str
    content: bytes

    _validate_document_id = field_validator("document_id")(_document_id)


class PDFPageInput(BaseModel):
    """All extractable text of one physical page, including an empty page."""

    model_config = ConfigDict(frozen=True)
    document_id: str
    document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_number: int = Field(gt=0, strict=True)
    text: str

    _validate_document_id = field_validator("document_id")(_document_id)


def pdf_page_source_id(document_id: str, document_sha256: str, page_number: int) -> str:
    """Hash an unambiguous tuple; arbitrarily long document names remain bounded.

    No whitespace, case or Unicode normalization is applied to the document ID.
    The complete original PDF digest and physical location remain in the payload.
    """
    identity = json.dumps([document_id, document_sha256, page_number], ensure_ascii=True, separators=(",", ":"))
    return "pdf:" + hashlib.sha256(identity.encode("ascii")).hexdigest()


class PDFPageSource(PDFPageInput, Source):
    """Immutable captured evidence independent of the input file's lifetime."""

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.definition_version != "1" or self.materialization != SourceMaterialization.CAPTURED:
            raise ValueError("PDF pages must be captured Sources with definition version 1")  # noqa: TRY003
        if self.name != pdf_page_source_id(self.document_id, self.document_sha256, self.page_number):
            raise ValueError("PDF source name must match its document revision and physical page")  # noqa: TRY003
        return self


def parse_pdf_document(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]:
    """Extract every page atomically using pypdf, retaining text and table numbers.

    Permission-only encryption with the empty user password is supported. A PDF
    needing a nonempty password or failing at any page is rejected as a whole.
    No OCR, whitespace cleanup, page merging or evidence-specific filtering occurs.
    """
    from pypdf import PdfReader

    from powercontext.sources._pdf_validation import validate_page_objects

    _document_id(value.document_id)
    if not value.content.startswith(b"%PDF-") or not value.content.rstrip().endswith(b"%%EOF"):
        raise ValueError("Expected a complete PDF with its header and end marker")  # noqa: TRY003
    digest = hashlib.sha256(value.content).hexdigest()
    try:
        reader = PdfReader(io.BytesIO(value.content), strict=True)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("PDF requires a nonempty password")  # noqa: TRY003, TRY301
        if not reader.pages:
            raise ValueError("PDF has no physical pages")  # noqa: TRY003, TRY301
        pages = tuple(reader.pages)
        validate_page_objects(pages)
        return tuple(
            PDFPageInput(
                document_id=value.document_id,
                document_sha256=digest,
                page_number=index,
                text=_extract_page_text(page),
            )
            for index, page in enumerate(pages, 1)
        )
    except Exception as error:
        # pypdf can surface stream, codec and page-tree errors from different
        # exception families; never expose a partially parsed document.
        raise ValueError("Cannot completely parse PDF document") from error  # noqa: TRY003


def _extract_page_text(page: PageObject) -> str:
    from pypdf.generic import ArrayObject, NullObject, StreamObject

    # pypdf treats some invalid /Contents values as an empty page, even in
    # strict mode. Do not silently turn a damaged later page into blank evidence.
    contents = page.get("/Contents")
    if contents is not None:
        contents = contents.get_object()
        streams = contents if isinstance(contents, ArrayObject) else [contents]
        if not isinstance(contents, NullObject):
            for stream in streams:
                if not isinstance(stream.get_object(), StreamObject):
                    raise TypeError("PDF page Contents must contain only streams")  # noqa: TRY003
    return page.extract_text() or ""


class _PDFPageTextEvidence:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class: type[PDFPageSource] = PDFPageSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PDFPageSource, /) -> TextEvidence:
        return TextEvidence(
            source_type="pdf-page",
            source_id=source.name,
            content=f"{source.document_id}\n{source.text}",
            metadata={
                "document_id": source.document_id,
                "document_sha256": source.document_sha256,
                "page_number": source.page_number,
            },
        )


class _PDFPageSourceDefinition:
    name = "pdf-page"
    version = "1"
    input_class: type[PDFPageInput] = PDFPageInput
    source_class: type[PDFPageSource] = PDFPageSource
    projections: tuple[SourceProjection[PDFPageSource], ...] = (_PDFPageTextEvidence(),)

    async def resolve(self, value: PDFPageInput, /) -> PDFPageSource:
        return PDFPageSource(
            name=pdf_page_source_id(value.document_id, value.document_sha256, value.page_number),
            materialization=SourceMaterialization.CAPTURED,
            **value.model_dump(),
        )

    async def read(self, source: PDFPageSource, /) -> PDFPageInput:
        return PDFPageInput(
            document_id=source.document_id,
            document_sha256=source.document_sha256,
            page_number=source.page_number,
            text=source.text,
        )


PDF_PAGE_SOURCE_DEFINITION: SourceDefinition[PDFPageInput, PDFPageSource, PDFPageInput] = _PDFPageSourceDefinition()

# Query-only financial vocabulary, independent of any document or question set.
# Original evidence is never rewritten. Groups are searched separately so the
# Memory admission floor cannot discard a page for missing unrelated synonyms.
_CONCEPTS: tuple[tuple[str, str], ...] = (
    (r"\b(?:geograph\w*|countries|regions|operates)\b", "geographic geographical countries regions segments divisions"),
    (r"\b(?:legal|litigation|lawsuits?|battles|proceedings)\b", "legal proceedings litigation contingencies lawsuits"),
    (r"\b(?:restructur\w*|reorganiz\w*)\b", "restructuring reorganization charges costs"),
    (r"\b(?:ebitda|depreciation|amortization)\b|\bd\s*&\s*a\b", "depreciation amortization operating income"),
    (r"\b(?:capex|capital expenditures?)\b", "capital spending expenditures property plant equipment additions"),
    (r"\b(?:income|earnings) statements?\b|\bp\s*&\s*l\b", "consolidated statements income operations earnings"),
    (r"\bcash flows?\b", "consolidated statements cash flows operating investing financing"),
    (r"\bbalance sheets?\b", "consolidated balance sheets assets liabilities equity"),
    (r"\b(?:revenue|sales)\b", "revenue revenues sales"),
    (r"\b(?:dividend|dividends)\b", "dividends distributions shareholders"),
)
_QUERY_NOISE = frozenset([
    "s",
    "has",
    "have",
    "had",
    "any",
    "reported",
    "important",
    "ongoing",
    "directly",
    "outlined",
    "explicitly",
    "then",
    "state",
    "quantity",
    "define",
    "answer",
    "respond",
    "question",
    "assuming",
    "perspective",
    "investment",
    "analyst",
    "only",
    "use",
    "details",
    "shown",
    "within",
    "give",
    "response",
    "relying",
    "calculate",
    "unadjusted",
    "adjusted",
    "usd",
    "millions",
    "fiscal",
    "fy",
    "primarily",
])


def _terms(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", re.sub(r"\bfy\s*(\d{4})\b", r"\1", text.casefold()), flags=re.UNICODE)


def _queries(question: str) -> tuple[list[str], list[list[str]]]:
    primary = list(dict.fromkeys(t for t in _terms(analyze_fts_query(question)) if t not in _QUERY_NOISE))
    concepts: list[list[str]] = [
        terms.split() for pattern, terms in _CONCEPTS if re.search(pattern, question, re.IGNORECASE)
    ]
    return primary, concepts


_STATEMENT_PREFIX = r"(?:condensed\s+)?(?:consolidated\s+)?statements?\s+(?:of\s+)?"
_HEADINGS: tuple[tuple[str, str], ...] = (
    (
        r"\b(?:ebitda|income|earnings|profit)\b|\bp\s*&\s*l\b",
        _STATEMENT_PREFIX + r"(?:income|earnings|operations|profit\s+and\s+loss)\b",
    ),
    (
        r"\b(?:ebitda|cash flows?|capex|depreciation|amortization)\b|\bd\s*&\s*a\b",
        _STATEMENT_PREFIX + r"cash\s+flows?\b",
    ),
    (
        r"\b(?:balance sheets?|assets|liabilities|equity)\b",
        r"(?:condensed\s+)?(?:consolidated\s+)?balance\s+sheets?\b|" + _STATEMENT_PREFIX + r"financial\s+position\b",
    ),
    (r"\b(?:legal|litigation|lawsuits?|battles|proceedings)\b", r"(?:item\s+3[.\s]+)?legal\s+proceedings\b"),
    (
        r"\b(?:geograph\w*|countries|regions|operates)\b",
        r"(?:our\s+)?(?:divisions|reportable\s+segments|business\s+segments)\b",
    ),
)


def _heading_score(question: str, text: str) -> float:
    # Financial questions often require a statement even when the requested
    # metric is absent (for example EBITDA). Reward an actual page heading, not
    # repeated mentions of the statement in narrative disclosures or exhibits.
    opening = text.partition("\n")[2]
    return 8.0 * sum(
        bool(re.search(query, question, re.IGNORECASE))
        and bool(
            re.search(
                r"^[ \t]*(?:" + heading + r")[ \t]*(?:\(continued\))?[ \t]*[.:]?[ \t]*$",
                opening,
                re.IGNORECASE | re.MULTILINE,
            )
        )
        for query, heading in _HEADINGS
    )


def _rank_pages(hits: list[MemoryHit], primary: list[str], concepts: list[list[str]], question: str) -> list[MemoryHit]:
    """BM25 over the retrieved pool plus coverage of independent query concepts."""
    texts = [Counter(_terms(hit.text.partition("\n")[2])) for hit in hits]
    lengths = [sum(terms.values()) for terms in texts]
    average = sum(lengths) / max(len(lengths), 1) or 1
    frequencies: Counter[str] = Counter()
    for terms in texts:
        frequencies.update(terms.keys())
    weights = dict.fromkeys(primary, 1.0)
    for concept in concepts:
        for term in concept:
            weights.setdefault(term, 0.35)

    def score(index: int) -> float:
        counts = texts[index]
        value = 0.0
        for term, weight in weights.items():
            frequency = counts[term]
            inverse = math.log1p((len(hits) - frequencies[term] + 0.5) / (frequencies[term] + 0.5))
            value += weight * inverse * frequency * 2.2 / (frequency + 1.2 * (0.65 + 0.35 * lengths[index] / average))
        # Match the requested issuer against the captured document label without
        # letting that label (present on every page) dominate topical ranking.
        label = set(_terms(hits[index].text.partition("\n")[0]))
        value *= 1 + 0.25 * min(2, len(label.intersection(primary)))
        for concept in concepts:
            value += sum(term in counts for term in concept) / len(concept)
        return value + _heading_score(question, hits[index].text)

    return [hits[index] for index in sorted(range(len(hits)), key=lambda index: (-score(index), index))]


async def search_pdf_pages(
    memory: ScopedMemoryApplication, question: str, limit: int = 10
) -> tuple[MemoryCitation, ...]:
    """Find distinct captured pages through scoped, public Memory search/get APIs.

    Search is offline FTS with bounded query expansion and local lexical reranking.
    Only exact identities returned by Memory are eligible. No side index or cache
    survives a call; reopening a Runtime or switching scopes cannot reuse evidence.
    Zero limit and empty/nonlexical questions return an empty tuple.
    """
    from powercontext.builtin.runtime import GetMemoryEntryRequest, SearchMemoryRequest

    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise ValueError("limit must be a nonnegative integer")  # noqa: TRY003
    if not isinstance(question, str):
        raise TypeError("question must be a string")  # noqa: TRY003
    if limit == 0 or not question.strip():
        return ()
    primary, concepts = _queries(question)
    if not primary:
        return ()
    queries = [" ".join(primary), *(" ".join(group) for group in concepts)]
    # Individual topical terms recover candidates excluded by multi-term coverage
    # gates. Bounded fanout keeps long natural-language instructions inexpensive.
    queries.extend(term for term in primary if not term.isdecimal())
    queries = list(dict.fromkeys(queries))[:24]
    candidates: dict[tuple[str, str, str], MemoryHit] = {}
    for query in queries:
        page = await memory.search(SearchMemoryRequest(query=query, mode="fts", limit=min(512, max(80, limit * 4))))
        for hit in page.hits:
            candidates.setdefault((hit.memory_ref.artifact_id, hit.entry_id, hit.entry_version_id), hit)
    result: list[MemoryCitation] = []
    seen: set[str] = set()
    for hit in _rank_pages(list(candidates.values()), primary, concepts, question):
        citation = MemoryCitation(
            memory_ref=hit.memory_ref, entry_id=hit.entry_id, entry_version_id=hit.entry_version_id
        )
        entry = (await memory.get(GetMemoryEntryRequest(citation=citation))).entry
        references = {ref.source_id for ref in entry.sources if ref.source_type == "pdf-page"}
        # A page-level result must identify exactly one page, not a multi-source
        # summary. Deduplication is by immutable Source identity, never text.
        if len(references) != 1 or len(entry.sources) != 1 or references.intersection(seen):
            continue
        seen.update(references)
        result.append(citation)
        if len(result) == limit:
            break
    return tuple(result)


__all__ = [
    "PDF_PAGE_SOURCE_DEFINITION",
    "PDFDocumentInput",
    "PDFPageInput",
    "PDFPageSource",
    "parse_pdf_document",
    "pdf_page_source_id",
    "search_pdf_pages",
]
