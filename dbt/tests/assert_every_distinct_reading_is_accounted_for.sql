-- Membership, not arithmetic. Every distinct reading must appear in exactly one fact,
-- and neither fact may contain a key the policy grain does not.
WITH accounted AS (
    SELECT household_id, source_timestamp_text FROM {{ ref('fact_interval_charge_scenario') }}
    UNION ALL
    SELECT household_id, source_timestamp_text FROM {{ ref('fact_interval_charge_exclusion') }}
),
grain AS (
    SELECT DISTINCT household_id, source_timestamp_text FROM {{ ref('int_distinct_readings') }}
)
SELECT 'missing_from_facts' AS problem, household_id, source_timestamp_text
FROM (SELECT * FROM grain EXCEPT SELECT DISTINCT household_id, source_timestamp_text FROM accounted)
UNION ALL
SELECT 'not_a_distinct_reading', household_id, source_timestamp_text
FROM (SELECT DISTINCT household_id, source_timestamp_text FROM accounted EXCEPT SELECT * FROM grain)
