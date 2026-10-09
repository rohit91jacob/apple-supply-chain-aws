"""Extractors: download a source and land it, unchanged, in the raw bucket.

Each function is what one Lambda function runs (see ``lambdas.handlers``). They are
idempotent: content-addressed landing means a retry or re-run writes nothing new unless the
upstream bytes changed, and immutable documents (filed 10-Ks, archived PDF snapshots) are
not downloaded again once landed.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field

from apple_supply_chain import raw
from apple_supply_chain.config import Settings
from apple_supply_chain.fetch import Fetcher, build_fetcher
from apple_supply_chain.http import FetchError
from apple_supply_chain.logs import get_logger
from apple_supply_chain.sources import census, comtrade, edgar, supplier_list
from apple_supply_chain.storage import ObjectStore, build_store

log = get_logger(__name__)

PORTFOLIO_UA = (
    "apple-supply-chain-aws/0.1 (+https://github.com/rohit91jacob/apple-supply-chain-aws)"
)


@dataclass
class ExtractSummary:
    source: str
    counts: Counter = field(default_factory=Counter)
    skipped_reason: str = ""

    def add(self, status: str) -> None:
        self.counts[status] += 1

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "new": self.counts.get("new", 0),
            "unchanged": self.counts.get("unchanged", 0),
            "cached": self.counts.get("cached", 0),
            "skipped": self.skipped_reason or None,
        }


def _pointer_exists(store: ObjectStore, bucket: str, source: str, dataset: str, item: str) -> bool:
    return store.exists(bucket, f"source={source}/dataset={dataset}/item={item}/_latest.json")


# --------------------------------------------------------------------------- EDGAR
def extract_edgar(settings: Settings, store: ObjectStore, fetcher: Fetcher) -> dict:
    s = ExtractSummary("sec_edgar")
    bucket = settings.raw_bucket

    payload = fetcher.get(edgar.COMPANYFACTS_URL)
    json.loads(payload)  # fail fast on an HTML error page served with 200
    s.add(
        raw.land(
            store,
            bucket,
            source="sec_edgar",
            dataset="companyfacts",
            item="aapl",
            payload=payload,
            ext="json",
            source_url=edgar.COMPANYFACTS_URL,
            content_type="application/json",
        ).status
    )

    sub_bytes = fetcher.get(edgar.SUBMISSIONS_URL)
    submissions = json.loads(sub_bytes)
    s.add(
        raw.land(
            store,
            bucket,
            source="sec_edgar",
            dataset="submissions",
            item="aapl",
            payload=sub_bytes,
            ext="json",
            source_url=edgar.SUBMISSIONS_URL,
            content_type="application/json",
        ).status
    )
    older = []
    for page in submissions["filings"].get("files", []):
        url = f"https://data.sec.gov/submissions/{page['name']}"
        older.append(json.loads(fetcher.get(url)))

    filings = [
        f
        for f in edgar.ten_k_filings(submissions, older)
        if int(f["period_end"][:4]) >= settings.first_fiscal_year
    ]
    s.add(
        raw.land(
            store,
            bucket,
            source="sec_edgar",
            dataset="ten_k_index",
            item="aapl",
            payload=json.dumps(filings, indent=2).encode(),
            ext="json",
            source_url=edgar.SUBMISSIONS_URL,
            content_type="application/json",
        ).status
    )

    for filing in filings:
        acc = filing["accession"]
        have_instance = _pointer_exists(store, bucket, "sec_edgar", "ten_k_instance", acc)
        have_primary = _pointer_exists(store, bucket, "sec_edgar", "ten_k_document", acc)
        if have_instance and have_primary:
            s.add("cached")  # filed documents are immutable; never re-download
            continue
        docs = edgar.fetch_filing_documents(fetcher, filing)
        folder = edgar.filing_folder(acc)
        if "instance" in docs:
            s.add(
                raw.land(
                    store,
                    bucket,
                    source="sec_edgar",
                    dataset="ten_k_instance",
                    item=acc,
                    payload=docs["instance"],
                    ext="xml",
                    source_url=folder,
                    content_type="application/xml",
                ).status
            )
        s.add(
            raw.land(
                store,
                bucket,
                source="sec_edgar",
                dataset="ten_k_document",
                item=acc,
                payload=docs["primary"],
                ext="htm",
                source_url=f"{folder}/{filing['primary_document']}",
                content_type="text/html",
            ).status
        )
    return s.as_dict()


# ------------------------------------------------------------------ supplier list
def extract_supplier_list(settings: Settings, store: ObjectStore, fetcher: Fetcher) -> dict:
    s = ExtractSummary("apple_supplier_list")
    bucket = settings.raw_bucket
    for ed in supplier_list.EDITIONS:
        item = str(ed.edition)
        archived = "web.archive.org" in ed.url
        if archived and _pointer_exists(store, bucket, "apple_supplier_list", "pdf", item):
            s.add("cached")  # Wayback snapshots are immutable
            continue
        payload = fetcher.get(ed.url)
        if not payload.startswith(b"%PDF"):
            raise FetchError(f"{ed.url} did not return a PDF")
        s.add(
            raw.land(
                store,
                bucket,
                source="apple_supplier_list",
                dataset="pdf",
                item=item,
                payload=payload,
                ext="pdf",
                source_url=ed.url,
                content_type="application/pdf",
            ).status
        )
    return s.as_dict()


# ------------------------------------------------------------------------ Comtrade
def extract_comtrade(settings: Settings, store: ObjectStore, fetcher: Fetcher) -> dict:
    s = ExtractSummary("un_comtrade")
    for dataset in ("exports", "us_imports"):
        for year in settings.trade_years:
            params = comtrade.request_params(
                dataset, year, settings.trade_reporters, settings.trade_commodities
            )
            payload = comtrade.canonical(comtrade.fetch(fetcher, params))
            comtrade.parse(payload, dataset=dataset)  # validate before landing
            url = (
                comtrade.PREVIEW_URL + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
            )
            s.add(
                raw.land(
                    store,
                    settings.raw_bucket,
                    source="un_comtrade",
                    dataset=dataset,
                    item=str(year),
                    payload=payload,
                    ext="json",
                    source_url=url,
                    content_type="application/json",
                ).status
            )
    return s.as_dict()


# -------------------------------------------------------------------------- Census
def extract_census(settings: Settings, store: ObjectStore, fetcher: Fetcher) -> dict:
    s = ExtractSummary("us_census")
    if not settings.census_api_key:
        s.skipped_reason = "CENSUS_API_KEY not set (optional source)"
        return s.as_dict()
    hs4_codes = sorted({c[:4] for c in settings.trade_commodities})
    for year in settings.trade_years:
        for hs4 in hs4_codes:
            params = census.request_params(year, hs4, settings.census_api_key)
            payload = census.fetch(fetcher, params)
            census.parse(payload, year=year, hs4=hs4)
            # never persist the API key: the recorded URL omits it
            url = f"{census.IMPORTS_URL}?time={year}-12&I_COMMODITY={hs4}"
            s.add(
                raw.land(
                    store,
                    settings.raw_bucket,
                    source="us_census",
                    dataset="imports_hs",
                    item=f"{year}-{hs4}",
                    payload=payload,
                    ext="json",
                    source_url=url,
                    content_type="application/json",
                ).status
            )
    return s.as_dict()


EXTRACTORS = {
    "sec_edgar": (extract_edgar, None),
    "apple_supplier_list": (extract_supplier_list, PORTFOLIO_UA),
    "un_comtrade": (extract_comtrade, PORTFOLIO_UA),
    "us_census": (extract_census, PORTFOLIO_UA),
}


def run_extractor(name: str, settings: Settings) -> dict:
    func, ua = EXTRACTORS[name]
    store = build_store(settings)
    fetcher = build_fetcher(settings, user_agent=ua)
    result = func(settings, store, fetcher)
    log.info("extract %s: %s", name, result)
    return result
