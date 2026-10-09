"""Live checks against the real public sources (network). Run with ``pytest -m live``."""

from __future__ import annotations

import json

import pytest

from apple_supply_chain.config import DEFAULT_SEC_USER_AGENT
from apple_supply_chain.extract import PORTFOLIO_UA
from apple_supply_chain.fetch import LiveFetcher
from apple_supply_chain.http import HttpClient
from apple_supply_chain.sources import comtrade, edgar, supplier_list

pytestmark = pytest.mark.live


def test_sec_companyfacts_live():
    doc = json.loads(
        LiveFetcher(HttpClient(user_agent=DEFAULT_SEC_USER_AGENT)).get(edgar.COMPANYFACTS_URL)
    )
    rows = edgar.latest_facts(edgar.parse_companyfacts(doc))
    assert any(r["metric"] == "inventory" for r in rows)


def test_comtrade_preview_live_one_year():
    params = comtrade.request_params("exports", 2023, ("156", "699"), ("8517",))
    rows = comtrade.parse(
        comtrade.fetch(LiveFetcher(HttpClient(user_agent=PORTFOLIO_UA)), params), dataset="exports"
    )
    assert {r["reporter_iso3"] for r in rows} == {"CHN", "IND"}


def test_current_supplier_list_live():
    ed = supplier_list.EDITIONS[-1]
    pdf = LiveFetcher(HttpClient(user_agent=PORTFOLIO_UA)).get(ed.url)
    rows = supplier_list.parse_pdf(pdf, ed)
    assert 150 <= len({r["supplier_key"] for r in rows}) <= 250
