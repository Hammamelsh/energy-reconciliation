-- The reported reason must be a known one AND the first that applies by EXCLUSION_ORDER.
--
-- This is the check that survives a balanced error: swapping two reasons leaves every
-- count identical and every total unchanged, so the reconciliation test still passes.
-- Recomputing the precedence from the stored flags is what detects it.
SELECT household_id, source_timestamp_text, exclusion_reason
FROM {{ ref('fact_interval_charge_exclusion') }}
WHERE exclusion_reason NOT IN {{ exclusion_reasons() }}
   OR exclusion_reason <> ({{ exclusion_reason_case() }})
