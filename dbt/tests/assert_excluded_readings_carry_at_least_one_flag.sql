-- A row in the exclusion fact with no condition set would be an unexplained exclusion.
SELECT household_id, source_timestamp_text
FROM {{ ref('fact_interval_charge_exclusion') }}
WHERE NOT (is_ineligible_group OR is_outside_schedule_period OR is_conflicted
           OR is_off_grid OR is_missing_value OR is_unmatched_label OR is_unpriced_band)
