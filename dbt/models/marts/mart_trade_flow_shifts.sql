-- Who ships the phones and computers. For each dataset (exporters' exports to the World;
-- US imports by partner), year and product group: value, share of the selected-country
-- total, year-on-year growth and rank. Shares are relative to the countries queried
-- (ASC_TRADE_REPORTERS), not to total world trade.
with flows as (
    select
        dataset,
        year,
        product_group,
        country_iso3,
        min(country_name) as country_name,
        sum(value_usd) as value_usd,
        max(case when is_reported then 1 else 0 end) = 1 as is_reported
    from {{ ref('stg_trade_flows') }}
    where country_iso3 is not null and country_iso3 <> 'WLD'
    group by dataset, year, product_group, country_iso3
),

totals as (
    select
        dataset,
        year,
        product_group,
        sum(value_usd) as selected_total_usd
    from flows
    group by dataset, year, product_group
),

joined as (
    select
        f.dataset,
        f.year,
        f.product_group,
        f.country_iso3,
        f.country_name,
        f.value_usd,
        t.selected_total_usd,
        f.is_reported,
        lag(f.value_usd) over (
            partition by f.dataset, f.product_group, f.country_iso3 order by f.year
        ) as prior_value_usd,
        lag(f.year) over (
            partition by f.dataset, f.product_group, f.country_iso3 order by f.year
        ) as prior_year
    from flows as f
    inner join totals as t
        on f.dataset = t.dataset and f.year = t.year and f.product_group = t.product_group
)

select
    dataset,
    year,
    product_group,
    country_iso3,
    country_name,
    value_usd,
    selected_total_usd,
    {{ safe_divide('value_usd', 'selected_total_usd') }} as share_of_selected,
    case
        when prior_year = year - 1 then {{ safe_divide('value_usd', 'prior_value_usd') }} - 1
    end as yoy_growth,
    rank() over (partition by dataset, year, product_group order by value_usd desc) as rank_in_year,
    is_reported
from joined
