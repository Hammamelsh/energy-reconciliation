-- The charge, recomputed row by row from the stored inputs. DECIMAL x DECIMAL is exact;
-- any row that disagrees means a float crept in or the price join moved.
SELECT household_id, source_timestamp_text, energy_charge_gbp
FROM {{ ref('fact_interval_charge_scenario') }} f
JOIN {{ ref('dim_tariff_price') }} p
  ON p.tariff_group = f.tariff_group AND p.band_label = f.band_label
WHERE f.energy_charge_gbp
      <> CAST(f.consumption_kwh * p.price_gbp_per_kwh AS DECIMAL(38, 16))
