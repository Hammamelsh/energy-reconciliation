-- The reconciliation identity:
--     distinct readings in scope = charged + excluded (each with one reason)
-- Nothing may be silently dropped between the policy grain and the two facts.
WITH counts AS (
    SELECT
        (SELECT COUNT(*) FROM {{ ref('int_distinct_readings') }})          AS distinct_readings,
        (SELECT COUNT(*) FROM {{ ref('fact_interval_charge_scenario') }})  AS charged,
        (SELECT COUNT(*) FROM {{ ref('fact_interval_charge_exclusion') }}) AS excluded
)
SELECT * FROM counts WHERE charged + excluded <> distinct_readings
