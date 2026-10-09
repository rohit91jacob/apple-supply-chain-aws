"""End to end on offline fixtures: the Step Functions definition drives every stage.

SEC inputs are real (trimmed); supplier-list PDFs and Comtrade responses are SYNTHETIC.
"""

from __future__ import annotations

import json

import pytest

from apple_supply_chain.cli import main
from apple_supply_chain.config import DEFAULT_TRADE_COMMODITIES, DEFAULT_TRADE_REPORTERS
from apple_supply_chain.fetch import fixture_relpath
from apple_supply_chain.fixtures import comtrade_response
from apple_supply_chain.lakehouse.iceberg import build_catalog
from apple_supply_chain.pipeline import run_pipeline
from apple_supply_chain.report.site import build_site
from apple_supply_chain.sources import comtrade
from apple_supply_chain.warehouse import connect

pytestmark = pytest.mark.e2e

MARTS = [
    "dim_country",
    "fct_working_capital_annual",
    "fct_working_capital_quarterly",
    "mart_country_dependency",
    "mart_revenue_mix",
    "mart_supplier_concentration",
    "mart_supplier_sites_by_country",
    "mart_trade_flow_shifts",
]


def _snapshot(settings) -> dict:
    con = connect(settings)
    try:
        out = {}
        for m in MARTS:
            out[m] = con.execute(f"select * from marts.{m} order by all").fetchall()
        for g in ("graph_edition_metrics", "graph_country_exposure"):
            out[g] = con.execute(f"select * from graph.{g} order by all").fetchall()
        return out
    finally:
        con.close()


def test_pipeline_end_to_end_then_rerun_is_idempotent(fixture_settings, tmp_path):
    first = run_pipeline(fixture_settings, run_id="e2e-1")
    assert first["status"] == "SUCCEEDED", first
    out = first["output"]
    assert out["silver_dq"]["errors"] == 0 and out["gold_dq"]["errors"] == 0
    assert {r["source"] for r in out["extract"]} == {
        "sec_edgar",
        "apple_supplier_list",
        "un_comtrade",
        "us_census",
    }
    census = next(r for r in out["extract"] if r["source"] == "us_census")
    assert census["skipped"].startswith("CENSUS_API_KEY not set")

    snap1 = _snapshot(fixture_settings)
    # Real SEC figures survive the whole chain (US$, Apple FY2025 10-K)
    annual = {r[0]: r for r in snap1["fct_working_capital_annual"]}
    con = connect(fixture_settings)
    fy25 = con.execute(
        "select revenue_usd, cost_of_sales_usd, inventory_usd, manufacturing_purchase_obligations_usd, dio_days "
        "from marts.fct_working_capital_annual where fiscal_year = 2025"
    ).fetchone()
    con.close()
    assert 2025 in annual
    assert fy25[0] == 416_161e6 and fy25[1] == 220_960e6 and fy25[2] == 5_718e6
    assert fy25[3] == 56.2e9
    assert fy25[4] == pytest.approx((5_718 + 7_286) / 2 / 220_960 * 364)

    catalog = build_catalog(fixture_settings)
    snaps_before = len(catalog.load_table("silver.financial_facts").history())

    # ---- rerun: nothing new is downloaded, every output is identical
    second = run_pipeline(fixture_settings, run_id="e2e-2")
    assert second["status"] == "SUCCEEDED"
    for r in second["output"]["extract"]:
        if r["source"] != "us_census":
            assert r["new"] == 0, r
    assert _snapshot(fixture_settings) == snap1
    # Iceberg keeps history: the overwrite adds snapshots (delete + append), rows unchanged
    table = catalog.load_table("silver.financial_facts")
    assert len(table.history()) > snaps_before
    assert table.scan().to_arrow().num_rows == 247

    # ---- results site from the same warehouse
    summary = build_site(fixture_settings, tmp_path / "site")
    assert summary["latest_fiscal_year"] == 2025 and summary["source_mode"] == "fixtures"
    page = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert "SYNTHETIC" in page and "<svg" in page

    # ---- Neptune bulk-load files and run history
    neptune = list(
        (fixture_settings.lake_dir / fixture_settings.curated_bucket / "neptune").rglob("*.csv")
    )
    assert neptune
    history = json.loads((fixture_settings.data_dir / "runs" / "e2e-2.json").read_text())
    assert history["status"] == "SUCCEEDED" and history["history"]


def test_dq_error_stops_pipeline_with_exit_code_3(
    fixture_settings, fixture_tree, tmp_path, monkeypatch
):
    # Copy the fixture tree and corrupt one (synthetic) Comtrade response: a negative value.
    import shutil

    bad = tmp_path / "bad-fixtures"
    shutil.copytree(fixture_tree, bad)
    params = comtrade.request_params(
        "exports", 2023, DEFAULT_TRADE_REPORTERS, DEFAULT_TRADE_COMMODITIES
    )
    path = bad / "http" / fixture_relpath(comtrade.PREVIEW_URL, params)
    doc = json.loads(comtrade_response("exports", 2023))
    doc["data"][0]["primaryValue"] = -1.0
    path.write_text(json.dumps(doc))
    monkeypatch.setenv("ASC_FIXTURES_DIR", str(bad))

    assert main(["pipeline", "--run-id", "e2e-bad"]) == 3
    history = json.loads((fixture_settings.data_dir / "runs" / "e2e-bad.json").read_text())
    assert history["error"] == "DataQualityFailed"
    entered = [h["state"] for h in history["history"] if h["type"] == "StateEntered"]
    assert "BuildMarts" not in entered
    assert main(["dq", "--layer", "silver"]) == 3


def test_cli_stages_individually(fixture_settings):
    assert main(["extract", "--source", "sec_edgar"]) == 0
    assert main(["extract", "--source", "apple_supplier_list", "--source", "un_comtrade"]) == 0
    assert main(["silver"]) == 0
    assert main(["dq", "--layer", "silver"]) == 0
    assert main(["marts"]) == 0
    # dbt ran in-process; its DuckDB handle must be released, or (on Windows) reading the
    # file - which is how the warehouse is copied to S3 between Lambdas - is refused.
    assert fixture_settings.duckdb_path.read_bytes()[:4]
    assert main(["graph"]) == 0
    assert main(["dq", "--layer", "gold"]) == 0
    assert main(["sql", "select count(*) from marts.mart_revenue_mix"]) == 0
