{{ config(materialized='table') }}

-- One row per **uncharged** distinct reading, with the single reason that applies first
-- by EXCLUSION_ORDER, and every condition also kept as its own flag so the precedence
-- hides nothing.
--
-- There is deliberately no charge column: an excluded reading has no charge at all.
{{ exclusion_fact(ref('int_classified_readings'), var('run_id')) }}
