"""Data-quality gates between layers.

``silver`` checks run on the Iceberg silver tables before dbt; ``gold`` checks run on the
warehouse after dbt and the graph stage. An *error* that fails stops the pipeline (the Step
Functions Choice state routes to ``DataQualityFailed``; the CLI exits with code 3). A *warn*
is reported but does not block.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date

import duckdb

from apple_supply_chain.config import Settings
from apple_supply_chain.lakehouse.iceberg import build_catalog, list_tables, ns, read_table
from apple_supply_chain.warehouse import connect

FIRST_RECONCILED_FY = 2013


@dataclass(frozen=True)
class CheckResult:
    layer: str
    name: str
    severity: str  # "error" | "warn"
    passed: bool
    violations: int
    detail: str = ""


def _count(con: duckdb.DuckDBPyConnection, sql: str) -> int:
    return int(con.execute(sql).fetchone()[0])


def _check(layer, name, severity, con, sql, detail="") -> CheckResult:
    n = _count(con, f"select count(*) from ({sql}) as v")
    return CheckResult(layer, name, severity, n == 0, n, detail)


# ------------------------------------------------------------------------ silver
def silver_connection(settings: Settings) -> duckdb.DuckDBPyConnection:
    catalog = build_catalog(settings)
    con = duckdb.connect()
    con.execute("create schema silver")
    for ident in list_tables(catalog, ns(settings, "silver")):
        name = ident.split(".", 1)[1]
        con.register(f"tmp_{name}", read_table(catalog, ident))
        con.execute(f"create table silver.{name} as select * from tmp_{name}")
    return con


def silver_checks(
    con: duckdb.DuckDBPyConnection, *, today: date | None = None
) -> list[CheckResult]:
    today = today or date.today()
    layer = "silver"
    annual_rev = (
        "select cast(extract(year from period_end) as int) as fy, value from silver.financial_facts "
        "where metric = 'revenue' and duration_days between 350 and 380"
    )
    checks = [
        _check(
            layer,
            "financial_facts not empty",
            "error",
            con,
            "select 1 where (select count(*) from silver.financial_facts) = 0",
        ),
        _check(
            layer,
            "financial_facts unique per metric and period",
            "error",
            con,
            "select metric, period_start, period_end from silver.financial_facts "
            "group by 1, 2, 3 having count(*) > 1",
        ),
        _check(
            layer,
            "core metrics are non-negative",
            "error",
            con,
            "select * from silver.financial_facts where value < 0 and metric in "
            "('revenue','cost_of_sales','inventory','accounts_payable','accounts_receivable')",
        ),
        _check(
            layer,
            "annual revenue has no fiscal-year gaps",
            "error",
            con,
            f"with y as ({annual_rev}) select fy from y where fy > (select min(fy) from y) "
            "and fy - 1 not in (select fy from y)",
        ),
        _check(
            layer,
            "latest annual 10-K is recent (<= 2 fiscal years old)",
            "warn",
            con,
            f"with y as ({annual_rev}) select 1 where (select max(fy) from y) < {today.year - 2}",
        ),
        _check(
            layer,
            f"segment/product/country revenue reconciles to total (FY{FIRST_RECONCILED_FY}+, 0.5%)",
            "error",
            con,
            _reconcile_sql(f">= {FIRST_RECONCILED_FY}"),
        ),
        _check(
            layer,
            "revenue breakdowns before FY2013 reconcile (legacy schemes, informational)",
            "warn",
            con,
            _reconcile_sql(f"< {FIRST_RECONCILED_FY}"),
        ),
        _check(
            layer,
            "purchase obligations: within-12-months <= total",
            "error",
            con,
            "select * from silver.purchase_obligations "
            "where payable_within_12m_usd > amount_usd * 1.0001",
        ),
        _check(
            layer,
            "purchase obligations found for every 10-K since FY2010",
            "warn",
            con,
            f"with y as ({annual_rev}) select fy from y where fy >= 2010 and fy not in "
            "(select fiscal_year from silver.purchase_obligations)",
        ),
        _check(
            layer,
            "supplier list: at least one edition parsed",
            "error",
            con,
            "select 1 where (select count(distinct edition) from silver.supplier_sites) = 0",
        ),
        _check(
            layer,
            "supplier list: every landed PDF edition produced rows",
            "error",
            con,
            "select item from silver.raw_manifest where source = 'apple_supplier_list' "
            "and dataset = 'pdf' and try_cast(item as integer) not in "
            "(select distinct edition from silver.supplier_sites)",
        ),
        _check(
            layer,
            "supplier rows resolve to a country (<= 1% unresolved per edition)",
            "error",
            con,
            "select edition from silver.supplier_sites group by edition "
            "having avg(case when country_iso3 is null then 1.0 else 0.0 end) > 0.01",
        ),
        _check(
            layer,
            "supplier rows unique per edition and row number",
            "error",
            con,
            "select edition, row_number from silver.supplier_sites group by 1, 2 having count(*) > 1",
        ),
        _check(
            layer,
            "supplier count per edition near Apple's stated ~200 (150-250)",
            "warn",
            con,
            "select edition from silver.supplier_sites group by edition "
            "having count(distinct supplier_key) not between 150 and 250",
        ),
        _check(
            layer,
            "trade_flows not empty",
            "error",
            con,
            "select 1 where (select count(*) from silver.trade_flows) = 0",
        ),
        _check(
            layer,
            "trade values are non-negative",
            "error",
            con,
            "select * from silver.trade_flows where primary_value_usd < 0",
        ),
        _check(
            layer,
            "trade rows unique",
            "error",
            con,
            "select dataset, year, reporter_code, partner_code, cmd_code from silver.trade_flows "
            "group by 1, 2, 3, 4, 5 having count(*) > 1",
        ),
        _check(
            layer,
            "6-digit cellular phones (sum of 851712/851713/851714) <= HS 8517 parent",
            "error",
            con,
            "with c as (select dataset, year, reporter_code, partner_code, "
            "sum(primary_value_usd) as v from silver.trade_flows "
            "where cmd_code in ('851712', '851713', '851714') group by 1, 2, 3, 4) "
            "select c.* from c join silver.trade_flows p "
            "on c.dataset = p.dataset and c.year = p.year and c.reporter_code = p.reporter_code "
            "and c.partner_code = p.partner_code and p.cmd_code = '8517' "
            "where c.v > p.primary_value_usd * 1.0001",
        ),
        _check(
            layer,
            "lineage: every silver row maps to a raw object",
            "error",
            con,
            "select source_sha256 from ("
            "select source_sha256 from silver.financial_facts union all "
            "select source_sha256 from silver.segment_revenue union all "
            "select source_sha256 from silver.supplier_sites union all "
            "select source_sha256 from silver.trade_flows) "
            "where source_sha256 not in (select sha256 from silver.raw_manifest)",
        ),
    ]
    return checks


def _reconcile_sql(fy_filter: str) -> str:
    return (
        "with tot as (select cast(extract(year from period_end) as int) as fy, value "
        "from silver.financial_facts where metric = 'revenue' and duration_days between 350 and 380), "
        "parts as (select fiscal_year as fy, breakdown, sum(value) as s from silver.segment_revenue "
        "where not is_rollup group by 1, 2) "
        "select parts.* from parts join tot on parts.fy = tot.fy "
        f"where parts.fy {fy_filter} and abs(parts.s - tot.value) > 0.005 * tot.value"
    )


# -------------------------------------------------------------------------- gold
def gold_checks(con: duckdb.DuckDBPyConnection) -> list[CheckResult]:
    layer = "gold"
    return [
        _check(
            layer,
            "working-capital mart not empty",
            "error",
            con,
            "select 1 where (select count(*) from marts.fct_working_capital_annual) = 0",
        ),
        _check(
            layer,
            "mart covers the latest annual fiscal year in silver",
            "error",
            con,
            "select 1 where (select max(fiscal_year) from marts.fct_working_capital_annual) <> "
            "(select max(cast(extract(year from period_end) as int)) from silver.financial_facts "
            "where metric = 'revenue' and duration_days between 350 and 380)",
        ),
        _check(
            layer,
            "every parsed edition reaches the concentration mart",
            "error",
            con,
            "select distinct edition from silver.supplier_sites where country_iso3 is not null "
            "and edition not in (select edition from marts.mart_supplier_concentration)",
        ),
        _check(
            layer,
            "networkx HHI equals dbt HHI (supplier-country pairs)",
            "error",
            con,
            "select g.edition from graph.graph_edition_metrics g join marts.mart_supplier_concentration m "
            "on g.edition = m.edition where abs(g.hhi_pairs - m.hhi_pairs) > 1e-9",
        ),
        _check(
            layer,
            "networkx single-country suppliers equal dbt",
            "error",
            con,
            "select g.edition from graph.graph_edition_metrics g join marts.mart_supplier_concentration m "
            "on g.edition = m.edition where g.single_country_suppliers <> m.single_country_suppliers",
        ),
        _check(
            layer,
            "scenario shares are within [0, 1] and fully-disrupted <= affected",
            "error",
            con,
            "select * from graph.graph_country_exposure where site_share_exposed < 0 "
            "or site_share_exposed > 1 or suppliers_fully_disrupted > suppliers_affected",
        ),
        _check(
            layer,
            "DIO within a plausible 0-60 day range",
            "warn",
            con,
            "select * from marts.fct_working_capital_annual where dio_days < 0 or dio_days > 60",
        ),
    ]


def summarize(results: list[CheckResult]) -> dict:
    errors = [r for r in results if not r.passed and r.severity == "error"]
    warns = [r for r in results if not r.passed and r.severity == "warn"]
    return {
        "passed": not errors,
        "errors": len(errors),
        "warnings": len(warns),
        "checks": [asdict(r) for r in results],
    }


def run_silver_checks(settings: Settings) -> dict:
    con = silver_connection(settings)
    try:
        return summarize(silver_checks(con))
    finally:
        con.close()


def run_gold_checks(settings: Settings) -> dict:
    con = connect(settings)
    try:
        return summarize(gold_checks(con))
    finally:
        con.close()
