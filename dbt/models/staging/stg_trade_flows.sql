-- HS 8517 (telephone sets & transmission apparatus) and HS 8471 (computers) at 4 digits, plus
-- a continuous "cellular phones" series: 851712 until HS 2017, 851713 (smartphones) from HS 2022.
with flows as (
    select * from {{ source('silver', 'trade_flows') }}
    where primary_value_usd is not null
)

select
    dataset,
    cast(year as integer) as year,
    flow_code,
    case when dataset = 'exports' then reporter_iso3 else partner_iso3 end as country_iso3,
    case when dataset = 'exports' then reporter_name else partner_name end as country_name,
    reporter_iso3,
    partner_iso3,
    cmd_code,
    case
        when cmd_code = '8517' then 'hs8517_phones_and_telecom'
        when cmd_code = '8471' then 'hs8471_computers'
        when cmd_code in ('851712', '851713') then 'cellular_phones'
    end as product_group,
    classification,
    cast(primary_value_usd as double) as value_usd,
    is_reported
from flows
where cmd_code in ('8517', '8471', '851712', '851713')
