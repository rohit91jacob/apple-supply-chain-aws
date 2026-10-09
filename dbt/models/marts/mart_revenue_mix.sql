-- Revenue mix by reportable segment (geography), product category and country, FY2013+.
with rev as (
    select * from {{ ref('stg_segment_revenue') }}
    where is_rollup = false and fiscal_year >= {{ var('first_mix_fiscal_year') }}
),

totals as (
    select
        fiscal_year,
        breakdown,
        sum(revenue_usd) as breakdown_total_usd
    from rev
    group by fiscal_year, breakdown
),

joined as (
    select
        rev.fiscal_year,
        rev.breakdown,
        rev.member_label,
        rev.revenue_usd,
        totals.breakdown_total_usd,
        lag(rev.revenue_usd) over (
            partition by rev.breakdown, rev.member_label order by rev.fiscal_year
        ) as prior_revenue_usd
    from rev
    inner join totals
        on rev.fiscal_year = totals.fiscal_year and rev.breakdown = totals.breakdown
)

select
    fiscal_year,
    breakdown,
    member_label,
    revenue_usd,
    breakdown_total_usd,
    {{ safe_divide('revenue_usd', 'breakdown_total_usd') }} as share_of_total,
    {{ safe_divide('revenue_usd', 'prior_revenue_usd') }} - 1 as yoy_growth
from joined
