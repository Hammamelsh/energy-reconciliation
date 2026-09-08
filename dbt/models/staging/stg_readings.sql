{{ config(materialized='view') }}

-- A column contract over the source and nothing else. No filter, no rename, no policy:
-- the four analytical policies are applied downstream by the generated macros, so this
-- view cannot quietly become a second place where rules live.
--
-- Columns are listed rather than SELECT *, so a column removed by a future ingestion
-- change fails here, next to the source, instead of somewhere further down.
SELECT
    load_id,
    archive_name,
    member_name,
    source_record_no,
    household_id,
    tariff_group,
    source_timestamp_text,
    observed_at_naive,
    timezone_status,
    interval_anchor_status,
    on_half_hour_grid,
    consumption_kwh,
    consumption_raw_text,
    value_category
FROM {{ source('warehouse', 'readings') }}
