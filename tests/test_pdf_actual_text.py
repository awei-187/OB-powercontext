# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

"""Declared text replacement, shared Form isolation, and atomic malformed-input rejection."""

import hashlib
import io

import pytest
from pypdf import PdfReader
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    StreamObject,
    TextStringObject,
)

from powercontext.sources.pdf_pages import PDFDocumentInput, _extract_page_text, parse_pdf_document
from tests.e2e.test_pdf_locations_and_headings import _capture, _locations
from tests.test_pdf_integrity import _serialize, _writer

START = b"BT /F1 12 Tf 72 700 Td "
END = b" ET"


def stream(writer, data):
    obj = DecodedStreamObject()
    obj.set_data(data)
    return writer._add_object(obj)


def form(writer, data, resources):
    obj = DecodedStreamObject()
    obj.set_data(data)
    obj[NameObject("/Type")] = NameObject("/XObject")
    obj[NameObject("/Subtype")] = NameObject("/Form")
    obj[NameObject("/BBox")] = ArrayObject([NumberObject(v) for v in (0, 0, 612, 792)])
    obj[NameObject("/Resources")] = resources
    return writer._add_object(obj)


def simple(data):
    w = _writer()
    w.pages[1][NameObject("/Contents")] = stream(w, data)
    return w


def named():
    w = _writer()
    for i, page in enumerate(w.pages):
        props = DictionaryObject({NameObject("/ActualText"): TextStringObject("PageOne" if i == 0 else "PageTwo")})
        page["/Resources"][NameObject("/Properties")] = DictionaryObject({
            NameObject("/Replacement"): w._add_object(props)
        })
        page[NameObject("/Contents")] = stream(w, START + b"/Span /Replacement BDC (X) Tj EMC" + END)
    return w


def forms(body, *, outer=False, nested=False, repeat=False):
    w = _writer()
    font = w.pages[1]["/Resources"]["/Font"]
    res = DictionaryObject({NameObject("/Font"): font})
    ref = form(w, body, res)
    if nested:
        res2 = DictionaryObject({
            NameObject("/Font"): font,
            NameObject("/XObject"): DictionaryObject({NameObject("/Child"): ref}),
        })
        ref = form(w, b"/Child Do", res2)
    for page in w.pages:
        page["/Resources"][NameObject("/XObject")] = DictionaryObject({NameObject("/Shared"): ref})
        data = b"/Shared Do /Shared Do" if repeat else b"/Shared Do"
        if outer:
            data = b"/Span << /ActualText (Whole) >> BDC " + data + b" EMC"
        page[NameObject("/Contents")] = stream(w, data)
    return w


cases = []


def add(name, writer, expected, *, rejection=False):
    cases.append((name, writer, expected, rejection))


add("named-page-scopes", named(), ["PageOne", "PageTwo"])
body = START + b"/Span << /ActualText (FormText) >> BDC (wrong) Tj EMC" + END
add("shared-form", forms(body), ["FormText", "FormText"])
add("repeated-shared-form", forms(body, repeat=True), ["FormText FormText", "FormText FormText"])
add("nested-form", forms(body, nested=True), ["FormText", "FormText"])
add("outer-form-replacement", forms(body, repeat=True, outer=True), ["Whole", "Whole"])
for name, content in [
    ("bad-property", START + b"/Span << /ActualText 123 >> BDC (X) Tj EMC" + END),
    ("bad-utf16", START + b"/Span << /ActualText <FEFF00> >> BDC (X) Tj EMC" + END),
    ("unclosed", START + b"/Span << /ActualText (Y) >> BDC (X) Tj" + END),
    ("cross-form-close", b"EMC " + START + b"(X) Tj" + END),
    ("partial-tj-type", START + b"/Span << /ActualText (Y) >> BDC [(A) -200 /Bad] TJ EMC" + END),
]:
    add("form-" + name, forms(content, outer=name == "cross-form-close"), None, rejection=True)

for name, content, expected in [
    ("repeat-span", b"/Span << /ActualText (A) >> BDC (x) Tj EMC /Span << /ActualText (B) >> BDC (x) Tj EMC", "AB"),
    ("inner-only", b"/P BMC (Before ) Tj /Span << /ActualText (A) >> BDC (x) Tj EMC ( After) Tj EMC", "Before A After"),
    ("empty-first-show", b"/Span << /ActualText (A) >> BDC () Tj (x) Tj EMC", "A"),
    (
        "positive-negative-spacing",
        b"/Span << /ActualText (One) >> BDC [(x) 700 (y) -700 (z)] TJ EMC ( Next) Tj",
        "One Next",
    ),
    ("single-quote", b"14 TL /Span << /ActualText (A) >> BDC (x) ' EMC (B) Tj", "AB"),
    ("double-quote", b'14 TL /Span << /ActualText (A) >> BDC 0 0 (x) " EMC (B) Tj', "AB"),
    ("graphic-save-restore", b"q /F1 20 Tf /Span << /ActualText (A) >> BDC (x) Tj EMC Q (B) Tj", "AB"),
    ("null-actual-text", b"/Span << /ActualText null >> BDC (Normal) Tj EMC", "Normal"),
    ("literal-backslashes", rb"/Span << /ActualText (C:\\path\(name\)) >> BDC (x) Tj EMC", "C:\\path(name)"),
    ("utf16-surrogate", b"/Span << /ActualText <FEFFD83DDE00> >> BDC (x) Tj EMC", "\U0001f600"),
    ("no-actual-markers", b"/P BMC (Body) Tj EMC", "Body"),
]:
    add(name, simple(START + content + END), ["First complete page", expected])

for name, content in [
    ("missing-named-property", b"/Span /Missing BDC (x) Tj EMC"),
    ("bad-tj-after-first", b"/Span << /ActualText (A) >> BDC [(x) -200 /Bad] TJ EMC"),
    ("surrogate-alone", b"/Span << /ActualText <FEFFD800> >> BDC (x) Tj EMC"),
    ("wrong-bmc-arity", b"/P 1 BMC (x) Tj EMC"),
    ("wrong-emc-arity", b"/P BMC (x) Tj 1 EMC"),
]:
    add(name, simple(START + content + END), None, rejection=True)


add(
    "latin-ligature",
    simple(START + b"(Sec) Tj /Span << /ActualText (ti) >> BDC (X) Tj EMC (on) Tj" + END),
    ["First complete page", "Section"],
)
add(
    "utf16-replacement",
    simple(START + b"/Span << /ActualText <FEFF00740069> >> BDC (X) Tj EMC" + END),
    ["First complete page", "ti"],
)
add(
    "empty-replacement",
    simple(START + b"(A) Tj /Span << /ActualText () >> BDC (X) Tj EMC (B) Tj" + END),
    ["First complete page", "AB"],
)
add(
    "nested-replacements",
    simple(
        START
        + b"/Span << /ActualText (outer) >> BDC (x) Tj /Span << /ActualText (inner) >> BDC (y) Tj EMC (z) Tj EMC"
        + END
    ),
    ["First complete page", "outer"],
)
add(
    "declared-number-differs-from-glyphs",
    simple(START + b"/Span << /ActualText (900) >> BDC (100) Tj EMC" + END),
    ["First complete page", "900"],
)
add(
    "literal-operator-text",
    simple(START + b"/Span << /ActualText (EMC /Span BDC do_not_execute) >> BDC (X) Tj EMC" + END),
    ["First complete page", "EMC /Span BDC do_not_execute"],
)
add(
    "numeric-columns",
    simple(START + b"/Span << /ActualText (Balance) >> BDC (X) Tj EMC 120 0 Td (123) Tj 60 0 Td (456) Tj" + END),
    ["First complete page", "Balance 123 456"],
)
add(
    "artifact-replacement",
    simple(START + b"/Artifact << /ActualText (Header) >> BDC (X) Tj EMC" + END),
    ["First complete page", "Header"],
)
add(
    "unrecognized-tag-property",
    simple(START + b"/PrivateTag << /ActualText 123 >> BDC (Body) Tj EMC" + END),
    ["First complete page", "Body"],
)


@pytest.mark.parametrize(("name", "writer", "expected", "rejection"), cases, ids=[c[0] for c in cases])
def test_declared_text_and_atomic_errors(name, writer, expected, rejection):
    raw = _serialize(writer)
    received = []
    if rejection:
        with pytest.raises(ValueError):
            received.extend(parse_pdf_document(PDFDocumentInput(document_id=name, content=raw)))
        assert received == []
        return
    received = parse_pdf_document(PDFDocumentInput(document_id=name, content=raw))
    assert [" ".join(p.text.split()) for p in received] == expected
    assert [p.page_number for p in received] == [1, 2]
    assert all(p.document_sha256 == hashlib.sha256(raw).hexdigest() for p in received)
    assert parse_pdf_document(PDFDocumentInput(document_id=name, content=raw)) == received


@pytest.mark.parametrize(("name", "writer", "expected", "rejection"), cases, ids=[c[0] for c in cases])
def test_reused_reader_and_reversed_pages_preserve_originals(name, writer, expected, rejection):
    reader = PdfReader(io.BytesIO(_serialize(writer)), strict=True)
    baseline = [page.extract_text() for page in reader.pages]
    contents = [page["/Contents"] for page in reader.pages]
    assert all(isinstance(content, StreamObject) for content in contents)
    original_streams = [content.get_data() for content in contents if isinstance(content, StreamObject)]
    for order in ([0, 1], [1, 0], [0, 1]):
        if rejection:
            with pytest.raises((ValueError, TypeError)):
                tuple(_extract_page_text(reader.pages[i]) for i in order)
        else:
            for i in order:
                assert " ".join(_extract_page_text(reader.pages[i]).split()) == expected[i]
        assert [page.extract_text() for page in reader.pages] == baseline
        assert [content.get_data() for content in contents if isinstance(content, StreamObject)] == original_streams


async def test_replacement_survives_real_memory_restart_and_exact_retrieval(tmp_path):
    content = START + b"/Span << /ActualText (Revenue 987654) >> BDC (Bad glyphs) Tj EMC" + END
    config, scope, captured = await _capture(tmp_path, {"replacement report": _serialize(simple(content))})
    assert await _locations(config, scope, captured, "Revenue 987654", 20) == [("replacement report", 2)]


def test_recursive_form_is_rejected_without_returning_earlier_pages():
    writer = _writer()
    resources = DictionaryObject()
    child = form(writer, b"/Self Do", resources)
    resources[NameObject("/XObject")] = DictionaryObject({NameObject("/Self"): child})
    writer.pages[1]["/Resources"][NameObject("/XObject")] = DictionaryObject({NameObject("/Loop"): child})
    writer.pages[1][NameObject("/Contents")] = stream(writer, b"/Loop Do")
    received = []
    with pytest.raises(ValueError):
        received.extend(parse_pdf_document(PDFDocumentInput(document_id="recursive form", content=_serialize(writer))))
    assert received == []
