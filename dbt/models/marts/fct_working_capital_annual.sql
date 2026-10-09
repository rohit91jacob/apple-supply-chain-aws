-- Annual working-capital and supply-commitment metrics.
--   DIO = average inventory / cost of sales x days in year
--   DPO = average accounts payable / cost of sales x days in year
--   DSO = average accounts receivable / revenue x days in year
--   CCC = DIO + DSO - DPO   (negative = suppliers finance the operating cycle)
-- Averages use (prior year-end + year-end) / 2; the *_end variants use year-end only.
with fy as (
    select * from {{ ref('int_annual_financials') }}
),

po as (
    select fiscal_year, amount_usd, payable_within_12m_usd
    from {{ ref('stg_purchase_obligations') }}
    where kind = 'manufacturing'
),

base as (
    select
        fy.fiscal_year,
        fy.period_end,
        fy.days_in_year,
        fy.revenue_usd,
        fy.cost_of_sales_usd,
        coalesce(fy.gross_profit_usd, fy.revenue_usd - fy.cost_of_sales_usd) as gross_profit_usd,
        fy.inventory_usd,
        fy.accounts_payable_usd,
        fy.accounts_receivable_usd,
        fy.vendor_nontrade_receivables_usd,
        fy.ppe_net_usd,
        fy.capex_usd,
        fy.unconditional_purchase_obligations_usd,
        po.amount_usd as manufacturing_purchase_obligations_usd,
        po.payable_within_12m_usd as manufacturing_po_within_12m_usd,
        case
            when fy.prior_fiscal_year = fy.fiscal_year - 1
                then (fy.inventory_usd + fy.prior_inventory_usd) / 2.0
        end as avg_inventory_usd,
        case
            when fy.prior_fiscal_year = fy.fiscal_year - 1
                then (fy.accounts_payable_usd + fy.prior_accounts_payable_usd) / 2.0
        end as avg_accounts_payable_usd,
        case
            when fy.prior_fiscal_year = fy.fiscal_year - 1
                then (fy.accounts_receivable_usd + fy.prior_accounts_receivable_usd) / 2.0
        end as avg_accounts_receivable_usd
    from fy
    left join po on fy.fiscal_year = po.fiscal_year
    where fy.revenue_usd is not null and fy.cost_of_sales_usd is not null
),

ratios as (
    select
        base.*,
        {{ safe_divide('gross_profit_usd', 'revenue_usd') }} as gross_margin,
        {{ safe_divide('avg_inventory_usd', 'cost_of_sales_usd') }} * days_in_year as dio_days,
        {{ safe_divide('avg_accounts_payable_usd', 'cost_of_sales_usd') }} * days_in_year as dpo_days,
        {{ safe_divide('avg_accounts_receivable_usd', 'revenue_usd') }} * days_in_year as dso_days,
        {{ safe_divide('inventory_usd', 'cost_of_sales_usd') }} * days_in_year as dio_end_days,
        {{ safe_divide('accounts_payable_usd', 'cost_of_sales_usd') }} * days_in_year as dpo_end_days,
        {{ safe_divide('accounts_receivable_usd', 'revenue_usd') }} * days_in_year as dso_end_days,
        {{ safe_divide('cost_of_sales_usd', 'avg_inventory_usd') }} as inventory_turnover,
        {{ safe_divide('manufacturing_purchase_obligations_usd', 'cost_of_sales_usd') }} * days_in_year as mpo_days_of_cogs,
        {{ safe_divide('vendor_nontrade_receivables_usd', 'inventory_usd') }} as nontrade_receivables_to_inventory
    from base
)

select
    ratios.*,
    dio_days + dso_days - dpo_days as ccc_days,
    dio_end_days + dso_end_days - dpo_end_days as ccc_end_days
from ratios
