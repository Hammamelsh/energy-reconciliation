-- A half-open interval needs both bounds. One bound set and one NULL would silently
-- price part of history under an unstated rule.
SELECT tariff_group, band_label, effective_from, effective_until
FROM {{ ref('dim_tariff_price') }}
WHERE (effective_from IS NULL) <> (effective_until IS NULL)
