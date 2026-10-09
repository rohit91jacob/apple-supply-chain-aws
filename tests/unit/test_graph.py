"""Supplier network metrics on a hand-built graph with known answers."""

from __future__ import annotations

import csv
import io

import pytest

from apple_supply_chain.graph.network import (
    analyse,
    build_graph,
    disruption,
    edition_metrics,
    hhi,
    neptune_csv,
)


def _pair(s, c, sites=1, ed=2024):
    return {
        "edition": ed,
        "fiscal_year": ed - 1,
        "layout": "locations",
        "supplier_key": s,
        "supplier_name": s.title(),
        "country_iso3": c,
        "country_name": c,
        "region": "x",
        "sites": sites,
    }


PAIRS = [
    _pair("a", "CHN", 3),
    _pair("a", "VNM", 1),
    _pair("b", "CHN", 2),
    _pair("c", "TWN", 1),
    _pair("c", "CHN", 1),
    _pair("d", "JPN", 2),
]


def test_hhi_bounds():
    assert hhi([1.0]) == 1.0
    assert hhi([0.25] * 4) == pytest.approx(0.25)


def test_edition_metrics_known_values():
    m = edition_metrics(build_graph(PAIRS))
    # pairs per country: CHN 3, VNM 1, TWN 1, JPN 1 of 6
    assert m["hhi_pairs"] == pytest.approx((3 / 6) ** 2 + 3 * (1 / 6) ** 2)
    # sites: CHN 6, VNM 1, TWN 1, JPN 2 of 10
    assert m["hhi_sites"] == pytest.approx(0.36 + 0.01 + 0.01 + 0.04)
    assert m["single_country_suppliers"] == 2  # b (CHN), d (JPN)
    assert m["top_country_iso3"] == "CHN"


def test_disruption_china():
    d = disruption(build_graph(PAIRS), ["CHN"])
    assert d["site_share_exposed"] == pytest.approx(0.6)
    assert d["suppliers_affected"] == 3
    assert d["suppliers_fully_disrupted"] == 1  # only b has no other country
    assert d["suppliers_with_alternative"] == 2


def test_disruption_combined_and_unknown_country():
    g = build_graph(PAIRS)
    assert disruption(g, ["CHN", "TWN"])["suppliers_fully_disrupted"] == 2
    assert disruption(g, ["ZZZ"])["suppliers_affected"] == 0


def test_neptune_csv_shape():
    vertices, edges = neptune_csv(build_graph(PAIRS), 2024)
    v = list(csv.DictReader(io.StringIO(vertices)))
    e = list(csv.DictReader(io.StringIO(edges)))
    assert len(v) == 4 + 4 and len(e) == 6
    assert all(
        row["~from"].startswith("supplier:") and row["~to"].startswith("country:") for row in e
    )


def test_analyse_tables_per_edition():
    pairs = [*PAIRS, _pair("a", "CHN", 1, ed=2023)]
    t = analyse(pairs)
    assert t["graph_edition_metrics"].num_rows == 2
    assert set(t["graph_country_exposure"].column("scenario").to_pylist()) >= {
        "CHN",
        "China mainland + Taiwan",
    }
