{% macro safe_divide(numerator, denominator) -%}
    (cast({{ numerator }} as double) / nullif(cast({{ denominator }} as double), 0))
{%- endmacro %}
