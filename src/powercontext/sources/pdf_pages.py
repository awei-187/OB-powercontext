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
from powercontext.builtin.artifacts.search import analyze_fts_query, analyze_text
from powercontext.sources.definitions import SourceDefinition, SourceProjection
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

if TYPE_CHECKING:
    from pypdf import PageObject

    from powercontext.artifacts import ArtifactRef
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
    from powercontext.sources._pdf_actual_text import extract_actual_text

    return extract_actual_text(page)


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
_CASH_PAYOUT = (
    r"\b(?:pay|paid|payments?|payouts?|return(?:ed)?|distributions?)\b.{0,100}\b(?:shareholders?|stockholders?)\b|"
    r"\b(?:shareholders?|stockholders?)\b.{0,100}\b(?:payments?|payouts?|distributions?)\b"
)
_FREE_CASH = (
    r"\b(?:free|discretionary)\s+cash\b|"
    r"\bcash\b.{0,100}\b(?:after|less|net\s+of)\b.{0,60}\b(?:capital|fixed\s+assets|investment|capex)\b"
)
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
    (_CASH_PAYOUT, "dividends repurchases common stock financing cash flows"),
    (_FREE_CASH, "free cash flow operating capital spending expenditures"),
    (r"\b(?:inventory|inventories)\b", "inventory inventories"),
    (r"\b(?:lifo|fifo)\b", "lifo fifo inventory cost"),
    (
        r"\bgross (?:profit|margin)\b|\bcost of (?:goods sold|sales)\b|\bcogs\b",
        "gross profit margin cost sales revenue",
    ),
    (
        r"\bbad debts?\b|\bdoubtful\b|\buncollectible\b|\breceivables? allowance\b|"
        r"\bcustomer (?:bills|accounts)\b.*\b(?:unpaid|never.*paid|not.*paid)\b",
        "receivables allowance doubtful uncollectible credit losses",
    ),
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
    "find",
    "show",
    "provide",
    "compare",
    "including",
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


# A closed set avoids stemming issuer names or conflating unrelated words (for
# example business/bus). Both retrieval and local scoring see the same forms;
# persisted text and the native FTS analyzer remain untouched.
_NOUN_FORMS: tuple[tuple[str, ...], ...] = tuple(
    tuple(group.split())
    for group in (
        "inventory inventories",
        "category categories",
        "liability liabilities",
        "asset assets",
        "receivable receivables",
        "allowance allowances",
        "account accounts",
        "debt debts",
        "cost costs",
        "expense expenses",
        "loss losses",
        "tax taxes",
        "sale sales",
        "profit profits",
        "margin margins",
        "dividend dividends",
        "shareholder shareholders",
        "contribution contributions",
        "lease leases",
        "payment payments",
        "benefit benefits",
        "segment segments",
        "division divisions",
    )
)
_LEMMA: dict[str, str] = {form: forms[0] for forms in _NOUN_FORMS for form in forms}
_FORMS: dict[str, tuple[str, ...]] = {form: forms for forms in _NOUN_FORMS for form in forms}


def _raw_terms(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", re.sub(r"\bfy\s*(\d{4})\b", r"\1", text.casefold()), flags=re.UNICODE)


def _terms(text: str) -> list[str]:
    return [_LEMMA.get(term, term) for term in _raw_terms(text)]


def _queries(question: str) -> tuple[list[str], list[list[str]]]:
    # Native terms include underscore identifiers and encoded CJK tokens. Keep
    # those units intact for admission, while retaining the fiscal-year rewrite.
    native = re.sub(r"\bfy\s*(\d{4})\b", r"\1", analyze_fts_query(question))
    primary = list(dict.fromkeys(t for t in native.split() if t not in _QUERY_NOISE))
    concepts: list[list[str]] = [
        terms.split() for pattern, terms in _CONCEPTS if re.search(pattern, question, re.IGNORECASE)
    ]
    return primary, concepts


_STATEMENT_MODIFIERS = r"(?:condensed\s+)?(?:consolidated\s+)?"
_STATEMENT_PREFIX = _STATEMENT_MODIFIERS + r"statements?\s+(?:of\s+)?"
_HEADINGS: tuple[tuple[str, str], ...] = (
    (_FREE_CASH, r"free\s+cash\s+flows?\b"),
    (
        r"\b(?:ebitda|income|earnings|profit|cogs)\b|\bp\s*&\s*l\b|\bcost of (?:goods sold|sales)\b",
        _STATEMENT_PREFIX
        + r"(?:income|earnings|operations|profit\s+and\s+loss)\b|"
        + _STATEMENT_MODIFIERS
        + r"(?:income|earnings|operations|profit\s+and\s+loss)\s+statements?\b",
    ),
    (
        r"\b(?:ebitda|cash flows?|capex|depreciation|amortization)\b|\bd\s*&\s*a\b",
        _STATEMENT_PREFIX + r"cash\s+flows?\b|" + _STATEMENT_MODIFIERS + r"cash\s+flows?\s+statements?\b",
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


def _heading_position(text: str, heading: str) -> int | None:
    pattern = r"(?:" + heading + r")[ \t]*(?:\(continued\))?[ \t]*[.:]?"
    lines = (line.strip() for line in text.partition("\n")[2].splitlines() if line.strip())
    return next((index for index, line in enumerate(lines) if re.fullmatch(pattern, line, re.IGNORECASE)), None)


def _heading_score(question: str, text: str) -> float:
    # Financial questions often require a statement even when the requested
    # metric is absent (for example EBITDA). Reward an actual page heading, not
    # repeated mentions of the statement in narrative disclosures or exhibits.
    return 8.0 * sum(
        bool(re.search(query, question, re.IGNORECASE)) and _heading_position(text, heading) is not None
        for query, heading in _HEADINGS
    )


def _printed_page(question: str) -> str | None:
    match = re.search(r"\bprinted\s+page\s+(\d+|[ivxlcdm]+)\b", question, re.IGNORECASE)
    return match[1].casefold() if match else None


def _matches_printed_page(text: str, number: str) -> bool:
    # Use a number printed in the captured page itself. A numeric table cell or
    # a mention in prose is not a page locator; never infer a physical offset.
    lines = [line.strip() for line in text.partition("\n")[2].splitlines() if line.strip()]
    return bool(lines) and bool(
        re.fullmatch(
            r"(?:page\s+)?[-\u2013\u2014]?\s*" + re.escape(number) + r"\s*[-\u2013\u2014]?", lines[-1], re.IGNORECASE
        )
    )


def _heading_representatives(hits: list[MemoryHit], question: str, totals: list[float]) -> list[int]:
    representatives: list[int] = []
    for query, heading in _HEADINGS:
        if not re.search(query, question, re.IGNORECASE):
            continue
        matches = [
            (position, -totals[index], index)
            for index, hit in enumerate(hits)
            if (position := _heading_position(hit.text, heading)) is not None
        ]
        if matches:
            # Keep a representative of each requested statement. Its title near
            # the start of a page is stronger than the same words nested inside
            # a note's table, even when that note repeats more question terms.
            representatives.append(min(matches)[2])
    return representatives


def _rank_pages(hits: list[MemoryHit], primary: list[str], concepts: list[list[str]], question: str) -> list[MemoryHit]:
    """BM25 with bounded complementary evidence for separately recognized topics."""
    primary = list(dict.fromkeys(_LEMMA.get(term, term) for term in primary))
    concepts = [list(dict.fromkeys(_LEMMA.get(term, term) for term in group)) for group in concepts]
    texts = [Counter(_terms(hit.text.partition("\n")[2])) for hit in hits]
    lengths = [sum(terms.values()) for terms in texts]
    average = sum(lengths) / max(len(lengths), 1) or 1
    frequencies: Counter[str] = Counter()
    for terms in texts:
        frequencies.update(terms.keys())
    labels = [set(_terms(hit.text.partition("\n")[0])) for hit in hits]
    headings = [
        [set(_terms(line)) for line in hit.text.partition("\n")[2].splitlines() if 0 < len(_terms(line)) <= 6]
        for hit in hits
    ]

    def score(index: int, weights: dict[str, float]) -> float:
        counts = texts[index]
        value = 0.0
        for term, weight in weights.items():
            frequency = counts[term]
            inverse = math.log1p((len(hits) - frequencies[term] + 0.5) / (frequencies[term] + 0.5))
            value += weight * inverse * frequency * 2.2 / (frequency + 1.2 * (0.65 + 0.35 * lengths[index] / average))
        # Match the requested issuer against the captured document label without
        # letting that label (present on every page) dominate topical ranking.
        return value * (1 + 0.25 * min(2, len(labels[index].intersection(primary))))

    weights = dict.fromkeys(primary, 1.0)
    for concept in concepts:
        for term in concept:
            weights.setdefault(term, 0.7)
    totals = [score(index, weights) + _heading_score(question, hit.text) for index, hit in enumerate(hits)]
    ranked = sorted(range(len(hits)), key=lambda index: (-totals[index], index))

    # Keep the strongest joint matches first, then reserve at most six positions
    # for topic representatives before filling with the joint ranking. A long
    # multipart question must not let one rare term suppress every other topic.
    # This operates only on real native candidates, never inferred adjacent pages.
    representatives = _heading_representatives(hits, question, totals)
    for concept in concepts:
        topic_terms = set(concept)
        eligible = [
            index
            for index, counts in enumerate(texts)
            if len(topic_terms.intersection(counts)) >= min(2, len(topic_terms))
        ]
        if not eligible:
            continue
        topic_weights = dict.fromkeys(concept, 1.0)

        topic_scores: dict[int, float] = {}
        for index in eligible:
            # A short topical table/section label is stronger than incidental
            # mentions in prose. Numeric lines do not qualify as headings.
            heading = max(
                (
                    len(topic_terms.intersection(line))
                    for line in headings[index]
                    if not any(t.isdecimal() for t in line)
                ),
                default=0,
            )
            topic_scores[index] = (
                score(index, topic_weights) + 3 * heading + _heading_score(" ".join(concept), hits[index].text)
            )
        representatives.append(max(eligible, key=topic_scores.__getitem__))
    number = _printed_page(question)
    located = [index for index in ranked if number is not None and _matches_printed_page(hits[index].text, number)]
    representatives = list(dict.fromkeys(representatives))
    order = list(dict.fromkeys([*located, *ranked[:4], *representatives[:6], *ranked[4:]]))
    return [hits[index] for index in order]


_DOCUMENT_NOISE = frozenset([
    "annual",
    "report",
    "reports",
    "financial",
    "statements",
    "public",
    "quality",
    "form",
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "company",
    "co",
    "plc",
    "ltd",
    "limited",
    "holdings",
    "the",
])
_DOCUMENT_TOPICS = frozenset(term for _pattern, expansion in _CONCEPTS for term in expansion.split()) | _FORMS.keys()


def _requested_documents(hits: list[MemoryHit], question: str) -> dict[str, set[str]]:
    """Find label hints for additional native searches, never exclusive filters.

    Callers have already checked PDF provenance. Labels remain arbitrary user
    input: a matching prefix suggests a recovery query but cannot establish that
    other documents are irrelevant. Different years remain useful search hints.
    """
    words = " " + " ".join(_raw_terms(question)) + " "
    documents: dict[str, set[str]] = {}
    for hit in hits:
        label = hit.text.partition("\n")[0]
        prefix = re.split(r"(?<!\d)(?:19|20|21)\d{2}(?!\d)", label, maxsplit=1)[0]
        terms = [
            term
            for term in _raw_terms(prefix)
            if len(term) > 1 and not term.isdecimal() and term not in _DOCUMENT_NOISE and term not in _QUERY_NOISE
        ]
        name = " ".join(terms)
        # Avoid spending recovery calls on labels made only of financial topics.
        # This is a query-expansion heuristic, not proof of document identity.
        identity_terms = set(analyze_fts_query(name).split()) - _DOCUMENT_TOPICS
        if identity_terms and f" {name} " in words:
            documents.setdefault(name, set()).add(label)
    return documents


def _document_recovery_queries(hits: list[MemoryHit], requested: dict[str, set[str]]) -> list[str]:
    labels = {hit.text.partition("\n")[0] for hit in hits}
    frequencies = Counter(term for label in labels for term in set(analyze_fts_query(label).split()))
    queries: list[str] = []
    for name, documents in requested.items():
        for label in sorted(documents):
            # Native analysis preserves underscores. An issuer word misses pages
            # whose only issuer occurrence is the complete document ID. Recover
            # with a token from that label, preferring one that separates reports.
            anchors = [
                term for term in analyze_fts_query(label).split() if set(_raw_terms(term)).intersection(name.split())
            ]
            if anchors:
                queries.append(min(anchors, key=lambda term: (frequencies[term], -len(term), term)))
    return list(dict.fromkeys(queries))


async def _prefetch_pdf_eligibility(
    memory: ScopedMemoryApplication, hits: list[MemoryHit], eligibility: dict[tuple[str, str, str], bool]
) -> None:
    pending = [
        hit for hit in hits if (hit.memory_ref.artifact_id, hit.entry_id, hit.entry_version_id) not in eligibility
    ]
    # Some public adapters expose only search/get. Keep their exact read path,
    # and avoid loading a whole large scope for a small selective search.
    list_entries = getattr(memory, "list", None)
    capacity = getattr(memory, "capacity", None)
    if len(pending) < 32 or not callable(list_entries) or not callable(capacity):
        return
    observed = await capacity()
    if observed.manifest_entry_count > 4 * len(pending):
        return
    # Bulk reads retain the same immutable entry/version identities and Source
    # references as individual get calls. This helper only checks provenance;
    # candidate recovery separately verifies the complete snapshot revision.
    snapshot = await list_entries()
    for record in snapshot.entries:
        entry = record.entry
        key = (record.memory_ref.artifact_id, entry.entry_id, entry.entry_version_id)
        eligibility[key] = len(entry.sources) == 1 and entry.sources[0].source_type == "pdf-page"


async def _pdf_hits(
    memory: ScopedMemoryApplication, hits: list[MemoryHit], eligibility: dict[tuple[str, str, str], bool]
) -> list[MemoryHit]:
    from powercontext.builtin.runtime import GetMemoryEntryRequest

    await _prefetch_pdf_eligibility(memory, hits, eligibility)
    result: list[MemoryHit] = []
    for hit in hits:
        key = (hit.memory_ref.artifact_id, hit.entry_id, hit.entry_version_id)
        if key not in eligibility:
            citation = MemoryCitation(
                memory_ref=hit.memory_ref, entry_id=hit.entry_id, entry_version_id=hit.entry_version_id
            )
            entry = (await memory.get(GetMemoryEntryRequest(citation=citation))).entry
            eligibility[key] = len(entry.sources) == 1 and entry.sources[0].source_type == "pdf-page"
        if eligibility[key]:
            result.append(hit)
    return result


def _rank_documents(
    hits: list[MemoryHit], primary: list[str], concepts: list[list[str]], question: str
) -> list[MemoryHit]:
    # The projection's first line is only a grouping hint. Source identity comes
    # from Memory readback; labels do not prove which issuers a question requests.
    documents: dict[str, list[MemoryHit]] = {}
    coverage: dict[str, set[str]] = {}
    query_terms = set(_terms(" ".join(primary)))
    for hit in hits:
        label = hit.text.partition("\n")[0]
        documents.setdefault(label, []).append(hit)
        coverage.setdefault(label, set()).update(query_terms.intersection(_terms(hit.text)))

    # Words shared by most reports identify the topic, not a comparison subject.
    # Keep them in page scoring, but do not let a minor wording variation such
    # as "category" compete with the question's distinguishing document terms.
    frequency = Counter(term for terms in coverage.values() for term in terms)
    distinguishing = {term for term, count in frequency.items() if count <= max(1, len(documents) // 2)}
    coverage = {label: terms.intersection(distinguishing) for label, terms in coverage.items()}

    # Prefer documents whose query coverage is not a strict subset of another's.
    # Body matches count as well as labels, so an opaque ID can contribute a
    # comparison subject. Equal or complementary coverage shares result slots;
    # a generic title cannot erase a table covering the remaining query terms.
    preferred = {label for label, terms in coverage.items() if not any(terms < other for other in coverage.values())}
    groups = [
        _rank_pages(pages, primary, concepts, question) for label, pages in documents.items() if label in preferred
    ]
    ranked = [
        group[index] for index in range(max(map(len, groups), default=0)) for group in groups if index < len(group)
    ]
    remaining = _rank_pages(
        [hit for hit in hits if hit.text.partition("\n")[0] not in preferred], primary, concepts, question
    )
    requested = {label for labels in _requested_documents(hits, question).values() for label in labels}
    if preferred.intersection(requested):
        # Keep explicit issuer queries focused on the named reports. Complementary
        # reports already in the preferred group still share its result slots.
        return [*ranked, *remaining]
    # Coverage is only a document preference: a minor wording difference can
    # otherwise put every page of a repeated narrative before a real statement.
    # Preserve strong preferred hits while admitting complementary evidence
    # before the caller's top-k cut, just as page-level topic selection does.
    return [*ranked[:4], *remaining[:6], *ranked[4:], *remaining[6:]]


async def _complete_pdf_pool(
    memory: ScopedMemoryApplication, hits: list[MemoryHit], queries: list[str], memory_ref: ArtifactRef
) -> list[MemoryHit]:
    """Recover truncated lexical candidates from the same public Memory snapshot."""
    from powercontext.builtin.artifacts.memory.models import MemoryHit

    list_entries = getattr(memory, "list", None)
    if not callable(list_entries):
        return hits
    snapshot = await list_entries()
    # A concurrent write must not change the identity or state of the search
    # snapshot. Preserve its exact native citations if the head has advanced.
    if snapshot.memory_ref != memory_ref:
        return hits
    query_terms = set(analyze_fts_query(" ".join(queries)).split())
    candidates = {(hit.memory_ref.artifact_id, hit.entry_id, hit.entry_version_id): hit for hit in hits}
    for record in snapshot.entries:
        entry = record.entry
        key = (record.memory_ref.artifact_id, entry.entry_id, entry.entry_version_id)
        if (
            key in candidates
            or record.state != "active"
            or len(entry.sources) != 1
            or entry.sources[0].source_type != "pdf-page"
            or not query_terms.intersection(analyze_text(entry.text).split())
        ):
            continue
        candidates[key] = MemoryHit(
            memory_ref=record.memory_ref,
            entry_id=entry.entry_id,
            entry_version_id=entry.entry_version_id,
            text=entry.text,
            score=0.0,
            matched_by=(),
        )
    return list(candidates.values())


async def _search_candidates(
    memory: ScopedMemoryApplication, queries: list[str], question: str, limit: int
) -> list[MemoryHit]:
    from powercontext.builtin.runtime import SearchMemoryRequest

    candidates: dict[tuple[str, str, str], MemoryHit] = {}
    eligibility: dict[tuple[str, str, str], bool] = {}
    candidate_limit = min(512, max(80, limit * 4))
    remaining = 24 * candidate_limit
    calls = 0
    truncated = False

    async def collect(query: str, count: int) -> int:
        nonlocal remaining, calls, truncated
        page = await memory.search(SearchMemoryRequest(query=query, mode="fts", limit=count))
        remaining -= count
        calls += 1
        truncated |= len(page.hits) == count
        for hit in page.hits:
            candidates.setdefault((hit.memory_ref.artifact_id, hit.entry_id, hit.entry_version_id), hit)
        return len(page.hits)

    # Reserve room for issuer recovery before global topic queries consume the
    # budget. Topic-dense competing reports can otherwise fill every top-80 pool;
    # a late label boost cannot recover evidence that never entered that pool.
    initial = min(len(queries), 11)
    for query in queries[:initial]:
        await collect(query, candidate_limit)
    initial_hits = await _pdf_hits(memory, list(candidates.values()), eligibility)
    requested = _requested_documents(initial_hits, question)
    recovery = _document_recovery_queries(initial_hits, requested)
    saturated: list[str] = []
    for query in recovery[: min(24 - calls, remaining // candidate_limit)]:
        if await collect(query, candidate_limit) == candidate_limit:
            saturated.append(query)
    allocation = min(512, remaining // max(1, len(saturated)))
    for query in saturated:
        if calls == 24 or allocation <= candidate_limit:
            break
        await collect(query, allocation)
    for query in queries[initial:]:
        if calls == 24 or remaining < candidate_limit:
            break
        await collect(query, candidate_limit)

    hits = await _pdf_hits(memory, list(candidates.values()), eligibility)
    return (
        await _complete_pdf_pool(memory, hits, queries, next(iter(candidates.values())).memory_ref)
        if truncated
        else hits
    )


async def search_pdf_pages(
    memory: ScopedMemoryApplication, question: str, limit: int = 10
) -> tuple[MemoryCitation, ...]:
    """Find distinct captured pages through scoped, public Memory APIs.

    Search is offline FTS with bounded query expansion and local lexical reranking.
    Saturated searches can recover pages from the same current Memory snapshot.
    Only exact identities returned by Memory are eligible. No side index or cache
    survives a call; reopening a Runtime or switching scopes cannot reuse evidence.
    Zero limit and empty/nonlexical questions return an empty tuple.
    """
    from powercontext.builtin.runtime import GetMemoryEntryRequest

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
    if (number := _printed_page(question)) is not None:
        queries.insert(1, number)
    # Pair forms in one native query: its two-term admission rule accepts either
    # form. Separate groups avoid requiring a page to contain several synonyms.
    queries.extend(" ".join(_FORMS[term]) for term in primary if term in _FORMS)
    # Individual topical terms recover candidates excluded by multi-term coverage
    # gates. Bounded fanout keeps long natural-language instructions inexpensive.
    queries.extend(term for term in primary if not term.isdecimal())
    pool = await _search_candidates(memory, list(dict.fromkeys(queries))[:24], question, limit)
    ranked = _rank_documents(pool, primary, concepts, question)
    result: list[MemoryCitation] = []
    seen: set[str] = set()
    for hit in ranked:
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
