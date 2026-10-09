-- Fiscal quarters. 10-Qs report Q1-Q3 as 3-month facts; Q4 is derived as the annual 10-K
-- figure minus Q1..Q3 (the standard approach, since Q4 is never filed on its own).
with facts as (
    select * from {{ ref('stg_financial_facts') }}
),

reported as (
    select fiscal_year, metric, period_start, period_end, duration_days, value_usd
    from facts
    where period_type = 'quarter' and metric in ('revenue', 'cost_of_sales')
),

numbered as (
    select
        *,
        row_number() over (partition by fiscal_year, metric order by period_end) as fiscal_quarter
    from reported
),

annual as (
    select fiscal_year, metric, period_end, duration_days, value_usd
    from facts
    where period_type = 'annual' and metric in ('revenue', 'cost_of_sales')
),

q4 as (
    select
        a.fiscal_year,
        a.metric,
        max(n.period_end) as q3_end,
        a.period_end,
        count(*) as quarters_found,
        a.value_usd - sum(n.value_usd) as value_usd
    from annual as a
    inner join numbered as n
        on a.fiscal_year = n.fiscal_year and a.metric = n.metric and n.fiscal_quarter <= 3
    group by a.fiscal_year, a.metric, a.period_end, a.value_usd
    having count(*) = 3
),

all_quarters as (
    select fiscal_year, metric, fiscal_quarter, period_end, duration_days + 1 as duration_days, value_usd, false as is_derived
    from numbered
    where fiscal_quarter <= 3
    union all
    select
        fiscal_year,
        metric,
        4 as fiscal_quarter,
        period_end,
        cast({{ dbt.datediff('q3_end', 'period_end', 'day') }} as integer) as duration_days,
        value_usd,
        true as is_derived
    from q4
),

pivoted as (
    select
        fiscal_year,
        fiscal_quarter,
        max(period_end) as period_end,
        max(duration_days) as days_in_quarter,
        max(case when metric = 'revenue' then value_usd end) as revenue_usd,
        max(case when metric = 'cost_of_sales' then value_usd end) as cost_of_sales_usd,
        max(case when is_derived then 1 else 0 end) = 1 as is_q4_derived
    from all_quarters
    group by fiscal_year, fiscal_quarter
),

balances as (
    select
        period_end,
        max(case when metric = 'inventory' then value_usd end) as inventory_usd,
        max(case when metric = 'accounts_payable' then value_usd end) as accounts_payable_usd,
        max(case when metric = 'accounts_receivable' then value_usd end) as accounts_receivable_usd
    from facts
    where period_type = 'instant'
    group by period_end
)

select p.*, b.inventory_usd, b.accounts_payable_usd, b.accounts_receivable_usd
from pivoted as p
left join balances as b on p.period_end = b.period_end
