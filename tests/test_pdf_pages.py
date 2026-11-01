# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

"""PDF extraction, revision identity and native Source serialization boundaries."""

from __future__ import annotations

import hashlib
import io
import re
from collections import Counter
from pathlib import Path
from typing import cast

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NumberObject

from powercontext.builtin.runtime import ScopedMemoryApplication
from powercontext.sources import SourceDefinitionRegistry, SourceObservation, project_source_for_transport
from powercontext.sources.models import SourceMaterialization
from powercontext.sources.pdf_pages import (
    PDF_PAGE_SOURCE_DEFINITION,
    PDFDocumentInput,
    PDFPageInput,
    PDFPageSource,
    parse_pdf_document,
    search_pdf_pages,
)
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY
from tests.pdf_fixtures import pdf_bytes


def test_complete_text_tables_blank_pages_and_physical_boundaries():
    text = (
        "Company Zeta annual report\nPrinted page xii\nRevenue 2024 2023\nEurope 1,234.50 (56.70)",
        "",
        "Revenue continued\nAsia 987.65 432.10\nTotal 2,222.15 375.40\nFootnote: amounts in millions.",
    )
    raw = pdf_bytes(*text)
    pages = parse_pdf_document(PDFDocumentInput(document_id=" annual/报告:% \n", content=raw))
    assert len(pages) == 3
    for index, (expected, page) in enumerate(zip(text, pages, strict=True), 1):
        assert page.document_id == " annual/报告:% \n"
        assert page.page_number == index
        assert page.document_sha256 == hashlib.sha256(raw).hexdigest()
        assert page.text.strip() == expected
    assert "Asia" not in pages[0].text and "Europe" not in pages[2].text


@pytest.mark.parametrize("document_id", ["", " ", "\n\t", "\u2003"])
def test_empty_document_identity_rejected(document_id):
    with pytest.raises(ValueError):
        PDFDocumentInput(document_id=document_id, content=pdf_bytes("Revenue"))


@pytest.mark.parametrize("page_number", [0, -1, True, 1.5, "1"])
def test_page_number_must_be_a_positive_integer(page_number):
    with pytest.raises(ValueError):
        PDFPageInput(document_id="report", document_sha256="a" * 64, page_number=page_number, text="")


@pytest.mark.parametrize("digest", ["", "a" * 63, "g" * 64, "A" * 64, "a" * 64 + "\n"])
def test_digest_must_be_exact_lowercase_sha256(digest):
    with pytest.raises(ValueError):
        PDFPageInput(document_id="report", document_sha256=digest, page_number=1, text="")


@pytest.mark.parametrize("password", [None, ""])
def test_unencrypted_and_empty_user_password_preserve_text(password):
    raw = pdf_bytes("Revenue 1,234.50", "", "End 678.90", password=password)
    pages = parse_pdf_document(PDFDocumentInput(document_id="report", content=raw))
    assert [page.text.strip() for page in pages] == ["Revenue 1,234.50", "", "End 678.90"]
    assert all(page.document_sha256 == hashlib.sha256(raw).hexdigest() for page in pages)


def test_nonempty_password_rejected():
    with pytest.raises(ValueError):
        parse_pdf_document(PDFDocumentInput(document_id="report", content=pdf_bytes("Secret", password="locked")))  # noqa: S106


@pytest.mark.parametrize("raw", [b"", b"fake text", b"%PDF-1.7\ntruncated", b"%PDF-1.7\n%%EOF"])
def test_invalid_pdf_is_a_value_error(raw):
    with pytest.raises(ValueError):
        parse_pdf_document(PDFDocumentInput(document_id="report", content=raw))


@pytest.mark.parametrize("contents", [NumberObject(17), ArrayObject([NumberObject(17)]), DictionaryObject()])
def test_late_page_corruption_fails_the_entire_parse(contents):
    writer = PdfWriter(clone_from=io.BytesIO(pdf_bytes("First valid page", "Last page")))
    writer.pages[1][NameObject("/Contents")] = contents
    output = io.BytesIO()
    writer.write(output)
    with pytest.raises(ValueError):
        parse_pdf_document(PDFDocumentInput(document_id="report", content=output.getvalue()))


def test_truncated_pdf_with_some_valid_objects_fails():
    raw = pdf_bytes("First page", "Last page")
    with pytest.raises(ValueError):
        parse_pdf_document(PDFDocumentInput(document_id="report", content=raw[: raw.index(b"startxref")]))


async def test_source_identity_projection_roundtrip_and_revisions():
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    ids = ["a:b", "a%3Ab", "a/b", "a", " a ", "é", "e\u0301", "报告" * 1000]
    names = set()
    for document_id in ids:
        raw = pdf_bytes("Revenue 100", "Revenue 100")
        revised = pdf_bytes("Revenue 100", "Revenue 100", title="new revision")
        for content in (raw, revised):
            for page in parse_pdf_document(PDFDocumentInput(document_id=document_id, content=content)):
                source = await registry.resolve(page)
                assert await registry.read(source) == page
                assert (await registry.resolve(page)).name == source.name
                assert source.materialization == SourceMaterialization.CAPTURED
                assert len(source.name) <= 256
                assert source.name not in names
                names.add(source.name)
                observation = project_source_for_transport(registry, source)
                restored = SourceObservation.model_validate_json(observation.model_dump_json())
                captured = PDFPageSource.model_validate(restored.payload)
                assert await registry.read(captured) == page
                assert restored.projection(TEXT_EVIDENCE_PROJECTION_KEY) == {
                    "source_type": "pdf-page",
                    "source_id": source.name,
                    "content": f"{document_id}\n{page.text}",
                    "metadata": {
                        "document_id": document_id,
                        "document_sha256": page.document_sha256,
                        "page_number": page.page_number,
                    },
                }


async def test_tampered_source_identity_and_mutation_rejected():
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    page = parse_pdf_document(PDFDocumentInput(document_id="report", content=pdf_bytes("Revenue")))[0]
    source = await registry.resolve(page)
    assert isinstance(source, PDFPageSource)
    for field, value in [
        ("name", "wrong"),
        ("page_number", 2),
        ("definition_version", "2"),
        ("materialization", "referenced"),
    ]:
        with pytest.raises(ValueError):
            PDFPageSource.model_validate(source.model_dump() | {field: value})
    with pytest.raises(ValueError):
        source.__setattr__("text", "different text")


async def test_empty_and_invalid_search_arguments_do_not_need_memory():
    # Deliberately absent at runtime: these branches must reject/return before using Memory.
    memory = cast(ScopedMemoryApplication, None)
    for question, limit in [("Revenue", 0), ("", 10), (" \n", 10), ("?!", 10)]:
        assert await search_pdf_pages(memory, question, limit) == ()
    for limit in [-1, True, 0.1, "2"]:
        with pytest.raises(ValueError):
            await search_pdf_pages(memory, "Revenue", cast(int, limit))


def test_public_report_all_503_pages_match_independent_pypdf_extraction():
    path = (
        Path(__file__).parents[1]
        / "competition/challenges/source-03-pdf-retrieval/workload/public/pdfs/PEPSICO_2022_10K.pdf"
    )
    raw = path.read_bytes()
    pages = parse_pdf_document(PDFDocumentInput(document_id="public-report", content=raw))
    reader = PdfReader(io.BytesIO(raw))
    if reader.is_encrypted:
        reader.decrypt("")
    assert len(pages) == len(reader.pages) == 503
    assert hashlib.sha256(raw).hexdigest() == "7d8a9f3374e429c58f101319e2da8a0e601a89859e1e4f6854163dd5f8ce6b47"
    for physical_page, (actual, expected) in enumerate(zip(pages, reader.pages, strict=True), 1):
        assert actual.page_number == physical_page
        expected_text = expected.extract_text() or ""
        assert actual.text == expected_text
        assert Counter(re.findall(r"[a-z]+|\d+", actual.text.lower())) == Counter(
            re.findall(r"[a-z]+|\d+", expected_text.lower())
        )
