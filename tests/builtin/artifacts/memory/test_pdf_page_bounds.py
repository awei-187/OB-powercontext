# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

"""Only complete single-page PDF evidence can exceed the ordinary body bound."""

import json

import pytest

from powercontext.builtin.artifacts.memory.canonical import entry_content_bytes, entry_content_hash, normalize_text

PDF = {"source_type": "pdf-page", "source_id": "page-one"}
OTHER_PDF = {"source_type": "pdf-page", "source_id": "page-two"}
CSV = {"source_type": "csv-row", "source_id": "row-one"}


@pytest.mark.parametrize(
    ("kind", "sources"),
    [
        ("note", ()),
        ("source-evidence", ()),
        ("note", (PDF,)),
        ("source-evidence", (CSV,)),
        ("source-evidence", (PDF, CSV)),
        ("source-evidence", (PDF, OTHER_PDF)),
        ("source-evidence", ({"source_type": "pdf-page"},)),
        ("source-evidence", ({"source_type": "pdf-page", "source_id": ""},)),
    ],
)
def test_non_page_entries_keep_the_8192_utf8_byte_bound(kind, sources):
    arguments = {"kind": kind, "source_refs": sources, "artifact_refs": ()}
    assert json.loads(entry_content_bytes(text="x" * 8192, **arguments))["text"] == "x" * 8192
    with pytest.raises(ValueError, match="8192"):
        entry_content_bytes(text="x" * 8193, **arguments)
    with pytest.raises(ValueError, match="8192"):
        entry_content_hash(text="x" * 8193, **arguments)


def test_full_page_hash_retains_the_entire_body_and_canonical_source_identity():
    text = "é" * 5000 + " first tail"
    arguments = {"kind": "source-evidence", "source_refs": (PDF,), "artifact_refs": ()}
    assert json.loads(entry_content_bytes(text=text, **arguments))["text"] == text
    assert entry_content_hash(text=text, **arguments) != entry_content_hash(text=text + " changed", **arguments)
    assert entry_content_hash(text=text, **arguments) == entry_content_hash(
        text=text, kind="source-evidence", source_refs=(PDF, PDF), artifact_refs=()
    )
    with pytest.raises(ValueError, match="8192"):
        normalize_text(text)
