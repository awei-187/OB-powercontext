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

"""Standard named projection schemas understood without Source plugin code."""

from typing import cast

from pydantic import BaseModel, Field, JsonValue

from powercontext.sources.models import SourceProjectionKey

TEXT_EVIDENCE_PROJECTION_KEY = SourceProjectionKey(name="powercontext.text-evidence", version="1")


class TextEvidence(BaseModel):
    """Canonical JSON shape consumed as textual Artifact evidence."""

    source_type: str
    source_id: str
    content: str
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


def _restore_csv_row_order(value: JsonValue) -> JsonValue:
    """Restore CSV v1 presentation order without changing stored evidence or values.

    Canonical JSON deliberately sorts object keys. The CSV text-evidence contract
    carries the original order separately in ``columns``, so no worker Definition
    or file access is needed to recover it when reading a captured observation.
    Unknown/malformed metadata is left intact rather than silently dropping fields.
    """
    if not isinstance(value, dict) or value.get("source_type") != "csv-row":
        return value
    metadata = value.get("metadata")
    if not isinstance(metadata, dict):
        return value
    columns, row = metadata.get("columns"), metadata.get("row")
    if not isinstance(columns, list) or not isinstance(row, dict):
        return value
    if not all(isinstance(column, str) for column in columns):
        return value
    ordered_columns = cast(list[str], columns)
    if len(ordered_columns) != len(row) or set(ordered_columns) != set(row):
        return value
    ordered_row: dict[str, JsonValue] = {column: row[column] for column in ordered_columns}
    return {**value, "metadata": {**metadata, "row": ordered_row}}


__all__ = ["TEXT_EVIDENCE_PROJECTION_KEY", "TextEvidence"]
