{{ config(materialized='ephemeral') }}

-- Every distinct recorded reading, classified against eligibility, schedule coverage and
-- the four analytical policies.
--
-- The body is the generated macro, which is rendered from
-- `tariff/models.classified_readings_sql` -- the same function the Python execution path
-- calls. Eligibility, schedule period, conflict, off-grid, missing value, unmatched label
-- and unpriced band are decided there and nowhere else. If this file held predicates of
-- its own, the project would have two definitions of its policy and no way to keep them
-- equal.
--
-- Ephemeral: it is inlined into both facts, so the two cannot disagree about what was
-- classified, and no stored copy can go stale against the readings it describes.
{{ classified_readings(
     ref('stg_readings'),
     ref('dim_tariff_band_schedule'),
     ref('dim_tariff_price'),
     var('tariff_group')) }}
