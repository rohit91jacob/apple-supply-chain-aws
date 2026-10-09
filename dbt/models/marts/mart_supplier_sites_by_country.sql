-- Apple supplier footprint by country for every Supplier List edition.
--   suppliers  = distinct suppliers with >= 1 listed location in the country
--   sites      = facilities (address editions) or provinces/states (locations editions)
--   *_share    = share of the edition total (supplier-country pairs / sites)
with pairs as (
    select * from {{ ref('int_supplier_country_pairs') }}
),

by_country as (
    select
        edition,
        fiscal_year,
        layout,
        country_iso3,
        min(country_name) as country_name,
        min(region) as region,
        count(*) as suppliers,
        sum(sites) as sites
    from pairs
    group by edition, fiscal_year, layout, country_iso3
),

edition_totals as (
    select
        edition,
        sum(suppliers) as total_pairs,
        sum(sites) as total_sites
    from by_country
    group by edition
)

select
    c.edition,
    c.fiscal_year,
    c.layout,
    c.country_iso3,
    c.country_name,
    c.region,
    c.suppliers,
    c.sites,
    {{ safe_divide('c.suppliers', 't.total_pairs') }} as pair_share,
    {{ safe_divide('c.sites', 't.total_sites') }} as site_share,
    rank() over (partition by c.edition order by c.suppliers desc, c.country_iso3) as rank_by_suppliers
from by_country as c
inner join edition_totals as t on c.edition = t.edition
