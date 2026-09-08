{{ config(materialized='ephemeral') }}

-- Labels where the source does not agree with itself. Body from the generated macro.
{{ conflicting_labels(ref('stg_readings')) }}
