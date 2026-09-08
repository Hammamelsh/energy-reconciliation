-- Grain of the charged fact: one row per (run_id, household_id, source_timestamp_text).
-- A conflicted label is excluded entirely, so the charged output is unique by
-- construction; this proves it rather than assuming it. CREATE TABLE AS SELECT drops the
-- declared key, so nothing but this test enforces it.
SELECT run_id, household_id, source_timestamp_text, COUNT(*) AS rows_at_key
FROM {{ ref('fact_interval_charge_scenario') }}
GROUP BY 1, 2, 3
HAVING COUNT(*) > 1
