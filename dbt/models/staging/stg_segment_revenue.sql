select
    cast(fiscal_year as integer) as fiscal_year,
    cast(period_end as date) as period_end,
    breakdown,
    member_label,
    is_rollup,
    cast(value as double) as revenue_usd,
    accession,
    cast(filed as date) as filed
from {{ source('silver', 'segment_revenue') }}
