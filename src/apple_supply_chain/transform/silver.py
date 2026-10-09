"""Raw -> silver: parse landed objects into typed Iceberg tables (namespace ``silver``).

Every table is rebuilt from the current raw pointers on each run (deterministic), and each
row keeps the sha256 of the raw object it came from for lineage.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import pyarrow as pa

from apple_supply_chain import raw
from apple_supply_chain.config import Settings
from apple_supply_chain.countries import countries
from apple_supply_chain.lakehouse.iceberg import build_catalog, ns, write_table
from apple_supply_chain.logs import get_logger
from apple_supply_chain.sources import census, comtrade, edgar, supplier_list
from apple_supply_chain.storage import ObjectStore, build_store

log = get_logger(__name__)

S, F, INT, B, D = pa.string(), pa.float64(), pa.int64(), pa.bool_(), pa.date32()

SCHEMAS: dict[str, pa.Schema] = {
    "financial_facts": pa.schema(
        [
            ("metric", S),
            ("concept", S),
            ("unit", S),
            ("period_start", D),
            ("period_end", D),
            ("duration_days", INT),
            ("value", F),
            ("filing_fy", INT),
            ("filing_fp", S),
            ("form", S),
            ("filed", D),
            ("accession", S),
            ("frame", S),
            ("source_sha256", S),
        ]
    ),
    "segment_revenue": pa.schema(
        [
            ("fiscal_year", INT),
            ("period_start", D),
            ("period_end", D),
            ("breakdown", S),
            ("member", S),
            ("member_label", S),
            ("is_rollup", B),
            ("concept", S),
            ("value", F),
            ("accession", S),
            ("filed", D),
            ("source_sha256", S),
        ]
    ),
    "purchase_obligations": pa.schema(
        [
            ("fiscal_year", INT),
            ("as_of", D),
            ("kind", S),
            ("amount_usd", F),
            ("payable_within_12m_usd", F),
            ("snippet", S),
            ("accession", S),
            ("filed", D),
            ("source_sha256", S),
        ]
    ),
    "supplier_sites": pa.schema(
        [
            ("edition", INT),
            ("spend_year", S),
            ("fiscal_year", INT),
            ("layout", S),
            ("row_number", INT),
            ("supplier_name", S),
            ("location", S),
            ("country_raw", S),
            ("site_type", S),
            ("site_count", INT),
            ("supplier_key", S),
            ("country_iso3", S),
            ("country_name", S),
            ("region", S),
            ("source_sha256", S),
        ]
    ),
    "trade_flows": pa.schema(
        [
            ("dataset", S),
            ("year", INT),
            ("flow_code", S),
            ("reporter_code", S),
            ("reporter_iso3", S),
            ("reporter_name", S),
            ("partner_code", S),
            ("partner_iso3", S),
            ("partner_name", S),
            ("cmd_code", S),
            ("cmd_desc", S),
            ("classification", S),
            ("primary_value_usd", F),
            ("net_weight_kg", F),
            ("qty", F),
            ("qty_unit", S),
            ("is_reported", B),
            ("is_aggregate", B),
            ("source_sha256", S),
        ]
    ),
    "census_imports": pa.schema(
        [
            ("year", INT),
            ("hs4", S),
            ("census_cty_code", S),
            ("country_name_raw", S),
            ("partner_iso3", S),
            ("general_imports_usd", F),
            ("source_sha256", S),
        ]
    ),
    "ref_country": pa.schema([("iso3", S), ("name", S), ("comtrade_code", S), ("region", S)]),
    "raw_manifest": pa.schema(
        [
            ("source", S),
            ("dataset", S),
            ("item", S),
            ("sha256", S),
            ("key", S),
            ("bytes", INT),
            ("source_url", S),
            ("fetched_at", S),
        ]
    ),
}


def _to_table(name: str, rows: list[dict]) -> pa.Table:
    schema = SCHEMAS[name]
    cols = {f.name: [r.get(f.name) for r in rows] for f in schema}
    for f in schema:
        if f.type == D:
            cols[f.name] = [_date(v) for v in cols[f.name]]
    return pa.table(cols, schema=schema)


def _date(v):
    import datetime as dt  # noqa: PLC0415

    if v is None or isinstance(v, dt.date):
        return v
    return dt.date.fromisoformat(str(v)[:10])


# ----------------------------------------------------------------------- builders
def _financial_facts(store: ObjectStore, bucket: str) -> list[dict]:
    rows: list[dict] = []
    for ptr in raw.latest(store, bucket, "sec_edgar", "companyfacts"):
        doc = json.loads(raw.read_latest(store, bucket, ptr))
        for r in edgar.latest_facts(edgar.parse_companyfacts(doc)):
            rows.append({**r, "source_sha256": ptr["sha256"]})
    return rows


def _filings(store: ObjectStore, bucket: str) -> dict[str, dict]:
    ptrs = raw.latest(store, bucket, "sec_edgar", "ten_k_index")
    if not ptrs:
        return {}
    return {f["accession"]: f for f in json.loads(raw.read_latest(store, bucket, ptrs[0]))}


def _segment_revenue(store: ObjectStore, bucket: str) -> list[dict]:
    filings = _filings(store, bucket)
    rows: list[dict] = []
    for ptr in raw.latest(store, bucket, "sec_edgar", "ten_k_instance"):
        filing = filings.get(ptr["item"])
        if filing is None:
            continue
        parsed = edgar.parse_instance(
            raw.read_latest(store, bucket, ptr),
            accession=filing["accession"],
            filed=filing["filed"],
        )
        rows.extend({**r, "source_sha256": ptr["sha256"]} for r in parsed)
    return edgar.latest_segment_revenue(rows)


def _purchase_obligations(store: ObjectStore, bucket: str) -> list[dict]:
    filings = _filings(store, bucket)
    rows: list[dict] = []
    for ptr in raw.latest(store, bucket, "sec_edgar", "ten_k_document"):
        filing = filings.get(ptr["item"])
        if filing is None:
            continue
        parsed = edgar.parse_purchase_obligations(
            raw.read_latest(store, bucket, ptr), filing=filing
        )
        rows.extend({**r, "source_sha256": ptr["sha256"]} for r in parsed)
    return rows


def _supplier_sites(store: ObjectStore, bucket: str) -> list[dict]:
    editions = {str(e.edition): e for e in supplier_list.EDITIONS}
    rows: list[dict] = []
    for ptr in raw.latest(store, bucket, "apple_supplier_list", "pdf"):
        ed = editions.get(ptr["item"])
        if ed is None:
            continue
        parsed = supplier_list.parse_pdf(raw.read_latest(store, bucket, ptr), ed)
        rows.extend({**r, "source_sha256": ptr["sha256"]} for r in parsed)
    return rows


def _trade_flows(store: ObjectStore, bucket: str) -> list[dict]:
    rows: list[dict] = []
    for dataset in ("exports", "us_imports"):
        for ptr in raw.latest(store, bucket, "un_comtrade", dataset):
            parsed = comtrade.parse(raw.read_latest(store, bucket, ptr), dataset=dataset)
            rows.extend({**r, "source_sha256": ptr["sha256"]} for r in parsed)
    return rows


def _census(store: ObjectStore, bucket: str) -> list[dict]:
    rows: list[dict] = []
    for ptr in raw.latest(store, bucket, "us_census", "imports_hs"):
        year, hs4 = ptr["item"].split("-", 1)
        parsed = census.parse(raw.read_latest(store, bucket, ptr), year=int(year), hs4=hs4)
        rows.extend({**r, "source_sha256": ptr["sha256"]} for r in parsed)
    return rows


def _ref_country(_store: ObjectStore, _bucket: str) -> list[dict]:
    return [c.__dict__ for c in countries()]


def _manifest(store: ObjectStore, bucket: str) -> list[dict]:
    out = []
    for key in store.list_keys(bucket):
        if key.endswith("/_latest.json"):
            out.append(json.loads(store.get_bytes(bucket, key)))
    return sorted(out, key=lambda r: (r["source"], r["dataset"], r["item"]))


BUILDERS: dict[str, Callable[[ObjectStore, str], list[dict]]] = {
    "financial_facts": _financial_facts,
    "segment_revenue": _segment_revenue,
    "purchase_obligations": _purchase_obligations,
    "supplier_sites": _supplier_sites,
    "trade_flows": _trade_flows,
    "census_imports": _census,
    "ref_country": _ref_country,
    "raw_manifest": _manifest,
}


def build_silver_tables(
    settings: Settings, store: ObjectStore | None = None
) -> dict[str, pa.Table]:
    store = store or build_store(settings)
    return {name: _to_table(name, fn(store, settings.raw_bucket)) for name, fn in BUILDERS.items()}


def build_silver(settings: Settings, *, run_id: str = "") -> list[dict]:
    tables = build_silver_tables(settings)
    catalog = build_catalog(settings)
    results = []
    for name, table in tables.items():
        info = write_table(catalog, f"{ns(settings, 'silver')}.{name}", table, run_id=run_id)
        log.info("silver.%s: %d rows (snapshot %s)", name, info["rows"], info["snapshot_id"])
        results.append(info)
    return results
