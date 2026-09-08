-- The four PUBLISHER-DOCUMENTED prices, written out rather than derived, and the exact
-- pence-to-pounds relationship. A catalogue edit that changed a price would fail here.
WITH expected(tariff_group, band_label, pence, gbp) AS (
    VALUES ('ToU', 'High',   CAST(67.2000 AS DECIMAL(9,4)), CAST(0.672000 AS DECIMAL(9,6))),
           ('ToU', 'Normal', CAST(11.7600 AS DECIMAL(9,4)), CAST(0.117600 AS DECIMAL(9,6))),
           ('ToU', 'Low',    CAST(3.9900  AS DECIMAL(9,4)), CAST(0.039900 AS DECIMAL(9,6))),
           ('Std', 'flat',   CAST(14.2280 AS DECIMAL(9,4)), CAST(0.142280 AS DECIMAL(9,6)))
)
SELECT 'wrong_or_missing_price' AS problem, e.tariff_group, e.band_label
FROM expected e
LEFT JOIN {{ ref('dim_tariff_price') }} p
       ON p.tariff_group = e.tariff_group AND p.band_label = e.band_label
WHERE p.tariff_group IS NULL
   OR p.price_pence_per_kwh <> e.pence
   OR p.price_gbp_per_kwh <> e.gbp
   OR p.price_gbp_per_kwh * 100 <> p.price_pence_per_kwh
UNION ALL
SELECT 'unexpected_price', p.tariff_group, p.band_label
FROM {{ ref('dim_tariff_price') }} p
LEFT JOIN expected e
       ON e.tariff_group = p.tariff_group AND e.band_label = p.band_label
WHERE e.tariff_group IS NULL
