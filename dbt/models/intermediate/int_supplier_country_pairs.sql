-- The cross-edition unit: one row per edition x supplier x country. Address editions list
-- facilities (site_count = facilities); locations editions list provinces/states.
select
    edition,
    fiscal_year,
    layout,
    supplier_key,
    min(supplier_name) as supplier_name,
    country_iso3,
    min(country_name) as country_name,
    min(region) as region,
    sum(case when site_type = 'manufacturing' then site_count else 0 end) as sites,
    max(case when site_type = 'headquarters' then 1 else 0 end) = 1 as headquarters_only_row
from {{ ref('stg_supplier_sites') }}
group by edition, fiscal_year, layout, supplier_key, country_iso3
