"""SEC EDGAR: XBRL company facts, 10-K XBRL instances and 10-K text for Apple Inc.

Three products, all public:

* ``companyfacts`` (data.sec.gov/api/xbrl) - every non-dimensional us-gaap fact Apple has
  filed: inventory, cost of sales, payables, receivables, revenue, purchase obligations.
* 10-K XBRL instance documents - the *dimensional* facts companyfacts leaves out: net sales
  by reportable segment, by product category and by country.
* 10-K primary documents (HTML) - "manufacturing purchase obligations" are disclosed in
  prose only (not tagged), so they are extracted from the text.
"""

from __future__ import annotations

import html as htmllib
import json
import re
import xml.etree.ElementTree as ET
from datetime import date

from apple_supply_chain.fetch import Fetcher

CIK = "0000320193"
CIK_INT = 320193
COMPANYFACTS_URL = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{CIK}.json"
SUBMISSIONS_URL = f"https://data.sec.gov/submissions/CIK{CIK}.json"
ARCHIVE_BASE = f"https://www.sec.gov/Archives/edgar/data/{CIK_INT}"

# metric -> us-gaap concepts in priority order (first one present wins for a period)
METRIC_CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
        "Revenues",
    ),
    "cost_of_sales": ("CostOfGoodsAndServicesSold", "CostOfRevenue"),
    "gross_profit": ("GrossProfit",),
    "inventory": ("InventoryNet",),
    "accounts_payable": ("AccountsPayableCurrent",),
    "accounts_receivable": ("AccountsReceivableNetCurrent",),
    "vendor_nontrade_receivables": ("NontradeReceivablesCurrent",),
    "unconditional_purchase_obligations": (
        "UnrecordedUnconditionalPurchaseObligationBalanceSheetAmount",
    ),
    "ppe_net": ("PropertyPlantAndEquipmentNet",),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment",),
}
FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A"}
REVENUE_CONCEPTS = set(METRIC_CONCEPTS["revenue"])

XBRLI = "{http://www.xbrl.org/2003/instance}"
XBRLDI = "{http://xbrl.org/2006/xbrldi}"

AXIS_KIND = {
    "StatementBusinessSegmentsAxis": "segment",
    "ProductOrServiceAxis": "product",
    "StatementGeographicalAxis": "country",
    "SegmentGeographicalAxis": "country",
}
# XBRL member (local name) -> (breakdown, canonical label). Apple renamed members over the
# years (AppleIphoneMember -> IPhoneMember, GreaterChinaMember -> GreaterChinaSegmentMember)
# and older filings put product categories on the segment axis; this table normalises both.
# Members not listed (iPod, iTunes, Accessories, Desktops, ... from pre-FY2013 category
# schemes) are ignored, which is why trends start in FY2013.
CANONICAL_MEMBERS: dict[str, tuple[str, str]] = {
    "AmericasSegmentMember": ("segment", "Americas"),
    "AmericasMember": ("segment", "Americas"),
    "EuropeSegmentMember": ("segment", "Europe"),
    "EuropeMember": ("segment", "Europe"),
    "GreaterChinaSegmentMember": ("segment", "Greater China"),
    "GreaterChinaMember": ("segment", "Greater China"),
    "JapanSegmentMember": ("segment", "Japan"),
    "JapanMember": ("segment", "Japan"),
    "JP": ("segment", "Japan"),
    "RestOfAsiaPacificSegmentMember": ("segment", "Rest of Asia Pacific"),
    "AsiaPacificMember": ("segment", "Asia Pacific"),
    "RetailSegmentMember": ("segment", "Retail"),
    "RetailMember": ("segment", "Retail"),
    "IPhoneMember": ("product", "iPhone"),
    "AppleIphoneMember": ("product", "iPhone"),
    "IPadMember": ("product", "iPad"),
    "AppleIpadMember": ("product", "iPad"),
    "MacMember": ("product", "Mac"),
    "AppleMacMember": ("product", "Mac"),
    "ServiceMember": ("product", "Services"),
    "ServicesMember": ("product", "Services"),
    "WearablesHomeandAccessoriesMember": ("product", "Wearables, Home and Accessories"),
    "OtherProductsMember": ("product", "Other Products"),
    "ManufacturedProductOtherMember": ("product", "Other Products"),
    "ProductMember": ("product", "Products"),
    "US": ("country", "United States"),
    "CN": ("country", "China"),
    "OtherCountriesMember": ("country", "Other countries"),
}
ROLLUP_LABELS = {"Products"}


# ------------------------------------------------------------------------- filings
def ten_k_filings(submissions: dict, older_pages: list[dict] | None = None) -> list[dict]:
    """10-K filings (with XBRL) from the submissions JSON, oldest first."""
    rows: list[dict] = []
    for block in [submissions["filings"]["recent"], *(older_pages or [])]:
        for i, form in enumerate(block["form"]):
            if form != "10-K" or not block["isXBRL"][i]:
                continue
            rows.append(
                {
                    "accession": block["accessionNumber"][i],
                    "filed": block["filingDate"][i],
                    "period_end": block["reportDate"][i],
                    "primary_document": block["primaryDocument"][i],
                }
            )
    unique = {r["accession"]: r for r in rows}
    return sorted(unique.values(), key=lambda r: r["period_end"])


def filing_folder(accession: str) -> str:
    return f"{ARCHIVE_BASE}/{accession.replace('-', '')}"


def instance_document(index: dict) -> str | None:
    """Pick the XBRL instance from a filing folder's index.json."""
    names = [item["name"] for item in index["directory"]["item"]]
    inline = [n for n in names if n.endswith("_htm.xml")]
    if inline:
        return inline[0]
    skip = ("_cal.xml", "_def.xml", "_lab.xml", "_pre.xml")
    candidates = [
        n for n in names if n.endswith(".xml") and not n.endswith(skip) and n != "FilingSummary.xml"
    ]
    return candidates[0] if candidates else None


def fetch_filing_documents(fetcher: Fetcher, filing: dict) -> dict[str, bytes]:
    folder = filing_folder(filing["accession"])
    index = json.loads(fetcher.get(f"{folder}/index.json"))
    docs: dict[str, bytes] = {}
    instance = instance_document(index)
    if instance:
        docs["instance"] = fetcher.get(f"{folder}/{instance}")
    docs["primary"] = fetcher.get(f"{folder}/{filing['primary_document']}")
    return docs


# ------------------------------------------------------------------- companyfacts
def _days(start: str | None, end: str) -> int | None:
    if not start:
        return None
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def parse_companyfacts(doc: dict) -> list[dict]:
    """Flatten selected concepts into one row per reported fact (all filings)."""
    gaap = doc.get("facts", {}).get("us-gaap", {})
    rows: list[dict] = []
    for metric, concepts in METRIC_CONCEPTS.items():
        for rank, concept in enumerate(concepts):
            fact = gaap.get(concept)
            if not fact:
                continue
            for unit, values in fact.get("units", {}).items():
                for v in values:
                    if v.get("form") not in FORMS:
                        continue
                    rows.append(
                        {
                            "metric": metric,
                            "concept": concept,
                            "concept_rank": rank,
                            "unit": unit,
                            "period_start": v.get("start"),
                            "period_end": v["end"],
                            "duration_days": _days(v.get("start"), v["end"]),
                            "value": float(v["val"]),
                            "filing_fy": v.get("fy"),
                            "filing_fp": v.get("fp"),
                            "form": v["form"],
                            "filed": v["filed"],
                            "accession": v["accn"],
                            "frame": v.get("frame"),
                        }
                    )
    return rows


def latest_facts(rows: list[dict]) -> list[dict]:
    """One row per (metric, period): best-ranked concept, then the most recent filing.

    The most recent filing wins so restatements and recasts replace original figures.
    """
    best: dict[tuple, dict] = {}
    for r in rows:
        k = (r["metric"], r["period_start"], r["period_end"])
        cur = best.get(k)
        if (
            cur is None
            or r["concept_rank"] < cur["concept_rank"]
            or (
                r["concept_rank"] == cur["concept_rank"]
                and (r["filed"], r["accession"]) > (cur["filed"], cur["accession"])
            )
        ):
            best[k] = r
    return sorted(
        best.values(), key=lambda r: (r["metric"], r["period_end"], r["period_start"] or "")
    )


# --------------------------------------------------------------- XBRL instances
def _local(qname: str) -> str:
    return qname.split(":", 1)[-1]


def parse_instance(xml_bytes: bytes, *, accession: str, filed: str) -> list[dict]:
    """Annual net-sales facts broken down by segment, product category or country."""
    root = ET.fromstring(xml_bytes)  # noqa: S314 - trusted SEC source, no DTDs/entities
    contexts: dict[str, dict] = {}
    for ctx in root.iter(f"{XBRLI}context"):
        dims = {
            _local(m.get("dimension", "")): m.text.strip()
            for m in ctx.iter(f"{XBRLDI}explicitMember")
            if m.text
        }
        period = ctx.find(f"{XBRLI}period")
        start = period.findtext(f"{XBRLI}startDate") if period is not None else None
        end = period.findtext(f"{XBRLI}endDate") if period is not None else None
        contexts[ctx.get("id", "")] = {"dims": dims, "start": start, "end": end}

    rows: list[dict] = []
    seen: set[tuple] = set()
    for el in root:
        concept = el.tag.rsplit("}", 1)[-1]
        if concept not in REVENUE_CONCEPTS or not el.text:
            continue
        ctx = contexts.get(el.get("contextRef", ""))
        if not ctx or not ctx["start"] or not ctx["end"]:
            continue
        duration = _days(ctx["start"], ctx["end"]) or 0
        if not 350 <= duration <= 380:
            continue
        dims = dict(ctx["dims"])
        if dims.get("ConsolidationItemsAxis") == "us-gaap:OperatingSegmentsMember":
            dims.pop("ConsolidationItemsAxis")
        if len(dims) != 1:
            continue
        axis, member = next(iter(dims.items()))
        if AXIS_KIND.get(axis) is None or _local(member) not in CANONICAL_MEMBERS:
            continue
        kind, label = CANONICAL_MEMBERS[_local(member)]
        key = (kind, label, ctx["end"])
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "fiscal_year": int(ctx["end"][:4]),
                "period_start": ctx["start"],
                "period_end": ctx["end"],
                "breakdown": kind,
                "member": _local(member),
                "member_label": label,
                "is_rollup": label in ROLLUP_LABELS,
                "concept": concept,
                "value": float(el.text),
                "accession": accession,
                "filed": filed,
            }
        )
    return rows


def latest_segment_revenue(rows: list[dict]) -> list[dict]:
    """For each (fiscal year, breakdown) keep every member from the *latest* filing only.

    Taking whole member sets from one filing keeps recasts consistent: e.g. FY2017 products
    come from the FY2019 10-K (with "Wearables, Home and Accessories") rather than mixing in
    the FY2017 10-K's "Other Products".
    """
    latest: dict[tuple, tuple] = {}
    for r in rows:
        k = (r["fiscal_year"], r["breakdown"])
        latest[k] = max(latest.get(k, ("", "")), (r["filed"], r["accession"]))
    keep = [
        r
        for r in rows
        if (r["filed"], r["accession"]) == latest[(r["fiscal_year"], r["breakdown"])]
    ]
    return sorted(keep, key=lambda r: (r["fiscal_year"], r["breakdown"], r["member_label"]))


# ------------------------------------------------------------- 10-K text mining
_MONEY = r"\$\s?([\d.,]+)\s*(billion|million)"
PURCHASE_OBLIGATION_PATTERNS = (
    # FY2019+: "the Company had manufacturing purchase obligations of $56.2 billion,
    #           with $55.4 billion payable within 12 months"
    (
        "manufacturing",
        re.compile(
            r"had manufacturing purchase obligations of "
            + _MONEY
            + r"(?:, with "
            + _MONEY
            + r" payable within 12 months)?",
            re.I,
        ),
    ),
    # FY2009-FY2018: "the Company had outstanding off-balance sheet third-party manufacturing
    #                 commitments and component purchase commitments of $41.9 billion"
    (
        "manufacturing",
        re.compile(
            r"(?:had )?outstanding off-balance sheet third-party manufacturing commitments and component purchase commitments of "
            + _MONEY,
            re.I,
        ),
    ),
)


# FY2017-FY2020: a contractual-obligations table, in millions, columns
# "<1 year | 1-3 years | 4-5 years | >5 years | Total", e.g.
# "Manufacturing purchase obligations (1) 47,961 1,849 61 40 49,911"
_CELL = r"([\d,]+|—|-)"
OBLIGATION_TABLE = re.compile(
    r"Manufacturing purchase obligations(?: \(\d\))? " + " ".join([_CELL] * 5), re.I
)


def _cell_millions(cell: str) -> float:
    return 0.0 if cell in {"—", "-"} else float(cell.replace(",", "")) * 1e6


def _to_usd(amount: str, scale: str) -> float:
    value = float(amount.replace(",", ""))
    return float(round(value * (1e9 if scale.lower() == "billion" else 1e6)))


def html_to_text(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="ignore")
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", htmllib.unescape(text)).replace("\u200b", "")


def parse_purchase_obligations(raw_html: bytes, *, filing: dict) -> list[dict]:
    """Manufacturing purchase obligations disclosed in the 10-K prose (first match)."""
    text = html_to_text(raw_html)
    for kind, pattern in PURCHASE_OBLIGATION_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        groups = m.groups()
        within = _to_usd(groups[2], groups[3]) if len(groups) > 2 and groups[2] else None
        start = max(0, m.start() - 120)
        return [
            {
                "fiscal_year": int(filing["period_end"][:4]),
                "as_of": filing["period_end"],
                "kind": kind,
                "amount_usd": _to_usd(groups[0], groups[1]),
                "payable_within_12m_usd": within,
                "snippet": text[start : m.end() + 20].strip(),
                "accession": filing["accession"],
                "filed": filing["filed"],
            }
        ]
    m = OBLIGATION_TABLE.search(text)
    if m:
        cells = m.groups()
        return [
            {
                "fiscal_year": int(filing["period_end"][:4]),
                "as_of": filing["period_end"],
                "kind": "manufacturing",
                "amount_usd": _cell_millions(cells[4]),
                "payable_within_12m_usd": _cell_millions(cells[0]),
                "snippet": text[max(0, m.start() - 60) : m.end()].strip(),
                "accession": filing["accession"],
                "filed": filing["filed"],
            }
        ]
    return []
