"""Parsers for each source, on committed real SEC fixtures and generated synthetic files."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from apple_supply_chain.countries import resolve, split_trailing_country
from apple_supply_chain.extract import extract_supplier_list
from apple_supply_chain.fetch import FixtureFetcher, fixture_relpath
from apple_supply_chain.fixtures import comtrade_response, make_pdf, supplier_list_pdf
from apple_supply_chain.http import FetchError
from apple_supply_chain.sources import census, comtrade, edgar, supplier_list
from apple_supply_chain.storage import LocalObjectStore

HTTP = Path(__file__).resolve().parents[1] / "fixtures" / "http"


# ------------------------------------------------------------------- countries
@pytest.mark.parametrize(
    ("name", "iso3"),
    [
        ("China mainland", "CHN"),
        ("China", "CHN"),
        ("USA", "USA"),
        ("U.S.", "USA"),
        ("Korea", "KOR"),
        ("South Korea", "KOR"),
        ("Viet Nam", "VNM"),
        ("Other Asia, nes", "TWN"),
        ("Puerto Rico", "PRI"),
    ],
)
def test_resolve_aliases(name, iso3):
    assert resolve(name).iso3 == iso3


def test_split_trailing_country_prefers_longest_match():
    rest, c = split_trailing_country("Gyeonggi-Do, Jeollanam-Do South Korea")
    assert (rest, c.iso3) == ("Gyeonggi-Do, Jeollanam-Do", "KOR")
    rest, c = split_trailing_country("Singapore Singapore")
    assert (rest, c.iso3) == ("Singapore", "SGP")
    assert split_trailing_country("Nowhere Land")[1] is None


# ----------------------------------------------------------------------- fetch
def test_fixture_relpath_is_stable_and_windows_safe():
    url = "https://web.archive.org/web/2019id_/https://www.apple.com/x.pdf"
    path = fixture_relpath(url)
    assert ":" not in path
    assert fixture_relpath(comtrade.PREVIEW_URL, {"b": "2", "a": "1"}) == fixture_relpath(
        comtrade.PREVIEW_URL, {"a": "1", "b": "2"}
    )


def test_fixture_fetcher_missing_file_raises(tmp_path):
    with pytest.raises(FetchError):
        FixtureFetcher(tmp_path).get("https://example.org/missing")


# ----------------------------------------------------------------------- EDGAR
def _read(url: str) -> bytes:
    return (HTTP / fixture_relpath(url)).read_bytes()


def test_companyfacts_latest_facts_one_row_per_period():
    rows = edgar.latest_facts(edgar.parse_companyfacts(json.loads(_read(edgar.COMPANYFACTS_URL))))
    keys = [(r["metric"], r["period_start"], r["period_end"]) for r in rows]
    assert len(keys) == len(set(keys))
    fy25 = {
        r["metric"]: r["value"]
        for r in rows
        if r["period_end"] == "2025-09-27" and r["period_start"] is None
    }
    # Figures as printed in Apple's FY2025 10-K / Q4 FY25 statements (US$ millions)
    assert fy25["inventory"] == 5_718e6
    assert fy25["accounts_payable"] == 69_860e6


def test_latest_facts_prefers_priority_concept_then_latest_filing():
    base = {
        "metric": "revenue",
        "period_start": "2020-01-01",
        "period_end": "2020-12-31",
        "accession": "a",
    }
    rows = [
        {**base, "concept_rank": 1, "value": 1.0, "filed": "2021-01-01"},
        {**base, "concept_rank": 0, "value": 2.0, "filed": "2021-01-01"},
        {**base, "concept_rank": 0, "value": 3.0, "filed": "2022-01-01"},
    ]
    assert edgar.latest_facts(rows)[0]["value"] == 3.0


def test_instance_segments_reconcile_to_total_net_sales():
    folder = edgar.filing_folder("0000320193-25-000079")
    rows = edgar.parse_instance(
        _read(f"{folder}/aapl-20250927_htm.xml"), accession="x", filed="2025-10-31"
    )
    fy25 = [r for r in rows if r["fiscal_year"] == 2025]
    for breakdown in ("segment", "product", "country"):
        total = sum(r["value"] for r in fy25 if r["breakdown"] == breakdown and not r["is_rollup"])
        assert total == pytest.approx(416_161e6), breakdown
    labels = {r["member_label"] for r in fy25 if r["breakdown"] == "segment"}
    assert labels == {"Americas", "Europe", "Greater China", "Japan", "Rest of Asia Pacific"}


def test_latest_segment_revenue_keeps_one_filing_per_year():
    rows = [
        {
            "fiscal_year": 2017,
            "breakdown": "product",
            "member_label": "Other Products",
            "filed": "2017-11-03",
            "accession": "a",
        },
        {
            "fiscal_year": 2017,
            "breakdown": "product",
            "member_label": "Wearables, Home and Accessories",
            "filed": "2019-10-31",
            "accession": "b",
        },
    ]
    kept = edgar.latest_segment_revenue(rows)
    assert [r["member_label"] for r in kept] == ["Wearables, Home and Accessories"]


@pytest.mark.parametrize(
    ("text", "amount", "within"),
    [
        # FY2021+ prose (quoted from Apple's FY2025 10-K)
        (
            "As of September 27, 2025, the Company had manufacturing purchase obligations of $56.2 billion, with $55.4 billion payable within 12 months.",
            56.2e9,
            55.4e9,
        ),
        # FY2009-FY2015 prose (quoted from Apple's FY2015 10-K)
        (
            "the Company had outstanding off-balance sheet third-party manufacturing commitments and component purchase commitments of $29.5 billion.",
            29.5e9,
            None,
        ),
        # FY2017-FY2020 contractual-obligations table, US$ millions (Apple's FY2020 10-K)
        (
            "Leases 1,622 3,097 2,352 5,888 12,959 Manufacturing purchase obligations (1) 47,961 1,849 61 40 49,911 Other",
            49_911e6,
            47_961e6,
        ),
    ],
)
def test_purchase_obligation_patterns(text, amount, within):
    rows = edgar.parse_purchase_obligations(
        f"<p>{text}</p>".encode(),
        filing={"period_end": "2025-09-27", "accession": "x", "filed": "2025-10-31"},
    )
    assert rows[0]["amount_usd"] == pytest.approx(amount)
    assert rows[0]["payable_within_12m_usd"] == (pytest.approx(within) if within else None)


def test_instance_document_prefers_inline_extracted_xml():
    index = {
        "directory": {"item": [{"name": "a_cal.xml"}, {"name": "a.xml"}, {"name": "a_htm.xml"}]}
    }
    assert edgar.instance_document(index) == "a_htm.xml"
    index = {
        "directory": {
            "item": [{"name": "a_cal.xml"}, {"name": "FilingSummary.xml"}, {"name": "a.xml"}]
        }
    }
    assert edgar.instance_document(index) == "a.xml"


# --------------------------------------------------------------- supplier list
@pytest.mark.parametrize("edition", supplier_list.EDITIONS, ids=lambda e: f"{e.edition}-{e.layout}")
def test_supplier_pdf_layouts_parse_synthetic(edition):
    rows = supplier_list.parse_pdf(supplier_list_pdf(edition), edition)
    assert rows, "no rows parsed"
    assert all(r["country_iso3"] for r in rows)
    assert all(r["supplier_name"] and "SYNTHETIC" not in r["supplier_name"] for r in rows)
    if edition.layout == "address":
        hq = [r for r in rows if r["site_type"] == "headquarters"]
        assert [r["supplier_name"] for r in hq] == ["Sample Fabless Design Inc."]
        assert hq[0]["site_count"] == 0
    else:
        assert {r["site_type"] for r in rows} == {"manufacturing"}


def test_supplier_locations_rows_count_regions():
    ed = next(e for e in supplier_list.EDITIONS if e.layout == "locations")
    rows = supplier_list.parse_pdf(supplier_list_pdf(ed), ed)
    battery = [
        r
        for r in rows
        if r["supplier_name"] == "Mock Battery Holdings" and r["country_iso3"] == "CHN"
    ]
    if battery:  # the synthetic edition samples suppliers
        assert battery[0]["site_count"] == 2  # "Guangdong, Jiangxi"


def test_supplier_key_normalises_legal_suffixes():
    assert supplier_list.supplier_key("Foo Precision Co., Ltd.") == supplier_list.supplier_key(
        "FOO Precision Company Limited"
    )
    assert supplier_list.supplier_key("AT&S AG") == "at and s"


# --------------------------------------------------------------------- Comtrade
def test_comtrade_parse_synthetic_and_child_le_parent():
    rows = comtrade.parse(comtrade_response("exports", 2023), dataset="exports")
    assert {r["reporter_iso3"] for r in rows} >= {"CHN", "IND", "VNM", "TWN"}
    parent = {(r["reporter_code"]): r["primary_value_usd"] for r in rows if r["cmd_code"] == "8517"}
    cellular: dict = {}
    for r in rows:
        if r["cmd_code"] in ("851713", "851714"):
            cellular[r["reporter_code"]] = (
                cellular.get(r["reporter_code"], 0) + r["primary_value_usd"]
            )
    assert {r["cmd_code"] for r in rows} >= {"851713", "851714"}
    for code, value in cellular.items():
        assert value <= parent[code]
    # HS 2017 years carry the undivided 851712 code instead
    old = comtrade.parse(comtrade_response("exports", 2019), dataset="exports")
    assert {r["cmd_code"] for r in old} & {"851713", "851714"} == set()


def test_comtrade_error_and_cap():
    with pytest.raises(comtrade.ComtradeError):
        comtrade.parse(
            b'{"error": "Maximum number of periods for preview is 1"}', dataset="exports"
        )
    capped = json.dumps({"data": [{}] * comtrade.MAX_RECORDS, "error": ""}).encode()
    with pytest.raises(comtrade.ComtradeError):
        comtrade.parse(capped, dataset="exports")


def test_comtrade_request_params_one_period():
    p = comtrade.request_params("us_imports", 2024, ("156", "842", "699"), ("8517",))
    assert p["period"] == "2024" and p["reporterCode"] == "842" and p["partnerCode"] == "156,699"
    with pytest.raises(ValueError, match="unknown"):
        comtrade.request_params("nope", 2024, ("156",), ("8517",))


# ----------------------------------------------------------------------- Census
def test_census_parse_skips_aggregates():
    # SYNTHETIC response in the Census API's array-of-arrays shape
    payload = json.dumps(
        [
            ["CTY_CODE", "CTY_NAME", "GEN_VAL_YR", "time"],
            ["-", "TOTAL FOR ALL COUNTRIES", "100", "2024-12"],
            ["0003", "EUROPEAN UNION", "10", "2024-12"],
            ["5700", "CHINA", "60", "2024-12"],
            ["5330", "INDIA", "20", "2024-12"],
        ]
    ).encode()
    rows = census.parse(payload, year=2024, hs4="8517")
    assert [(r["partner_iso3"], r["general_imports_usd"]) for r in rows] == [
        ("CHN", 60.0),
        ("IND", 20.0),
    ]


def test_census_request_includes_key_param():
    assert census.request_params(2024, "8517", "k")["key"] == "k"


def test_make_pdf_is_a_pdf():
    pdf = make_pdf([[("text", 10, 10, 9, "hello (world)")]])
    assert pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF")


def test_comtrade_canonical_ignores_elapsed_time():
    a = b'{"elapsedTime": "0.25 secs", "count": 0, "data": [], "error": ""}'
    b = b'{"error": "", "data": [], "count": 0, "elapsedTime": "1.03 secs"}'
    assert comtrade.canonical(a) == comtrade.canonical(b)


def test_stated_fiscal_year_reads_fy_editions_only():
    live = supplier_list.EDITIONS[-1]
    assert supplier_list.stated_fiscal_year(supplier_list_pdf(live)) == live.fiscal_year
    address = next(e for e in supplier_list.EDITIONS if e.layout == "address")
    assert supplier_list.stated_fiscal_year(supplier_list_pdf(address)) is None


class _UrlFetcher:
    """Serves fixed bodies by URL; any other URL is refused like a bot challenge."""

    def __init__(self, bodies: dict[str, bytes]) -> None:
        self.bodies = bodies

    def get(self, url: str, params: dict | None = None) -> bytes:
        if url not in self.bodies:
            raise FetchError(f"GET {url} failed: HTTP 403")
        return self.bodies[url]


def _only_live_edition(monkeypatch):
    live = supplier_list.EDITIONS[-1]
    monkeypatch.setattr(supplier_list, "EDITIONS", (live,))
    return live


def _landed_pdfs(settings, store) -> list[str]:
    return [k for k in store.list_keys(settings.raw_bucket) if k.endswith(".pdf")]


def test_a_newer_list_on_the_current_edition_page_is_reported_not_landed(
    fixture_settings, monkeypatch
):
    live = _only_live_edition(monkeypatch)
    newer = supplier_list_pdf(replace(live, fiscal_year=live.fiscal_year + 1))
    store = LocalObjectStore(fixture_settings.data_dir / "lake")
    bodies = {live.url: supplier_list_pdf(live), supplier_list.CURRENT_EDITION_URL: newer}
    summary = extract_supplier_list(fixture_settings, store, _UrlFetcher(bodies))
    assert summary["newer_edition"] == live.fiscal_year + 1
    assert summary["new"] == 1
    assert len(_landed_pdfs(fixture_settings, store)) == 1


def test_a_refused_current_edition_page_does_not_fail_the_extract(fixture_settings, monkeypatch):
    live = _only_live_edition(monkeypatch)
    store = LocalObjectStore(fixture_settings.data_dir / "lake")
    fetcher = _UrlFetcher({live.url: supplier_list_pdf(live)})
    summary = extract_supplier_list(fixture_settings, store, fetcher)
    assert summary["newer_edition"] is None
    assert summary["new"] == 1
    # Landed editions are fixed files, so a rerun fetches nothing.
    again = extract_supplier_list(fixture_settings, store, _UrlFetcher({}))
    assert again["cached"] == 1


def test_an_edition_url_serving_another_fiscal_year_is_refused(fixture_settings, monkeypatch):
    live = _only_live_edition(monkeypatch)
    newer = supplier_list_pdf(replace(live, fiscal_year=live.fiscal_year + 1))
    store = LocalObjectStore(fixture_settings.data_dir / "lake")
    with pytest.raises(FetchError, match=f"fiscal year {live.fiscal_year + 1}, not"):
        extract_supplier_list(fixture_settings, store, _UrlFetcher({live.url: newer}))
    assert not _landed_pdfs(fixture_settings, store), "nothing may be landed"
