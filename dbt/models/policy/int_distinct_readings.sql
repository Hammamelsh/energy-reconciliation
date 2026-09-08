{{ config(materialized='ephemeral') }}

-- The policy grain: one row per distinct recorded reading.
--
-- The body comes from the generated macro, which is rendered from policy.py. Nothing is
-- re-expressed here; if this file contained SQL of its own there would be two
-- definitions of the rule again.
--
-- Ephemeral on purpose: it is inlined into whatever selects it, so no stored copy can
-- go stale against the readings it summarises.
{{ distinct_readings(ref('stg_readings')) }}
