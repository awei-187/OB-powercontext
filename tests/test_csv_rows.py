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

from __future__ import annotations

import asyncio
import csv
import io
import json
from itertools import product
from urllib.parse import quote

import pytest

from powercontext.sources import (
    SourceDefinitionRegistry,
    SourceMaterialization,
    TextEvidence,
    manifest_for_definition,
    project_source_for_transport,
)
from powercontext.sources.csv_rows import (
    CSV_ROW_SOURCE_DEFINITION,
    CSVDocumentInput,
    CSVRowInput,
    CSVRowSource,
    csv_row_source_id,
    parse_csv_document,
)
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY


def parse(content: bytes, *, document_id: str = "document", primary_key: str = "id") -> tuple[CSVRowInput, ...]:
    return parse_csv_document(CSVDocumentInput(document_id=document_id, primary_key=primary_key, content=content))


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"\xef\xbb\xbf",
        b"\n",
        b'""\n',
        b" \t\n",
        b"id,\n",
        b"id, \t\n",
        b"id,id\n",
        b"id,name\n1,valid\n2\n",
        b"id,name\n1,valid\n2,too,many\n",
        b"id,name\n1,valid\n,empty\n",
        b"id,name\n1,valid\n \t,blank\n",
        b"id,name\n1,valid\n1,duplicate\n",
        b'id,name\n1,valid\n2,"unclosed\n',
        b'id,name\n1,valid\n2,"closed"garbage\n',
        b"id,name\n1,valid\n2,\xff\n",
        b"id,name\n1,valid\n2,\xed\xa0\x80\n",
        b"id,name\n1,valid\n2,\xc0\x80\n",
        b'id\n""\n',
        b"id\n \n",
        b"id,name\n,\n",
    ],
)
def test_invalid_documents_raise_instead_of_returning_a_partial_iterable(content: bytes) -> None:
    with pytest.raises(ValueError):
        parse(content)


@pytest.mark.parametrize("document_id", ["", " ", " document", "document\t", "\u2003document", "document\n"])
def test_document_identity_is_validated_even_without_rows(document_id: str) -> None:
    with pytest.raises(ValueError):
        parse(b"id,name\n", document_id=document_id)
    with pytest.raises(ValueError):
        csv_row_source_id(document_id, "1")


@pytest.mark.parametrize("primary_key", ["", " ", "ID", " id", "id "])
def test_primary_key_requires_exact_header_match(primary_key: str) -> None:
    with pytest.raises(ValueError):
        parse(b"id,name\n", primary_key=primary_key)


@pytest.mark.parametrize("content", [b"id", b"id\n\n", b"\xef\xbb\xbfid\r\n\r\n", b"id\r\r"])
def test_header_only_documents_return_an_empty_tuple(content: bytes) -> None:
    assert parse(content) == ()


def test_only_bom_at_start_is_removed_and_blank_records_do_not_destroy_multiline_values() -> None:
    content = '\ufeffid, id ,note\r\n\r\n001, key ,"a\r\n\r\nb\rc\nd"\r\n\r\n002,\ufeffkey,\ufeffdata'
    rows = parse(content.encode(), primary_key=" id ")
    assert [row.values for row in rows] == [("001", " key ", "a\r\n\r\nb\rc\nd"), ("002", "\ufeffkey", "\ufeffdata")]
    assert rows[0].columns == ("id", " id ", "note")


def test_standard_reader_semantics_accept_quotes_in_unquoted_fields() -> None:
    assert parse(b'id,note\n1,plain"quote\n')[0].values == ("1", 'plain"quote')


def test_roundtrip_string_values_and_order_through_registry_and_transport() -> None:
    # Each pair exercises field boundaries as well as escaping within a field.
    cells = ["", "  ", "001", "false", "null", "2026-01-02", "a,b", 'say "hi"', "a\r\nb", "雪❄", "\ufeff"]
    values = [(f" key:{i}/% ", left, right) for i, (left, right) in enumerate(product(cells, repeat=2))]
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow((" id ", "z", "a"))
    writer.writerows(values)
    rows = parse(output.getvalue().encode(), document_id="表:格/%", primary_key=" id ")
    assert tuple(row.values for row in rows) == tuple(values)
    registry = SourceDefinitionRegistry((CSV_ROW_SOURCE_DEFINITION,))
    manifest = manifest_for_definition(CSV_ROW_SOURCE_DEFINITION)
    assert (manifest.name, manifest.version) == ("csv-row", "1")

    async def scenario() -> None:
        for row in rows:
            source = await registry.resolve(row)
            assert isinstance(source, CSVRowSource)
            assert source.materialization == SourceMaterialization.CAPTURED
            assert source.name == source.source_id == csv_row_source_id(row.document_id, row.primary_key_value)
            assert await registry.read(source) == row
            restored = CSVRowSource.model_validate_json(source.model_dump_json())
            assert await registry.read(restored) == row
            evidence = TextEvidence.model_validate(registry.project(restored, TEXT_EVIDENCE_PROJECTION_KEY))
            mapping = dict(zip(row.columns, row.values, strict=True))
            assert evidence.content == json.dumps(mapping, ensure_ascii=False, separators=(",", ":"))
            assert list(json.loads(evidence.content)) == list(row.columns)
            assert evidence.metadata == {
                "document_id": row.document_id,
                "primary_key": row.primary_key,
                "primary_key_value": row.primary_key_value,
                "columns": list(row.columns),
                "row": mapping,
            }
            observation = project_source_for_transport(registry, restored)
            assert observation.definition_fingerprint == manifest.fingerprint
            assert TextEvidence.model_validate(observation.projection(TEXT_EVIDENCE_PROJECTION_KEY)) == evidence

    asyncio.run(scenario())


def test_identity_length_is_measured_after_encoding_including_both_delimiters() -> None:
    assert len(csv_row_source_id("d", "x" * 250)) == 256
    assert len(csv_row_source_id("d", "雪" * 27 + "x" * 7)) == 256
    for key in ["x" * 251, "雪" * 27 + "x" * 8]:
        with pytest.raises(ValueError):
            csv_row_source_id("d", key)
        with pytest.raises(ValueError):
            parse(f"id\n{key}\n".encode(), document_id="d")


def test_identity_components_cannot_collide_or_be_normalized() -> None:
    components = ["a:b", "a/b", "a%2Fb", "a%b", "雪", "e\u0301", "é", "a~b"]
    ids = [csv_row_source_id(doc, key) for doc, key in product(components, repeat=2)]
    assert len(set(ids)) == len(ids)
    assert csv_row_source_id("a:b", "c") != csv_row_source_id("a", "b:c")
    for doc, key in product(components, repeat=2):
        assert csv_row_source_id(doc, key) == f"csv:{quote(doc, safe='')}:{quote(key, safe='')}"
    rows = parse(b"id,note\nkey,one\n key,two\nkey ,three\n key ,four\n")
    assert len({csv_row_source_id(row.document_id, row.primary_key_value) for row in rows}) == 4


@pytest.mark.parametrize(
    "changes",
    [
        {"primary_key_value": "other"},
        {"primary_key_value": " "},
        {"columns": ("id", "id")},
        {"columns": ("id", " ")},
        {"values": ("1",)},
        {"primary_key": "missing"},
        {"document_id": " bad"},
    ],
)
def test_manually_supplied_rows_cannot_create_inconsistent_captured_evidence(changes: dict[str, object]) -> None:
    data = {
        "document_id": "d",
        "primary_key": "id",
        "primary_key_value": "1",
        "columns": ("id", "note"),
        "values": ("1", "ok"),
    }
    with pytest.raises(ValueError):
        CSVRowInput.model_validate(data | changes)


def test_captured_source_rejects_forged_identity_and_reference_materialization() -> None:
    row = parse(b"id,note\n1,value\n")[0]
    source = asyncio.run(CSV_ROW_SOURCE_DEFINITION.resolve(row))
    for changes in ({"name": "wrong"}, {"source_id": "wrong"}, {"materialization": "referenced"}):
        with pytest.raises(ValueError):
            CSVRowSource.model_validate(source.model_dump() | changes)
