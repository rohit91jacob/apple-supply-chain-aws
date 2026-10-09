"""UN Comtrade public preview API (keyless): annual HS trade for phones and computers.

Endpoint: ``https://comtradeapi.un.org/public/v1/preview/C/A/HS``. The preview tier is
free and needs no key, but returns at most 500 records per call and accepts **one period
per call**, so the extractor issues one request per year and dataset. Requests are spaced
(see ``http.HttpClient``) to respect the fair-usage policy.

Two datasets:

* ``exports`` - each selected reporter's exports to the World (partner 0).
* ``us_imports`` - US imports from each selected partner (mirror view; it covers years in
  which an exporter, e.g. Viet Nam, has not yet reported).

Comtrade data are (c) United Nations and may not be re-disseminated as-is beyond limited
amounts (see DATA_LICENSE.md): raw responses stay in the (private) raw bucket and only
derived aggregates are published on the results site.
"""

from __future__ import annotations

import json

from apple_supply_chain.countries import by_comtrade_code
from apple_supply_chain.fetch import Fetcher

PREVIEW_URL = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"
MAX_RECORDS = 500

HS_LABELS = {
    "8517": "Telephone sets incl. smartphones; other voice/data transmission apparatus",
    "8471": "Automatic data-processing machines (computers)",
    "851712": "Telephones for cellular networks (HS 2007-2017)",
    "851713": "Smartphones (HS 2022)",
    "851714": "Other telephones for cellular networks (HS 2022)",
}


def request_params(
    dataset: str, year: int, reporters: tuple[str, ...], commodities: tuple[str, ...]
) -> dict:
    base = {
        "period": str(year),
        "cmdCode": ",".join(commodities),
        "includeDesc": "true",
    }
    if dataset == "exports":
        return {**base, "reporterCode": ",".join(reporters), "partnerCode": "0", "flowCode": "X"}
    if dataset == "us_imports":
        partners = [r for r in reporters if r != "842"]
        return {**base, "reporterCode": "842", "partnerCode": ",".join(partners), "flowCode": "M"}
    raise ValueError(f"unknown Comtrade dataset {dataset!r}")


def fetch(fetcher: Fetcher, params: dict) -> bytes:
    return fetcher.get(PREVIEW_URL, params=params)


VOLATILE_FIELDS = ("elapsedTime",)


def canonical(payload: bytes) -> bytes:
    """Drop per-request fields (``elapsedTime``) so identical data hashes identically.

    Without this every weekly run would land a "new" raw object for unchanged data.
    """
    doc = json.loads(payload)
    for key in VOLATILE_FIELDS:
        doc.pop(key, None)
    return json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()


class ComtradeError(RuntimeError):
    pass


def parse(payload: bytes, *, dataset: str) -> list[dict]:
    doc = json.loads(payload)
    if doc.get("error"):
        raise ComtradeError(doc["error"])
    data = doc.get("data") or []
    if len(data) >= MAX_RECORDS:
        raise ComtradeError(
            f"preview returned {len(data)} rows (cap {MAX_RECORDS}); split the query"
        )
    rows = []
    for r in data:
        # Keep the plain totals only: no customs-procedure / transport-mode / 2nd-partner split.
        if r.get("customsCode") not in (None, "C00") or r.get("motCode") not in (None, 0):
            continue
        if r.get("partner2Code") not in (None, 0):
            continue
        reporter = by_comtrade_code(r["reporterCode"])
        partner = by_comtrade_code(r["partnerCode"]) if r["partnerCode"] else None
        rows.append(
            {
                "dataset": dataset,
                "year": int(r["refYear"]),
                "flow_code": r["flowCode"],
                "reporter_code": str(r["reporterCode"]),
                "reporter_iso3": reporter.iso3 if reporter else r.get("reporterISO"),
                "reporter_name": reporter.name if reporter else r.get("reporterDesc"),
                "partner_code": str(r["partnerCode"]),
                "partner_iso3": "WLD"
                if r["partnerCode"] == 0
                else (partner.iso3 if partner else r.get("partnerISO")),
                "partner_name": "World"
                if r["partnerCode"] == 0
                else (partner.name if partner else r.get("partnerDesc")),
                "cmd_code": str(r["cmdCode"]),
                "cmd_desc": HS_LABELS.get(str(r["cmdCode"]), r.get("cmdDesc")),
                "classification": r.get("classificationCode"),
                "primary_value_usd": float(r["primaryValue"])
                if r.get("primaryValue") is not None
                else None,
                "net_weight_kg": float(r["netWgt"]) if r.get("netWgt") else None,
                "qty": float(r["qty"]) if r.get("qty") else None,
                "qty_unit": r.get("qtyUnitAbbr"),
                "is_reported": bool(r.get("isReported")),
                "is_aggregate": bool(r.get("isAggregate")),
            }
        )
    return rows
