"""Static results site (``asc report --out site``): one HTML page + summary.json.

No JavaScript framework and no external assets: charts are inline SVG built here, with a
legend, direct end-labels, native hover tooltips on every point/bar and a data table under
each chart. Colours are the validated reference palette (first three categorical slots for
line charts; light and dark steps). Every number on the page is read from the warehouse.
"""

from __future__ import annotations

import html
import json
import math
from datetime import UTC, datetime
from pathlib import Path

from apple_supply_chain.config import Settings
from apple_supply_chain.warehouse import connect

LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"]

CSS = """
.viz-root{color-scheme:light;--surface:#fcfcfb;--text:#0b0b0b;--muted:#52514e;--grid:#e4e3df;
%LIGHT%font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--surface);color:var(--text);margin:0}
@media (prefers-color-scheme:dark){.viz-root{color-scheme:dark;--surface:#1a1a19;--text:#fff;--muted:#c3c2b7;--grid:#383835;%DARK%}}
main{max-width:1040px;margin:0 auto;padding:24px}
h1{font-size:28px;margin:0 0 4px}h2{font-size:20px;margin:36px 0 4px}p.lead,p.note,.muted{color:var(--muted)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:20px 0}
.tile{border:1px solid var(--grid);border-radius:8px;padding:12px}.tile b{display:block;font-size:26px}
.tile span{color:var(--muted);font-size:13px}
svg text{fill:var(--muted);font-size:12px}svg .lbl{fill:var(--text);font-size:12px}
.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:13px;margin:6px 0}.legend i{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:6px;vertical-align:-1px}
table{border-collapse:collapse;font-size:13px;margin:8px 0;width:100%}td,th{border-bottom:1px solid var(--grid);padding:4px 8px;text-align:right}
td:first-child,th:first-child{text-align:left}details{margin:4px 0 16px}summary{cursor:pointer;color:var(--muted)}
.badge{display:inline-block;padding:1px 8px;border-radius:10px;border:1px solid var(--grid);font-size:12px;color:var(--muted)}
footer{margin-top:40px;color:var(--muted);font-size:13px}
"""


def _css() -> str:
    light = "".join(f"--s{i + 1}:{c};" for i, c in enumerate(LIGHT))
    dark = "".join(f"--s{i + 1}:{c};" for i, c in enumerate(DARK))
    return CSS.replace("%LIGHT%", light).replace("%DARK%", dark)


def _e(v) -> str:
    return html.escape(str(v))


def _fmt(v, kind: str = "num") -> str:
    if v is None:
        return "-"
    if kind == "pct":
        return f"{v * 100:.1f}%"
    if kind == "usd_b":
        return f"${v / 1e9:,.1f}B"
    if kind == "days":
        return f"{v:.1f}"
    if kind == "hhi":
        return f"{v:.3f}"
    if isinstance(v, float):
        return f"{v:,.1f}"
    return f"{v:,}" if isinstance(v, int) else str(v)


# ---------------------------------------------------------------------- charts
def _nice_step(raw: float) -> float:
    exp = math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if m * 10**exp >= raw:
            return m * 10**exp
    return 10 ** (exp + 1)


def line_chart(
    series: dict[str, list[tuple]], *, kind: str, y_label: str, width=960, height=300
) -> str:
    """``series``: name -> [(x, y)], at most 3 series (palette all-pairs cap)."""
    pts = [(x, y) for s in series.values() for x, y in s if y is not None]
    if not pts:
        return "<p class='muted'>No data.</p>"
    xs = sorted({x for x, _ in pts})
    lo = min(0.0, *(y for _, y in pts))
    step = _nice_step((max(y for _, y in pts) - lo) / 4 or 1.0)
    ymin = math.floor(lo / step) * step
    ymax = math.ceil(max(y for _, y in pts) / step) * step or step
    left, right, top, bottom = 56, 150, 16, 32
    pw, ph = width - left - right, height - top - bottom

    def sx(x):
        return left + (xs.index(x) / max(len(xs) - 1, 1)) * pw

    def sy(y):
        return top + ph - (y - ymin) / (ymax - ymin) * ph

    out = [
        f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='{_e(y_label)}' width='100%'>"
    ]
    for i in range(round((ymax - ymin) / step) + 1):
        v = ymin + step * i
        out.append(
            f"<line x1='{left}' x2='{left + pw}' y1='{sy(v):.1f}' y2='{sy(v):.1f}' stroke='var(--grid)'/>"
        )
        out.append(
            f"<text x='{left - 6}' y='{sy(v) + 4:.1f}' text-anchor='end'>{_e(_fmt(v, kind))}</text>"
        )
    if ymin < 0:
        out.append(
            f"<line x1='{left}' x2='{left + pw}' y1='{sy(0):.1f}' y2='{sy(0):.1f}' stroke='var(--muted)'/>"
        )
    step = max(1, len(xs) // 12)
    for x in xs[::step]:
        out.append(f"<text x='{sx(x):.1f}' y='{height - 10}' text-anchor='middle'>{_e(x)}</text>")
    for i, (name, data) in enumerate(series.items()):
        color = f"var(--s{i + 1})"
        data = [(x, y) for x, y in data if y is not None]
        if not data:
            continue
        path = " ".join(
            f"{'M' if j == 0 else 'L'}{sx(x):.1f},{sy(y):.1f}" for j, (x, y) in enumerate(data)
        )
        out.append(f"<path d='{path}' fill='none' stroke='{color}' stroke-width='2'/>")
        for x, y in data:
            out.append(
                f"<circle cx='{sx(x):.1f}' cy='{sy(y):.1f}' r='4' fill='{color}' stroke='var(--surface)' stroke-width='2'>"
                f"<title>{_e(name)} · {_e(x)}: {_e(_fmt(y, kind))}</title></circle>"
            )
        lx, ly = data[-1]
        out.append(
            f"<text class='lbl' x='{sx(lx) + 8:.1f}' y='{sy(ly) + 4:.1f}'>{_e(name)} {_e(_fmt(ly, kind))}</text>"
        )
    out.append("</svg>")
    legend = "".join(
        f"<span><i style='background:var(--s{i + 1})'></i>{_e(n)}</span>"
        for i, n in enumerate(series)
    )
    return f"<div class='legend'>{legend}</div>" + "".join(out)


def bar_chart(rows: list[tuple[str, float]], *, kind: str, label: str, width=960) -> str:
    if not rows:
        return "<p class='muted'>No data.</p>"
    bar_h, gap, left = 22, 6, 220
    height = len(rows) * (bar_h + gap) + 10
    vmax = max(v for _, v in rows) or 1.0
    pw = width - left - 90
    out = [f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='{_e(label)}' width='100%'>"]
    for i, (name, v) in enumerate(rows):
        y = i * (bar_h + gap) + 4
        w = max(v / vmax * pw, 1)
        out.append(
            f"<text class='lbl' x='{left - 8}' y='{y + 15}' text-anchor='end'>{_e(name)}</text>"
        )
        out.append(
            f"<rect x='{left}' y='{y}' width='{w:.1f}' height='{bar_h}' rx='4' fill='var(--s1)'>"
            f"<title>{_e(name)}: {_e(_fmt(v, kind))}</title></rect>"
        )
        out.append(f"<text x='{left + w + 6:.1f}' y='{y + 15}'>{_e(_fmt(v, kind))}</text>")
    out.append("</svg>")
    return "".join(out)


def stacked_share_chart(
    years: list, parts: dict[str, dict], *, label: str, width=960, height=280
) -> str:
    """100% stacked columns; ``parts``: name -> {year: share}. Up to 5 parts."""
    left, top, bottom = 56, 10, 30
    pw, ph = width - left - 20, height - top - bottom
    colw = pw / max(len(years), 1)
    out = [f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='{_e(label)}' width='100%'>"]
    for i in range(5):
        y = top + ph * i / 4
        out.append(f"<text x='{left - 6}' y='{y + 4:.1f}' text-anchor='end'>{100 - 25 * i}%</text>")
    for j, yr in enumerate(years):
        x = left + j * colw + 3
        acc = 0.0
        for i, (name, shares) in enumerate(parts.items()):
            s = shares.get(yr, 0.0) or 0.0
            h = s * ph
            y = top + ph - (acc + s) * ph
            out.append(
                f"<rect x='{x:.1f}' y='{y + 1:.1f}' width='{colw - 6:.1f}' height='{max(h - 2, 0):.1f}' fill='var(--s{i + 1})'>"
                f"<title>{_e(name)} · FY{_e(yr)}: {s * 100:.1f}%</title></rect>"
            )
            acc += s
        out.append(
            f"<text x='{x + (colw - 6) / 2:.1f}' y='{height - 10}' text-anchor='middle'>{_e(str(yr)[2:])}</text>"
        )
    out.append("</svg>")
    legend = "".join(
        f"<span><i style='background:var(--s{i + 1})'></i>{_e(n)}</span>"
        for i, n in enumerate(parts)
    )
    return f"<div class='legend'>{legend}</div>" + "".join(out)


def table(
    headers: list[str], rows: list[list], kinds: list[str], *, summary: str = "Data table"
) -> str:
    head = "".join(f"<th>{_e(h)}</th>" for h in headers)
    body = "".join(
        "<tr>"
        + "".join(f"<td>{_e(_fmt(v, k))}</td>" for v, k in zip(r, kinds, strict=True))
        + "</tr>"
        for r in rows
    )
    return (
        f"<details><summary>{_e(summary)}</summary><table><tr>{head}</tr>{body}</table></details>"
    )


# ------------------------------------------------------------------------ data
def _q(con, sql: str, params=None) -> list[tuple]:
    return con.execute(sql, params or []).fetchall()


def collect(settings: Settings) -> dict:
    con = connect(settings)
    try:
        wc = _q(
            con,
            "select fiscal_year, dio_days, dpo_days, dso_days, ccc_days, revenue_usd, cost_of_sales_usd, inventory_usd, "
            "manufacturing_purchase_obligations_usd, mpo_days_of_cogs, vendor_nontrade_receivables_usd, gross_margin "
            "from marts.fct_working_capital_annual where dio_days is not null order by 1",
        )
        quarters = _q(
            con,
            "select fiscal_period, dio_days, dpo_days, ccc_days from marts.fct_working_capital_quarterly "
            "where dio_days is not null order by period_end",
        )
        seg = _q(
            con,
            "select fiscal_year, member_label, share_of_total, revenue_usd from marts.mart_revenue_mix "
            "where breakdown = 'segment' order by 1, 2",
        )
        conc = _q(
            con,
            "select edition, fiscal_year, layout, n_suppliers, n_countries, n_pairs, n_sites, hhi_pairs, hhi_sites, "
            "china_pair_share, china_site_share, india_pair_share, vietnam_pair_share, single_country_supplier_share, "
            "china_only_suppliers from marts.mart_supplier_concentration order by 1",
        )
        latest_ed = conc[-1][0] if conc else None
        countries = _q(
            con,
            "select country_name, suppliers, pair_share, sites, site_share from marts.mart_supplier_sites_by_country "
            "where edition = ? order by suppliers desc, country_name limit 12",
            [latest_ed],
        )
        exposure = _q(
            con,
            "select scenario, site_share_exposed, suppliers_affected_share, suppliers_fully_disrupted_share, "
            "suppliers_fully_disrupted, suppliers_affected from graph.graph_country_exposure where edition = ? "
            "order by site_share_exposed desc",
            [latest_ed],
        )
        trade = _q(
            con,
            "select dataset, product_group, year, country_iso3, country_name, value_usd, share_of_selected "
            "from marts.mart_trade_flow_shifts where country_iso3 in ('CHN','IND','VNM') order by year",
        )
        manifest = _q(
            con,
            "select source, count(*), max(fetched_at) from silver.raw_manifest group by 1 order by 1",
        )
    finally:
        con.close()
    return {
        "wc": wc,
        "quarters": quarters,
        "seg": seg,
        "conc": conc,
        "countries": countries,
        "exposure": exposure,
        "trade": trade,
        "manifest": manifest,
        "latest_edition": latest_ed,
    }


def _trade_series(trade, dataset: str, group: str) -> dict:
    names = {"CHN": "China", "IND": "India", "VNM": "Viet Nam"}
    out: dict[str, list] = {n: [] for n in names.values()}
    for ds, pg, yr, iso, _name, value, _share in trade:
        if ds == dataset and pg == group:
            out[names[iso]].append((yr, value))
    return out


def build_site(settings: Settings, out_dir: Path) -> dict:
    d = collect(settings)
    out_dir.mkdir(parents=True, exist_ok=True)
    wc, conc = d["wc"], d["conc"]
    last = wc[-1] if wc else None
    lc = conc[-1] if conc else None
    china_scn = next((e for e in d["exposure"] if e[0] == "China mainland"), None)
    summary = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source_mode": settings.source_mode,
        "latest_fiscal_year": last[0] if last else None,
        "dio_days": round(last[1], 1) if last else None,
        "dpo_days": round(last[2], 1) if last else None,
        "ccc_days": round(last[4], 1) if last else None,
        "manufacturing_purchase_obligations_usd_bn": round(last[8] / 1e9, 1)
        if last and last[8]
        else None,
        "supplier_list_edition": lc[0] if lc else None,
        "suppliers": lc[3] if lc else None,
        "supplier_countries": lc[4] if lc else None,
        "hhi_supplier_country_pairs": round(lc[7], 3) if lc else None,
        "china_share_of_supplier_country_pairs": round(lc[9], 3) if lc else None,
        "china_disruption_site_share_exposed": round(china_scn[1], 3) if china_scn else None,
        "china_disruption_suppliers_fully_disrupted_share": round(china_scn[3], 3)
        if china_scn
        else None,
    }
    banner = ""
    if settings.source_mode == "fixtures":
        banner = (
            "<p class='badge'>FIXTURE BUILD: SEC figures are real (trimmed); supplier lists and trade values are "
            "SYNTHETIC test data, not real.</p>"
        )

    tiles = ""
    if last and lc:
        tiles = (
            "<div class='tiles'>"
            + "".join(
                f"<div class='tile'><b>{_e(v)}</b><span>{_e(t)}</span></div>"
                for v, t in [
                    (f"{last[1]:.1f} days", f"Days inventory outstanding, FY{last[0]}"),
                    (f"{last[4]:.1f} days", f"Cash conversion cycle, FY{last[0]}"),
                    (_fmt(last[8], "usd_b"), f"Manufacturing purchase obligations, FY{last[0]}"),
                    (f"{lc[3]} / {lc[4]}", f"Suppliers / countries, {lc[0]} list"),
                    (_fmt(lc[9], "pct"), f"China share of supplier-country pairs, {lc[0]}"),
                    (
                        _fmt(china_scn[1], "pct") if china_scn else "-",
                        "Listed sites in China mainland (disruption scenario)",
                    ),
                ]
            )
            + "</div>"
        )

    years = sorted({r[0] for r in d["seg"]})
    seg_names = ["Americas", "Europe", "Greater China", "Japan", "Rest of Asia Pacific"]
    seg_parts = {n: {r[0]: r[2] for r in d["seg"] if r[1] == n} for n in seg_names}

    body = f"""
<h1>Apple supply chain analytics</h1>
<p class='lead'>SEC EDGAR XBRL (10-K/10-Q), Apple's annual Supplier List and UN Comtrade trade flows, built by a
Step Functions + Lambda + S3 + Iceberg + dbt + graph pipeline running on local AWS emulation. Generated
{_e(summary["generated_at"])}.</p>{banner}
{tiles}

<h2>Working capital: DIO, DPO and the cash conversion cycle</h2>
<p class='note'>Average-balance days on annual cost of sales / revenue. A negative CCC means Apple collects from
customers before it pays suppliers.</p>
{
        line_chart(
            {
                "DIO": [(r[0], r[1]) for r in wc],
                "DPO": [(r[0], r[2]) for r in wc],
                "CCC": [(r[0], r[4]) for r in wc],
            },
            kind="days",
            y_label="days",
        )
    }
{
        table(
            [
                "FY",
                "DIO",
                "DPO",
                "DSO",
                "CCC",
                "Revenue",
                "Cost of sales",
                "Inventory",
                "Mfg purchase obligations",
                "MPO days of COGS",
            ],
            [[r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9]] for r in wc],
            ["num", "days", "days", "days", "days", "usd_b", "usd_b", "usd_b", "usd_b", "days"],
        )
    }

<h2>Quarterly DIO and DPO</h2>
<p class='note'>Quarter-end balances over the quarter's cost of sales; Q4 flows are derived (10-K annual minus Q1-Q3).</p>
{
        line_chart(
            {
                "DIO": [(r[0], r[1]) for r in d["quarters"]],
                "DPO": [(r[0], r[2]) for r in d["quarters"]],
                "CCC": [(r[0], r[3]) for r in d["quarters"]],
            },
            kind="days",
            y_label="days",
        )
    }

<h2>Geographic revenue mix (reportable segments)</h2>
{stacked_share_chart(years, seg_parts, label="segment share of net sales")}
{
        table(
            ["FY", "Segment", "Share", "Net sales"],
            [[r[0], r[1], r[2], r[3]] for r in d["seg"]],
            ["num", "num", "pct", "usd_b"],
        )
    }

<h2>Supplier footprint over Supplier List editions</h2>
<p class='note'>Share of supplier-country pairs (comparable across the 2019 -> 2021 layout change from facility
addresses to province lists). 2016 and 2020 editions could not be retrieved.</p>
{
        line_chart(
            {
                "China mainland": [(r[0], r[9]) for r in conc],
                "Viet Nam": [(r[0], r[12]) for r in conc],
                "India": [(r[0], r[11]) for r in conc],
            },
            kind="pct",
            y_label="share of supplier-country pairs",
        )
    }
<h2>Concentration (HHI over countries)</h2>
{
        line_chart(
            {"HHI, supplier-country pairs": [(r[0], r[7]) for r in conc]}, kind="hhi", y_label="HHI"
        )
    }
{
        table(
            [
                "Edition",
                "Spend year",
                "Layout",
                "Suppliers",
                "Countries",
                "Pairs",
                "Sites",
                "HHI pairs",
                "HHI sites",
                "China pairs",
                "China sites",
                "Single-country suppliers",
            ],
            [
                [r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9], r[10], r[13]]
                for r in conc
            ],
            ["num", "num", "num", "num", "num", "num", "num", "hhi", "hhi", "pct", "pct", "pct"],
        )
    }

<h2>Disruption scenario: what is exposed if a country is cut off? ({
        _e(d["latest_edition"])
    } list)</h2>
<p class='note'>Share of listed sites in the country set; suppliers with any site there; and suppliers with
<em>every</em> listed site there (no alternative country on the list). Sites are provinces/states in this layout.</p>
{bar_chart([(r[0], r[1]) for r in d["exposure"]], kind="pct", label="share of sites exposed")}
{
        table(
            ["Scenario", "Sites exposed", "Suppliers affected", "Suppliers fully disrupted"],
            [[r[0], r[1], r[2], r[3]] for r in d["exposure"]],
            ["num", "pct", "pct", "pct"],
            summary="Scenario table",
        )
    }
{
        table(
            ["Country", "Suppliers", "Pair share", "Sites", "Site share"],
            [list(r) for r in d["countries"]],
            ["num", "num", "pct", "num", "pct"],
            summary="Top countries, latest edition",
        )
    }

<h2>Trade-flow shifts: HS 8517 exports (phones and telecom apparatus)</h2>
<p class='note'>UN Comtrade, reporter-declared exports to the World, US$. Viet Nam had not reported its latest year at
build time.</p>
{
        line_chart(
            _trade_series(d["trade"], "exports", "hs8517_phones_and_telecom"),
            kind="usd_b",
            y_label="US$",
        )
    }
<h2>US imports of cellular phones by partner</h2>
<p class='note'>HS 851712 to 2021, 851713 (smartphones) from HS 2022, as reported by the US.</p>
{
        line_chart(
            _trade_series(d["trade"], "us_imports", "cellular_phones"), kind="usd_b", y_label="US$"
        )
    }

<h2>Lineage</h2>
{
        table(
            ["Source", "Raw objects", "Last fetched"],
            [list(r) for r in d["manifest"]],
            ["num", "num", "num"],
            summary="Raw zone objects by source",
        )
    }
<footer>Data: SEC EDGAR (public), Apple Supplier List (© Apple; parsed at runtime, not redistributed), UN Comtrade
(© United Nations; limited derived figures shown). AWS services are emulated locally; see the repository README.</footer>
"""
    page = (
        f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Apple supply chain analytics</title><style>{_css()}</style></head>"
        f"<body class='viz-root'><main>{body}</main></body></html>"
    )
    (out_dir / "index.html").write_text(page, encoding="utf-8")
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    (out_dir / ".nojekyll").write_text("")
    return summary
