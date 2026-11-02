# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

"""Native lexical matches survive PDF query processing and exact readback."""

import pytest

from powercontext.artifacts import MemoryCitation
from powercontext.builtin.runtime import GetMemoryEntryRequest, SearchMemoryRequest, open_builtin_runtime
from powercontext.sources.pdf_pages import search_pdf_pages
from tests.e2e.test_pdf_locations_and_headings import _capture


@pytest.mark.parametrize(
    ("document_id", "texts", "question", "expected_pages"),
    [
        (
            "LUMEN_2024_10K",
            ["alpha", "beta", "alpha beta", "alpha beta gamma", "gross_margin 42"],
            "LUMEN_2024_10K",
            {1, 2, 3, 4, 5},
        ),
        (
            "LUMEN_2024_10K",
            ["alpha", "beta", "alpha beta", "alpha beta gamma", "gross_margin 42"],
            "gross_margin",
            {5},
        ),
        ("中国", ["operating statement 17"], "中国", {1}),
    ],
)
async def test_native_lexical_match_survives_pdf_query_processing(
    tmp_path, document_id, texts, question, expected_pages
):
    config, scope, captured = await _capture(tmp_path, {document_id: texts})
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope)

        async def locations(citations):
            pages = set()
            for citation in citations:
                entry = (await memory.get(GetMemoryEntryRequest(citation=citation))).entry
                assert len(entry.sources) == 1 and entry.sources[0].source_type == "pdf-page"
                page = captured[entry.sources[0].source_id]
                assert entry.text == f"{page.document_id}\n{page.text}".strip()
                pages.add(page.page_number)
            return pages

        native = await memory.search(SearchMemoryRequest(query=question, mode="fts", limit=20))
        assert (
            await locations(
                tuple(
                    MemoryCitation(
                        memory_ref=hit.memory_ref, entry_id=hit.entry_id, entry_version_id=hit.entry_version_id
                    )
                    for hit in native.hits
                )
            )
            == expected_pages
        )
        observed = await search_pdf_pages(memory, question, 20)
        assert await locations(observed) == expected_pages
