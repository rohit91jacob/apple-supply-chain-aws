-- Quarterly DIO / DPO / DSO / CCC on quarter-end balances and the quarter's flows
-- (days = actual days in the fiscal quarter). Q4 flows are derived (annual - Q1..Q3).
with q as (
    select * from {{ ref('int_quarterly_financials') }}
    where revenue_usd is not null and cost_of_sales_usd is not null
),

ratios as (
    select
        fiscal_year,
        fiscal_quarter,
        cast(fiscal_year as varchar) || '-Q' || cast(fiscal_quarter as varchar) as fiscal_period,
        period_end,
        days_in_quarter,
        is_q4_derived,
        revenue_usd,
        cost_of_sales_usd,
        inventory_usd,
        accounts_payable_usd,
        accounts_receivable_usd,
        {{ safe_divide('inventory_usd', 'cost_of_sales_usd') }} * days_in_quarter as dio_days,
        {{ safe_divide('accounts_payable_usd', 'cost_of_sales_usd') }} * days_in_quarter as dpo_days,
        {{ safe_divide('accounts_receivable_usd', 'revenue_usd') }} * days_in_quarter as dso_days
    from q
)

select
    ratios.*,
    dio_days + dso_days - dpo_days as ccc_days
from ratios
