-- Every breakdown (segments, product categories, countries) must add up to total net sales
-- from companyfacts within 0.5% for each fiscal year in the mix mart.
with mix as (
    select fiscal_year, breakdown, max(breakdown_total_usd) as breakdown_total_usd
    from {{ ref('mart_revenue_mix') }}
    group by fiscal_year, breakdown
),

totals as (
    select fiscal_year, revenue_usd
    from {{ ref('fct_working_capital_annual') }}
)

select mix.*, totals.revenue_usd
from mix
inner join totals on mix.fiscal_year = totals.fiscal_year
where abs(mix.breakdown_total_usd - totals.revenue_usd) > 0.005 * totals.revenue_usd
