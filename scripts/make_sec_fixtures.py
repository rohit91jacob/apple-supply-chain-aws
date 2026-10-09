"""Build the committed, *real* SEC EDGAR fixtures in tests/fixtures/http from a live raw zone.

Usage (after a live ``asc extract --source sec_edgar``)::

    uv run python scripts/make_sec_fixtures.py --data-dir ~/projects/_data/apple-supply-chain-aws

The output is trimmed so every file stays well under the 300 KB pre-commit limit:
companyfacts keeps the pipeline's concepts for periods ending 2021+, submissions keeps the
three latest 10-Ks, each XBRL instance keeps only the net-sales facts and their contexts, and
each 10-K document keeps the paragraph that discloses manufacturing purchase obligations.
"""

from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from apple_supply_chain import raw
from apple_supply_chain.config import Settings
from apple_supply_chain.fetch import fixture_relpath
from apple_supply_chain.sources import edgar
from apple_supply_chain.storage import LocalObjectStore

MIN_END = "2021-01-01"
N_FILINGS = 3
NS = {
    "xbrli": "http://www.xbrl.org/2003/instance",
    "xbrldi": "http://xbrl.org/2006/xbrldi",
    "us-gaap": "http://fasb.org/us-gaap/2025",
    "iso4217": "http://www.xbrl.org/2003/iso4217",
}


def _write(root: Path, url: str, payload: bytes) -> Path:
    path = root / fixture_relpath(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def trim_companyfacts(doc: dict) -> dict:
    keep = {c for cs in edgar.METRIC_CONCEPTS.values() for c in cs}
    gaap = {}
    for concept, fact in doc["facts"]["us-gaap"].items():
        if concept not in keep:
            continue
        units = {
            unit: [v for v in vals if v["end"] >= MIN_END and v.get("form") in edgar.FORMS]
            for unit, vals in fact["units"].items()
        }
        gaap[concept] = {"label": fact.get("label"), "units": units}
    return {"cik": doc["cik"], "entityName": doc["entityName"], "facts": {"us-gaap": gaap}}


def trim_submissions(doc: dict, accessions: set[str]) -> dict:
    recent = doc["filings"]["recent"]
    idx = [i for i, a in enumerate(recent["accessionNumber"]) if a in accessions]
    trimmed = {k: [v[i] for i in idx] for k, v in recent.items() if isinstance(v, list)}
    return {"cik": doc["cik"], "name": doc["name"], "filings": {"recent": trimmed, "files": []}}


def trim_instance(xml: bytes) -> bytes:
    root = ET.fromstring(xml)  # noqa: S314
    xbrli = "{http://www.xbrl.org/2003/instance}"
    facts = [el for el in root if el.tag.rsplit("}", 1)[-1] in edgar.REVENUE_CONCEPTS]
    ctx_ids = {el.get("contextRef") for el in facts}
    out = ET.Element(root.tag, root.attrib)
    for el in root:
        if (el.tag == f"{xbrli}context" and el.get("id") in ctx_ids) or (
            el.tag == f"{xbrli}unit" and el.get("id") in {"usd"}
        ):
            out.append(el)
    for el in facts:
        out.append(el)
    for prefix, uri in NS.items():
        ET.register_namespace(prefix, uri)
    ET.register_namespace("srt", "http://fasb.org/srt/2025")
    return ET.tostring(out, xml_declaration=True, encoding="utf-8")


def trim_document(html: bytes) -> bytes:
    text = edgar.html_to_text(html)
    m = re.search(r"Manufacturing Purchase Obligations.{0,900}?payable within 12 months\.", text)
    snippet = m.group(0) if m else ""
    return (
        "<html><body><!-- Excerpt of the 10-K primary document (SEC EDGAR), trimmed for tests -->"
        f"<p>{snippet}</p></body></html>"
    ).encode()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True, type=Path)
    ap.add_argument("--out", default=Path("tests/fixtures/http"), type=Path)
    args = ap.parse_args()
    settings = Settings(data_dir=args.data_dir.expanduser().resolve())
    store = LocalObjectStore(settings.lake_dir)
    bucket = settings.raw_bucket

    def latest_bytes(dataset: str, item: str) -> bytes:
        ptr = next(p for p in raw.latest(store, bucket, "sec_edgar", dataset) if p["item"] == item)
        return raw.read_latest(store, bucket, ptr)

    facts = json.loads(latest_bytes("companyfacts", "aapl"))
    _write(
        args.out, edgar.COMPANYFACTS_URL, json.dumps(trim_companyfacts(facts), indent=1).encode()
    )

    filings = json.loads(latest_bytes("ten_k_index", "aapl"))[-N_FILINGS:]
    subs = json.loads(latest_bytes("submissions", "aapl"))
    accs = {f["accession"] for f in filings}
    _write(
        args.out, edgar.SUBMISSIONS_URL, json.dumps(trim_submissions(subs, accs), indent=1).encode()
    )

    for f in filings:
        folder = edgar.filing_folder(f["accession"])
        instance_name = f["primary_document"].replace(".htm", "_htm.xml")
        index = {"directory": {"item": [{"name": instance_name}, {"name": f["primary_document"]}]}}
        _write(args.out, f"{folder}/index.json", json.dumps(index, indent=1).encode())
        _write(
            args.out,
            f"{folder}/{instance_name}",
            trim_instance(latest_bytes("ten_k_instance", f["accession"])),
        )
        _write(
            args.out,
            f"{folder}/{f['primary_document']}",
            trim_document(latest_bytes("ten_k_document", f["accession"])),
        )
    sizes = sorted((p.stat().st_size, str(p)) for p in args.out.rglob("*") if p.is_file())
    for size, p in sizes:
        print(f"{size:>8}  {p}")


if __name__ == "__main__":
    main()
