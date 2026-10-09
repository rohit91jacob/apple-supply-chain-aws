-- Where all four quarters exist, quarterly cost of sales must add up to the annual figure
-- (Q4 is derived, so this guards the derivation and the fiscal-year assignment).
with q as (
    select fiscal_year, count(*) as n, sum(cost_of_sales_usd) as cogs_usd
    from {{ ref('fct_working_capital_quarterly') }}
    group by fiscal_year
)

select q.fiscal_year, q.cogs_usd, a.cost_of_sales_usd
from q
inner join {{ ref('fct_working_capital_annual') }} as a on q.fiscal_year = a.fiscal_year
where q.n = 4 and abs(q.cogs_usd - a.cost_of_sales_usd) > 1000000
