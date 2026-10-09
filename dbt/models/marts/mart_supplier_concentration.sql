-- Geographic concentration of the supplier base per edition.
--   HHI = sum over countries of (country share)^2, on supplier-country pairs and on sites.
--   single_country_suppliers = suppliers whose every listed location is in one country.
with by_country as (
    select * from {{ ref('mart_supplier_sites_by_country') }}
),

suppliers as (
    select
        edition,
        supplier_key,
        count(*) as n_countries,
        max(country_iso3) as only_country
    from {{ ref('int_supplier_country_pairs') }}
    group by edition, supplier_key
),

supplier_stats as (
    select
        edition,
        count(*) as n_suppliers,
        sum(case when n_countries = 1 then 1 else 0 end) as single_country_suppliers,
        sum(case when n_countries = 1 and only_country = 'CHN' then 1 else 0 end) as china_only_suppliers,
        avg(cast(n_countries as double)) as avg_countries_per_supplier
    from suppliers
    group by edition
),

hhi as (
    select
        edition,
        min(fiscal_year) as fiscal_year,
        min(layout) as layout,
        count(*) as n_countries,
        sum(suppliers) as n_pairs,
        sum(sites) as n_sites,
        sum(pair_share * pair_share) as hhi_pairs,
        sum(site_share * site_share) as hhi_sites,
        max(case when rank_by_suppliers = 1 then country_iso3 end) as top_country_iso3,
        max(case when rank_by_suppliers = 1 then pair_share end) as top_country_pair_share,
        max(case when country_iso3 = 'CHN' then pair_share else 0 end) as china_pair_share,
        max(case when country_iso3 = 'CHN' then site_share else 0 end) as china_site_share,
        max(case when country_iso3 = 'IND' then pair_share else 0 end) as india_pair_share,
        max(case when country_iso3 = 'VNM' then pair_share else 0 end) as vietnam_pair_share
    from by_country
    group by edition
)

select
    hhi.*,
    s.n_suppliers,
    s.single_country_suppliers,
    {{ safe_divide('s.single_country_suppliers', 's.n_suppliers') }} as single_country_supplier_share,
    s.china_only_suppliers,
    s.avg_countries_per_supplier
from hhi
inner join supplier_stats as s on hhi.edition = s.edition
