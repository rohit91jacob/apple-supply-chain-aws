-- One row per fiscal year: annual flows from 10-K duration facts, balances at fiscal year
-- end, and the prior year-end balances needed for average-balance ratios.
with facts as (
    select * from {{ ref('stg_financial_facts') }}
),

flows as (
    select
        fiscal_year,
        max(period_end) as period_end,
        max(case when metric = 'revenue' then value_usd end) as revenue_usd,
        max(case when metric = 'cost_of_sales' then value_usd end) as cost_of_sales_usd,
        max(case when metric = 'gross_profit' then value_usd end) as gross_profit_usd,
        max(case when metric = 'capex' then value_usd end) as capex_usd,
        -- XBRL periods are inclusive: 2024-09-29..2025-09-27 is 364 days (52 weeks)
        max(duration_days) + 1 as days_in_year
    from facts
    where period_type = 'annual'
    group by fiscal_year
),

balances as (
    select
        f.fiscal_year,
        max(case when b.metric = 'inventory' then b.value_usd end) as inventory_usd,
        max(case when b.metric = 'accounts_payable' then b.value_usd end) as accounts_payable_usd,
        max(case when b.metric = 'accounts_receivable' then b.value_usd end) as accounts_receivable_usd,
        max(case when b.metric = 'vendor_nontrade_receivables' then b.value_usd end) as vendor_nontrade_receivables_usd,
        max(case when b.metric = 'ppe_net' then b.value_usd end) as ppe_net_usd,
        max(case when b.metric = 'unconditional_purchase_obligations' then b.value_usd end) as unconditional_purchase_obligations_usd
    from flows as f
    inner join facts as b
        on b.period_type = 'instant' and b.period_end = f.period_end
    group by f.fiscal_year
),

joined as (
    select
        flows.*,
        balances.inventory_usd,
        balances.accounts_payable_usd,
        balances.accounts_receivable_usd,
        balances.vendor_nontrade_receivables_usd,
        balances.ppe_net_usd,
        balances.unconditional_purchase_obligations_usd
    from flows
    left join balances on flows.fiscal_year = balances.fiscal_year
)

select
    joined.*,
    lag(inventory_usd) over (order by fiscal_year) as prior_inventory_usd,
    lag(accounts_payable_usd) over (order by fiscal_year) as prior_accounts_payable_usd,
    lag(accounts_receivable_usd) over (order by fiscal_year) as prior_accounts_receivable_usd,
    lag(fiscal_year) over (order by fiscal_year) as prior_fiscal_year
from joined
