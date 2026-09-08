{#
  GENERATED FILE -- DO NOT EDIT.

  Rendered from src/energy_reconciliation/policy.py, which is the single definition of
  this project's analytical policies. To change a rule, edit that module and run:

      uv run render-dbt-macros

  `uv run render-dbt-macros --check` and tests/test_dbt_macros.py fail if this file and
  policy.py disagree. Neither of them rewrites the file.

  The `readings` argument is the relation to read: pass `ref('stg_readings')` or any
  other dbt relation. The SQL body is otherwise fixed by policy.py.
#}

{% macro distinct_readings(readings) %}
    SELECT DISTINCT
           household_id,
           tariff_group,
           source_timestamp_text,
           observed_at_naive,
           on_half_hour_grid          AS on_half_hour_grid,
           consumption_kwh,
           value_category,
           COALESCE(CAST(consumption_kwh AS VARCHAR), '~' || value_category)     AS value_signature
    FROM {{ readings }}
{% endmacro %}

{% macro conflicting_labels(readings) %}
    SELECT household_id, source_timestamp_text
    FROM {{ readings }}
    GROUP BY household_id, source_timestamp_text
    HAVING COUNT(DISTINCT COALESCE(CAST(consumption_kwh AS VARCHAR), '~' || value_category)) > 1
{% endmacro %}
