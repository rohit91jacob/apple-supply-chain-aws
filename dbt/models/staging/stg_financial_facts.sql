-- One row per metric x period. Classifies each fact as an annual flow, a quarterly flow or
-- an instant (balance-sheet) value.
with facts as (
    select * from {{ source('silver', 'financial_facts') }}
    where unit = 'USD'
)

select
    metric,
    concept,
    cast(period_start as date) as period_start,
    cast(period_end as date) as period_end,
    duration_days,
    case
        when duration_days is null then 'instant'
        when duration_days between 350 and 380 then 'annual'
        when duration_days between 80 and 100 then 'quarter'
        else 'other'
    end as period_type,
    -- Apple's fiscal year ends on the last Saturday of September; Q1 ends in late December.
    cast(extract(year from period_end) as integer)
    + case when extract(month from period_end) >= 10 then 1 else 0 end as fiscal_year,
    cast(value as double) as value_usd,
    form,
    cast(filed as date) as filed,
    accession
from facts
