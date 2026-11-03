# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

"""Financial metric names must retrieve their underlying statements and notes."""

import pytest

from tests.e2e.test_pdf_locations_and_headings import _capture, _locations


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("metric", ["turnover", "liquidity", "intensity", "margin", "borrowings"])
async def test_financial_components_survive_repeated_question_wording(tmp_path, metric, reverse):
    issuer, year = ("AZURE", 2036) if reverse else ("TOPAZ", 2041)
    balance = (
        f"CONSOLIDATED BALANCE SHEETS\n{year} {year - 1}\nCurrent assets\n"
        "Cash and equivalents 250 210\nAccounts receivable 140 120\nInventories 80 70\n"
        "Current liabilities 160 150\nProperty plant and equipment 900 870\nTotal assets 1400 1300"
    )
    earnings = (
        f"CONSOLIDATED STATEMENTS OF EARNINGS\n{year} {year - 1}\n"
        "Sales 2400 2200\nCost of products sold 1200 1100\nGross profit 1200 1100\nNet earnings 350 320"
    )
    cost_note = (
        "Cost of Goods Sold and Selling, Marketing and Administrative Expenses:\n"
        f"{year} {year - 1}\nCost of goods sold as a percentage of sales increased.\n"
        "Higher input prices and freight expenses reduced profitability.\nProducts sold 50 46"
    )
    debt_note = (
        f"Note 12. Borrowings\nAt December 31 {year} {year - 1}\n"
        "Long term obligations 400 350\nCurrent loans 50 40\nFloating rate notes 100 90"
    )
    questions = {
        "turnover": ("What is the inventory turnover ratio", [balance, earnings]),
        "liquidity": ("Is the quick ratio reasonably healthy", [balance]),
        "intensity": ("Is the business capital intensive", [balance]),
        "margin": ("What drove the gross margin change", [cost_note]),
        "borrowings": ("Did outstanding debt increase", [debt_note]),
    }
    wording, evidence = questions[metric]
    question = f"{wording} for {issuer} in {year}? If the metric is not relevant, explain why."
    narrative = (
        "Management discussion\n"
        f"{wording} for {issuer} in {year} is a useful question for a company. "
        "The metric is relevant to management and is discussed throughout the annual report. "
    ) * 5
    texts = [narrative for _ in range(35)]
    texts[9:9] = evidence
    if reverse:
        texts.reverse()
    name = f"{issuer}_{year}_ANNUAL"
    targets = {(name, index + 1) for index, text in enumerate(texts) if text in evidence}
    config, scope, captured = await _capture(tmp_path, {name: texts})
    found = await _locations(config, scope, captured, question, 20)
    assert targets <= set(found)


@pytest.mark.parametrize("separator", [" ", "-", "\u2011"])
async def test_capital_intensity_covers_stock_and_flow_components(tmp_path, separator):
    question = f"Is River a capital{separator}intensive business in 2029?"
    narrative = (
        "Business discussion\n"
        + (question.replace("\u2011", "-") + " Management reviews this question each year. ") * 12
    )
    texts = [narrative] * 35
    texts[7] = "Consolidated Statements of Income\n2029 2028\nRevenue 950 900\nCost of sales 430 400"
    texts[15] = "Consolidated Balance Sheets\n2029 2028\nProperty plant and equipment 600 550\nTotal assets 1000 950"
    texts[29] = "Consolidated Statements of Cash Flows\n2029 2028\nCapital expenditures 170 150\nOperating cash 240 210"
    config, scope, captured = await _capture(tmp_path, {"RIVER_2029": texts})
    found = await _locations(config, scope, captured, question, 20)
    assert {("RIVER_2029", 8), ("RIVER_2029", 16), ("RIVER_2029", 30)} <= set(found)


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("topic", ["cashflow", "categories", "clients", "cyclicality"])
async def test_business_concepts_match_underlying_disclosures(tmp_path, topic, reverse):
    questions = {
        "cashflow": "Is free cashflow conversion improving",
        "categories": "Which service categories account for a material share of revenue",
        "clients": "Who are the primary clients",
        "cyclicality": "Is the business subject to cyclicality",
    }
    disclosures = {
        "cashflow": "Consolidated Statements of Cash Flows\n2033 2032\nOperating cash 100 90\nCapital spending 30 25",
        "categories": "Summary of Reportable Segment Information\nRevenues:\nServices 250\nProducts 120\nTotal 370",
        "clients": "Risks Related to Our Contracts\nOur counterparties include institutional buyers. Contract renewals are negotiated annually.",
        "cyclicality": "Market outlook\nDemand for our products is cyclical and sensitive to economic conditions.",
    }
    issuer = "LUMEN" if reverse else "MARIGOLD"
    question = f"{questions[topic]} for {issuer} in 2033?"
    repeated = "Analyst discussion\n" + (question + " This is a useful question for management to explain. ") * 12
    texts = [repeated] * 35
    texts[12] = disclosures[topic]
    if reverse:
        texts.reverse()
    name = f"{issuer}_2033"
    target = (name, texts.index(disclosures[topic]) + 1)
    config, scope, captured = await _capture(tmp_path, {name: texts})
    assert target in await _locations(config, scope, captured, question, 20)
