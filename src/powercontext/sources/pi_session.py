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

"""Capture a Pi v3 branch as immutable, complete event evidence."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_serializer, field_validator

from powercontext.sources.connectors import (
    ConnectorRunCompletion,
    ConnectorRunSession,
    ConnectorRunStatus,
    ConnectorSubmissionStatus,
)
from powercontext.sources.definitions import SourceProjection
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

_Identity = Annotated[str, Field(min_length=1)]


class PiSessionInput(BaseModel):
    """UTF-8 JSONL archive and optional selected node (defaults to the last)."""

    model_config = ConfigDict(frozen=True, strict=True)

    content: bytes
    leaf_id: str | None = None


class PiEventInput(BaseModel):
    """One visible event, including the entire original JSON record."""

    model_config = ConfigDict(frozen=True, strict=True)

    session_id: _Identity
    event_id: _Identity
    parent_id: str | None
    event_type: _Identity
    role: _Identity
    content: str
    record: dict[str, JsonValue]


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: object) -> str:
    # ASCII escaping also handles JSON strings containing escaped UTF-16 surrogates.
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def _identity(session_id: str, event_id: str) -> str:
    # An encoded pair avoids delimiter ambiguities and bounds arbitrarily long IDs.
    return "pi-event:" + _digest([session_id, event_id])


def _object(value: JsonValue, field: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise ValueError(f"Pi {field} must be an object")  # noqa: TRY003, TRY004
    return value


def _text(value: JsonValue, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"Pi {field} must be a string")  # noqa: TRY003, TRY004
    return value


def _nonempty(value: JsonValue, field: str) -> str:
    result = _text(value, field)
    if not result:
        raise ValueError(f"Pi {field} must be non-empty")  # noqa: TRY003
    return result


def _visible_text(value: JsonValue, *, tool_calls: bool = False) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        raise ValueError("Pi content must be a string or list of blocks")  # noqa: TRY003, TRY004
    parts: list[str] = []
    for value_block in value:
        block = _object(value_block, "content block")
        if block.get("type") == "text":
            parts.append(_text(block.get("text"), "text block"))
        elif tool_calls and block.get("type") == "toolCall":
            name = _nonempty(block.get("name"), "tool name")
            call_id = _nonempty(block.get("id"), "tool call ID")
            arguments = _object(block.get("arguments"), "tool arguments")
            parts.append(f"[tool_call {name} {call_id}] {_json(arguments)}")
    return "\n".join(parts)


def _event(session_id: str, record: dict[str, JsonValue]) -> PiEventInput | None:
    event_type = _nonempty(record.get("type"), "entry type")
    if event_type == "message":
        message = _object(record.get("message"), "message")
        role = _nonempty(message.get("role"), "message role")
        if role == "bashExecution":
            command = _text(message.get("command"), "bash command")
            output = _text(message.get("output"), "bash output")
            body = f"$ {command}\n{output}" if command or output else ""
        else:
            body = _visible_text(message.get("content"), tool_calls=True)
            if role == "toolResult" and body:
                name = _nonempty(message.get("toolName"), "tool result name")
                call_id = _nonempty(message.get("toolCallId"), "tool result call ID")
                body = f"[tool_result {name} {call_id}] {body}"
    elif event_type in {"compaction", "branch_summary"}:
        role = event_type
        body = _text(record.get("summary"), "summary")
    elif event_type == "custom_message":
        role = "custom"
        body = _visible_text(record.get("content"))
    else:
        return None
    if not body:
        return None
    return PiEventInput(
        session_id=session_id,
        event_id=_nonempty(record.get("id"), "entry ID"),
        parent_id=None if record["parentId"] is None else _text(record["parentId"], "parent ID"),
        event_type=event_type,
        role=role,
        content=f"{role}: {body}",
        record=record,
    )


def _unique_object(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key {key!r}")  # noqa: TRY003
        result[key] = value
    return result


def _invalid_constant(value: str) -> JsonValue:
    raise ValueError(f"Invalid JSON constant {value}")  # noqa: TRY003


def _parse(value: PiSessionInput) -> tuple[str, dict[str, dict[str, JsonValue]], tuple[str, ...]]:
    records = [
        _object(json.loads(line, object_pairs_hook=_unique_object, parse_constant=_invalid_constant), "record")
        for line in value.content.decode("utf-8-sig").split("\n")
        if line.strip()
    ]
    if not records:
        raise ValueError("Pi archive must contain a session header")  # noqa: TRY003
    header = records[0]
    if header.get("type") != "session" or type(header.get("version")) is not int or header["version"] != 3:
        raise ValueError("Pi archive requires a version 3 session header")  # noqa: TRY003
    session_id = _nonempty(header.get("id"), "session ID")
    by_id: dict[str, dict[str, JsonValue]] = {}
    for record in records[1:]:
        event_id = _nonempty(record.get("id"), "entry ID")
        event_type = _nonempty(record.get("type"), "entry type")
        if event_id in by_id or event_type == "session":
            raise ValueError(f"Duplicate Pi entry or session header: {event_id!r}")  # noqa: TRY003
        if "parentId" not in record:
            raise ValueError(f"Pi entry {event_id!r} has no parentId")  # noqa: TRY003
        parent = record["parentId"]
        if parent is not None and (not isinstance(parent, str) or parent not in by_id):
            raise ValueError(f"Pi entry {event_id!r} must reference an earlier parent")  # noqa: TRY003
        # Validate every record, even on an unselected branch, before any submission.
        _event(session_id, record)
        _digest(record)
        by_id[event_id] = record
    leaf = value.leaf_id if value.leaf_id is not None else next(reversed(by_id), None)
    if leaf is not None and leaf not in by_id:
        raise ValueError(f"Pi leaf {leaf!r} does not exist")  # noqa: TRY003
    path: list[str] = []
    while leaf is not None:
        path.append(leaf)
        parent = by_id[leaf]["parentId"]
        leaf = None if parent is None else _text(parent, "parent ID")
    return session_id, by_id, tuple(reversed(path))


def parse_pi_session(value: PiSessionInput) -> tuple[PiEventInput, ...]:
    """Validate the whole archive, then return visible events from root to leaf.

    Control nodes retain their graph position. Compaction and context edits never
    replace the raw evidence preceding them. Invalid archives raise ValueError.
    """
    session_id, records, path = _parse(value)
    return tuple(event for entry_id in path if (event := _event(session_id, records[entry_id])) is not None)


def _requires_record_encoding(record: dict[str, JsonValue]) -> bool:
    pending: list[JsonValue] = [record]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
        elif isinstance(value, int) and not -(2**53 - 1) <= value <= 2**53 - 1:
            return True
    return False


class _StoredPiEvent(PiEventInput):
    """Lossless record codec at the Source boundary, not the public event API.

    RFC8785 cannot serialize integers outside its safe integer range. Such
    records are stored as JSON text (a disjoint type from the original object),
    then decoded before model validation. No numeric value is converted to float.
    """

    @field_serializer("record", when_used="json")
    def encode_record(self, record: dict[str, JsonValue]) -> dict[str, JsonValue] | str:
        return _json(record) if _requires_record_encoding(record) else record

    @field_validator("record", mode="before", json_schema_input_type=dict[str, JsonValue] | str)
    @classmethod
    def decode_record(cls, value: object) -> object:
        if isinstance(value, str):
            return _object(
                json.loads(value, object_pairs_hook=_unique_object, parse_constant=_invalid_constant), "record"
            )
        return value


class PiEventSource(Source):
    """An immutable captured event, independent of the session file's lifetime."""

    event: _StoredPiEvent


class _PiEventAdapter:
    input_class: type[PiEventInput] = PiEventInput
    name = "pi-event"
    source_class: type[PiEventSource] = PiEventSource

    async def resolve(self, value: PiEventInput, /) -> PiEventSource:
        return PiEventSource(
            name=_identity(value.session_id, value.event_id),
            materialization=SourceMaterialization.CAPTURED,
            event=_StoredPiEvent.model_validate(value.model_dump()),
        )

    async def read(self, source: PiEventSource, /) -> PiEventInput:
        return PiEventInput.model_validate(source.event.model_dump())


class _PiTextProjection:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class: type[PiEventSource] = PiEventSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PiEventSource, /) -> TextEvidence:
        event = source.event
        return TextEvidence(
            source_type="pi-event",
            source_id=source.name,
            content=event.content,
            metadata={
                "session_id": event.session_id,
                "event_id": event.event_id,
                "parent_id": event.parent_id,
                "event_type": event.event_type,
                "role": event.role,
            },
        )


class _PiEventDefinition(_PiEventAdapter):
    version = "1"
    projections: tuple[SourceProjection[PiEventSource], ...] = (_PiTextProjection(),)


PI_EVENT_SOURCE_DEFINITION = _PiEventDefinition()


class _Checkpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: Literal[1] = 1
    # Session -> entry ID -> original record digest, including selected control ancestors.
    records: dict[str, dict[str, Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]]] = Field(default_factory=dict)


class PiSessionConnector:
    """Submit new branch events; let ConnectorLifecycle commit progress.

    A failed run may already have durable Sources. Retrying submits the same
    stable identities so Runtime ingestion deduplicates or rejects a conflict.
    No state is kept outside the binding's persisted checkpoint.
    """

    name = "pi-session-history"
    version = "1"
    source_definitions = frozenset({"pi-event"})

    def __init__(self, path: str | Path, leaf_id: str | None = None) -> None:
        self.path = Path(path)
        self.leaf_id = leaf_id

    async def run(self, session: ConnectorRunSession, /) -> ConnectorRunCompletion:
        content = await asyncio.to_thread(self.path.read_bytes)
        session_id, records, path = _parse(PiSessionInput(content=content, leaf_id=self.leaf_id))
        checkpoint = _Checkpoint() if session.checkpoint is None else _Checkpoint.model_validate(session.checkpoint)
        # Never mutate a loaded checkpoint: stores may return their live object.
        checkpoint = checkpoint.model_copy(deep=True)
        previous = checkpoint.records.setdefault(session_id, {})
        for entry_id, record in records.items():
            if entry_id in previous and previous[entry_id] != _digest(record):
                raise ValueError(f"Previously imported Pi entry {entry_id!r} was rewritten")  # noqa: TRY003
        for entry_id in path:
            if entry_id in previous:
                continue
            record = records[entry_id]
            event = _event(session_id, record)
            if event is not None:
                outcome = await session.submit(_identity(session_id, entry_id), "pi-event", event)
                if outcome.status is not ConnectorSubmissionStatus.ACCEPTED:
                    return ConnectorRunCompletion(status=ConnectorRunStatus.INCOMPLETE)
            previous[entry_id] = _digest(record)
        return ConnectorRunCompletion(status=ConnectorRunStatus.COMPLETE, checkpoint=checkpoint.model_dump(mode="json"))
