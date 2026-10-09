# Data dictionary

Layers: **raw** (S3 objects, unchanged) → **silver** (Iceberg, namespace `silver` / Glue
`asc_silver`) → **staging / intermediate** (dbt views) → **marts** (dbt tables; exported to
Iceberg `gold`) and **graph** (networkx outputs; exported to Iceberg `gold`). Money is US$ (not
millions), shares are 0-1, days are calendar days.

## Raw zone (`asc-raw` bucket)

```
source=<source>/dataset=<dataset>/item=<item>/<sha256>.<ext>   immutable payload
source=<source>/dataset=<dataset>/item=<item>/_latest.json     pointer: sha256, key, bytes, source_url, fetched_at
```

| source / dataset | item | Content |
|---|---|---|
| `sec_edgar/companyfacts` | `aapl` | `data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json` |
| `sec_edgar/submissions` | `aapl` | filing index (`data.sec.gov/submissions`) |
| `sec_edgar/ten_k_index` | `aapl` | derived list of 10-K filings with XBRL since FY2009 |
| `sec_edgar/ten_k_instance` | accession | 10-K XBRL instance (`*_htm.xml` or `aapl-YYYYMMDD.xml`) |
| `sec_edgar/ten_k_document` | accession | 10-K primary HTML document |
| `apple_supplier_list/pdf` | edition year | Supplier List PDF (Apple copyright; private bucket only) |
| `un_comtrade/exports`, `un_comtrade/us_imports` | year | preview API response, canonicalised (volatile `elapsedTime` removed, keys sorted) |
| `us_census/imports_hs` | `YYYY-HS4` | optional; API key never stored (recorded URL omits it) |

## Silver (Iceberg)

### `silver.financial_facts`
One row per metric and period (best concept, latest filing wins - restatements replace originals).

| Column | Type | Description |
|---|---|---|
| metric | string | `revenue`, `cost_of_sales`, `gross_profit`, `inventory`, `accounts_payable`, `accounts_receivable`, `vendor_nontrade_receivables`, `unconditional_purchase_obligations`, `ppe_net`, `capex` |
| concept | string | us-gaap concept used (e.g. `RevenueFromContractWithCustomerExcludingAssessedTax`, falling back to `SalesRevenueNet` before FY2018) |
| unit | string | `USD` |
| period_start | date | null for instants (balance-sheet values) |
| period_end | date | |
| duration_days | int | `period_end - period_start` (exclusive count: 363 for a 52-week year) |
| value | double | US$ |
| filing_fy, filing_fp, form, filed, accession | | the filing that reported the value |
| frame | string | SEC frame id when present (e.g. `CY2024`) |
| source_sha256 | string | raw object lineage |

### `silver.segment_revenue`
Net sales by breakdown from 10-K XBRL instances. For each (fiscal year, breakdown) every member
comes from the **latest** filing that reports that year, so recasts stay internally consistent.

| Column | Description |
|---|---|
| fiscal_year | year of `period_end` (Apple's fiscal year ends late September) |
| breakdown | `segment` (Americas, Europe, Greater China, Japan, Rest of Asia Pacific; Retail / Asia Pacific before the FY2015 recast), `product` (iPhone, Mac, iPad, Wearables Home and Accessories / Other Products, Services, plus the `Products` roll-up), `country` (United States, China, Other countries) |
| member | XBRL member local name (e.g. `GreaterChinaSegmentMember`) |
| member_label | canonical label (old and new member names map to one label) |
| is_rollup | true for `Products` (excluded from sums) |
| value | US$ |
| accession, filed, source_sha256 | lineage |

### `silver.purchase_obligations`
Manufacturing purchase obligations extracted from 10-K text (three phrasings: FY2010-FY2016
prose, FY2017-FY2020 contractual-obligations table, FY2021+ prose).

| Column | Description |
|---|---|
| fiscal_year, as_of | fiscal year and balance date |
| kind | `manufacturing` |
| amount_usd | total obligation |
| payable_within_12m_usd | null where the 10-K does not split it (FY2010-FY2016) |
| snippet | the matched text, for audit |

### `silver.supplier_sites`
One row per parsed Supplier List row.

| Column | Description |
|---|---|
| edition | publication year (2014, 2015, 2017, 2018, 2019, 2021, 2022, 2023, 2024) |
| spend_year / fiscal_year | the spend period Apple states (CY2013 ... FY2023) / its numeric year |
| layout | `address` (2014-2019: one row per facility address) or `locations` (2021+: one row per supplier x country, listing provinces/states) |
| row_number | position in the edition |
| supplier_name | as printed |
| supplier_key | normalised join key (case, punctuation, legal suffixes removed) |
| location | street address (address layout) or province/state list (locations layout) |
| country_raw / country_iso3 / country_name / region | country as printed, resolved ISO3, canonical name, UN M49 sub-region |
| site_type | `manufacturing`, or `headquarters` for suppliers Apple lists by HQ because they have no own manufacturing sites |
| site_count | 1 per facility (address), number of provinces/states listed (locations), 0 for headquarters rows |

### `silver.trade_flows`
UN Comtrade preview rows (plain totals only: customs code C00, all transport modes, no second partner).

| Column | Description |
|---|---|
| dataset | `exports` (reporter → World) or `us_imports` (USA ← partner) |
| year | calendar year |
| reporter_code / reporter_iso3 / reporter_name | UN Comtrade reporter (490 "Other Asia, nes" is resolved to Taiwan) |
| partner_code / partner_iso3 / partner_name | `WLD` / World for exports |
| cmd_code, cmd_desc, classification | `8517`, `8471`, `851712` (HS2007-2017 cellular phones), `851713` (HS2022 smartphones), `851714` (HS2022 other cellular/wireless telephones); HS edition (H4/H5/H6) |
| primary_value_usd, net_weight_kg, qty, qty_unit | as reported or estimated by UNSD |
| is_reported, is_aggregate | Comtrade flags |

### Other silver tables
* `silver.census_imports` - optional US Census general imports by country (`year, hs4, census_cty_code, country_name_raw, partner_iso3, general_imports_usd`); empty without a key.
* `silver.ref_country` - `iso3, name, comtrade_code, region` (51 countries).
* `silver.raw_manifest` - one row per raw pointer (`source, dataset, item, sha256, key, bytes, source_url, fetched_at`).

## Marts (dbt; `marts` schema, Iceberg `gold`)

### `fct_working_capital_annual` (grain: fiscal year)
| Column | Definition |
|---|---|
| revenue_usd, cost_of_sales_usd, gross_profit_usd, capex_usd | annual 10-K flows |
| inventory_usd, accounts_payable_usd, accounts_receivable_usd, vendor_nontrade_receivables_usd, ppe_net_usd, unconditional_purchase_obligations_usd | balances at fiscal year end |
| manufacturing_purchase_obligations_usd, manufacturing_po_within_12m_usd | from `silver.purchase_obligations` |
| days_in_year | inclusive period length (364 or 371) |
| avg_* | (prior year-end + year-end) / 2; null when the prior year is missing |
| dio_days | avg inventory / cost of sales × days_in_year |
| dpo_days | avg accounts payable / cost of sales × days_in_year |
| dso_days | avg accounts receivable / revenue × days_in_year |
| ccc_days | dio + dso − dpo |
| *_end_days | same ratios on year-end balances |
| inventory_turnover | cost of sales / avg inventory |
| mpo_days_of_cogs | manufacturing purchase obligations / cost of sales × days_in_year |
| nontrade_receivables_to_inventory | vendor non-trade receivables / inventory |
| gross_margin | gross profit / revenue |

### `fct_working_capital_quarterly` (grain: fiscal quarter)
`fiscal_year, fiscal_quarter, fiscal_period ('2025-Q4'), period_end, days_in_quarter, is_q4_derived`,
flows and quarter-end balances, and `dio_days, dpo_days, dso_days, ccc_days` on quarter-end
balances. Q4 flows = 10-K annual − (Q1 + Q2 + Q3).

### `mart_revenue_mix` (grain: fiscal year × breakdown × member, FY2013+)
`revenue_usd, breakdown_total_usd, share_of_total, yoy_growth`.

### `mart_supplier_sites_by_country` (grain: edition × country)
`suppliers` (supplier-country pairs = distinct suppliers with a location there), `sites`,
`pair_share`, `site_share`, `rank_by_suppliers`.

### `mart_supplier_concentration` (grain: edition)
`n_suppliers, n_countries, n_pairs, n_sites`, `hhi_pairs` / `hhi_sites` (Σ share², 0-1),
`top_country_iso3, top_country_pair_share`, `china_/india_/vietnam_pair_share`,
`china_site_share`, `single_country_suppliers` (+ share), `china_only_suppliers`,
`avg_countries_per_supplier`.

### `mart_trade_flow_shifts` (grain: dataset × year × product group × country)
`product_group` ∈ `hs8517_phones_and_telecom`, `hs8471_computers`, `cellular_phones`
(851712 ≤ 2021, 851713 + 851714 ≥ 2022). `value_usd, selected_total_usd, share_of_selected` (share of the
queried countries, **not** of world trade), `yoy_growth` (only when the prior year exists),
`rank_in_year, is_reported`.

### `mart_country_dependency` (grain: country)
Latest supplier-list footprint (`suppliers, sites, supplier_pair_share, site_share`) next to the
latest-year export shares `hs8517_export_share, hs8471_export_share`.

### `dim_country`
`country_iso3, country_name, comtrade_code, region`.

## Graph outputs (`graph` schema, Iceberg `gold`)

| Table | Grain | Columns |
|---|---|---|
| `graph_edition_metrics` | edition | `n_suppliers, n_countries, n_edges, n_sites, hhi_pairs, hhi_sites, top_country_iso3, single_country_suppliers, single_country_supplier_share, density` (bipartite density) |
| `graph_country_exposure` | edition × scenario | `scenario` (top-10 countries by suppliers + "China mainland + Taiwan", "China mainland + Hong Kong"), `countries`, `site_share_exposed`, `suppliers_affected` (+ share), `suppliers_fully_disrupted` (+ share; all listed sites inside the scenario), `suppliers_with_alternative` |
| `graph_supplier_dependency` | edition × supplier | `n_countries, countries, is_single_country, primary_country_iso3, primary_country_site_share, sites` |

Neptune bulk-load files: `s3://<curated>/neptune/edition=<e>/vertices.csv` (`~id, ~label,
name:String, iso3:String, region:String`) and `edges.csv` (`~id, ~from, ~to, ~label
(manufactures_in), edition:Int, sites:Int`).
