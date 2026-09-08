-- The flat rate's period is UNKNOWN, so its bounds are NULL and it must charge nothing.
-- The NULL is meaningful and is preserved on purpose; this asserts the consequence.
SELECT f.household_id, f.source_timestamp_text, f.band_label
FROM {{ ref('fact_interval_charge_scenario') }} f
JOIN {{ ref('dim_tariff_price') }} p
  ON p.tariff_group = f.tariff_group AND p.band_label = f.band_label
WHERE p.effective_from IS NULL OR p.effective_until IS NULL
