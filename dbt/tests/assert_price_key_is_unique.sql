-- (tariff_group, band_label) is the price key. A duplicate would multiply every charge
-- joined to it.
SELECT tariff_group, band_label, COUNT(*) AS rows_at_key
FROM {{ ref('dim_tariff_price') }}
GROUP BY 1, 2
HAVING COUNT(*) > 1
