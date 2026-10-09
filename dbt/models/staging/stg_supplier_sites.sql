select
    cast(edition as integer) as edition,
    spend_year,
    cast(fiscal_year as integer) as fiscal_year,
    layout,
    cast(row_number as integer) as row_number,
    supplier_name,
    supplier_key,
    location,
    site_type,
    cast(site_count as integer) as site_count,
    country_iso3,
    country_name,
    region
from {{ source('silver', 'supplier_sites') }}
where country_iso3 is not null
