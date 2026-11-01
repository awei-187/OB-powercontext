# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

"""PDF provenance and complementary evidence survive arbitrary document labels."""

import pytest

from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.runtime import RememberMemoryRequest, open_builtin_runtime
from tests.e2e.test_pdf_locations_and_headings import _capture, _locations


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("lowercase", [False, True])
async def test_comparison_retains_an_opaque_report_beyond_twenty_named_pages(tmp_path, reverse, lowercase):
    documents = {}
    targets = []
    for label, company, position in [("ACACIA_PEAK_2041_10K", "Acacia Peak", 13), ("record-q9", "Cobalt Shore", 27)]:
        texts = ["Annual report 2041\nInventory accounting policies and category definitions."] * 35
        texts[0] = company + "\nAnnual report 2041"
        texts[position - 1] = (
            "Inventories by category\nRaw materials 721\nWork in process 82\nFinished goods 931\nTotal 1734"
        )
        documents[label] = texts
        targets.append((label, position))
    if reverse:
        documents = dict(reversed(documents.items()))
    config, scope, captured = await _capture(tmp_path, documents)
    question = "For Acacia Peak and Cobalt Shore, compare inventories by category, including raw materials."
    found = await _locations(config, scope, captured, question.lower() if lowercase else question, 20)
    assert set(targets) <= set(found)


@pytest.mark.parametrize("title", ["Overview", "Synopsis", "Outline"])
async def test_generic_document_titles_cannot_exclude_a_relevant_table(tmp_path, title):
    label = title.upper() + "_2041"
    config, scope, captured = await _capture(
        tmp_path,
        {
            label: [f"{title}\nInventories are discussed elsewhere. No category balances are provided here."] * 30,
            "record-table": ["Inventories by category\nRaw materials 721\nWork in process 82\nFinished goods 931"],
        },
    )
    found = await _locations(
        config,
        scope,
        captured,
        f"Give an {title.lower()} of inventories by category, including raw materials and finished goods.",
        5,
    )
    assert ("record-table", 1) in found


@pytest.mark.parametrize("note_label", ["MARIGOLD_BASIN_2042_10K", "opaque-record-z81"])
async def test_source_less_notes_do_not_control_pdf_document_selection(tmp_path, note_label):
    config, scope, captured = await _capture(
        tmp_path,
        {
            "opaque-record-z81": [
                "Marigold Basin\nInventories by category\nRaw materials 753\nFinished goods 489\n2042"
            ],
        },
    )
    question = "Show Marigold Basin inventories by category."
    assert await _locations(config, scope, captured, question, 5) == [("opaque-record-z81", 1)]
    async with open_builtin_runtime(config) as runtime:
        await runtime.memory.for_scope(scope).remember(
            RememberMemoryRequest(
                entries=(
                    MemoryEntryInput(
                        kind="note",
                        text=f"{note_label}\nMarigold Basin inventories by category. Consult the original report.",
                    ),
                )
            )
        )
    # Reopen after the mixed-source write; only the captured PDF may be cited.
    assert await _locations(config, scope, captured, question, 5) == [("opaque-record-z81", 1)]


@pytest.mark.parametrize("verb", ["Find", "Show", "Provide"])
async def test_request_verbs_do_not_make_a_third_party_report_exclusive(tmp_path, verb):
    texts = ["Acacia Peak\nAnnual report 2041\nOperating policies and financial information."] * 30
    texts[12] = (
        "Consolidated Statement of Income\nAcacia Peak\n2041 2040\nRevenue 5200 4900\n"
        "Operating profit 2800 2600\nNet income 1800 1700"
    )
    config, scope, captured = await _capture(
        tmp_path,
        {
            "ACACIA_PEAK_2041_10K": texts,
            "COBALT_SHORE_2041_10K": [
                f"Cobalt Shore\nWe {verb.lower()} information about suppliers such as Acacia Peak.\n"
                "See the consolidated income statement and financial reporting policies for 2041."
            ]
            * 30,
        },
    )
    found = await _locations(config, scope, captured, f"{verb} Acacia Peak consolidated income statement for 2041.", 20)
    assert ("ACACIA_PEAK_2041_10K", 13) in found
