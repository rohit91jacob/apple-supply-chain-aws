{#- Use the configured schema name as-is (staging, intermediate, marts) instead of
    dbt's default "<target_schema>_<custom>" so local and Athena layouts match. -#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- elif target.type == 'athena' -%}
        asc_{{ custom_schema_name | trim }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
