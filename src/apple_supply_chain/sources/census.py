"""US Census Bureau international trade API (optional, key-gated).

``api.census.gov/data/timeseries/intltrade/imports/hs`` now redirects keyless requests to a
"missing key" page, so this source only runs when ``CENSUS_API_KEY`` is set; otherwise the
extractor reports ``skipped``. It adds US general imports by country for the same HS codes,
as an independent cross-check of the Comtrade US-import mirror. US Government works are in
the public domain.
"""

from __future__ import annotations

import json

from apple_supply_chain.countries import resolve
from apple_supply_chain.fetch import Fetcher

IMPORTS_URL = "https://api.census.gov/data/timeseries/intltrade/imports/hs"


def request_params(year: int, hs4: str, api_key: str) -> dict:
    return {
        "get": "CTY_CODE,CTY_NAME,GEN_VAL_YR",
        "time": f"{year}-12",  # December year-to-date value = calendar-year total
        "I_COMMODITY": hs4,
        "COMM_LVL": "HS4",
        "key": api_key,
    }


def fetch(fetcher: Fetcher, params: dict) -> bytes:
    return fetcher.get(IMPORTS_URL, params=params)


def parse(payload: bytes, *, year: int, hs4: str) -> list[dict]:
    table = json.loads(payload)
    if not table:
        return []
    header, *body = table
    idx = {name: i for i, name in enumerate(header)}
    rows = []
    for rec in body:
        code = rec[idx["CTY_CODE"]]
        # Census country codes are 4 digits; aggregates (regions, "TOTAL FOR ALL COUNTRIES")
        # start with 0 or are letters.
        if not code.isdigit() or code.startswith("0"):
            continue
        country = resolve(rec[idx["CTY_NAME"]].title())
        rows.append(
            {
                "year": year,
                "hs4": hs4,
                "census_cty_code": code,
                "country_name_raw": rec[idx["CTY_NAME"]],
                "partner_iso3": country.iso3 if country else None,
                "general_imports_usd": float(rec[idx["GEN_VAL_YR"]]),
            }
        )
    return rows
