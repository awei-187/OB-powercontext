# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Independent Pi archive and real Runtime recovery regressions."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from pydantic import JsonValue

from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    CommitConnectorCheckpoint,
    SubmitSourceObservation,
    open_builtin_contexts,
    open_builtin_runtime,
)
from powercontext.builtin.scope import ScopeDraft
from powercontext.errors import ConnectorSubmissionRejectedError, SourceConflictError
from powercontext.sources import (
    ConnectorBinding,
    ConnectorRunStatus,
    SourceDefinitionRegistry,
    SourceRef,
    manifest_for_definition,
    project_source_for_transport,
)
from powercontext.sources.connectors import ConnectorLifecycle
from powercontext.sources.pi_session import (
    PI_EVENT_SOURCE_DEFINITION,
    PiEventInput,
    PiSessionConnector,
    PiSessionInput,
    parse_pi_session,
)


def archive(records, session_id="s", leaf=None):
    header = {"type": "session", "id": session_id, "version": 3}
    return PiSessionInput(
        content="\n".join(json.dumps(row, ensure_ascii=False) for row in [header, *records]).encode(), leaf_id=leaf
    )


def message(entry_id="a", parent=None, content="Original", role="user"):
    return {"type": "message", "id": entry_id, "parentId": parent, "message": {"role": role, "content": content}}


def test_raw_unicode_blocks_summaries_controls_and_multiple_roots():
    records = [
        message(content="  请求\u2028next  "),
        {"type": "context_edit", "id": "edit", "parentId": "a", "targetId": "a", "replacement": None},
        message(
            "tool",
            "edit",
            [
                {"type": "thinking", "thinking": "not evidence"},
                {"type": "text", "text": "before"},
                {"type": "toolCall", "id": "c", "name": "read", "arguments": {"z": "中文", "a": [1, True]}},
                {"type": "text", "text": "after\n"},
            ],
            "assistant",
        ),
        {"type": "compaction", "id": "sum", "parentId": "tool", "summary": "summary", "firstKeptEntryId": "sum"},
        message("another-root", None, "independent"),
    ]
    events = parse_pi_session(archive(records, leaf="sum"))
    assert [event.event_id for event in events] == ["a", "tool", "sum"]
    assert events[0].content == "user:   请求\u2028next  "
    assert events[1].content == 'assistant: before\n[tool_call read c] {"a":[1,true],"z":"中文"}\nafter\n'
    assert events[1].parent_id == "edit"
    assert events[1].record == records[2]
    assert [event.event_id for event in parse_pi_session(archive(records))] == ["another-root"]


def test_empty_controls_and_whitespace_are_distinct():
    assert parse_pi_session(archive([])) == ()
    assert parse_pi_session(archive([message(content=[])])) == ()
    assert parse_pi_session(archive([message(content=[{"type": "thinking", "thinking": "secret"}])])) == ()
    assert parse_pi_session(archive([message(content="  ")]))[0].content == "user:   "
    assert parse_pi_session(archive([{"type": "model_change", "id": "m", "parentId": None}])) == ()


@pytest.mark.parametrize(
    "bad",
    [
        {"type": "message", "id": "b", "message": {"role": "user", "content": "missing parent"}},
        {"type": "model_change", "id": "b", "parentId": []},
        {"type": "model_change", "id": "b", "parentId": "later"},
        {"type": "model_change", "id": "a", "parentId": None},
        {"type": "session", "version": 3, "id": "b", "parentId": None},
        {"type": "message", "id": "b", "parentId": None, "message": []},
        {"type": "message", "id": "b", "parentId": None, "message": {"role": "user", "content": 42}},
        {"type": "model_change", "id": "", "parentId": None},
        {"type": "model_change", "id": 42, "parentId": None},
    ],
)
def test_invalid_unselected_branch_is_not_ignored(bad):
    with pytest.raises(ValueError):
        parse_pi_session(archive([message(), bad], leaf="a"))


@pytest.mark.parametrize(
    "tail",
    [
        b"null",
        b"[]",
        b"{bad}",
        b"\xff",
        b'{"type":"custom","id":"b","parentId":null,"data":NaN}',
        b'{"type":"custom","id":"b","parentId":null,"data":1e999}',
        b'{"type":"custom","id":"b","id":"c","parentId":null}',
    ],
)
def test_invalid_json_has_no_partial_result(tail):
    with pytest.raises(ValueError):
        parse_pi_session(PiSessionInput(content=archive([message()]).content + b"\n" + tail, leaf_id="a"))


def test_long_chain_does_not_use_python_recursion():
    records = [message(str(i), str(i - 1) if i else None) for i in range(2500)]
    events = parse_pi_session(archive(records))
    assert len(events) == 2500
    assert events[-1].event_id == "2499"


def test_identity_full_payload_and_detached_readback():
    async def scenario():
        registry = SourceDefinitionRegistry((PI_EVENT_SOURCE_DEFINITION,))
        identities = set()
        for sid, eid in [("a:b", "c"), ("a", "b:c"), ("长" * 500, "值" * 500)]:
            record = message(eid, content="X" * 20000)
            event = parse_pi_session(archive([record], session_id=sid))[0]
            source = await registry.resolve(event)
            identities.add(source.name)
            assert len(source.name) <= 256
            assert await registry.read(source) == event
            restored = PI_EVENT_SOURCE_DEFINITION.source_class.model_validate_json(source.model_dump_json())
            assert await registry.read(restored) == event
            observation = project_source_for_transport(registry, source)
            assert observation.payload["event"] == event.model_dump()
            event.record["extra"] = "caller mutation"
            assert (await registry.read(source)) == parse_pi_session(archive([record], session_id=sid))[0]
            readback = await registry.read(source)
            assert isinstance(readback, PiEventInput)
            readback.record["extra"] = "read mutation"
            assert (await registry.read(source)) == parse_pi_session(archive([record], session_id=sid))[0]
        assert len(identities) == 3

    asyncio.run(scenario())


def test_runtime_checkpoint_restart_branch_mutation_and_file_repair(tmp_path):
    async def scenario():
        fixture = await RuntimeFixture.create(tmp_path)
        rows = [message(), message("left", "a"), message("right", "a")]
        fixture.write(rows)
        first = await fixture.run("left")
        assert len(first.items) == 2
        second = await fixture.run("right")
        assert len(second.items) == 1
        assert second.previous_checkpoint == first.committed_checkpoint
        # A changed event on the *other* branch must also fail before any writes.
        rows[1]["message"]["content"] = "rewritten off-path"
        fixture.write(rows)
        with pytest.raises(ValueError, match="rewritten"):
            await fixture.run("right")
        assert await fixture.checkpoint() == second.committed_checkpoint
        rows[1]["message"]["content"] = "Original"
        fixture.write(rows)
        assert (await fixture.run("left")).items == ()
        fixture.path.write_bytes(archive(rows).content + b'\n{"type":')
        with pytest.raises(ValueError):
            await fixture.run("right")
        assert await fixture.checkpoint() == second.committed_checkpoint
        fixture.write([*rows, message("tail", "right")])
        added = await fixture.run()
        assert len(added.items) == 1
        assert len(await fixture.entries()) == 4

    asyncio.run(scenario())


def test_runtime_large_tool_result_keeps_exact_record_after_restart(tmp_path):
    async def scenario():
        fixture = await RuntimeFixture.create(tmp_path)
        body = "完整工具结果\n" * 3000
        result = message("result", "a", [{"type": "text", "text": body}], "toolResult")
        result["message"].update({"toolName": "read", "toolCallId": "call-1", "details": {"exit": 0}})
        records = [message(), result]
        fixture.write(records)
        await fixture.run()
        expected = parse_pi_session(archive(records))[1]
        assert len(expected.content.encode()) > 8192
        # Read immutable evidence after the original provider file is unavailable.
        fixture.path.write_bytes(b"broken provider file")
        stored = (await fixture.entries())[1].source
        source = PI_EVENT_SOURCE_DEFINITION.source_class.model_validate(stored.payload)
        assert await fixture.registry.read(source) == expected
        assert stored.projections[0].value["content"] == expected.content
        assert stored.payload["event"]["record"] == result

    asyncio.run(scenario())


@pytest.mark.parametrize("integer", [2**53, -(2**53), 2**53 + 1, -(2**53 + 1), 10**100, -(10**100)])
def test_numeric_records_round_trip_without_float_conversion(tmp_path, integer):
    async def scenario():
        fixture = await RuntimeFixture.create(tmp_path)
        arguments = {"nested": [integer, str(integer), True, None, {"record": "a real string"}]}
        numeric = message(
            "numeric",
            "a",
            [
                {"type": "toolCall", "name": "read", "id": "c", "arguments": arguments},
            ],
            "assistant",
        )
        numeric["message"]["details"] = {"number": integer, "other": [-integer, 1.25]}
        records = [message(), numeric]
        expected = parse_pi_session(archive(records))[1]
        fixture.write(records)
        first = await fixture.run()
        assert len(first.items) == 2
        assert (await fixture.run()).items == ()
        assert await fixture.checkpoint() == first.committed_checkpoint
        stored = (await fixture.entries())[1].source
        source = PI_EVENT_SOURCE_DEFINITION.source_class.model_validate(stored.payload)
        restored = await fixture.registry.read(source)
        assert restored == expected
        assert isinstance(restored, PiEventInput)
        assert restored.record == numeric
        assert type(restored.record["message"]["details"]["number"]) is int
        assert str(integer) in restored.content
        assert stored.projections[0].value["content"] == expected.content
        # The source codec must also survive its public JSON serialization path.
        reloaded = PI_EVENT_SOURCE_DEFINITION.source_class.model_validate_json(source.model_dump_json())
        assert await fixture.registry.read(reloaded) == expected
        # Encoded records must still participate in immutable-payload conflicts.
        numeric["message"]["details"]["number"] = integer + 1
        changed_event = parse_pi_session(archive(records))[1]
        changed = project_source_for_transport(fixture.registry, await fixture.registry.resolve(changed_event))
        async with open_builtin_runtime(fixture.config) as runtime:
            with pytest.raises(SourceConflictError):
                await runtime.ingestion.submit(
                    SubmitSourceObservation(scope_id=fixture.binding.scope_id, observation=changed)
                )
        assert await fixture.checkpoint() == first.committed_checkpoint

    asyncio.run(scenario())


def test_numeric_codec_keeps_native_input_and_existing_object_payload_readable():
    async def scenario():
        registry = SourceDefinitionRegistry((PI_EVENT_SOURCE_DEFINITION,))
        row = message(content="metadata")
        row["message"]["details"] = {"record": '{"integer":9007199254740993}', "number": 2**53 - 1}
        event = parse_pi_session(archive([row]))[0]
        source = await registry.resolve(event)
        payload = source.model_dump(mode="json")
        assert payload["event"]["record"] == row
        restored = PI_EVENT_SOURCE_DEFINITION.source_class.model_validate(payload)
        assert await registry.read(restored) == event
        row["message"]["details"]["number"] += 2
        event = parse_pi_session(archive([row]))[0]
        assert event.model_dump(mode="json")["record"] == row
        source = await registry.resolve(event)
        assert isinstance(source, PI_EVENT_SOURCE_DEFINITION.source_class)
        assert source.event.record == row
        assert isinstance(source.model_dump(mode="json")["event"]["record"], str)
        assert await registry.read(source) == event

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["exception", "cancel", "reject", "checkpoint"])
def test_runtime_partial_writes_retry_without_progress_loss(tmp_path, failure):
    async def scenario():
        fixture = await RuntimeFixture.create(tmp_path)
        fixture.write([message()])
        first = await fixture.run()
        fixture.write([message(), message("b", "a"), message("c", "b")])
        if failure == "reject":
            failed = await fixture.run(failure=failure)
            assert failed.status is ConnectorRunStatus.INCOMPLETE
        else:
            with pytest.raises(asyncio.CancelledError if failure == "cancel" else OSError):
                await fixture.run(failure=failure)
        assert await fixture.checkpoint() == first.committed_checkpoint
        assert len(await fixture.entries()) == 3  # Source writes committed before the failure.
        retried = await fixture.run()
        assert len(retried.items) == 2
        assert len(await fixture.entries()) == 3  # Runtime idempotency, no duplicate journal entries.
        assert (await fixture.run()).items == ()

    asyncio.run(scenario())


def test_runtime_partial_write_rewrite_cannot_overwrite_evidence(tmp_path):
    async def scenario():
        fixture = await RuntimeFixture.create(tmp_path)
        rows = [message(), message("b", "a"), message("c", "b")]
        fixture.write(rows)
        with pytest.raises(OSError):
            await fixture.run(failure="exception")
        rows[1]["message"]["content"] = "altered after failed run"
        fixture.write(rows)
        with pytest.raises(SourceConflictError):
            await fixture.run()
        assert await fixture.checkpoint() is None
        stored = await fixture.entries()
        assert len(stored) == 3
        assert stored[1].source.payload["event"]["content"] == "user: Original"

    asyncio.run(scenario())


class RuntimeFixture:
    """Fresh Runtime instances share only the actual SQLite database and file."""

    def __init__(self, directory: Path, config: BuiltinConfig, binding: ConnectorBinding):
        self.path = directory / "session.jsonl"
        self.config = config
        self.binding = binding
        self.registry = SourceDefinitionRegistry((PI_EVENT_SOURCE_DEFINITION,))

    @classmethod
    async def create(cls, directory):
        config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{directory / 'pi.db'}"))
        async with open_builtin_runtime(config) as runtime:
            assert runtime.scopes is not None
            scope = await runtime.scopes.create(ScopeDraft(title="Pi", summary="Pi evidence", idempotency_key="pi"))
            await runtime.ingestion.register(manifest_for_definition(PI_EVENT_SOURCE_DEFINITION))
        binding = ConnectorBinding(
            scope_id=scope.scope_id, binding_id="pi", connector_name="pi-session-history", connector_version="1"
        )
        return cls(directory, config, binding)

    def write(self, records):
        self.path.write_bytes(archive(records).content)

    async def checkpoint(self):
        async with open_builtin_runtime(self.config) as runtime:
            return (await runtime.ingestion.checkpoint(self.binding)).checkpoint

    async def entries(self):
        async with open_builtin_contexts(self.config) as contexts:
            return await (await contexts.get(self.binding.scope_id)).sources.journal.entries()

    async def run(self, leaf=None, *, failure=None):
        registry = self.registry
        async with open_builtin_runtime(self.config) as runtime:

            class Sink:
                async def submit(self, binding, item_id, definition_name, value, /) -> SourceRef:
                    source = await registry.resolve(value)
                    result = await runtime.ingestion.submit(
                        SubmitSourceObservation(
                            scope_id=binding.scope_id, observation=project_source_for_transport(registry, source)
                        )
                    )
                    if value.event_id == "c":
                        if failure == "exception":
                            raise OSError("simulated response loss")  # noqa: TRY003
                        if failure == "cancel":
                            raise asyncio.CancelledError
                        if failure == "reject":
                            raise ConnectorSubmissionRejectedError("simulated rejection")  # noqa: TRY003
                    return result.source_ref

            class Checkpoints:
                async def load(self, binding, /) -> JsonValue | None:
                    return (await runtime.ingestion.checkpoint(binding)).checkpoint

                async def save(self, binding, checkpoint, /, *, expected):
                    if failure == "checkpoint":
                        raise OSError("simulated checkpoint failure")  # noqa: TRY003
                    await runtime.ingestion.commit(
                        CommitConnectorCheckpoint(binding=binding, checkpoint=checkpoint, expected=expected)
                    )

            return await ConnectorLifecycle(sink=Sink(), checkpoints=Checkpoints()).run(
                PiSessionConnector(self.path, leaf), self.binding
            )
