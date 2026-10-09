select
    cast(fiscal_year as integer) as fiscal_year,
    cast(as_of as date) as as_of,
    kind,
    cast(amount_usd as double) as amount_usd,
    cast(payable_within_12m_usd as double) as payable_within_12m_usd,
    accession
from {{ source('silver', 'purchase_obligations') }}
