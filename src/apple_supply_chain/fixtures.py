"""Offline fixtures for tests and CI.

Two kinds, kept apart on purpose:

* **Real, committed** (``tests/fixtures/http/``): small trimmed SEC EDGAR responses for Apple
  (companyfacts, submissions, three 10-K folders). SEC EDGAR content is public information
  that may be redistributed (see DATA_LICENSE.md).
* **SYNTHETIC, generated at test time** (never committed): Apple Supplier List PDFs and UN
  Comtrade responses. Apple's PDFs are copyrighted and Comtrade data may not be
  re-disseminated as-is, so the fixtures for those two sources are fabricated with fictional
  supplier names and seeded random trade values in the exact file formats the parsers read.
  Every synthetic file says so (PDF title/header line, ``"_synthetic": true`` in JSON).
"""

from __future__ import annotations

import json
import random
import shutil
from pathlib import Path

from apple_supply_chain.config import DEFAULT_TRADE_COMMODITIES, DEFAULT_TRADE_REPORTERS
from apple_supply_chain.countries import by_comtrade_code
from apple_supply_chain.fetch import fixture_relpath
from apple_supply_chain.sources import comtrade
from apple_supply_chain.sources.supplier_list import EDITIONS, Edition

SEED = 20261009
FIXTURE_TRADE_YEARS = (2022, 2023, 2024)

# Fictional suppliers: (name, [(country, region list or street address)])
_SUPPLIERS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "Example Precision Components Co., Ltd.",
        [("China mainland", "Guangdong, Jiangsu"), ("Vietnam", "Bac Ninh")],
    ),
    (
        "Sample Display Technologies Inc.",
        [("South Korea", "Gyeonggi-Do"), ("China mainland", "Jiangsu")],
    ),
    (
        "Demo Semiconductor Corporation",
        [("Taiwan", "Taiwan"), ("Japan", "Kumamoto"), ("United States", "Arizona")],
    ),
    ("Placeholder Acoustics Limited", [("China mainland", "Guangdong")]),
    ("Fixture Glass Company", [("United States", "Kentucky"), ("China mainland", "Henan")]),
    ("Mock Battery Holdings", [("China mainland", "Guangdong, Jiangxi"), ("India", "Karnataka")]),
    (
        "Test Circuit Boards Co., Ltd.",
        [("Taiwan", "Taiwan"), ("China mainland", "Jiangsu"), ("Thailand", "Ayutthaya")],
    ),
    ("Synthetic Camera Modules Corp.", [("Japan", "Nagasaki"), ("Thailand", "Lamphun")]),
    (
        "Dummy Assembly Partners Limited",
        [("China mainland", "Henan, Sichuan"), ("India", "Tamil Nadu"), ("Vietnam", "Bac Giang")],
    ),
    ("Specimen Connectors Incorporated", [("Malaysia", "Penang"), ("Philippines", "Laguna")]),
    ("Trial Metals Group", [("China mainland", "Zhejiang")]),
    ("Model Haptics Co.", [("Japan", "Nagano")]),
]


# ------------------------------------------------------------------ PDF writing
def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(pages: list[list[tuple]], width: float = 792.0, height: float = 612.0) -> bytes:
    """Minimal PDF: each page item is ("text", x, top, size, str) or ("line", x0, top0, x1, top1)."""
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    catalog = add(b"")  # filled later
    pages_obj = add(b"")
    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    info = add(
        b"<< /Title (SYNTHETIC test fixture - not Apple data) /Producer (apple-supply-chain-aws fixtures) >>"
    )
    kids = []
    for items in pages:
        ops = []
        for it in items:
            if it[0] == "text":
                _, x, top, size, s = it
                ops.append(
                    f"BT /F1 {size} Tf {x:.2f} {height - top - size:.2f} Td ({_esc(s)}) Tj ET"
                )
            else:
                _, x0, t0, x1, t1 = it
                ops.append(f"0.5 w {x0:.2f} {height - t0:.2f} m {x1:.2f} {height - t1:.2f} l S")
        stream = "\n".join(ops).encode("latin-1")
        content = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        page = add(
            (
                f"<< /Type /Page /Parent {pages_obj} 0 R /MediaBox [0 0 {width} {height}] "
                f"/Resources << /Font << /F1 {font} 0 R >> >> /Contents {content} 0 R >>"
            ).encode()
        )
        kids.append(page)
    objects[catalog - 1] = f"<< /Type /Catalog /Pages {pages_obj} 0 R >>".encode()
    objects[pages_obj - 1] = (
        f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>".encode()
    )
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R /Info {info} 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)


def _edition_suppliers(edition: Edition) -> list[tuple[str, list[tuple[str, str]]]]:
    rng = random.Random(SEED + edition.edition)
    chosen = [s for s in _SUPPLIERS if rng.random() < 0.85] or _SUPPLIERS[:3]
    return chosen


def supplier_list_pdf(edition: Edition) -> bytes:
    suppliers = _edition_suppliers(edition)
    title = f"SYNTHETIC Supplier List {edition.edition} - fictional test data"
    if edition.layout == "address":
        items: list[tuple] = [
            ("text", 48, 40, 14, title),
            ("text", 48, 90, 9, "Supplier Name"),
            ("text", 250, 90, 9, "Address"),
        ]
        top = 110.0
        for name, sites in suppliers:
            for i, (country, regions) in enumerate(sites):
                address = f"No. {10 + i} Example Road, {regions.split(',')[0]}, {country if country != 'China mainland' else 'China'}"
                if len(address) > 60 and i == 0:
                    # wrapped continuation line, as in real address editions
                    head, tail = address.rsplit(", ", 1)
                    items += [("text", 48, top, 9, name), ("text", 250, top, 9, head + ",")]
                    top += 10
                    items.append(("text", 250, top, 9, tail))
                else:
                    items += [("text", 48, top, 9, name), ("text", 250, top, 9, address)]
                top += 17
        items.append(
            (
                "text",
                48,
                top + 10,
                9,
                "Because the suppliers below do not have internal manufacturing sites related to Apple spend, we have provided the locations",
            )
        )
        items.append(
            (
                "text",
                48,
                top + 22,
                9,
                "of their headquarters. As part of our program, Apple audits the facilities providing manufacturing services to our suppliers.",
            )
        )
        items.append(("text", 48, top + 40, 9, "Sample Fabless Design Inc."))
        items.append(("text", 250, top + 40, 9, "1 Example Way, Austin, Texas, USA"))
        return make_pdf([items], width=792, height=max(612, top + 80))
    if edition.layout == "locations_table":
        rows = [
            (name if i == 0 else "", regions.replace(",", ";"), country)
            for name, sites in suppliers
            for i, (country, regions) in enumerate(sites)
        ]
        items = [
            ("text", 76, 40, 12, title),
            ("text", 76, 80, 9, "Supplier Name"),
            ("text", 297, 80, 9, "Primary Locations Where Manufacturing for Apple Occurs"),
        ]
        top, row_h = 100.0, 22.0
        xs = (70, 290, 410, 560)
        items.append(("line", xs[0], top, xs[-1], top))
        for name, regions, country in rows:
            items += [
                ("text", 76, top + 6, 9, name),
                ("text", 297, top + 6, 9, regions),
                ("text", 416, top + 6, 9, country),
            ]
            top += row_h
            items.append(("line", xs[0], top, xs[-1], top))
        items.append(("line", xs[0], 100, xs[0], top))
        items += [("line", x, 100, x, top) for x in xs[1:]]
        return make_pdf([items], width=612, height=max(792, top + 60))
    items = [
        ("text", 36, 40, 14, title),
        ("text", 166, 104, 9, "SUPPLIER NAME"),
        ("text", 550, 104, 9, "PRIMARY LOCATIONS WHERE MANUFACTURING FOR APPLE OCCURS"),
    ]
    top = 130.0
    for name, sites in suppliers:
        for i, (country, regions) in enumerate(sites):
            if i == 0:
                items.append(("text", 166, top, 9, name))
            items += [("text", 550, top, 9, regions), ("text", 940, top, 9, country)]
            top += 30
    return make_pdf([items], width=1224, height=max(792, top + 60))


# --------------------------------------------------------------------- Comtrade
def comtrade_response(dataset: str, year: int) -> bytes:
    rng = random.Random(f"{SEED}-{dataset}-{year}")
    params = comtrade.request_params(
        dataset, year, DEFAULT_TRADE_REPORTERS, DEFAULT_TRADE_COMMODITIES
    )
    cmds = params["cmdCode"].split(",")
    reporters = params["reporterCode"].split(",")
    partners = params["partnerCode"].split(",")
    data = []
    for rep in reporters:
        for par in partners:
            parent = None
            for cmd in cmds:
                if cmd == "851712" and year >= 2022:
                    continue
                if cmd == "851713" and year < 2022:
                    continue
                value = round(rng.uniform(1e8, 2e11), 0)
                if cmd == "8517":
                    parent = value
                elif cmd.startswith("8517") and parent is not None:
                    value = round(parent * rng.uniform(0.3, 0.7), 0)
                country = by_comtrade_code(rep if dataset == "exports" else par)
                data.append(
                    {
                        "typeCode": "C",
                        "freqCode": "A",
                        "refYear": year,
                        "period": str(year),
                        "reporterCode": int(rep),
                        "reporterISO": None,
                        "reporterDesc": None,
                        "flowCode": params["flowCode"],
                        "partnerCode": int(par),
                        "partnerISO": None,
                        "partnerDesc": None,
                        "partner2Code": 0,
                        "classificationCode": "H6",
                        "cmdCode": cmd,
                        "cmdDesc": None,
                        "customsCode": "C00",
                        "motCode": 0,
                        "qtyUnitCode": -1,
                        "qty": 0.0,
                        "netWgt": round(value / 150, 0),
                        "primaryValue": value,
                        "isReported": country is not None,
                        "isAggregate": True,
                    }
                )
    return json.dumps(
        {
            "_synthetic": True,
            "_note": "SYNTHETIC test fixture - values are random, not UN Comtrade data",
            "count": len(data),
            "data": data,
            "error": "",
        },
        indent=1,
    ).encode()


# ----------------------------------------------------------------------- build
def build_fixture_tree(out_dir: Path, committed_dir: Path) -> dict:
    """Assemble ``out_dir/http``: committed real SEC files + generated synthetic files."""
    http = out_dir / "http"
    if http.exists():
        shutil.rmtree(http)
    shutil.copytree(committed_dir / "http", http)
    written = 0
    for ed in EDITIONS:
        path = http / fixture_relpath(ed.url)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(supplier_list_pdf(ed))
        written += 1
    for dataset in ("exports", "us_imports"):
        for year in FIXTURE_TRADE_YEARS:
            params = comtrade.request_params(
                dataset, year, DEFAULT_TRADE_REPORTERS, DEFAULT_TRADE_COMMODITIES
            )
            path = http / fixture_relpath(comtrade.PREVIEW_URL, params)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(comtrade_response(dataset, year))
            written += 1
    return {"http_dir": str(http), "synthetic_files": written}
