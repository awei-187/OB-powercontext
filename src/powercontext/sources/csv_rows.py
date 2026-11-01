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

"""Lossless, captured CSV row evidence identified by document and primary key."""

from __future__ import annotations

import csv
import io
import json
from typing import Self
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, model_validator

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.definitions import SourceDefinition, SourceProjection
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence


def _validate_document_id(document_id: str) -> None:
    if not document_id or document_id != document_id.strip():
        raise ValueError("document_id must be non-empty without surrounding whitespace")  # noqa: TRY003


def _primary_key_index(columns: tuple[str, ...], primary_key: str) -> int:
    if not columns or any(not column.strip() for column in columns):
        raise ValueError("CSV headers must be non-empty and not whitespace-only")  # noqa: TRY003
    if len(set(columns)) != len(columns):
        raise ValueError("CSV headers must be unique")  # noqa: TRY003
    if not primary_key or primary_key not in columns:
        raise ValueError("primary_key must exactly match a CSV header")  # noqa: TRY003
    return columns.index(primary_key)


def csv_row_source_id(document_id: str, primary_key_value: str) -> str:
    """Return a bounded, delimiter-safe identity without normalizing either component."""
    _validate_document_id(document_id)
    if not primary_key_value.strip():
        raise ValueError("primary_key_value must not be empty or whitespace-only")  # noqa: TRY003
    identity = f"csv:{quote(document_id, safe='')}:{quote(primary_key_value, safe='')}"
    if len(identity) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"CSV row identity must not exceed {MAX_SOURCE_ID_LENGTH} characters")  # noqa: TRY003
    return identity


class CSVDocumentInput(BaseModel):
    """One complete offline CSV document; parsing validates its contents atomically."""

    document_id: str
    primary_key: str
    content: bytes


class CSVRowInput(BaseModel):
    """One validated row, retaining header order and every original string value."""

    model_config = ConfigDict(frozen=True)

    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]

    @model_validator(mode="after")
    def validate_row(self) -> Self:
        csv_row_source_id(self.document_id, self.primary_key_value)
        index = _primary_key_index(self.columns, self.primary_key)
        if len(self.values) != len(self.columns):
            raise ValueError("CSV row width must match its header")  # noqa: TRY003
        if self.values[index] != self.primary_key_value:
            raise ValueError("primary_key_value must match the captured key column")  # noqa: TRY003
        return self


class CSVRowSource(CSVRowInput, Source):
    """An immutable captured row, independent of the original file or its row position."""

    source_id: str

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.definition_version != "1" or self.materialization != SourceMaterialization.CAPTURED:
            raise ValueError("CSV rows must be captured Sources with definition version 1")  # noqa: TRY003
        expected = csv_row_source_id(self.document_id, self.primary_key_value)
        if self.source_id != expected or self.name != expected:
            raise ValueError("CSV source name and source_id must match its row identity")  # noqa: TRY003
        return self


def parse_csv_document(value: CSVDocumentInput) -> tuple[CSVRowInput, ...]:
    """Parse strict UTF-8 CSV, returning rows only after the whole document is valid.

    Only empty physical records after the header are ignored. Quoted empty fields,
    whitespace-only records and delimiters are data and undergo normal validation.
    """
    _validate_document_id(value.document_id)
    # newline="" preserves embedded CR, LF and CRLF rather than normalizing evidence.
    reader = csv.reader(io.StringIO(value.content.decode("utf-8-sig"), newline=""), strict=True)
    rows: list[CSVRowInput] = []
    keys: set[str] = set()
    try:
        columns = tuple(next(reader, ()))
        index = _primary_key_index(columns, value.primary_key)
        for record in reader:
            if not record:
                continue
            if len(record) != len(columns):
                raise ValueError(f"CSV record ending at line {reader.line_num} has an invalid width")  # noqa: TRY003
            key = record[index]
            if key in keys:
                raise ValueError(f"Duplicate primary key at line {reader.line_num}")  # noqa: TRY003
            rows.append(
                CSVRowInput(
                    document_id=value.document_id,
                    primary_key=value.primary_key,
                    primary_key_value=key,
                    columns=columns,
                    values=tuple(record),
                )
            )
            keys.add(key)
    except csv.Error as error:
        raise ValueError(f"Invalid CSV at line {reader.line_num}: {error}") from error  # noqa: TRY003
    return tuple(rows)


class _CSVRowTextEvidence:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class: type[CSVRowSource] = CSVRowSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: CSVRowSource, /) -> TextEvidence:
        row = dict(zip(source.columns, source.values, strict=True))
        return TextEvidence(
            source_type="csv-row",
            source_id=source.source_id,
            content=json.dumps(row, ensure_ascii=False, separators=(",", ":")),
            metadata={
                "document_id": source.document_id,
                "primary_key": source.primary_key,
                "primary_key_value": source.primary_key_value,
                "columns": list(source.columns),
                "row": row,
            },
        )


class _CSVRowSourceDefinition:
    name = "csv-row"
    version = "1"
    input_class: type[CSVRowInput] = CSVRowInput
    source_class: type[CSVRowSource] = CSVRowSource
    projections: tuple[SourceProjection[CSVRowSource], ...] = (_CSVRowTextEvidence(),)

    async def resolve(self, value: CSVRowInput, /) -> CSVRowSource:
        identity = csv_row_source_id(value.document_id, value.primary_key_value)
        return CSVRowSource(
            name=identity, source_id=identity, materialization=SourceMaterialization.CAPTURED, **value.model_dump()
        )

    async def read(self, source: CSVRowSource, /) -> CSVRowInput:
        return CSVRowInput(
            document_id=source.document_id,
            primary_key=source.primary_key,
            primary_key_value=source.primary_key_value,
            columns=source.columns,
            values=source.values,
        )


CSV_ROW_SOURCE_DEFINITION: SourceDefinition[CSVRowInput, CSVRowSource, CSVRowInput] = _CSVRowSourceDefinition()

__all__ = [
    "CSV_ROW_SOURCE_DEFINITION",
    "CSVDocumentInput",
    "CSVRowInput",
    "CSVRowSource",
    "csv_row_source_id",
    "parse_csv_document",
]
