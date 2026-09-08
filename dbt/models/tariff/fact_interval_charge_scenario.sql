{{ config(materialized='table') }}

-- One row per **charged** reading. Grain: (run_id, household_id, source_timestamp_text).
--
-- energy_charge_gbp = consumption_kwh * price_gbp_per_kwh, DECIMAL x DECIMAL, exact.
-- The pence-to-pounds division is never written here: DuckDB evaluates DECIMAL / integer
-- as DOUBLE. price_gbp_per_kwh is already the exact quotient, computed once in Python.
--
-- A reading excluded for any reason is absent from this table -- it has no charge, which
-- is a different fact from a charge of zero. A reading of exactly zero kWh that passes
-- every rule IS charged, at exactly zero, and belongs here.
{{ scenario_fact(ref('int_classified_readings'), var('run_id')) }}
