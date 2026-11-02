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

"""Validate evidence-bearing PDF objects before pypdf's tolerant text extraction.

The competition pins pypdf 6.19.0. Its strict reader still permits partial zlib
output and skips invalid ToUnicode records. Validate those structures directly,
without changing pypdf globals, logger settings, recovery code or input objects.
"""

from __future__ import annotations

import io
import zlib
from collections.abc import Iterator

from pypdf._configuration import get_configuration
from pypdf.filters import decode_stream_data
from pypdf.generic import (
    ArrayObject,
    ByteStringObject,
    DictionaryObject,
    IndirectObject,
    NameObject,
    NullObject,
    NumberObject,
    PdfObject,
    StreamObject,
    read_object,
)


class _InvalidPDFData(ValueError):
    """Malformed encoded evidence must not become a successful partial capture."""


def _resolve(value: PdfObject) -> PdfObject:
    resolved = value.get_object()
    if resolved is None:
        raise _InvalidPDFData("Unresolved PDF object")  # noqa: TRY003
    return resolved


def _decode_null_parameters(stream: StreamObject) -> None:
    """Decode a reader-local stream with null dictionary entries treated as absent."""
    if stream.get("/Subtype") == "/Image":
        # Text extraction must not introduce image codecs or their dependencies.
        return
    parameters = stream.get("/DecodeParms")
    if parameters is None or not isinstance(_resolve(parameters), NullObject):
        return
    filters = _resolve(stream.get("/Filter", NullObject()))
    if not isinstance(filters, ArrayObject) or len(filters) < 2:
        return
    # pypdf 6.19 pairs multiple filters with only one explicit null parameter,
    # silently leaving later filters unapplied. Prime its normal decoded cache
    # using PDF's equivalent omitted-entry form, before any text/CMap extraction.
    # Keep the original metadata object (including indirect nulls) and raw bytes.
    del stream["/DecodeParms"]
    try:
        stream.get_data()
    finally:
        stream[NameObject("/DecodeParms")] = parameters


def _validate_flate_stream(stream: StreamObject) -> None:
    filters = _resolve(stream.get("/Filter", ArrayObject()))
    filters = filters if isinstance(filters, ArrayObject) else ArrayObject([filters])
    filters = [_resolve(item) for item in filters]
    positions = [index for index, item in enumerate(filters) if item in ("/FlateDecode", "/Fl")]
    if not positions:
        return
    parameters = _resolve(stream.get("/DecodeParms", NullObject()))
    if isinstance(parameters, NullObject):
        parameters = ArrayObject([NullObject() for _ in filters])
    elif not isinstance(parameters, ArrayObject):
        parameters = ArrayObject([parameters])
    if len(parameters) != len(filters):
        raise _InvalidPDFData("PDF filter and DecodeParms lengths differ")  # noqa: TRY003
    # Raw, already-decrypted bytes: get_data() would hide the decoder's recovery.
    # _data is the pinned pypdf StreamObject storage also used by its decoder.
    data = stream._data
    for index in range(positions[-1] + 1):
        filter_name, params = filters[index], _resolve(parameters[index])
        if not isinstance(filter_name, NameObject) or not isinstance(params, DictionaryObject | NullObject):
            raise _InvalidPDFData("Invalid PDF filter or DecodeParms")  # noqa: TRY003
        if filter_name in ("/FlateDecode", "/Fl"):
            decoder = zlib.decompressobj()
            decoder.decompress(data, max_length=get_configuration().zlib_maximum_output_length)
            if decoder.unconsumed_tail or not decoder.eof:
                raise _InvalidPDFData("Incomplete or oversized PDF Flate stream")  # noqa: TRY003
            # eof verifies the full zlib stream and Adler checksum. Bytes after
            # a complete stream (e.g. a harmless trailing newline) are not loss.
        if index < positions[-1]:
            stage = StreamObject()
            stage._data = data
            stage[NameObject("/Filter")] = filter_name
            stage[NameObject("/DecodeParms")] = params
            data = decode_stream_data(stage)


_WHITESPACE = b"\x00\t\n\x0c\r "
_DELIMITERS = _WHITESPACE + b"()<>[]{}/%"


def _cmap_tokens(data: bytes) -> Iterator[PdfObject | str]:
    """Use pypdf's strict PDF-object lexer, retaining PostScript operators.

    Unlike a regex over angle brackets, this respects literal strings, comments,
    dictionaries, hex whitespace and multiline arrays. Prolog procedures remain
    opaque; only mapping-block operators have semantic meaning here.
    """
    source = io.BytesIO(data)
    while token := source.read(1):
        if token in _WHITESPACE:
            continue
        if token == b"%":
            while source.read(1) not in (b"\r", b"\n", b""):
                pass
            continue
        if token in b"<([/0123456789+.-":
            source.seek(-1, 1)
            yield read_object(source, None, forced_encoding="bytes")
        elif token in b"{}":
            yield token.decode("ascii")
        else:
            word = bytearray(token)
            while (following := source.read(1)) and following not in _DELIMITERS:
                word.extend(following)
            if following:
                source.seek(-1, 1)
            yield word.decode("latin-1")


def _code(value: PdfObject | str) -> bytes:
    if not isinstance(value, ByteStringObject) or not value:
        raise _InvalidPDFData("CMap source code must be a nonempty byte string")  # noqa: TRY003
    return bytes(value)


def _unicode_target(value: PdfObject | str) -> bytes:
    if not isinstance(value, ByteStringObject):
        raise _InvalidPDFData("CMap destination must be a byte string")  # noqa: TRY003
    # pypdf also supports empty destinations and legacy one-byte mappings.
    # Preserve those losslessly; multi-byte destinations must be complete UTF-16.
    if len(value) > 1:
        value.decode("utf-16-be", errors="surrogatepass")
    return bytes(value)


def _validate_mapping(kind: str, values: list[PdfObject | str]) -> None:
    start = _code(values[0])
    if kind == "bfchar":
        _unicode_target(values[1])
        return
    stop = _code(values[1])
    if len(start) != len(stop) or start > stop:
        raise _InvalidPDFData("Invalid CMap source range")  # noqa: TRY003
    if kind == "codespacerange":
        return
    count = int.from_bytes(stop, "big") - int.from_bytes(start, "big") + 1
    target = values[2]
    if isinstance(target, ArrayObject):
        if len(target) != count:
            raise _InvalidPDFData("CMap range destination count differs from source range")  # noqa: TRY003
        for item in target:
            _unicode_target(item)
    else:
        first = _unicode_target(target)
        if not first or int.from_bytes(first, "big") + count - 1 >= 256 ** len(first):
            raise _InvalidPDFData("CMap destination range overflows")  # noqa: TRY003


def _validate_cmap(data: bytes) -> None:
    widths = {"bfchar": 2, "bfrange": 3, "codespacerange": 2}
    previous: PdfObject | str | None = None
    active: str | None = None
    expected = 0
    values: list[PdfObject | str] = []
    for token in _cmap_tokens(data):
        if active is not None:
            if token == "end" + active:
                width = widths[active]
                if len(values) != expected * width:
                    raise _InvalidPDFData("Incomplete CMap mapping block")  # noqa: TRY003
                for index in range(0, len(values), width):
                    _validate_mapping(active, values[index : index + width])
                active, values = None, []
            else:
                values.append(token)
        elif isinstance(token, str) and token.startswith("begin") and token[5:] in widths:
            if not isinstance(previous, NumberObject) or previous < 0:
                raise _InvalidPDFData("CMap mapping block requires a nonnegative record count")  # noqa: TRY003
            active, expected = token[5:], int(previous)
        elif isinstance(token, str) and token.startswith("end") and token[3:] in widths:
            raise _InvalidPDFData("CMap mapping block has no matching begin")  # noqa: TRY003
        previous = token
    if active is not None:
        raise _InvalidPDFData("Unterminated CMap mapping block")  # noqa: TRY003


def validate_page_objects(pages: tuple[PdfObject, ...]) -> None:
    """Check each page/resource object once, including shared and nested Forms.

    Follow resource dictionaries rather than only page /Contents, so compressed
    Forms and font ToUnicode streams cannot escape validation. Parent backlinks
    are unnecessary: all physical pages have already been flattened by PdfReader.
    Image-only codecs are not decoded, requiring neither OCR nor extra binaries.
    """
    pending: list[PdfObject] = list(pages)
    visited: set[int] = set()
    cmaps: set[int] = set()
    while pending:
        value = pending.pop()
        if isinstance(value, IndirectObject):
            value = value.get_object()
        if id(value) in visited:
            continue
        visited.add(id(value))
        if isinstance(value, StreamObject):
            _validate_flate_stream(value)
            _decode_null_parameters(value)
        if isinstance(value, DictionaryObject):
            if "/ToUnicode" in value:
                cmap = value["/ToUnicode"]
                if isinstance(cmap, StreamObject) and id(cmap) not in cmaps:
                    _validate_flate_stream(cmap)
                    _decode_null_parameters(cmap)
                    _validate_cmap(cmap.get_data())
                    cmaps.add(id(cmap))
            pending.extend(item for key, item in value.items() if key != "/Parent")
        elif isinstance(value, ArrayObject):
            pending.extend(value)
