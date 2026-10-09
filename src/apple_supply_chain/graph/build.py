"""Graph stage: read supplier-country pairs from the warehouse, analyse, publish."""

from __future__ import annotations

from apple_supply_chain.config import Settings
from apple_supply_chain.graph.network import analyse, build_graph, neptune_csv
from apple_supply_chain.lakehouse.iceberg import build_catalog, ns, write_table
from apple_supply_chain.logs import get_logger
from apple_supply_chain.storage import build_store
from apple_supply_chain.warehouse import connect

log = get_logger(__name__)

GRAPH_SCHEMA = "graph"


def load_pairs(settings: Settings) -> list[dict]:
    con = connect(settings)
    try:
        cur = con.execute(
            "select edition, fiscal_year, layout, supplier_key, supplier_name, country_iso3, "
            "country_name, region, sites from intermediate.int_supplier_country_pairs "
            "order by edition, supplier_key, country_iso3"
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
    finally:
        con.close()


def build_graph_outputs(settings: Settings, *, run_id: str = "") -> dict:
    pairs = load_pairs(settings)
    tables = analyse(pairs)
    con = connect(settings)
    try:
        con.execute(f"create schema if not exists {GRAPH_SCHEMA}")
        for name, table in tables.items():
            con.register("graph_tmp", table)
            con.execute(f"create or replace table {GRAPH_SCHEMA}.{name} as select * from graph_tmp")
            con.unregister("graph_tmp")
    finally:
        con.close()
    catalog = build_catalog(settings)
    for name, table in tables.items():
        write_table(catalog, f"{ns(settings, 'gold')}.{name}", table, run_id=run_id)

    # Neptune bulk-load files for every edition (cloud mapping; see docs/runbook.md).
    store = build_store(settings)
    editions = sorted({p["edition"] for p in pairs})
    for ed in editions:
        g = build_graph([p for p in pairs if p["edition"] == ed])
        vertices, edges = neptune_csv(g, ed)
        store.put_bytes(
            settings.curated_bucket, f"neptune/edition={ed}/vertices.csv", vertices.encode()
        )
        store.put_bytes(settings.curated_bucket, f"neptune/edition={ed}/edges.csv", edges.encode())
    result = {name: t.num_rows for name, t in tables.items()}
    log.info("graph outputs: %s (editions %s)", result, editions)
    return {"tables": result, "editions": editions}
