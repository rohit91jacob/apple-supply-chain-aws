"""Config parsing, the verification parser and report helpers."""

from __future__ import annotations

import pytest

from apple_supply_chain.config import ConfigError, Settings
from apple_supply_chain.fixtures import make_pdf
from apple_supply_chain.report.site import _fmt, _nice_step, line_chart
from apple_supply_chain.verify import EXPECTED_ITEMS, _numbers, missing_items, parse_statements


def test_settings_defaults_and_ranges(monkeypatch, tmp_path):
    monkeypatch.setenv("ASC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ASC_TRADE_YEARS", "2019-2021")
    s = Settings.from_env()
    assert s.trade_years == (2019, 2020, 2021)
    assert s.warehouse.endswith("lake/asc-curated/warehouse")
    monkeypatch.setenv("ASC_TRADE_YEARS", "2020,2022")
    assert Settings.from_env().trade_years == (2020, 2022)


@pytest.mark.parametrize(
    ("var", "value"),
    [
        ("ASC_STORE", "gcs"),
        ("ASC_CATALOG", "hive"),
        ("ASC_SOURCE_MODE", "mock"),
        ("ASC_TRADE_YEARS", "2024-2020"),
    ],
)
def test_settings_reject_invalid(monkeypatch, var, value):
    monkeypatch.setenv(var, value)
    with pytest.raises(ConfigError):
        Settings.from_env()


def test_cli_returns_usage_code_on_bad_config(monkeypatch):
    from apple_supply_chain.cli import main

    monkeypatch.setenv("ASC_STORE", "nope")
    assert main(["dq"]) == 2


def test_numbers_handles_pdf_noise():
    assert _numbers(" $ 94,930 $ 89,498 96 ,169 (1,688) —") == [94930, 89498, 96169, -1688, 0]


def test_parse_statements_on_a_synthetic_statement():
    # SYNTHETIC statement in the layout of Apple's Q4 condensed statements (values invented)
    p1 = [
        "Net sales:",
        "Products $ 10 $ 9 $ 100 $ 90",
        "Total net sales (1) 12 11 120 110",
        "Cost of sales:",
        "Total cost of sales 6 5 60 55",
        "Gross margin 6 6 60 55",
        "(1) Net sales by reportable segment:",
        "Americas $ 5 $ 4 $ 50 $ 40",
        "Greater China 2 2 20 22",
        "(1) Net sales by category:",
        "iPhone $ 7 $ 6 $ 70 $ 65",
        "Services 3 3 30 28",
    ]
    p2 = ["Inventories 7 8", "Accounts payable $ 70 $ 68"]
    p3 = ["Inventories 1 (2)", "Payments for acquisition of property, plant and equipment (12) (9)"]
    pdf = make_pdf(
        [
            [("text", 20, 20 + 14 * i, 9, line) for i, line in enumerate(page)]
            for page in (p1, p2, p3)
        ]
    )
    got = parse_statements(pdf, 2025)
    assert got[(2025, "net_sales")] == 120 and got[(2024, "net_sales")] == 110
    assert got[(2025, "cost_of_sales")] == 60
    assert got[(2025, "segment:Greater China")] == 20
    assert got[(2024, "category:iPhone")] == 65
    assert got[(2025, "inventory")] == 7  # balance sheet, not the cash-flow change
    assert got[(2025, "capex")] == 12
    # Lines the synthetic statement lacks are reported as missing, never silently dropped.
    missing = missing_items(got, 2025)
    assert (2025, "segment:Japan") in missing and (2024, "ppe_net") in missing
    assert (2025, "net_sales") not in missing
    assert len(missing_items({}, 2025)) == 2 * len(EXPECTED_ITEMS) == 38


def test_report_helpers():
    assert _nice_step(23) == 25 and _nice_step(0.04) == 0.05
    assert _fmt(0.1234, "pct") == "12.3%" and _fmt(None) == "-"
    svg = line_chart({"A": [(2020, 1.0), (2021, 2.0)]}, kind="days", y_label="d")
    assert "<title>A · 2021: 2.0</title>" in svg


def test_iceberg_write_is_idempotent_and_survives_schema_change(tmp_path, monkeypatch):
    import pyarrow as pa

    from apple_supply_chain.lakehouse.iceberg import build_catalog, read_table, write_table

    monkeypatch.setenv("ASC_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ASC_STORE", raising=False)
    catalog = build_catalog(Settings.from_env())
    t = pa.table({"x": pa.array([1, 2], pa.int64())})
    first = write_table(catalog, "gold.t", t)
    second = write_table(catalog, "gold.t", t)
    assert read_table(catalog, "gold.t").num_rows == 2
    assert second["snapshots"] > first["snapshots"]
    changed = pa.table({"x": pa.array([1.5], pa.float64()), "y": ["a"]})
    write_table(catalog, "gold.t", changed)
    assert read_table(catalog, "gold.t").column_names == ["x", "y"]
