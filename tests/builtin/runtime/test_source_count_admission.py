# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0

"""Real SQLite admission, with controlled workers at the scheduler boundary."""

from __future__ import annotations

import asyncio
from functools import partial

import pytest
from sqlalchemy import event, update

from powercontext.builtin.persistence.cursors import SourceCursorRepository
from powercontext.builtin.persistence.processing_intents import ArtifactProcessingIntentRepository
from powercontext.builtin.persistence.sources import SourceRepository
from powercontext.builtin.persistence.tables import SOURCE_JOURNAL_HEADS_TABLE, SOURCES_TABLE
from powercontext.builtin.runtime import artifact_processing as processing
from powercontext.builtin.runtime.artifact_processing import ArtifactProcessingBinding, ArtifactProcessingSupervisor
from powercontext.builtin.runtime.processing_discovery import source_count_scopes
from powercontext.builtin.sources import BUILTIN_SOURCE_REGISTRY, SourceCursor
from powercontext.builtin.sources.content import ContentSource
from powercontext.builtin.triggers import SOURCE_WINDOW_TRIGGER_NAME
from powercontext.sources import SourceMaterialization
from tests.builtin.runtime.test_processing_scheduler import _intent, _Launcher, _profile, _wait

BINDING = SOURCE_WINDOW_TRIGGER_NAME


async def _capture(database, scope, count):
    repository = SourceRepository(BUILTIN_SOURCE_REGISTRY)
    async with database.transaction() as connection:
        for index in range(count):
            await repository.add(
                connection,
                scope,
                ContentSource(
                    name=f"source-{index}", materialization=SourceMaterialization.CAPTURED, content=f"Fact {index}"
                ),
            )


def _binding(launcher, threshold=3):
    return ArtifactProcessingBinding(
        BINDING,
        "memory",
        launcher,
        count_scope_filter=partial(source_count_scopes, binding_name=BINDING, threshold=threshold),
    )


def test_count_uses_rows_after_family_cursor_and_supports_huge_thresholds(tmp_path):
    async def scenario():
        async with _profile(tmp_path, "identities") as profile:
            await _capture(profile.database, "left", 3)
            await _capture(profile.database, "right", 1)
            await _capture(profile.database, "left", 3)  # replay all identities
            async with profile.database.transaction() as connection:
                qualify = partial(source_count_scopes, connection, ("left", "right", "absent"), binding_name=BINDING)
                assert await qualify(threshold=3) == {"left"}
                assert await qualify(threshold=10**100) == set()
                await SourceCursorRepository().save(
                    connection, "left", BINDING, SourceCursor(sequence=1), expected_generation=None
                )
                assert await qualify(threshold=3) == set()
                assert await source_count_scopes(
                    connection, ("left",), binding_name="topic-memory-source-window", threshold=3
                ) == {"left"}
                # Sparse persisted positions must not be mistaken for more identities.
                await connection.execute(
                    update(SOURCES_TABLE)
                    .where(SOURCES_TABLE.c.scope_id == "left", SOURCES_TABLE.c.journal_position == 3)
                    .values(journal_position=30)
                )
                await connection.execute(
                    update(SOURCE_JOURNAL_HEADS_TABLE)
                    .where(SOURCE_JOURNAL_HEADS_TABLE.c.scope_id == "left")
                    .values(position=30)
                )
                assert await qualify(threshold=3) == set()
                assert await qualify(threshold=2) == {"left"}

    asyncio.run(scenario())


class _AdmissionFailure(Exception):
    pass


class _FailingRequests(ArtifactProcessingIntentRepository):
    failure = None

    async def request(self, connection, scope_id, binding_name, /):
        result = await super().request(connection, scope_id, binding_name)
        if scope_id == "b" and self.failure is not None:
            failure, self.failure = self.failure, None
            raise failure
        return result


@pytest.mark.parametrize("boundary", ["request", "cancel", "commit"])
def test_admission_rollback_does_not_lose_page_or_publish_work(tmp_path, boundary):
    async def scenario():
        async with _profile(tmp_path, "rollback") as profile:
            for scope in ("a", "b"):
                await _capture(profile.database, scope, 3)
            intents = _FailingRequests()
            launcher = _Launcher(profile.database)
            supervisor = ArtifactProcessingSupervisor(
                database=profile.database, bindings=(_binding(launcher),), lease_mode="single-process", intents=intents
            )
            await supervisor._acquire()
            state = supervisor._families[BINDING]

            def fail_commit(_connection):
                raise _AdmissionFailure

            try:
                if boundary == "commit":
                    event.listen(profile.database.engine.sync_engine, "commit", fail_commit, once=True)
                else:
                    intents.failure = asyncio.CancelledError() if boundary == "cancel" else _AdmissionFailure()
                try:
                    with pytest.raises(asyncio.CancelledError if boundary == "cancel" else _AdmissionFailure):
                        await supervisor._discover_count(state)
                finally:
                    if boundary == "commit":
                        event.remove(profile.database.engine.sync_engine, "commit", fail_commit)
                assert state.count_after == state.next_count_at == 0
                assert not state.ready and not launcher.assignments
                for scope in ("a", "b"):
                    assert (await _intent(profile.database, BINDING, scope)).requested_generation == 0
                await supervisor._discover_count(state)
                assert tuple(state.ready) == ("a", "b")
                for scope in ("a", "b"):
                    assert (await _intent(profile.database, BINDING, scope)).requested_generation == 1
            finally:
                await supervisor._lose_leadership()

    asyncio.run(scenario())


def test_bounded_pages_cross_ineligible_scopes_without_starving_later_work(tmp_path, monkeypatch):
    monkeypatch.setattr(processing, "_DISCOVERY_PAGE_SIZE", 2)

    async def scenario():
        async with _profile(tmp_path, "pages") as profile:
            for scope in ("a", "b", "c", "d", "e"):
                await _capture(profile.database, scope, 3 if scope == "e" else 1)
            launcher = _Launcher(profile.database)
            async with ArtifactProcessingSupervisor(
                database=profile.database, bindings=(_binding(launcher),), lease_mode="single-process"
            ):
                await _wait(lambda: len(launcher.assignments) == 1)
                assert launcher.assignments[0].scope_id == "e"
                for scope in ("a", "b", "c", "d"):
                    assert (await _intent(profile.database, BINDING, scope)).requested_generation == 0

    asyncio.run(scenario())


def test_cancelled_worker_restarts_accepted_request_even_when_threshold_is_raised(tmp_path):
    async def scenario():
        async with _profile(tmp_path, "cancelled-worker") as profile:
            await _capture(profile.database, "scope", 3)
            launcher = _Launcher(profile.database, gates={"scope": asyncio.Event()})
            async with ArtifactProcessingSupervisor(
                database=profile.database, bindings=(_binding(launcher),), lease_mode="single-process"
            ):
                await _wait(lambda: len(launcher.assignments) == 1)
            intent = await _intent(profile.database, BINDING, "scope")
            assert intent.requested_generation == 1 and intent.handled_generation == 0
            assert launcher.terminated == ["scope"]
        async with _profile(tmp_path, "cancelled-worker") as profile:
            recovered = _Launcher(profile.database)
            async with ArtifactProcessingSupervisor(
                database=profile.database, bindings=(_binding(recovered, threshold=100),), lease_mode="single-process"
            ) as supervisor:
                await _wait(lambda: supervisor.family_status["memory"]["completed"] == 1)
                assert len(recovered.assignments) == 1
                assert recovered.assignments[0].claimed_request_generation == 1

    asyncio.run(scenario())


def test_accepted_failure_retries_without_reapplying_count_predicate(tmp_path):
    async def scenario():
        async with _profile(tmp_path, "retry") as profile:
            await _capture(profile.database, "scope", 3)
            attempts = 0

            async def fail_once(work):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise _AdmissionFailure

            launcher = _Launcher(profile.database, on_work=fail_once)
            async with ArtifactProcessingSupervisor(
                database=profile.database,
                bindings=(_binding(launcher),),
                lease_mode="single-process",
                retry_base_seconds=0.01,
                retry_jitter=lambda: 1,
            ) as supervisor:
                await _wait(lambda: supervisor.family_status["memory"]["completed"] == 1)
                assert attempts == 2
                assert [item.claimed_request_generation for item in launcher.assignments] == [1, 1]
                intent = await _intent(profile.database, BINDING, "scope")
                assert intent.handled_generation == intent.requested_generation == 1

    asyncio.run(scenario())


def test_count_and_explicit_admission_coalesce_and_running_scope_is_single_flight(tmp_path):
    async def scenario():
        async with _profile(tmp_path, "single-flight") as profile:
            await _capture(profile.database, "scope", 3)
            async with profile.database.transaction() as connection:
                await ArtifactProcessingIntentRepository().request(connection, "scope", BINDING)
            gate = asyncio.Event()
            launcher = _Launcher(profile.database, gates={"scope": gate})
            async with ArtifactProcessingSupervisor(
                database=profile.database,
                bindings=(_binding(launcher),),
                lease_mode="single-process",
                oceanbase_tick_seconds=0.01,
            ) as supervisor:
                await _wait(lambda: len(launcher.assignments) == 1)
                await _capture(profile.database, "scope", 6)
                # Deterministic repeated discovery while the same Scope is running.
                state = supervisor._families[BINDING]
                for _ in range(3):
                    state.next_count_at = 0
                    await supervisor._discover_count(state)
                assert (await _intent(profile.database, BINDING, "scope")).requested_generation == 1
                assert launcher.maximum_active == 1
                gate.set()
                await _wait(lambda: supervisor.family_status["memory"]["completed"] == 1)
                assert len(launcher.assignments) == 1

    asyncio.run(scenario())
