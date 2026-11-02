# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

"""Bulk provenance reads preserve public search/get citation behavior."""

from typing import cast

import pytest

from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.runtime import (
    GetMemoryEntryRequest,
    RememberMemoryRequest,
    RetireMemoryEntryRequest,
    ReviseMemoryEntryRequest,
    ScopedMemoryApplication,
    open_builtin_runtime,
)
from powercontext.sources.pdf_pages import search_pdf_pages
from tests.e2e.test_pdf_locations_and_headings import _capture


class SearchGetOnly:
    def __init__(self, memory):
        self.memory = memory

    async def search(self, request):
        return await self.memory.search(request)

    async def get(self, request):
        return await self.memory.get(request)


async def test_bulk_provenance_preserves_exact_order_with_source_less_notes(tmp_path):
    texts = [f"Quartz inventories by category\nAccounting policy {number}." for number in range(64)]
    texts[21] = "Quartz inventories by category\nRaw materials 772\nFinished goods 419\nTotal 1191"
    config, scope, captured = await _capture(tmp_path, {"QUARTZ_2045": texts})
    async with open_builtin_runtime(config) as runtime:
        await runtime.memory.for_scope(scope).remember(
            RememberMemoryRequest(
                entries=tuple(
                    MemoryEntryInput(kind="note", text=f"QUARTZ_2045\nQuartz inventories by category {number}.")
                    for number in range(20)
                )
            )
        )
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope)
        narrow = cast(ScopedMemoryApplication, SearchGetOnly(memory))
        question = "Show Quartz inventories by category and raw materials."
        expected = await search_pdf_pages(narrow, question, 20)
        observed = await search_pdf_pages(memory, question, 20)
        assert observed == expected
        locations = []
        for citation in observed:
            entry = (await memory.get(GetMemoryEntryRequest(citation=citation))).entry
            assert len(entry.sources) == 1 and entry.sources[0].source_type == "pdf-page"
            page = captured[entry.sources[0].source_id]
            assert entry.text == f"{page.document_id}\n{page.text}".strip()
            locations.append(page.page_number)
        assert 22 in locations


class AdvanceBeforeList(SearchGetOnly):
    def __init__(self, memory, citation, action):
        super().__init__(memory)
        self.advanced = False
        self.citation = citation
        self.action = action
        self.snapshot = None

    async def capacity(self):
        return await self.memory.capacity()

    async def list(self):
        if not self.advanced:
            self.advanced = True
            if self.action == "append":
                await self.memory.remember(
                    RememberMemoryRequest(entries=(MemoryEntryInput(kind="note", text="Unrelated new revision."),))
                )
            elif self.action == "revise":
                await self.memory.revise(
                    ReviseMemoryEntryRequest(citation=self.citation, kind="note", text="Unrelated new revision.")
                )
            else:
                await self.memory.retire(RetireMemoryEntryRequest(citation=self.citation))
        self.snapshot = await self.memory.list()
        return self.snapshot


@pytest.mark.parametrize("action", ["append", "revise", "retire"])
async def test_head_advance_during_bulk_read_preserves_old_exact_citations(tmp_path, action):
    config, scope, captured = await _capture(
        tmp_path, {"QUARTZ_2045": [f"Quartz inventories quantity {number}." for number in range(64)]}
    )
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope)
        expected = await search_pdf_pages(
            cast(ScopedMemoryApplication, SearchGetOnly(memory)), "Quartz inventories", 20
        )
        advancing = AdvanceBeforeList(memory, expected[0], action)
        observed = await search_pdf_pages(cast(ScopedMemoryApplication, advancing), "Quartz inventories", 20)
        assert observed == expected
        assert (await memory.capacity()).memory_ref != expected[0].memory_ref
        assert advancing.snapshot is not None
        if action != "append":
            assert all(
                record.entry.entry_version_id != expected[0].entry_version_id for record in advancing.snapshot.entries
            )
        for citation in observed:
            entry = (await memory.get(GetMemoryEntryRequest(citation=citation))).entry
            page = captured[entry.sources[0].source_id]
            assert entry.text == f"{page.document_id}\n{page.text}".strip()
