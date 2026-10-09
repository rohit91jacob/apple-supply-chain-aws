-- Per country: the latest supplier-list footprint next to its latest export share of phones
-- (HS 8517) and computers (HS 8471) among the selected exporters.
with latest_edition as (
    select max(edition) as edition
    from {{ ref('mart_supplier_sites_by_country') }}
),

suppliers as (
    select
        s.country_iso3,
        s.suppliers,
        s.sites,
        s.pair_share,
        s.site_share,
        s.edition
    from {{ ref('mart_supplier_sites_by_country') }} as s
    inner join latest_edition as l on s.edition = l.edition
),

latest_trade_year as (
    select
        product_group,
        max(year) as year
    from {{ ref('mart_trade_flow_shifts') }}
    where dataset = 'exports'
    group by product_group
),

trade as (
    select
        t.country_iso3,
        max(case when t.product_group = 'hs8517_phones_and_telecom' then t.share_of_selected end) as hs8517_export_share,
        max(case when t.product_group = 'hs8471_computers' then t.share_of_selected end) as hs8471_export_share,
        max(t.year) as trade_year
    from {{ ref('mart_trade_flow_shifts') }} as t
    inner join latest_trade_year as y
        on t.product_group = y.product_group and t.year = y.year
    where t.dataset = 'exports'
    group by t.country_iso3
)

select
    d.country_iso3,
    d.country_name,
    d.region,
    s.edition as supplier_list_edition,
    coalesce(s.suppliers, 0) as suppliers,
    coalesce(s.sites, 0) as sites,
    coalesce(s.pair_share, 0) as supplier_pair_share,
    coalesce(s.site_share, 0) as site_share,
    t.trade_year,
    t.hs8517_export_share,
    t.hs8471_export_share
from {{ ref('dim_country') }} as d
left join suppliers as s on d.country_iso3 = s.country_iso3
left join trade as t on d.country_iso3 = t.country_iso3
where s.country_iso3 is not null or t.country_iso3 is not null
