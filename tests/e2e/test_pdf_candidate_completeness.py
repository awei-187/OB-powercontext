# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

"""A report's repeated query wording cannot hide another report's statement."""

import textwrap
from typing import cast

import pytest

from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.runtime import (
    GetMemoryEntryRequest,
    RememberMemoryRequest,
    RetireMemoryEntryRequest,
    ScopedMemoryApplication,
    open_builtin_runtime,
)
from powercontext.sources.pdf_pages import search_pdf_pages
from tests.e2e.test_pdf_bulk_provenance import AdvanceBeforeList, SearchGetOnly
from tests.e2e.test_pdf_locations_and_headings import _capture, _locations


def report_texts(count, reverse=False):
    narrative = (
        "Quasar North operating cash flow in 2019. The consolidated statements cash flows mention "
        "operating investing financing cash income. "
    ) * 4
    statement = (
        "CONSOLIDATED STATEMENTS OF CASH FLOWS\nQuasar North\nYear ended 2019\n"
        "Operating activities\nCash provided by operating activities 105\n"
        "Investing activities (40)\nFinancing activities (15)\n"
        + textwrap.fill("Accounting convention explains changes between annual balances and cash movements. " * 35, 82)
        + "\nsequoiaendofstatement"
    )
    reports = {
        "packet-statement": [statement],
        "packet-discussion": [
            "Narrative discussion\n" + textwrap.fill(narrative, 82) + f"\nReview note {index}" for index in range(count)
        ],
    }
    return dict(reversed(reports.items())) if reverse else reports


@pytest.mark.parametrize("count", [21, 84])
@pytest.mark.parametrize("reverse", [False, True])
async def test_statement_survives_repeated_words_in_another_report(tmp_path, count, reverse):
    config, scope, captured = await _capture(tmp_path, report_texts(count, reverse))
    found = await _locations(config, scope, captured, "What was Quasar North operating cash flow in 2019?", 20)
    assert ("packet-statement", 1) in found


async def test_recovered_pages_respect_retirement_and_pdf_provenance(tmp_path):
    reports = report_texts(84)
    reports["unrelated-document"] = ["Basilisk pebbles."]
    config, scope, captured = await _capture(tmp_path, reports)
    question = "What was Quasar North operating cash flow in 2019?"
    assert ("packet-statement", 1) in await _locations(config, scope, captured, question, 20)
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope)
        target = next(
            record for record in (await memory.list()).entries if "sequoiaendofstatement" in record.entry.text
        )
        await memory.retire(RetireMemoryEntryRequest(citation=target.citation))
        await memory.remember(RememberMemoryRequest(entries=(MemoryEntryInput(kind="note", text=target.entry.text),)))
        # Retirement affects new retrieval; the old exact citation remains valid.
        assert (await memory.get(GetMemoryEntryRequest(citation=target.citation))).entry == target.entry
    found = await _locations(config, scope, captured, question, 20)
    assert found
    assert all(document == "packet-discussion" for document, _ in found)


async def test_source_less_notes_cannot_crowd_out_all_pdf_candidates(tmp_path):
    reports = report_texts(84)
    notes = reports.pop("packet-discussion")
    reports["unrelated-document"] = ["Basilisk pebbles."]
    config, scope, captured = await _capture(tmp_path, reports)
    async with open_builtin_runtime(config) as runtime:
        await runtime.memory.for_scope(scope).remember(
            RememberMemoryRequest(entries=tuple(MemoryEntryInput(kind="note", text=text) for text in notes))
        )
    found = await _locations(config, scope, captured, "What was Quasar North operating cash flow in 2019?", 20)
    assert found == [("packet-statement", 1)]


@pytest.mark.parametrize("action", ["append", "revise", "retire"])
async def test_saturated_search_does_not_mix_a_new_memory_revision(tmp_path, action):
    config, scope, captured = await _capture(tmp_path, report_texts(84))
    question = "What was Quasar North operating cash flow in 2019?"
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope)
        expected = await search_pdf_pages(cast(ScopedMemoryApplication, SearchGetOnly(memory)), question, 20)
        advancing = AdvanceBeforeList(memory, expected[0], action)
        observed = await search_pdf_pages(cast(ScopedMemoryApplication, advancing), question, 20)
        assert advancing.advanced
        assert observed == expected
        for citation in observed:
            entry = (await memory.get(GetMemoryEntryRequest(citation=citation))).entry
            page = captured[entry.sources[0].source_id]
            assert entry.text == f"{page.document_id}\n{page.text}".strip()
