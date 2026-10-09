"""Supplier network graph: suppliers <-> countries, per Supplier List edition.

The graph is bipartite. Supplier nodes connect to the country nodes where the supplier lists
manufacturing locations; the edge weight is the number of sites (facilities in address
editions, provinces/states in locations editions). Locally it is built with networkx; the
cloud mapping is Amazon Neptune, for which :func:`neptune_csv` writes Gremlin bulk-load files.

Metrics
-------
* HHI (Herfindahl-Hirschman index) over countries, on edges (supplier-country pairs) and on
  weights (sites): sum of squared shares, 0..1 (1 = everything in one country).
* single-country dependency: suppliers whose every listed location is in one country.
* disruption scenario for a country set S:
  - ``site_share_exposed``: share of all sites located in S
  - ``suppliers_affected_share``: suppliers with at least one site in S
  - ``suppliers_fully_disrupted_share``: suppliers with *all* sites in S (no listed
    alternative country; they become isolated when S is removed from the graph)
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable

import networkx as nx
import pyarrow as pa

SCENARIO_COMBOS: dict[str, tuple[str, ...]] = {
    "China mainland + Taiwan": ("CHN", "TWN"),
    "China mainland + Hong Kong": ("CHN", "HKG"),
}
TOP_N_SINGLE_COUNTRY_SCENARIOS = 10


def build_graph(pairs: Iterable[dict]) -> nx.Graph:
    """``pairs`` rows: supplier_key, supplier_name, country_iso3, country_name, region, sites."""
    g = nx.Graph()
    for p in pairs:
        s = f"supplier:{p['supplier_key']}"
        c = f"country:{p['country_iso3']}"
        g.add_node(s, kind="supplier", name=p["supplier_name"])
        g.add_node(
            c, kind="country", name=p["country_name"], iso3=p["country_iso3"], region=p["region"]
        )
        weight = max(int(p["sites"] or 0), 0)
        if g.has_edge(s, c):
            g[s][c]["sites"] += weight
        else:
            g.add_edge(s, c, sites=weight)
    return g


def _nodes(g: nx.Graph, kind: str) -> list[str]:
    return [n for n, d in g.nodes(data=True) if d["kind"] == kind]


def hhi(shares: Iterable[float]) -> float:
    return float(sum(s * s for s in shares))


def edition_metrics(g: nx.Graph) -> dict:
    suppliers = _nodes(g, "supplier")
    countries = _nodes(g, "country")
    n_edges = g.number_of_edges()
    total_sites = sum(d["sites"] for _, _, d in g.edges(data=True))
    deg = {c: g.degree(c) for c in countries}
    wdeg = {c: g.degree(c, weight="sites") for c in countries}
    top = max(countries, key=lambda c: (deg[c], c)) if countries else None
    single = [s for s in suppliers if g.degree(s) == 1]
    return {
        "n_suppliers": len(suppliers),
        "n_countries": len(countries),
        "n_edges": n_edges,
        "n_sites": total_sites,
        "hhi_pairs": hhi(d / n_edges for d in deg.values()) if n_edges else None,
        "hhi_sites": hhi(w / total_sites for w in wdeg.values()) if total_sites else None,
        "top_country_iso3": g.nodes[top]["iso3"] if top else None,
        "single_country_suppliers": len(single),
        "single_country_supplier_share": len(single) / len(suppliers) if suppliers else None,
        "density": nx.bipartite.density(g, suppliers) if suppliers and countries else None,
    }


def disruption(g: nx.Graph, iso3s: Iterable[str]) -> dict:
    targets = {f"country:{i}" for i in iso3s} & set(g.nodes)
    suppliers = _nodes(g, "supplier")
    total_sites = sum(d["sites"] for _, _, d in g.edges(data=True))
    exposed_sites = sum(g[s][c]["sites"] for c in targets for s in g.neighbors(c))
    affected = {s for c in targets for s in g.neighbors(c)}
    remaining = g.copy()
    remaining.remove_nodes_from(targets)
    fully = [s for s in affected if remaining.degree(s) == 0]
    n = len(suppliers)
    return {
        "site_share_exposed": exposed_sites / total_sites if total_sites else 0.0,
        "suppliers_affected": len(affected),
        "suppliers_affected_share": len(affected) / n if n else 0.0,
        "suppliers_fully_disrupted": len(fully),
        "suppliers_fully_disrupted_share": len(fully) / n if n else 0.0,
        "suppliers_with_alternative": len(affected) - len(fully),
    }


def scenarios_for(g: nx.Graph) -> dict[str, tuple[str, ...]]:
    countries = sorted(_nodes(g, "country"), key=lambda c: (-g.degree(c), c))
    out = {
        g.nodes[c]["name"]: (g.nodes[c]["iso3"],)
        for c in countries[:TOP_N_SINGLE_COUNTRY_SCENARIOS]
    }
    out.update(SCENARIO_COMBOS)
    return out


def supplier_dependency(g: nx.Graph) -> list[dict]:
    rows = []
    for s in _nodes(g, "supplier"):
        nbrs = sorted(g.neighbors(s), key=lambda c: (-g[s][c]["sites"], c))
        sites = sum(g[s][c]["sites"] for c in nbrs)
        primary = nbrs[0] if nbrs else None
        rows.append(
            {
                "supplier_key": s.split(":", 1)[1],
                "supplier_name": g.nodes[s]["name"],
                "n_countries": len(nbrs),
                "countries": ",".join(g.nodes[c]["iso3"] for c in nbrs),
                "is_single_country": len(nbrs) == 1,
                "primary_country_iso3": g.nodes[primary]["iso3"] if primary else None,
                "primary_country_site_share": (g[s][primary]["sites"] / sites)
                if primary and sites
                else None,
                "sites": sites,
            }
        )
    return rows


def neptune_csv(g: nx.Graph, edition: int) -> tuple[str, str]:
    """Gremlin bulk-load CSVs (vertices, edges) for Amazon Neptune's loader."""
    v = io.StringIO()
    vw = csv.writer(v, lineterminator="\n")
    vw.writerow(["~id", "~label", "name:String", "iso3:String", "region:String"])
    for n, d in sorted(g.nodes(data=True)):
        vw.writerow([n, d["kind"], d.get("name", ""), d.get("iso3", ""), d.get("region", "")])
    e = io.StringIO()
    ew = csv.writer(e, lineterminator="\n")
    ew.writerow(["~id", "~from", "~to", "~label", "edition:Int", "sites:Int"])
    for a, b, d in sorted(g.edges(data=True)):
        s, c = (a, b) if a.startswith("supplier:") else (b, a)
        ew.writerow([f"{edition}:{s}->{c}", s, c, "manufactures_in", edition, d["sites"]])
    return v.getvalue(), e.getvalue()


# ----------------------------------------------------------------------- tables
def analyse(pairs: list[dict]) -> dict[str, pa.Table]:
    """Run every metric for every edition; ``pairs`` = rows of int_supplier_country_pairs."""
    editions = sorted({p["edition"] for p in pairs})
    metrics, exposure, deps = [], [], []
    for ed in editions:
        rows = [p for p in pairs if p["edition"] == ed]
        g = build_graph(rows)
        meta = {"edition": ed, "fiscal_year": rows[0]["fiscal_year"], "layout": rows[0]["layout"]}
        metrics.append({**meta, **edition_metrics(g)})
        for name, iso3s in scenarios_for(g).items():
            exposure.append(
                {**meta, "scenario": name, "countries": ",".join(iso3s), **disruption(g, iso3s)}
            )
        deps.extend({**meta, **d} for d in supplier_dependency(g))
    return {
        "graph_edition_metrics": pa.Table.from_pylist(metrics),
        "graph_country_exposure": pa.Table.from_pylist(exposure),
        "graph_supplier_dependency": pa.Table.from_pylist(deps),
    }
