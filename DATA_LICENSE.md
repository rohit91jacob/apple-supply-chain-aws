# Data licences and attribution

The code in this repository is MIT-licensed ([LICENSE](LICENSE)). The data it processes is
not, and almost none of it is committed. This file records, per source, what the terms allow
and what the repository does as a result.

| Source | Owner / terms | Committed in this repo? | What the pipeline does |
|---|---|---|---|
| **SEC EDGAR** XBRL `companyfacts`, `submissions`, 10-K filing folders (instance XML + primary HTML) for Apple Inc. (CIK 0000320193) | U.S. Securities and Exchange Commission. The [SEC privacy and website policy](https://www.sec.gov/privacy) states that information presented on www.sec.gov "is considered public information and may be copied or further distributed by users of the web site without the SEC's permission". Automated access must declare a User-Agent with a contact address and stay under 10 requests/second (same page). | **Yes, small trimmed real extracts** in `tests/fixtures/http/data.sec.gov/` and `tests/fixtures/http/www.sec.gov/` (largest file 106 KB): companyfacts limited to the pipeline's 13 concepts and periods ending 2021+, three 10-K instances reduced to their net-sales facts, and the one paragraph of each 10-K that discloses manufacturing purchase obligations. Rebuilt by `scripts/make_sec_fixtures.py`. | Downloads at runtime (`SEC_USER_AGENT`, about 7 requests/s at most). |
| **Apple Supplier List** (annual PDF, 2014-2024 editions) | © Apple Inc. All rights reserved. No licence to redistribute. | **No.** No PDF and no derived fixture is committed. Test fixtures for this source are **SYNTHETIC** PDFs with fictional supplier names, generated at test time by `apple_supply_chain.fixtures`. | Downloads each edition at runtime: the current one from `supplychainreports.apple`, earlier ones from the Internet Archive's Wayback Machine snapshots of the original apple.com URLs. Parses them in memory/raw storage that is never published. The results site shows only aggregate counts and shares (suppliers per country, HHI), not the list itself. |
| **UN Comtrade** public preview API (`comtradeapi.un.org/public/v1/preview`) | © United Nations. Per the [Policy on Comtrade Data Use](https://uncomtrade.org/docs/policy-on-comtrade-data-use/), data are for internal use and may not be re-disseminated as-is without permission. The [re-dissemination guidance](https://uncomtrade.org/docs/re-dissemination-of-data/) exempts "publication of limited amounts of UN Comtrade data in a few tables, graphs, visualization". Fair use: no scraping, respect rate limits. | **No.** Test fixtures for this source are **SYNTHETIC** JSON responses (seeded random values, `"_synthetic": true`) generated at test time. | Downloads at runtime (one request per year and dataset, spaced 3 s apart). The results site shows a few derived series and shares (limited amounts, as the exemption allows), cited as "UN Comtrade". |
| **US Census Bureau** international trade API (optional) | Works of the US Government are in the public domain. The API now requires a (free) key. | No. Unit tests use a **SYNTHETIC** response in the API's shape. | Runs only when `CENSUS_API_KEY` (or the SSM parameter on AWS) is set; skipped otherwise. |
| **Apple newsroom Q4 condensed consolidated statements** (FY2023-FY2025 PDFs) | © Apple Inc. | No. | Downloaded at runtime by `asc verify` only, to reconcile pipeline figures (see [docs/verification.md](docs/verification.md)). |
| `src/apple_supply_chain/reference/countries.csv` | Compiled for this project from ISO 3166-1 alpha-3 codes, UN M49 sub-regions and UN Comtrade reporter codes (facts). | Yes | Country resolution and the `dim_country` dimension. |

## Attribution to use when you publish results

> Financial data: U.S. Securities and Exchange Commission, EDGAR (Apple Inc. filings).
> Supplier footprint derived from the Apple Supplier List (© Apple Inc.).
> Trade data: UN Comtrade (United Nations Statistics Division).

"Apple", "iPhone", "Mac" and "iPad" are trademarks of Apple Inc. This project has no
affiliation with Apple Inc., the SEC or the United Nations.
