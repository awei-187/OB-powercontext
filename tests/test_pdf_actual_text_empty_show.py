# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

"""An empty text-show string still anchors declared replacement text in order."""

import hashlib
import io

import pytest
from pypdf import PdfReader

from powercontext.sources.pdf_pages import PDFDocumentInput, _extract_page_text, parse_pdf_document
from tests.e2e.test_pdf_locations_and_headings import _capture, _locations
from tests.test_pdf_actual_text import END, START, forms, simple
from tests.test_pdf_integrity import _serialize


@pytest.mark.parametrize("show", [b"() Tj", b"[()] TJ", b"[() ()] TJ", b"[-200 () 200 ()] TJ", b"() '", b'0 0 () "'])
@pytest.mark.parametrize(
    ("replacement", "expected"),
    [(b"( )", "Net income"), (b"( bridge )", "Net bridge income"), (b"<FEFF0020>", "Net income"), (b"()", "Netincome")],
)
def test_empty_text_show_emits_declared_text_at_its_position(show, replacement, expected):
    content = START + b"(Net) Tj /Span << /ActualText " + replacement + b" >> BDC " + show + b" EMC (income) Tj" + END
    raw = _serialize(simple(content))
    pages = parse_pdf_document(PDFDocumentInput(document_id="empty glyphs", content=raw))
    assert [p.text.strip() for p in pages] == ["First complete page", expected]
    assert [p.page_number for p in pages] == [1, 2]
    assert all(p.document_sha256 == hashlib.sha256(raw).hexdigest() for p in pages)
    assert parse_pdf_document(PDFDocumentInput(document_id="empty glyphs", content=raw)) == pages
    reader = PdfReader(io.BytesIO(raw), strict=True)
    original = [page.extract_text() for page in reader.pages]
    for order in ([1, 0], [0, 1]):
        for i in order:
            assert _extract_page_text(reader.pages[i]) == pages[i].text
        assert [page.extract_text() for page in reader.pages] == original


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (b"(Net) Tj /Span << /ActualText ( ) >> BDC () Tj (ignored) Tj () Tj EMC (income) Tj", "Net income"),
        (
            b"(Net) Tj /Span << /ActualText ( ) >> BDC /Span << /ActualText (wrong) >> BDC () Tj EMC () Tj EMC (income) Tj",
            "Net income",
        ),
        (
            b"(Net) Tj /Span << /ActualText ( ) >> BDC () Tj /Span << /ActualText (wrong) >> BDC (x) Tj EMC EMC (income) Tj",
            "Net income",
        ),
        (b"(Net) Tj /P BMC /Span << /ActualText ( ) >> BDC () Tj EMC EMC (income) Tj", "Net income"),
        (
            b"(Net) Tj /Span << /ActualText () >> BDC () Tj /Span << /ActualText (wrong) >> BDC (x) Tj EMC EMC (income) Tj",
            "Netincome",
        ),
        (
            b"(Net) Tj /Span << /ActualText ( A ) >> BDC () Tj EMC /Span << /ActualText (B ) >> BDC [()] TJ EMC (income) Tj",
            "Net A B income",
        ),
        (
            b"(Left) Tj /Span << /ActualText (not a text show) >> BDC EMC /Span << /ActualText ( bridge ) >> BDC () Tj EMC (Right) Tj",
            "Left bridge Right",
        ),
        (
            b"(Left) Tj /Span << /ActualText (not a text show) >> BDC /Span << /ActualText (also unused) >> BDC EMC EMC (Right) Tj",
            "LeftRight",
        ),
        (b"/Span << /ActualText (Balance) >> BDC () Tj EMC 120 0 Td (123) Tj 60 0 Td (456) Tj", "Balance 123 456"),
    ],
)
def test_empty_show_keeps_outer_precedence_order_and_zero_glyph_advance(content, expected):
    raw = _serialize(simple(START + content + END))
    pages = parse_pdf_document(PDFDocumentInput(document_id="ordered empty shows", content=raw))
    assert pages[1].text.strip() == expected


@pytest.mark.parametrize("nested", [False, True])
def test_repeated_shared_form_does_not_reuse_empty_show_emission_state(nested):
    content = START + b"/Span << /ActualText (bridge) >> BDC () Tj [()] TJ EMC" + END
    raw = _serialize(forms(content, nested=nested, repeat=True))
    pages = parse_pdf_document(PDFDocumentInput(document_id="shared empty show", content=raw))
    assert [" ".join(p.text.split()) for p in pages] == ["bridge bridge", "bridge bridge"]
    reader = PdfReader(io.BytesIO(raw), strict=True)
    original = [page.extract_text() for page in reader.pages]
    for i in (1, 0, 1, 0):
        assert _extract_page_text(reader.pages[i]) == pages[i].text
    assert [page.extract_text() for page in reader.pages] == original


def test_error_after_empty_show_restores_operands_and_rejects_document_atomically():
    content = START + b"/Span << /ActualText (bridge) >> BDC [() (x) /Bad] TJ EMC" + END
    raw = _serialize(simple(content))
    received = []
    with pytest.raises(ValueError):
        received.extend(parse_pdf_document(PDFDocumentInput(document_id="bad later operand", content=raw)))
    assert received == []
    reader = PdfReader(io.BytesIO(raw), strict=True)
    original = [page.extract_text() for page in reader.pages]
    for _ in range(2):
        with pytest.raises(ValueError):
            _extract_page_text(reader.pages[1])
        assert [page.extract_text() for page in reader.pages] == original


async def test_empty_show_word_boundary_survives_memory_restart(tmp_path):
    content = START + b"(Net) Tj /Span << /ActualText ( ) >> BDC () Tj EMC (income) Tj" + END
    config, scope, captured = await _capture(tmp_path, {"empty glyph report": _serialize(simple(content))})
    assert await _locations(config, scope, captured, "Net income", 20) == [("empty glyph report", 2)]
