select
    country_iso3,
    country_name,
    comtrade_code,
    region
from {{ ref('stg_ref_country') }}
