# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

"""Real PDF regressions for loss hidden by the pinned decoder's recovery paths."""

from __future__ import annotations

import base64
import io
import zlib

import pytest
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    EncodedStreamObject,
    NameObject,
    NullObject,
    NumberObject,
)

from powercontext.sources.pdf_pages import PDFDocumentInput, parse_pdf_document
from tests.pdf_fixtures import pdf_bytes


def _writer():
    return PdfWriter(clone_from=io.BytesIO(pdf_bytes("First complete page", "Page Revenue 987,654.32")))


def _encode(data, filters=("/FlateDecode",)):
    stream = EncodedStreamObject()
    stream._data = data
    stream[NameObject("/Filter")] = (
        NameObject(filters[0]) if len(filters) == 1 else ArrayObject([NameObject(item) for item in filters])
    )
    return stream


def _serialize(writer):
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def _parse(writer):
    return parse_pdf_document(PDFDocumentInput(document_id="integrity report", content=_serialize(writer)))


def _assert_atomic_failure(writer):
    received = []
    with pytest.raises(ValueError):
        for page in _parse(writer):
            received.append(page)
    # A consumer must never ingest an apparently successful earlier page.
    assert received == []


@pytest.mark.parametrize("removed", [1, 2, 4, 5, 12, 30])
def test_truncated_zlib_in_late_page_rejects_even_complete_decoded_text(removed):
    writer = _writer()
    page = writer.pages[1]
    encoded = zlib.compress(page["/Contents"].get_data())
    page[NameObject("/Contents")] = writer._add_object(_encode(encoded[:-removed]))
    _assert_atomic_failure(writer)


@pytest.mark.parametrize("damage", ["checksum", "garbage", "empty"])
def test_damaged_flate_page_fails_atomically(damage):
    writer = _writer()
    page = writer.pages[1]
    encoded = zlib.compress(page["/Contents"].get_data())
    data = {"checksum": encoded[:-1] + bytes([encoded[-1] ^ 0xFF]), "garbage": b"broken deflate", "empty": b""}
    page[NameObject("/Contents")] = writer._add_object(_encode(data[damage]))
    _assert_atomic_failure(writer)


@pytest.mark.parametrize("encoding", ["flate", "trailing-newline", "ascii85-flate", "flate-flate", "predictor"])
def test_valid_filter_chains_preserve_full_text(encoding):
    writer = _writer()
    page = writer.pages[1]
    decoded = page["/Contents"].get_data()
    filters = ("/FlateDecode",)
    data = zlib.compress(decoded)
    if encoding == "trailing-newline":
        data += b"\r\n"
    elif encoding == "ascii85-flate":
        data = base64.a85encode(data) + b"~>"
        filters = ("/ASCII85Decode", "/FlateDecode")
    elif encoding == "flate-flate":
        data = zlib.compress(data)
        filters = ("/FlateDecode", "/FlateDecode")
    elif encoding == "predictor":
        data = zlib.compress(b"\x00" + decoded)
    stream = _encode(data, filters)
    if encoding == "predictor":
        stream[NameObject("/DecodeParms")] = DictionaryObject({
            NameObject("/Predictor"): NumberObject(12),
            NameObject("/Columns"): NumberObject(len(decoded)),
        })
    elif len(filters) > 1:
        stream[NameObject("/DecodeParms")] = ArrayObject([NullObject(), NullObject()])
    page[NameObject("/Contents")] = writer._add_object(stream)
    assert [page.text.strip() for page in _parse(writer)] == ["First complete page", "Page Revenue 987,654.32"]


def test_compressed_empty_content_is_a_valid_blank_page():
    writer = _writer()
    writer.pages[1][NameObject("/Contents")] = writer._add_object(_encode(zlib.compress(b"")))
    assert [page.text.strip() for page in _parse(writer)] == ["First complete page", ""]


@pytest.mark.parametrize("damaged", [False, True])
def test_nested_form_stream_is_validated_and_extractable(damaged):
    writer = _writer()
    page = writer.pages[1]
    data = zlib.compress(page["/Contents"].get_data())
    form = _encode(data[:-1] if damaged else data)
    form[NameObject("/Type")] = NameObject("/XObject")
    form[NameObject("/Subtype")] = NameObject("/Form")
    form[NameObject("/BBox")] = ArrayObject([NumberObject(x) for x in (0, 0, 612, 792)])
    form[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): page["/Resources"]["/Font"]})
    page["/Resources"][NameObject("/XObject")] = DictionaryObject({NameObject("/Report"): writer._add_object(form)})
    content = DecodedStreamObject()
    content.set_data(b"/Report Do")
    page[NameObject("/Contents")] = writer._add_object(content)
    if damaged:
        _assert_atomic_failure(writer)
    else:
        assert _parse(writer)[1].text.strip() == "Page Revenue 987,654.32"


def _add_cmap(writer, mapping, *, compressed=False, truncate=False):
    data = (
        b"/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
        b"/CIDSystemInfo << /Registry (Example) /Ordering (Unicode) /Supplement 0 >> def\n"
        b"/CMapName /Evidence def\n/CMapType 2 def\n"
        b"1 begincodespacerange\n<00> <FF>\nendcodespacerange\n" + mapping + b"\nendcmap\nend\nend"
    )
    if compressed:
        data = zlib.compress(data)
        stream = _encode(data[:-2] if truncate else data)
    else:
        stream = DecodedStreamObject()
        stream.set_data(data)
    writer.pages[1]["/Resources"]["/Font"]["/F1"][NameObject("/ToUnicode")] = writer._add_object(stream)


@pytest.mark.parametrize(
    "mapping",
    [
        b"1 beginbfchar\n<50> <XY00>\nendbfchar",
        b"1 beginbfchar\n<Z0> <03A9>\nendbfchar",
        b"2 beginbfchar\n<50> <03A9>\nendbfchar",
        b"1 beginbfchar\n<50>\nendbfchar",
        b"1 beginbfchar\n<50> <03A9>",
        b"1 beginbfchar\n<50> <000001>\nendbfchar",
        b"1 beginbfrange\n<50> <51> [<03A9>]\nendbfrange",
        b"1 beginbfrange\n<51> <50> <03A9>\nendbfrange",
        b"1 beginbfrange\n<50> <51> <FFFF>\nendbfrange",
        b"1 beginbfrange\n<50> <51> [<03A9> <XX>]\nendbfrange",
    ],
)
def test_corrupt_cmap_records_fail_atomically(mapping):
    writer = _writer()
    _add_cmap(writer, mapping)
    _assert_atomic_failure(writer)


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize(
    ("mapping", "expected"),
    [
        (b"1 beginbfchar\n<50> <03A9>\nendbfchar", "\u03a9age"),
        (b"1 beginbfchar\n<50> <D83DDE00>\nendbfchar", "\U0001f600age"),
        (b"1 beginbfchar\n<50> <00660069>\nendbfchar", "fiage"),
        (b"1 beginbfrange\n<50> <51> <03A9>\nendbfrange", "\u03a9age"),
        (b"1 beginbfrange\n<50> <51> [\n<03A9>\n<03AA>\n]\nendbfrange", "\u03a9age"),
    ],
)
def test_valid_cmaps_preserve_non_ascii_and_multiline_arrays(mapping, expected, compressed):
    writer = _writer()
    _add_cmap(writer, mapping, compressed=compressed)
    page = _parse(writer)[1]
    assert page.text.strip() == expected + " Revenue 987,654.32"


def test_truncated_compressed_cmap_fails_atomically():
    writer = _writer()
    _add_cmap(writer, b"1 beginbfchar\n<50> <03A9>\nendbfchar", compressed=True, truncate=True)
    _assert_atomic_failure(writer)
