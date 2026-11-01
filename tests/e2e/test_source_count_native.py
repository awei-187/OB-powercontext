# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0

"""Additional count regressions with native workers and the public offline provider.

The provider and licensed input stay in the unchanged competition assets. These
tests exercise public Runtime behavior; they never replace native processors.
"""

from __future__ import annotations

import asyncio
import sqlite3
from importlib import import_module

import pytest

from powercontext.builtin.runtime import open_builtin_runtime

checks = import_module("competition.challenges.processing-01-count-trigger.acceptance.checks")


@pytest.mark.parametrize("family", ["memory", "topic-memory"])
def test_concurrent_capture_replays_count_each_identity_once(tmp_path, monkeypatch, family):
    async def scenario():
        with checks.provider(monkeypatch) as server:
            prefix = family.replace("-", "_")
            settings = checks.config(
                tmp_path / "concurrent.db", server, families=(family,), **{f"{prefix}_source_count_threshold": 6}
            )
            async with open_builtin_runtime(settings) as runtime:
                sid = await checks.scope(runtime)
                rows = checks.messages()
                receipts = await asyncio.gather(
                    *(checks.capture(runtime, sid, [row]) for row in rows[:3] for _ in range(3))
                )
                assert len({result[0].sequence for result in receipts}) == 3
                await checks.stay_refs(runtime, sid, family, set())
                receipts += await asyncio.gather(*(checks.capture(runtime, sid, [row]) for row in rows[3:6]))
                expected = checks.receipt_refs([item for result in receipts for item in result])
                await checks.wait_refs(runtime, sid, family, expected)
                await checks.check_reads(runtime, sid, family, expected)
                await checks.stay_refs(runtime, sid, family, expected)
            async with open_builtin_runtime(settings) as runtime:
                await checks.check_reads(runtime, sid, family, expected)
                await checks.capture(runtime, sid, rows[:6])
                await checks.stay_refs(runtime, sid, family, expected)

    asyncio.run(scenario())


def test_topic_partly_committed_wave_recovers_below_new_threshold(tmp_path, monkeypatch):
    async def scenario():
        database = tmp_path / "partial-wave.db"
        with checks.provider(monkeypatch) as server:
            settings = checks.config(
                database,
                server,
                families=("topic-memory",),
                topic_memory_source_count_threshold=3,
                topic_memory_source_window_limit=1,
            )
            async with open_builtin_runtime(settings) as runtime:
                sid = await checks.scope(runtime)
                with sqlite3.connect(database) as connection:
                    connection.execute(
                        "CREATE TRIGGER interrupt_later_window BEFORE INSERT ON pc_artifacts "
                        "WHEN NEW.family = 'topic-memory' AND "
                        "(SELECT COUNT(*) FROM pc_artifacts WHERE family = 'topic-memory') >= 1 "
                        "BEGIN SELECT RAISE(ABORT, 'controlled later window failure'); END"
                    )
                receipts = await checks.capture(runtime, sid, checks.messages()[:3])
                first = checks.receipt_refs(receipts[:1])
                await checks.wait_refs(runtime, sid, "topic-memory", first)
                await checks.stay_refs(runtime, sid, "topic-memory", first)
            with sqlite3.connect(database) as connection:
                connection.execute("DROP TRIGGER interrupt_later_window")
            settings = checks.config(
                database,
                server,
                families=("topic-memory",),
                topic_memory_source_count_threshold=100,
                topic_memory_source_window_limit=1,
            )
            async with open_builtin_runtime(settings) as runtime:
                expected = checks.receipt_refs(receipts)
                await checks.wait_refs(runtime, sid, "topic-memory", expected)
                await checks.check_reads(runtime, sid, "topic-memory", expected)
                await checks.capture(runtime, sid, checks.messages()[3:4])
                await checks.stay_refs(runtime, sid, "topic-memory", expected)

    asyncio.run(scenario())


@pytest.mark.parametrize("family", ["memory", "topic-memory"])
def test_provider_failure_keeps_accepted_work_when_count_is_disabled_after_restart(tmp_path, monkeypatch, family):
    async def scenario():
        database = tmp_path / "provider-failure.db"
        with checks.provider(monkeypatch) as server:
            prefix = family.replace("-", "_")
            settings = checks.config(database, server, families=(family,), **{f"{prefix}_source_count_threshold": 2})
            server.fail_generation = True
            async with open_builtin_runtime(settings) as runtime:
                sid = await checks.scope(runtime)
                expected = checks.receipt_refs(await checks.capture(runtime, sid, checks.messages()[:2]))
                async with asyncio.timeout(30):
                    while not server.generation_calls:  # noqa: ASYNC110 - observe the real provider boundary
                        await asyncio.sleep(0.1)
                await checks.stay_refs(runtime, sid, family, set())
                if family == "memory":
                    assert (await runtime.memory.for_scope(sid).cursor()).sequence == 0
            server.fail_generation = False
            settings = checks.config(database, server, families=(family,))
            async with open_builtin_runtime(settings) as runtime:
                await checks.wait_refs(runtime, sid, family, expected)
                await checks.check_reads(runtime, sid, family, expected)
                await checks.stay_refs(runtime, sid, family, expected)

    asyncio.run(scenario())
