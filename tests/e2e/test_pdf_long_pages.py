# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

"""A complete dense PDF page remains readable after durable ingestion."""

import io

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from powercontext.builtin.runtime import GetMemoryEntryRequest, open_builtin_runtime
from powercontext.sources.pdf_pages import search_pdf_pages
from tests.e2e.test_pdf_locations_and_headings import _capture

TAIL_MARKER = "zirconarchivefinalmarker"


def dense_pdf():
    """Emit two genuine pages with a complete, visible dense second-page table."""
    writer = PdfWriter()
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    rows = ["Detailed operating account balances"]
    rows.extend(
        f"Unit {number:03d} Revenue 123456 Expenses 45678 Inventory 9012 Receivables 3456 "
        "Cash 7890 Assets 234567 Liabilities 12345 Equity 222222 Operating income 77778 Net income 65000"
        for number in range(80)
    )
    rows.append(TAIL_MARKER)
    for lines in (["Summary of the complete financial schedule."], rows):
        page = writer.add_blank_page(width=1200, height=1600)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})
        })
        body = b"BT /F1 8 Tf 14 TL 32 1568 Td\n"
        body += b"\n".join(b"(" + line.encode("ascii") + b") Tj T*" for line in lines)
        body += b"\nET"
        stream = DecodedStreamObject()
        stream.set_data(body)
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


async def test_dense_complete_page_survives_runtime_restart_and_tail_retrieval(tmp_path):
    config, scope, captured = await _capture(tmp_path, {"DENSE_REPORT": dense_pdf()})
    assert len(captured) == 2
    expected = next(page for page in captured.values() if page.page_number == 2)
    projected = f"{expected.document_id}\n{expected.text}".strip()
    assert len(projected.encode("utf-8")) > 8192
    assert expected.text.rstrip().endswith(TAIL_MARKER)
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope)
        snapshot = await memory.list()
        assert len(snapshot.entries) == 2
        citations = await search_pdf_pages(memory, TAIL_MARKER, 20)
        assert len(citations) == 1
        entry = (await memory.get(GetMemoryEntryRequest(citation=citations[0]))).entry
        assert len(entry.sources) == 1
        assert captured[entry.sources[0].source_id] == expected
        assert entry.text.encode("utf-8") == projected.encode("utf-8")
    async with open_builtin_runtime(config) as runtime:
        entry = (await runtime.memory.for_scope(scope).get(GetMemoryEntryRequest(citation=citations[0]))).entry
        assert entry.text.encode("utf-8") == projected.encode("utf-8")
