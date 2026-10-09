{#- Generic tests shared by the marts. They compile to portable SQL (DuckDB and Trino). -#}

{% test values_between(model, column_name, min_value=none, max_value=none) %}
select {{ column_name }}
from {{ model }}
where {{ column_name }} is not null
  and (
    {%- if min_value is not none %} {{ column_name }} < {{ min_value }} {% else %} false {% endif -%}
    or
    {%- if max_value is not none %} {{ column_name }} > {{ max_value }} {% else %} false {% endif -%}
  )
{% endtest %}

{% test shares_sum_to_one(model, column_name, group_by, tolerance=0.0001) %}
select {{ group_by | join(', ') }}, sum({{ column_name }}) as total_share
from {{ model }}
group by {{ group_by | join(', ') }}
having abs(sum({{ column_name }}) - 1.0) > {{ tolerance }}
{% endtest %}

{% test unique_combination(model, columns) %}
select {{ columns | join(', ') }}, count(*) as n
from {{ model }}
group by {{ columns | join(', ') }}
having count(*) > 1
{% endtest %}
