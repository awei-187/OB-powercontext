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
import json
import urllib.request

import pytest
import rfc8785
from pydantic import ValidationError
from referencing.exceptions import Unresolvable

from powercontext.builtin.runtime.relational import _json_schema_validator
from powercontext.builtin.sources import CONTENT_SOURCE_DEFINITION, ContentCapture
from powercontext.sources import (
    TEXT_EVIDENCE_PROJECTION_KEY,
    Source,
    SourceCatalog,
    SourceDefinitionManifest,
    SourceDefinitionRegistry,
    SourceObservation,
    SourceProjectionKey,
    SourceProjectionValue,
    TextEvidence,
    manifest_for_definition,
    project_source_for_transport,
)
from powercontext.sources.csv_rows import CSV_ROW_SOURCE_DEFINITION, CSVDocumentInput, parse_csv_document


class EmptySourceBackend:
    async def list(self) -> tuple[Source, ...]:
        return ()

    async def get(self, source: Source, /) -> Source:
        raise AssertionError(source)


def test_definition_manifest_has_a_stable_content_addressed_identity() -> None:
    first = manifest_for_definition(CONTENT_SOURCE_DEFINITION)
    second = manifest_for_definition(CONTENT_SOURCE_DEFINITION)

    assert first == second
    assert first.fingerprint.startswith("sha256:")
    with pytest.raises(ValidationError, match="fingerprint does not match"):
        SourceDefinitionManifest.model_validate(first.model_dump(mode="json", by_alias=True) | {"version": "2"})


def test_source_observation_remains_usable_without_worker_definition_code() -> None:
    async def scenario() -> None:
        registry = SourceDefinitionRegistry((CONTENT_SOURCE_DEFINITION,))
        source = await registry.resolve(
            ContentCapture(source_id="turn-1", content="Keep the remote contract declarative.")
        )
        projected = project_source_for_transport(registry, source)
        catalog = SourceCatalog(backend=EmptySourceBackend())
        payload = await catalog.read(projected)
        projection = catalog.project(projected, TEXT_EVIDENCE_PROJECTION_KEY)

        assert isinstance(projected, SourceObservation)
        assert catalog.as_ref(projected).model_dump() == {"source_type": "content", "source_id": "turn-1"}
        assert payload == projected.payload
        assert catalog.projection_keys(projected) == (TEXT_EVIDENCE_PROJECTION_KEY,)
        assert registry.project(projected, TEXT_EVIDENCE_PROJECTION_KEY) == projection
        assert TextEvidence.model_validate(projection).content == "Keep the remote contract declarative."

    asyncio.run(scenario())


def test_remote_source_observation_requires_captured_materialization() -> None:
    async def scenario() -> None:
        registry = SourceDefinitionRegistry((CONTENT_SOURCE_DEFINITION,))
        source = await registry.resolve(ContentCapture(source_id="turn-1", content="Retain this value."))
        observation = project_source_for_transport(registry, source)

        with pytest.raises(ValidationError):
            SourceObservation.model_validate(observation.model_dump(mode="json") | {"materialization": "referenced"})

    asyncio.run(scenario())


def test_remote_schema_references_are_rejected_without_network_access(monkeypatch: pytest.MonkeyPatch) -> None:
    attempted = False

    def reject_request(*_args: object, **_kwargs: object) -> None:
        nonlocal attempted
        attempted = True
        raise OSError("network access is forbidden")  # noqa: TRY003

    monkeypatch.setattr(urllib.request, "urlopen", reject_request)
    validator = _json_schema_validator("remote", {"$ref": "http://127.0.0.1:9/schema"})

    with pytest.raises(Unresolvable):
        validator.validate({})
    assert not attempted

    with pytest.raises(ValidationError, match="remote schema references are not allowed"):
        SourceDefinitionManifest(
            name="remote",
            version="1",
            fingerprint=f"sha256:{'0' * 64}",
            source_schema={"$dynamicRef": "https://example.invalid/schema"},
        )


def test_csv_observation_reads_restore_order_without_changing_canonical_evidence() -> None:
    async def scenario() -> None:
        registry = SourceDefinitionRegistry((CSV_ROW_SOURCE_DEFINITION,))
        row = parse_csv_document(
            CSVDocumentInput(document_id="ordered", primary_key="id", content=b"id,z,a\n1,last,first\n")
        )[0]
        original = project_source_for_transport(registry, await registry.resolve(row))
        encoded = rfc8785.dumps(original.model_dump(mode="json"))
        restored = SourceObservation.model_validate_json(encoded)
        raw_evidence = restored.projections[0].value
        assert isinstance(raw_evidence, dict) and isinstance(raw_evidence["metadata"], dict)
        raw_row = raw_evidence["metadata"]["row"]
        assert isinstance(raw_row, dict)
        assert list(raw_row) == ["a", "id", "z"]

        # Public read routes must work even when the worker Definition is unavailable.
        catalog = SourceCatalog(backend=EmptySourceBackend())
        for evidence in (
            restored.projection(TEXT_EVIDENCE_PROJECTION_KEY),
            SourceDefinitionRegistry(()).project(restored, TEXT_EVIDENCE_PROJECTION_KEY),
            catalog.project(restored, TEXT_EVIDENCE_PROJECTION_KEY),
        ):
            assert isinstance(evidence, dict) and isinstance(evidence["metadata"], dict)
            ordered_row = evidence["metadata"]["row"]
            assert isinstance(ordered_row, dict)
            assert list(ordered_row) == ["id", "z", "a"]
            assert list(ordered_row.values()) == ["1", "last", "first"]
            assert evidence == original.projection(TEXT_EVIDENCE_PROJECTION_KEY)
        assert rfc8785.dumps(restored.model_dump(mode="json")) == encoded
        assert restored.definition_fingerprint == original.definition_fingerprint

    asyncio.run(scenario())


def _observation_for_ordering(value, *, source_type="csv-row", version="1", key=TEXT_EVIDENCE_PROJECTION_KEY):
    return SourceObservation(
        name="row-1",
        definition_version=version,
        source_type=source_type,
        definition_fingerprint=f"sha256:{'0' * 64}",
        payload={"name": "row-1", "definition_version": version, "materialization": "captured", "description": None},
        projections=(SourceProjectionValue(key=key, value=value),),
    )


@pytest.mark.parametrize(
    ("source_type", "evidence_type", "version", "key"),
    [
        ("content", "csv-row", "1", TEXT_EVIDENCE_PROJECTION_KEY),
        ("csv-row", "content", "1", TEXT_EVIDENCE_PROJECTION_KEY),
        ("csv-row", "csv-row", "2", TEXT_EVIDENCE_PROJECTION_KEY),
        ("csv-row", "csv-row", "1", SourceProjectionKey(name="custom", version="1")),
        ("csv-row", "csv-row", "1", SourceProjectionKey(name="powercontext.text-evidence", version="2")),
    ],
)
def test_csv_order_restoration_leaves_other_sources_and_projection_versions_unchanged(
    source_type, evidence_type, version, key
) -> None:
    value = {"source_type": evidence_type, "metadata": {"columns": ["z", "a"], "row": {"a": "first", "z": "last"}}}
    observation = _observation_for_ordering(value, source_type=source_type, version=version, key=key)
    assert list(observation.projection(key)["metadata"]["row"]) == ["a", "z"]


@pytest.mark.parametrize(
    "metadata",
    [
        None,
        {},
        {"columns": "z,a", "row": {"a": "first", "z": "last"}},
        {"columns": ["z", "a"], "row": ["first", "last"]},
        {"columns": ["z", ["a"]], "row": {"a": "first", "z": "last"}},
        {"columns": ["z", "z"], "row": {"a": "first", "z": "last"}},
        {"columns": ["z"], "row": {"a": "first", "z": "last"}},
        {"columns": ["z", "missing"], "row": {"a": "first", "z": "last"}},
    ],
)
def test_unknown_csv_metadata_is_not_repaired_by_discarding_captured_fields(metadata) -> None:
    value = {"source_type": "csv-row", "metadata": metadata}
    observation = _observation_for_ordering(value)
    # Order-sensitive serialization also catches inadvertent rewriting of the evidence.
    assert json.dumps(observation.projection(TEXT_EVIDENCE_PROJECTION_KEY)) == json.dumps(value)
    assert json.dumps(observation.model_dump(mode="json")["projections"][0]["value"]) == json.dumps(value)
