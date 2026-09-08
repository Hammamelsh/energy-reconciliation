{#
  GENERATED FILE -- DO NOT EDIT.

  Rendered from src/energy_reconciliation/policy.py (the four analytical policies) and
  src/energy_reconciliation/tariff/models.py (classification, the two fact projections
  and the exclusion-reason precedence). Those modules are the single definition of every
  rule below, and the Python execution path calls the same functions. To change a rule,
  edit the module and run:

      uv run render-dbt-macros

  `uv run render-dbt-macros --check` and tests/test_dbt_macros.py fail if this file and
  its sources disagree. Neither of them rewrites the file.

  Relation arguments are dbt relations: pass `ref(...)` or `source(...)`. The SQL bodies
  are otherwise fixed by the Python definitions.
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

{% macro classified_readings(readings, schedule, price, tariff_group) %}
    WITH distinct_readings AS (
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
    ),
    conflicting AS (
    SELECT household_id, source_timestamp_text
    FROM {{ readings }}
    GROUP BY household_id, source_timestamp_text
    HAVING COUNT(DISTINCT COALESCE(CAST(consumption_kwh AS VARCHAR), '~' || value_category)) > 1
    ),
    coverage AS (
        SELECT MIN(schedule_label_naive) AS first_label,
               MAX(schedule_label_naive) AS last_label
        FROM {{ schedule }}
    ),
    banded_group AS (
        SELECT DISTINCT tariff_group FROM {{ price }} WHERE band_label <> 'flat'
    )
    SELECT r.household_id,
           r.tariff_group,
           r.source_timestamp_text,
           r.observed_at_naive,
           r.on_half_hour_grid,
           r.consumption_kwh,
           r.value_category,
           s.band_label,
           p.price_pence_per_kwh,
           p.price_gbp_per_kwh,
           (g.tariff_group IS NULL OR r.tariff_group <> '{{ tariff_group }}')          AS is_ineligible_group,
           (cov.first_label IS NULL
            OR r.observed_at_naive < cov.first_label
            OR r.observed_at_naive > cov.last_label)                AS is_outside_schedule_period,
           (c.household_id IS NOT NULL)                             AS is_conflicted,
           (NOT COALESCE(r.on_half_hour_grid, FALSE))               AS is_off_grid,
           (r.value_category <> 'finite_numeric' OR r.consumption_kwh IS NULL) AS is_missing_value,
           (s.band_label IS NULL)                                   AS is_unmatched_label,
           (s.band_label IS NOT NULL AND p.price_gbp_per_kwh IS NULL) AS is_unpriced_band
    FROM distinct_readings r
    CROSS JOIN coverage cov
    LEFT JOIN banded_group g ON g.tariff_group = r.tariff_group
    LEFT JOIN conflicting c
           ON c.household_id = r.household_id
          AND c.source_timestamp_text = r.source_timestamp_text
    LEFT JOIN {{ schedule }} s
           ON s.schedule_label_naive = r.observed_at_naive
    -- A price applies only inside its half-open validity [effective_from, effective_until).
    -- A NULL bound is UNKNOWN, not open-ended, so it prices nothing. The schedule's
    -- coverage and the price's validity are checked independently: a label the schedule
    -- carries but no price covers is excluded as unpriced_band, never charged at zero.
    LEFT JOIN {{ price }} p
           ON p.tariff_group = r.tariff_group
          AND p.band_label = s.band_label
          AND p.effective_from IS NOT NULL
          AND p.effective_until IS NOT NULL
          AND r.observed_at_naive >= CAST(p.effective_from AS TIMESTAMP)
          AND r.observed_at_naive <  CAST(p.effective_until AS TIMESTAMP)
{% endmacro %}

{% macro scenario_fact(classified, run_id) %}
    SELECT '{{ run_id }}' AS run_id,
           household_id,
           tariff_group,
           source_timestamp_text,
           observed_at_naive,
           CAST(observed_at_naive AS DATE)                 AS source_date,
           CAST(EXTRACT(hour  FROM observed_at_naive) AS SMALLINT) AS source_hour,
           CAST(EXTRACT(month FROM observed_at_naive) AS SMALLINT) AS source_month,
           band_label,
           consumption_kwh,
           price_pence_per_kwh,
           CAST(consumption_kwh * price_gbp_per_kwh
                AS DECIMAL(38,16))     AS energy_charge_gbp,
           'A1'                               AS assumption_id
    FROM {{ classified }}
    WHERE NOT (is_ineligible_group OR is_outside_schedule_period OR is_conflicted OR is_off_grid OR is_missing_value OR is_unmatched_label OR is_unpriced_band)
{% endmacro %}

{% macro exclusion_fact(classified, run_id) %}
    SELECT '{{ run_id }}' AS run_id,
           household_id,
           tariff_group,
           source_timestamp_text,
           observed_at_naive,
           CAST(observed_at_naive AS DATE) AS source_date,
           on_half_hour_grid,
           consumption_kwh,
           value_category,
           CASE
        WHEN is_ineligible_group THEN 'ineligible_tariff_group'
        WHEN is_outside_schedule_period THEN 'outside_schedule_period'
        WHEN is_conflicted THEN 'conflicting_label'
        WHEN is_off_grid THEN 'off_grid_observation'
        WHEN is_missing_value THEN 'missing_value'
        WHEN is_unmatched_label THEN 'unmatched_schedule_label'
        WHEN is_unpriced_band THEN 'unpriced_band'
        END AS exclusion_reason,
           is_ineligible_group,
           is_outside_schedule_period,
           is_conflicted,
           is_off_grid,
           is_missing_value,
           is_unmatched_label,
           is_unpriced_band
    FROM {{ classified }}
    WHERE is_ineligible_group OR is_outside_schedule_period OR is_conflicted OR is_off_grid OR is_missing_value OR is_unmatched_label OR is_unpriced_band
{% endmacro %}

{% macro exclusion_reason_case() %}
    CASE
        WHEN is_ineligible_group THEN 'ineligible_tariff_group'
        WHEN is_outside_schedule_period THEN 'outside_schedule_period'
        WHEN is_conflicted THEN 'conflicting_label'
        WHEN is_off_grid THEN 'off_grid_observation'
        WHEN is_missing_value THEN 'missing_value'
        WHEN is_unmatched_label THEN 'unmatched_schedule_label'
        WHEN is_unpriced_band THEN 'unpriced_band'
        END
{% endmacro %}

{% macro exclusion_reasons() %}
    ('ineligible_tariff_group', 'outside_schedule_period', 'conflicting_label', 'off_grid_observation', 'missing_value', 'unmatched_schedule_label', 'unpriced_band')
{% endmacro %}
