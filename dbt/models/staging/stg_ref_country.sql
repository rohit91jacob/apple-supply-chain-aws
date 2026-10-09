select iso3 as country_iso3, name as country_name, comtrade_code, region
from {{ source('silver', 'ref_country') }}
