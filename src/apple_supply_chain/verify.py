"""Reconcile pipeline outputs with figures Apple publishes independently of XBRL.

Apple's newsroom posts condensed consolidated statements with each Q4 results release
(``FYxx_Q4_Consolidated_Financial_Statements.pdf``). Those PDFs are a separate publication
from the XBRL the pipeline reads, so matching them line by line checks the whole chain:
companyfacts / instance parsing, restatement handling, fiscal-year assignment and the marts.
The PDFs are downloaded at runtime and never stored in the repository (Apple copyright).

A second, weaker check compares supplier counts with Apple's own statement that the
2014-2019 lists cover its "top 200 suppliers".
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

from apple_supply_chain.config import Settings
from apple_supply_chain.extract import PORTFOLIO_UA
from apple_supply_chain.http import HttpClient
from apple_supply_chain.warehouse import connect

STATEMENTS = {
    2025: "https://www.apple.com/newsroom/pdfs/fy2025-q4/FY25_Q4_Consolidated_Financial_Statements.pdf",
    2024: "https://www.apple.com/newsroom/pdfs/fy2024-q4/FY24_Q4_Consolidated_Financial_Statements.pdf",
    2023: "https://www.apple.com/newsroom/pdfs/fy2023-q4/FY23_Q4_Consolidated_Financial_Statements.pdf",
}
TOP_200_EDITIONS = (2014, 2015, 2017, 2018, 2019)

INCOME_LINES = {
    ("net_sales", "Total net sales"): "net_sales",
    ("cost_of_sales", "Total cost of sales"): "cost_of_sales",
    ("other", "Gross margin"): "gross_margin",
}
SEGMENTS = ("Americas", "Europe", "Greater China", "Japan", "Rest of Asia Pacific")
CATEGORIES = ("iPhone", "Mac", "iPad", "Wearables, Home and Accessories", "Services")
BALANCE_LINES = {
    "Accounts receivable, net": "accounts_receivable",
    "Vendor non-trade receivables": "vendor_nontrade_receivables",
    "Inventories": "inventory",
    "Property, plant and equipment, net": "ppe_net",
    "Accounts payable": "accounts_payable",
}
CAPEX_LINE = "Payments for acquisition of property, plant and equipment"
# 19 line items per fiscal-year column; each statement PDF has two annual columns.
EXPECTED_ITEMS = (
    *INCOME_LINES.values(),
    *(f"segment:{s}" for s in SEGMENTS),
    *(f"category:{c}" for c in CATEGORIES),
    *BALANCE_LINES.values(),
    "capex",
)
_NUM = re.compile(r"\(?-?[\d,]+\)?|—")


def _numbers(rest: str) -> list[float]:
    rest = re.sub(r"(\d)\s+,(\d)", r"\1,\2", rest.replace("$", " ").replace("!", " "))
    out = []
    for tok in _NUM.findall(rest):
        if tok == "—":
            out.append(0.0)
            continue
        neg = tok.startswith("(")
        val = float(tok.strip("()").replace(",", ""))
        out.append(-val if neg else val)
    return out


def _split(line: str, label: str) -> list[float] | None:
    if not line.startswith(label):
        return None
    rest = line[len(label) :]
    rest = re.sub(r"^\s*\(\d\)", "", rest)  # footnote marker "(1)"
    if rest and not rest[0].isspace():
        return None
    return _numbers(rest)


def parse_statements(pdf_bytes: bytes, fiscal_year: int) -> dict[tuple[int, str], float]:
    """{(fiscal_year, line_item): USD millions} for the twelve-month / year-end columns."""
    import pdfplumber  # noqa: PLC0415

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        pages = [p.extract_text() or "" for p in pdf.pages]
    out: dict[tuple[int, str], float] = {}
    section = "other"
    for line in pages[0].splitlines():
        low = line.lower()
        if low.startswith("net sales:"):
            section = "net_sales"
        elif low.startswith("cost of sales:"):
            section = "cost_of_sales"
        elif low.startswith("operating expenses"):
            section = "other"
        elif "net sales by reportable segment" in low:
            section = "segments"
        elif "net sales by category" in low:
            section = "categories"
        for (sec, label), key in INCOME_LINES.items():
            nums = _split(line, label)
            if nums and len(nums) == 4 and sec in (section, "other"):
                out.setdefault((fiscal_year, key), nums[2])
                out.setdefault((fiscal_year - 1, key), nums[3])
        names = SEGMENTS if section == "segments" else CATEGORIES if section == "categories" else ()
        for name in names:
            nums = _split(line, name)
            if nums and len(nums) == 4:
                prefix = "segment" if section == "segments" else "category"
                out.setdefault((fiscal_year, f"{prefix}:{name}"), nums[2])
                out.setdefault((fiscal_year - 1, f"{prefix}:{name}"), nums[3])
    for line in pages[1].splitlines():
        for label, key in BALANCE_LINES.items():
            nums = _split(line, label)
            if nums and len(nums) == 2:
                out.setdefault((fiscal_year, key), nums[0])
                out.setdefault((fiscal_year - 1, key), nums[1])
    for line in pages[2].splitlines():
        nums = _split(line, CAPEX_LINE)
        if nums and len(nums) == 2:
            out.setdefault((fiscal_year, "capex"), abs(nums[0]))
            out.setdefault((fiscal_year - 1, "capex"), abs(nums[1]))
    return out


def missing_items(parsed: dict[tuple[int, str], float], fiscal_year: int) -> list[tuple[int, str]]:
    """Expected (fiscal_year, line_item) pairs that ``parse_statements`` did not find."""
    return [
        (year, item)
        for year in (fiscal_year, fiscal_year - 1)
        for item in EXPECTED_ITEMS
        if (year, item) not in parsed
    ]


def pipeline_values(settings: Settings) -> dict[tuple[int, str], float]:
    con = connect(settings)
    try:
        vals: dict[tuple[int, str], float] = {}
        cols = {
            "net_sales": "revenue_usd",
            "cost_of_sales": "cost_of_sales_usd",
            "gross_margin": "gross_profit_usd",
            "accounts_receivable": "accounts_receivable_usd",
            "vendor_nontrade_receivables": "vendor_nontrade_receivables_usd",
            "inventory": "inventory_usd",
            "ppe_net": "ppe_net_usd",
            "accounts_payable": "accounts_payable_usd",
            "capex": "capex_usd",
        }
        rows = con.execute(
            f"select fiscal_year, {', '.join(cols.values())} from marts.fct_working_capital_annual"
        ).fetchall()
        for row in rows:
            for key, value in zip(cols, row[1:], strict=True):
                if value is not None:
                    vals[(row[0], key)] = value / 1e6
        mix = con.execute(
            "select fiscal_year, breakdown, member_label, revenue_usd from marts.mart_revenue_mix "
            "where breakdown in ('segment', 'product')"
        ).fetchall()
        for fy, breakdown, label, value in mix:
            prefix = "segment" if breakdown == "segment" else "category"
            vals[(fy, f"{prefix}:{label}")] = value / 1e6
        return vals
    finally:
        con.close()


def supplier_counts(settings: Settings) -> dict[int, int]:
    con = connect(settings)
    try:
        return dict(
            con.execute(
                "select edition, n_suppliers from marts.mart_supplier_concentration"
            ).fetchall()
        )
    finally:
        con.close()


def run_verification(
    settings: Settings, out: Path, *, documents: dict[int, bytes] | None = None
) -> dict:
    if documents is None:
        client = HttpClient(user_agent=PORTFOLIO_UA)
        documents = {fy: client.get(url) for fy, url in STATEMENTS.items()}
    ours = pipeline_values(settings)
    comparisons = []
    for fy, pdf in sorted(documents.items()):
        parsed = parse_statements(pdf, fy)
        # A line the parser could not find is a failure, not a silently smaller denominator.
        for year, item in missing_items(parsed, fy):
            comparisons.append(
                {
                    "document": STATEMENTS.get(fy, f"FY{fy}"),
                    "fiscal_year": year,
                    "line_item": item,
                    "published": None,
                    "pipeline": None,
                    "matched": False,
                    "note": "line item not found in the published statement",
                }
            )
        for (year, item), published in sorted(parsed.items()):
            value = ours.get((year, item))
            comparisons.append(
                {
                    "document": STATEMENTS.get(fy, f"FY{fy}"),
                    "fiscal_year": year,
                    "line_item": item,
                    "published": published,
                    "pipeline": None if value is None else round(value, 1),
                    "matched": value is not None and abs(value - published) <= 0.5,
                }
            )
    counts = supplier_counts(settings)
    supplier_checks = [
        {
            "edition": ed,
            "published_statement": "top 200 suppliers",
            "pipeline_suppliers": counts.get(ed),
            "matched": counts.get(ed) == 200,
        }
        for ed in TOP_200_EDITIONS
        if ed in counts
    ]
    mismatches = [c for c in comparisons if not c["matched"]]
    result = {
        "compared": len(comparisons),
        "matched": len(comparisons) - len(mismatches),
        "mismatches": mismatches,
        "comparisons": comparisons,
        "supplier_count_checks": supplier_checks,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    return result
