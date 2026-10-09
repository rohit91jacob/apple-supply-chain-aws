# Verification

Everything below comes from runs on 9 October 2026 against the live sources, built with
`asc pipeline` (local emulation; see the README for what "local" means here) and checked with
`asc verify`. The machine-readable result is [`verification_results.json`](verification_results.json).

## 1. Financial statements vs Apple's own published statements: 114 / 114 figures match

**What is compared.** With each Q4 earnings release Apple posts condensed consolidated
statements as a PDF on its newsroom. They are a separate publication from the XBRL the pipeline
reads, so matching them checks the whole chain: companyfacts and instance parsing, the
"latest filing wins" restatement rule, the member canonicalisation, fiscal-year assignment and
the dbt marts.

| Document (downloaded at runtime, not stored) | Fiscal years covered |
|---|---|
| [FY25 Q4 Consolidated Financial Statements](https://www.apple.com/newsroom/pdfs/fy2025-q4/FY25_Q4_Consolidated_Financial_Statements.pdf) | FY2025, FY2024 |
| [FY24 Q4 Consolidated Financial Statements](https://www.apple.com/newsroom/pdfs/fy2024-q4/FY24_Q4_Consolidated_Financial_Statements.pdf) | FY2024, FY2023 |
| [FY23 Q4 Consolidated Financial Statements](https://www.apple.com/newsroom/pdfs/fy2023-q4/FY23_Q4_Consolidated_Financial_Statements.pdf) | FY2023, FY2022 |

19 line items per fiscal-year column, 6 columns: **114 comparisons, 114 exact matches** (to the
US$ million Apple prints; tolerance ±0.5 M for rounding). Line items: total net sales, total
cost of sales, gross margin; net sales of the five reportable segments; net sales of iPhone, Mac,
iPad, Wearables/Home/Accessories and Services; accounts receivable, vendor non-trade
receivables, inventories, PP&E net, accounts payable; and capital expenditure (cash-flow
statement).

A sample (US$ millions; "pipeline" = `marts.fct_working_capital_annual` / `marts.mart_revenue_mix`):

| Line item | FY2025 published | FY2025 pipeline | FY2022 published | FY2022 pipeline |
|---|---:|---:|---:|---:|
| Total net sales | 416,161 | 416,161 | 394,328 | 394,328 |
| Total cost of sales | 220,960 | 220,960 | 223,546 | 223,546 |
| Inventories | 5,718 | 5,718 | 4,946 | 4,946 |
| Accounts payable | 69,860 | 69,860 | 64,115 | 64,115 |
| Vendor non-trade receivables | 33,180 | 33,180 | 32,748 | 32,748 |
| Greater China net sales | 64,377 | 64,377 | 74,200 | 74,200 |
| iPhone net sales | 209,586 | 209,586 | 205,489 | 205,489 |
| Services net sales | 109,158 | 109,158 | 78,129 | 78,129 |
| Payments for PP&E | 12,715 | 12,715 | 10,708 | 10,708 |

The derived ratios follow mechanically from these inputs. Example, FY2025:
DIO = ((5,718 + 7,286) / 2) / 220,960 × 364 = **10.7 days**;
DPO = ((69,860 + 68,960) / 2) / 220,960 × 364 = **114.3 days**;
CCC = DIO + DSO − DPO = **−71.6 days**. Apple does not publish DIO/DPO, so there is no official
figure to compare these to; the inputs are what is verified.

**Not independently verified.** Manufacturing purchase obligations ($56.2 B at FY2025) are read
from the 10-K text itself, so the only "published" comparison would be the same sentence. The
FY2010-FY2025 series was spot-checked by hand against the 10-K paragraphs printed in
`silver.purchase_obligations.snippet`. FY2009 is missing (its 10-K uses a different table).

## 2. Internal reconciliations that run on every build (data-quality gates)

| Check (layer) | Result on the live build |
|---|---|
| Segment, product-category and country net sales each add up to total net sales within 0.5%, every fiscal year FY2013-FY2025 (silver, error) | pass: 13 years × 3 breakdowns |
| Same, FY2008-FY2012 (silver, warning) | **warning, 2 violations**: FY2011 and FY2012 product categories do not add up, because pre-FY2013 filings used other categories (iPod, iTunes/Software/Services, Accessories) that are deliberately not mapped. The revenue-mix mart starts at FY2013 for this reason. |
| Quarterly cost of sales adds up to the annual figure where all four quarters exist (dbt test) | pass |
| 6-digit cellular-phone trade values never exceed their HS 8517 parent (silver, error) | pass |
| HHI computed by networkx equals HHI computed by dbt SQL, every edition (gold, error) | pass, 9 editions, difference < 1e-9 |
| Single-country supplier counts agree between networkx and dbt (gold, error) | pass |
| Every silver row traces to a raw object (sha256 in `silver.raw_manifest`) (silver, error) | pass |
| dbt build: 17 models, 59 data tests | 76 / 76 nodes pass |

## 3. Supplier List parsing vs Apple's own statements

Apple states that the 2014-2019 lists cover its "top 200 suppliers".

| Edition | Apple's statement | Distinct suppliers parsed | Facility rows | Unresolved countries |
|---|---|---:|---:|---:|
| 2014 (spend CY2013) | top 200 suppliers | 200 | 802 | 0 |
| 2015 (CY2014) | top 200 suppliers | 200 | 761 | 0 |
| 2017 (CY2016) | top 200 suppliers | **201** | 769 | 0 |
| 2018 (CY2017) | top 200 suppliers | 200 | 777 | 0 |
| 2019 (FY2018) | top 200 suppliers | 200 | 808 | 0 |
| 2021 (FY2020) | "98 percent of direct spend" | 200 | 402 supplier-country rows | 0 |
| 2022 (FY2021) | " | 191 | 474 | 0 |
| 2023 (FY2022) | " | 188 | 432 | 0 |
| 2024 (FY2023) | " | 187 | 470 | 0 |

**Mismatch, reported as is:** the 2017 edition parses to 201 distinct names. I looked for a
split or duplicated name (normalised-key collisions, prefix matches, names absent from the
neighbouring editions) and found none; the 18 names unique to that edition are all real
companies. I have not established whether the PDF lists 201 names or whether one company
appears under two legal names, so the count is left at 201.

The 2014, 2015 and 2019 editions also list 10, 12 and 9 suppliers by **headquarters** address because they
"do not have internal manufacturing sites related to Apple spend"; those rows count as
suppliers but contribute 0 sites.

## 4. Trade flows (UN Comtrade): internally consistent, not reconciled to an outside publication

The trade marts are reproduced from UN Comtrade's own reporter-declared values; no second,
independent publication of the same series was reconciled. What was checked:

* Child codes never exceed their parent (above).
* The HS 2017 → HS 2022 change is handled explicitly. HS 2022 split 851712 ("telephones for
  cellular networks") into 851713 (smartphones) and 851714 (other cellular/wireless
  telephones), so `cellular_phones` is 851712 to 2021 and 851713 + 851714 from 2022; the
  codes never overlap in a year. (An earlier build used 851713 alone; 851714 is small - US
  2024 imports of it were US$0.31 B from China mainland, 0.09 B from Viet Nam and 0.01 B from
  India - and moved the US-import shares quoted in the README by at most 0.2 points.)
* Spot check of the mart against a separate, hand-issued preview query (US imports, 2024,
  partners 156/699/704, codes 8517/851713/851714): Viet Nam 851713 = US$2.18 B + 851714 =
  US$0.09 B, matching the mart's 2.27 B for Viet Nam; China mainland 41.73 + 0.31 = 42.05 B,
  matching. This is the same publisher, so it checks the pipeline, not Comtrade.
* Coverage gaps are visible rather than filled: Viet Nam had not reported 2024 at build time,
  so its 2024 exports are absent (its 2024 position is visible only in the US-import mirror).

A useful next step would be a mirror comparison (e.g. Viet Nam's reported exports to the US
vs US-reported imports from Viet Nam), which needs one extra bilateral query per year.

## 5. Rerun / idempotency (live)

| Run | Raw objects new | unchanged / cached | Marts |
|---|---:|---:|---|
| Cold rebuild of silver, warehouse and gold from the cached raw zone (`live-1`, 240 s) | 0 | 4 unchanged + 25 cached (SEC, PDFs), 20 Comtrade unchanged | built, DQ pass (the one expected warning above) |
| Immediate rerun (`live-2`, 224 s) | 0 | same | identical |

The very first live download (empty raw zone) took about 8 minutes, most of it Comtrade
back-off after HTTP 429 responses; the extractor now spaces Comtrade requests 3 s apart. A
bug found during this verification: Comtrade responses carry a per-request `elapsedTime`
field, so identical data hashed differently and every run landed 20 "new" objects. Payloads are
now canonicalised (that field dropped, keys sorted) before hashing; two consecutive extracts
then reported 20 new followed by 20 unchanged.
