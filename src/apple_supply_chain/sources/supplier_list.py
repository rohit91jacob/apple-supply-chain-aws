"""Apple Supplier List (annual PDF, Apple copyright): download at runtime and parse.

The PDFs are never committed. Apple only links the current edition, so earlier editions
are fetched from the Internet Archive's Wayback Machine snapshots of the same apple.com
URLs (``id_`` = the original bytes as captured).

Two layouts exist:

* ``address`` (2014-2019 editions): one row per manufacturing **facility**, with a street
  address ending in the country.
* ``locations`` (2021 edition onwards): one row per supplier x **country**, listing the
  provinces/states where manufacturing for Apple occurs.

Because the unit changed, the comparable cross-edition measure is the *supplier-country
pair*. Facility counts are only available for the address editions; for the locations
editions ``site_count`` counts the listed provinces/states (a lower bound on facilities).
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

from apple_supply_chain.countries import Country, resolve, split_trailing_country


@dataclass(frozen=True)
class Edition:
    edition: int  # year the list was published
    spend_year: str  # period the spend covers, as Apple states it
    fiscal_year: int  # numeric year used for trends
    layout: str  # "address" | "locations" | "locations_table" (ruled table, 2021 only)
    url: str
    original_url: str


_WB = "https://web.archive.org/web/{ts}id_/{url}"
_SR = "https://www.apple.com/supplier-responsibility/pdf/"

EDITIONS: tuple[Edition, ...] = (
    Edition(
        2014,
        "CY2013",
        2013,
        "address",
        _WB.format(ts="20140628034146", url=_SR + "Apple_Supplier_List_2014.pdf"),
        _SR + "Apple_Supplier_List_2014.pdf",
    ),
    Edition(
        2015,
        "CY2014",
        2014,
        "address",
        _WB.format(ts="20150402173808", url=_SR + "Apple_Supplier_List_2015.pdf"),
        _SR + "Apple_Supplier_List_2015.pdf",
    ),
    Edition(
        2017,
        "CY2016",
        2016,
        "address",
        _WB.format(
            ts="20170327222645",
            url="http://images.apple.com/supplier-responsibility/pdf/Apple-Supplier-List.pdf",
        ),
        "https://images.apple.com/supplier-responsibility/pdf/Apple-Supplier-List.pdf",
    ),
    Edition(
        2018,
        "CY2017",
        2017,
        "address",
        _WB.format(ts="20180412230419", url=_SR + "Apple-Supplier-List.pdf"),
        _SR + "Apple-Supplier-List.pdf",
    ),
    Edition(
        2019,
        "FY2018",
        2018,
        "address",
        _WB.format(ts="20190315115545", url=_SR + "Apple-Supplier-List.pdf"),
        _SR + "Apple-Supplier-List.pdf",
    ),
    Edition(
        2021,
        "FY2020",
        2020,
        "locations_table",
        _WB.format(ts="20210602061142", url=_SR + "Apple-Supplier-List.pdf"),
        _SR + "Apple-Supplier-List.pdf",
    ),
    Edition(
        2022,
        "FY2021",
        2021,
        "locations",
        _WB.format(ts="20230421084807", url=_SR + "Apple-Supplier-List.pdf"),
        _SR + "Apple-Supplier-List.pdf",
    ),
    Edition(
        2023,
        "FY2022",
        2022,
        "locations",
        _WB.format(ts="20230519163116", url=_SR + "Apple-Supplier-List.pdf"),
        _SR + "Apple-Supplier-List.pdf",
    ),
    Edition(
        2024,
        "FY2023",
        2023,
        "locations",
        # The dated file the current-edition page redirects to (byte-identical to it).
        "https://s203.q4cdn.com/367071867/files/doc_downloads/2024/04/Apple-Supplier-List.pdf",
        "https://www.supplychainreports.apple/Apple-Supplier-List",
    ),
)

# Always redirects to the newest list. It is only checked for a newer edition, never landed,
# and it may refuse automated clients (a bot challenge to CI runners).
CURRENT_EDITION_URL = "https://www.supplychainreports.apple/Apple-Supplier-List"

_HEADER_FIRST = {"supplier"}
_SECOND_COLUMN = {"address", "primary", "manufacturing", "facility"}
_FOOTER = re.compile(
    r"(©|all rights reserved|supplier responsibility|^supplier list(\s+\d+)?$|^\d+$|"
    r"suppliers designated with|this list (reflects|is)|trademarks of|fiscal year \d{4}\s*\d*$)",
    re.I,
)


_HQ_NOTE = re.compile(r"because the suppliers below do not have internal manufacturing")
_HQ_SKIP = re.compile(
    r"(of their headquarters|audits the facilities|headquarter address|^\s*global name\s*$)"
)


@dataclass
class _Line:
    top: float
    name: str
    rest: str


def _group_lines(words: list[dict], tol: float = 2.5) -> list[list[dict]]:
    lines: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(lines[-1][0]["top"] - w["top"]) <= tol:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [sorted(line, key=lambda w: w["x0"]) for line in lines]


def _page_lines(page) -> list[_Line]:
    words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
    grouped = _group_lines(words)
    name_x0 = col2_x0 = None
    header_bottom = 0.0
    for line in grouped:
        texts = [w["text"].lower() for w in line]
        if (texts and texts[0] in _HEADER_FIRST | {"clean"}) or "supplier" in texts:
            col2 = [w for w in line if w["text"].lower().strip(":") in _SECOND_COLUMN]
            sup = [w for w in line if w["text"].lower() == "supplier"]
            if col2 and sup:
                # "CLEAN ENERGY PROGRAM SUPPLIER* | SUPPLIER NAME": the name column is the
                # last "SUPPLIER" before the second column header.
                left = [w for w in sup if w["x0"] < col2[0]["x0"]]
                name_x0 = left[-1]["x0"] if left else sup[0]["x0"]
                col2_x0 = col2[0]["x0"]
                header_bottom = max(w["bottom"] for w in line)
                break
    if col2_x0 is None or name_x0 is None:
        return []
    out: list[_Line] = []
    for line in grouped:
        if line[0]["top"] <= header_bottom + 1:
            continue
        name = " ".join(w["text"] for w in line if name_x0 - 4 <= w["x0"] < col2_x0 - 3)
        rest = " ".join(w["text"] for w in line if w["x0"] >= col2_x0 - 3)
        text = f"{name} {rest}".strip()
        if not text or _FOOTER.search(text):
            continue
        # Header rows repeated mid-page in some editions
        if name.lower().startswith("supplier name"):
            continue
        out.append(_Line(line[0]["top"], name.strip(), rest.strip()))
    return out


def _address_country(address: str) -> Country | None:
    parts = [p.strip() for p in re.split(r",", address) if p.strip()]
    if not parts:
        return None
    last = parts[-1]
    country = resolve(last)
    if country is None:
        _, country = split_trailing_country(last)
    return country


def _parse_address(lines: list[_Line]) -> list[dict]:
    rows: list[dict] = []
    current: dict | None = None
    site_type = "manufacturing"
    for ln in lines:
        text = f"{ln.name} {ln.rest}".lower()
        if _HQ_NOTE.search(text):
            # Suppliers without own manufacturing sites are listed by headquarters address.
            site_type = "headquarters"
            current = None
            continue
        if site_type == "headquarters" and _HQ_SKIP.search(text):
            continue
        complete = current is not None and _address_country(current["location"]) is not None
        # A row is complete once its address ends in a known country; until then, further
        # lines (even ones with text in the name column) are wrapped continuations.
        if ln.name and ln.rest and (current is None or complete):
            current = {"supplier": ln.name, "location": ln.rest, "site_type": site_type}
            rows.append(current)
        elif current is not None:
            if ln.name and not complete:
                current["supplier"] = f"{current['supplier']} {ln.name}"
            elif ln.name and complete and not ln.rest:
                # wrapped supplier name on its own line after a complete address
                current["supplier"] = f"{current['supplier']} {ln.name}"
            if ln.rest:
                current["location"] = f"{current['location']} {ln.rest}".replace("- ", "-")

    out = []
    for r in rows:
        country = _address_country(r["location"])
        out.append(
            {
                "supplier_name": _clean_name(r["supplier"]),
                "location": _fix_hyphenation(r["location"]),
                "country_raw": r["location"].split(",")[-1].strip(),
                "country": country,
                "site_type": r["site_type"],
                "site_count": 1 if r["site_type"] == "manufacturing" else 0,
            }
        )
    return out


def _parse_locations_lines(lines: list[_Line]) -> list[dict]:
    rows: list[dict] = []
    supplier = ""
    pending_rest = ""
    pending_name = ""
    for ln in lines:
        if ln.name and not ln.rest:
            pending_name = f"{pending_name} {ln.name}".strip()
            continue
        if ln.name:
            name = f"{pending_name} {ln.name}".strip() if pending_name else ln.name
            pending_name = ""
            # a name on a row starts a new supplier unless the previous row was a
            # location-only wrap (handled through pending_rest)
            supplier = name
        elif pending_name:
            supplier = f"{supplier} {pending_name}".strip() if supplier else pending_name
            pending_name = ""
        rest = f"{pending_rest} {ln.rest}".strip()
        regions, country = split_trailing_country(rest)
        if country is None:
            pending_rest = rest
            continue
        pending_rest = ""
        rows.append(_location_row(supplier, regions, country))
    return rows


def _parse_locations_tables(pdf) -> list[dict]:
    """Ruled-table editions (2021): name cells span several rows (None = same supplier)."""
    rows: list[dict] = []
    supplier = ""
    for page in pdf.pages:
        for table in page.extract_tables():
            for cells in table:
                cells = [(c or "").replace("\n", " ").strip() for c in cells]
                if not any(cells) or "primary locations" in " ".join(cells).lower():
                    continue
                cells += [""] * (3 - len(cells))
                name, regions, country_text = cells[0], cells[1], cells[2]
                if name:
                    supplier = name
                country = resolve(country_text) if country_text else None
                if country is None:
                    regions, country = split_trailing_country(f"{regions} {country_text}".strip())
                if country is None or not supplier:
                    continue
                rows.append(_location_row(supplier, regions, country))
    return rows


def _location_row(supplier: str, regions: str, country: Country) -> dict:
    parts = [p.strip() for p in re.split(r"[;,]", regions) if p.strip()]
    return {
        "supplier_name": _clean_name(supplier),
        "location": regions,
        "country_raw": country.name,
        "country": country,
        "site_type": "manufacturing",
        "site_count": max(len(parts), 1),
    }


def _fix_hyphenation(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _clean_name(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip(" *")


def supplier_key(name: str) -> str:
    """A stable join key across editions (case, punctuation and legal suffixes removed)."""
    key = name.lower().replace("&", " and ")
    key = re.sub(r"\([^)]*\)", " ", key)
    key = re.sub(r"[^a-z0-9 ]+", " ", key)
    suffixes = r"\b(incorporated|inc|corporation|corp|company|co|limited|ltd|plc|ag|se|sa|nv|bv|gmbh|holdings?|group|llc|lp|kk|technology|technologies)\b"
    key = re.sub(suffixes, " ", key)
    return re.sub(r"\s+", " ", key).strip()


_STATED_FY = re.compile(r"fiscal\s+year\s+(\d{4})", re.I)


def stated_fiscal_year(pdf_bytes: bytes) -> int | None:
    """The fiscal year an FY-era list says it covers, or None if it states none (or several).

    Every edition from 2019 on prints "fiscal year YYYY" on its first or last page. The live
    URL always serves the newest list, so this is how a new edition is told apart from the
    configured one.
    """
    import pdfplumber  # noqa: PLC0415 - heavy import, only needed here

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        pages = pdf.pages[:2] + pdf.pages[-1:]
        text = " ".join(page.extract_text() or "" for page in pages)
    years = {int(y) for y in _STATED_FY.findall(text)}
    return years.pop() if len(years) == 1 else None


def parse_pdf(pdf_bytes: bytes, edition: Edition) -> list[dict]:
    """Parse one edition into rows (supplier, location text, country, site_count)."""
    import pdfplumber  # noqa: PLC0415 - heavy import, only needed here

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        if edition.layout == "address":
            lines = [ln for page in pdf.pages for ln in _page_lines(page)]
            rows = _parse_address(lines)
        elif edition.layout == "locations_table":
            rows = _parse_locations_tables(pdf)
        else:
            lines = [ln for page in pdf.pages for ln in _page_lines(page)]
            rows = _parse_locations_lines(lines)
    out = []
    for i, r in enumerate(rows):
        c: Country | None = r.pop("country")
        out.append(
            {
                "edition": edition.edition,
                "spend_year": edition.spend_year,
                "fiscal_year": edition.fiscal_year,
                "layout": "address" if edition.layout == "address" else "locations",
                "row_number": i + 1,
                **r,
                "supplier_key": supplier_key(r["supplier_name"]),
                "country_iso3": c.iso3 if c else None,
                "country_name": c.name if c else None,
                "region": c.region if c else None,
            }
        )
    return out
