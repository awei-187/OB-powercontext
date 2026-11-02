# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

"""Dictionary null parameters must decode like an omitted entry, including Forms."""

import base64
import hashlib
import io
import zlib

import pytest
from pypdf import PdfReader
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    EncodedStreamObject,
    NameObject,
    NullObject,
    NumberObject,
    StreamObject,
)

from powercontext.sources._pdf_validation import validate_page_objects
from powercontext.sources.pdf_pages import PDFDocumentInput, parse_pdf_document
from tests.e2e.test_pdf_locations_and_headings import _capture, _locations
from tests.test_pdf_integrity import _add_cmap, _encode, _serialize, _writer


def _filter_chain(writer, data, filters, parameters, damaged):
    for name in reversed(filters):
        if name == "/FlateDecode":
            data = zlib.compress(data)
            if damaged:
                data = data[:-2]
                damaged = False
        elif name == "/ASCIIHexDecode":
            data = data.hex().encode() + b">"
        else:
            data = base64.a85encode(data) + b"~>"
    stream = _encode(data, filters)
    if parameters == "null":
        stream[NameObject("/DecodeParms")] = NullObject()
    elif parameters == "indirect-null":
        stream[NameObject("/DecodeParms")] = writer._add_object(NullObject())
    elif parameters == "array":
        stream[NameObject("/DecodeParms")] = ArrayObject([NullObject() for _ in filters])
    return stream


def _filtered_document(parameters, location="page", filters=("/ASCIIHexDecode", "/FlateDecode"), *, damaged=False):
    writer = _writer()
    page = writer.pages[1]
    original = page["/Contents"].get_data()
    if location == "cmap":
        _add_cmap(writer, b"1 beginbfchar\n<50> <03A9>\nendbfchar")
        original = page["/Resources"]["/Font"]["/F1"]["/ToUnicode"].get_data()
    stream = _filter_chain(writer, original, filters, parameters, damaged)
    if location == "cmap":
        page["/Resources"]["/Font"]["/F1"][NameObject("/ToUnicode")] = writer._add_object(stream)
    elif location == "page":
        page[NameObject("/Contents")] = writer._add_object(stream)
    else:
        for index in range(2 if location == "nested" else 1):
            child = stream
            if index:
                stream = DecodedStreamObject()
                stream.set_data(b"/Child Do")
            stream[NameObject("/Type")] = NameObject("/XObject")
            stream[NameObject("/Subtype")] = NameObject("/Form")
            stream[NameObject("/BBox")] = ArrayObject([NumberObject(v) for v in (0, 0, 612, 792)])
            resources = DictionaryObject({NameObject("/Font"): page["/Resources"]["/Font"]})
            if index:
                resources[NameObject("/XObject")] = DictionaryObject({NameObject("/Child"): writer._add_object(child)})
            stream[NameObject("/Resources")] = resources
        page["/Resources"][NameObject("/XObject")] = DictionaryObject({
            NameObject("/Report"): writer._add_object(stream)
        })
        calls = DecodedStreamObject()
        calls.set_data(b"/Report Do")
        page[NameObject("/Contents")] = writer._add_object(calls)
    return writer, original


@pytest.mark.parametrize("parameters", ["omitted", "null", "indirect-null", "array"])
@pytest.mark.parametrize("location", ["page", "form", "nested", "cmap"])
def test_equivalent_default_parameters_preserve_complete_pages(parameters, location):
    writer, _ = _filtered_document(parameters, location)
    raw = _serialize(writer)
    pages = parse_pdf_document(PDFDocumentInput(document_id="encoded report", content=raw))
    expected = "\u03a9age" if location == "cmap" else "Page"
    assert [p.text.strip() for p in pages] == ["First complete page", expected + " Revenue 987,654.32"]
    assert [p.page_number for p in pages] == [1, 2]
    assert all(p.document_sha256 == hashlib.sha256(raw).hexdigest() for p in pages)


@pytest.mark.parametrize(
    "filters",
    [
        ("/ASCII85Decode", "/FlateDecode"),
        ("/FlateDecode", "/FlateDecode"),
        ("/ASCIIHexDecode", "/ASCII85Decode", "/FlateDecode"),
        ("/ASCIIHexDecode", "/ASCII85Decode"),
        ("/FlateDecode",),
    ],
)
def test_null_parameters_apply_to_every_filter(filters):
    writer, _ = _filtered_document("null", filters=filters)
    pages = parse_pdf_document(PDFDocumentInput(document_id="filter chain", content=_serialize(writer)))
    assert pages[1].text.strip() == "Page Revenue 987,654.32"


@pytest.mark.parametrize("parameters", ["omitted", "null", "array", "indirect-null"])
@pytest.mark.parametrize("location", ["page", "form", "cmap"])
def test_corrupt_inner_flate_is_rejected_atomically(parameters, location):
    writer, _ = _filtered_document(parameters, location, damaged=True)
    received = []
    with pytest.raises(ValueError):
        received.extend(parse_pdf_document(PDFDocumentInput(document_id="damaged report", content=_serialize(writer))))
    assert received == []


@pytest.mark.parametrize("parameters", ["null", "indirect-null", "array", "omitted"])
def test_decode_keeps_original_parameters_bytes_and_repeated_reader_results(parameters):
    writer, expected = _filtered_document(parameters)
    reader = PdfReader(io.BytesIO(_serialize(writer)), strict=True)
    stream = reader.pages[1]["/Contents"]
    assert isinstance(stream, StreamObject)
    metadata, encoded = dict(stream), stream._data
    for _ in range(2):
        validate_page_objects(tuple(reader.pages))
        assert stream.get_data() == expected
        assert reader.pages[1].extract_text().strip() == "Page Revenue 987,654.32"
        assert dict(stream) == metadata
        assert stream._data == encoded
        assert all(stream.raw_get(key) is value for key, value in metadata.items())


def test_nondefault_predictor_parameters_remain_effective_and_unchanged():
    writer = _writer()
    page = writer.pages[1]
    expected = page["/Contents"].get_data()
    stream = _encode(zlib.compress(b"\x00" + expected).hex().encode() + b">", ("/ASCIIHexDecode", "/FlateDecode"))
    stream[NameObject("/DecodeParms")] = ArrayObject([
        NullObject(),
        DictionaryObject({
            NameObject("/Predictor"): NumberObject(12),
            NameObject("/Columns"): NumberObject(len(expected)),
        }),
    ])
    page[NameObject("/Contents")] = writer._add_object(stream)
    reader = PdfReader(io.BytesIO(_serialize(writer)), strict=True)
    observed = reader.pages[1]["/Contents"]
    assert isinstance(observed, StreamObject)
    params = observed.raw_get("/DecodeParms")
    assert isinstance(params, ArrayObject)
    validate_page_objects(tuple(reader.pages))
    assert observed.get_data() == expected
    assert observed.raw_get("/DecodeParms") is params
    assert params[1]["/Predictor"] == 12
    assert reader.pages[1].extract_text().strip() == "Page Revenue 987,654.32"


def test_shared_form_reuse_and_repeated_parse_preserve_each_physical_page():
    writer, _ = _filtered_document("null", "nested")
    writer.add_page(writer.pages[1])
    raw = _serialize(writer)
    first = parse_pdf_document(PDFDocumentInput(document_id="shared form", content=raw))
    assert len(first) == 3
    assert [p.text.strip() for p in first[1:]] == ["Page Revenue 987,654.32"] * 2
    assert parse_pdf_document(PDFDocumentInput(document_id="shared form", content=raw)) == first


async def test_encoded_pages_survive_real_memory_restart_and_exact_retrieval(tmp_path):
    writer, _ = _filtered_document("null", "nested")
    config, scope, captured = await _capture(tmp_path, {"encoded report": _serialize(writer)})
    assert await _locations(config, scope, captured, "Revenue 987654", 20) == [("encoded report", 2)]


def test_decode_error_restores_original_null_parameter_metadata():
    writer, _ = _filtered_document("null")
    stream = writer.pages[1]["/Contents"]
    stream[NameObject("/Filter")] = ArrayObject([NameObject("/ASCIIHexDecode"), NameObject("/Unsupported")])
    reader = PdfReader(io.BytesIO(_serialize(writer)), strict=True)
    encoded = reader.pages[1]["/Contents"]
    assert isinstance(encoded, StreamObject)
    original = dict(encoded)
    with pytest.raises(NotImplementedError):
        validate_page_objects(tuple(reader.pages))
    assert dict(encoded) == original
    assert all(encoded.raw_get(key) is value for key, value in original.items())


def test_explicit_parameter_length_mismatch_is_not_reinterpreted_as_defaults():
    writer, _ = _filtered_document("array")
    writer.pages[1]["/Contents"][NameObject("/DecodeParms")] = ArrayObject([NullObject()])
    with pytest.raises(ValueError):
        parse_pdf_document(PDFDocumentInput(document_id="bad parameters", content=_serialize(writer)))


def test_compressed_empty_page_with_null_filter_parameters_stays_blank():
    writer = _writer()
    stream = _filter_chain(writer, b"", ("/ASCIIHexDecode", "/FlateDecode"), "null", False)
    writer.pages[1][NameObject("/Contents")] = writer._add_object(stream)
    pages = parse_pdf_document(PDFDocumentInput(document_id="blank page", content=_serialize(writer)))
    assert [p.text.strip() for p in pages] == ["First complete page", ""]


def test_text_validation_does_not_decode_image_only_streams():
    writer = _writer()
    image = _filter_chain(writer, b"\x00", ("/ASCIIHexDecode", "/FlateDecode"), "null", False)
    image.update({
        NameObject("/Type"): NameObject("/XObject"),
        NameObject("/Subtype"): NameObject("/Image"),
        NameObject("/Width"): NumberObject(1),
        NameObject("/Height"): NumberObject(1),
        NameObject("/ColorSpace"): NameObject("/DeviceGray"),
        NameObject("/BitsPerComponent"): NumberObject(8),
    })
    writer.pages[1]["/Resources"][NameObject("/XObject")] = DictionaryObject({
        NameObject("/Pixel"): writer._add_object(image)
    })
    reader = PdfReader(io.BytesIO(_serialize(writer)), strict=True)
    resources = reader.pages[1]["/Resources"]
    assert isinstance(resources, DictionaryObject)
    xobjects = resources["/XObject"]
    assert isinstance(xobjects, DictionaryObject)
    stored_image = xobjects["/Pixel"]
    assert isinstance(stored_image, EncodedStreamObject)
    original = dict(stored_image)
    validate_page_objects(tuple(reader.pages))
    assert reader.pages[1].extract_text().strip() == "Page Revenue 987,654.32"
    assert stored_image.decoded_self is None
    assert dict(stored_image) == original
