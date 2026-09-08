-- A reading is charged or excluded, never both. Counts alone cannot detect an overlap
-- that is balanced by an omission, so membership is compared directly.
SELECT f.household_id, f.source_timestamp_text
FROM {{ ref('fact_interval_charge_scenario') }} f
JOIN {{ ref('fact_interval_charge_exclusion') }} e
  ON e.household_id = f.household_id
 AND e.source_timestamp_text = f.source_timestamp_text
