"""Schema for the local warehouse.

One DuckDB file holds every loaded member. The schema keeps the source text alongside
the parsed values, so nothing observed is lost and nothing unresolved is implied to be
resolved.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import duckdb

DEFAULT_DATABASE = Path("data/warehouse/energy.duckdb")

#: Consumption is stored exactly, never rounded. The source's highest observed
#: precision is seven decimal places (6.5279999), so seven would leave no headroom at
#: all: one member with an eighth digit would start rejecting real readings. Ten
#: decimal places and eighteen integer digits give room without giving up exactness.
#: A value that still does not fit is rejected rather than rounded -- see
#: loader.classify_for_storage.
DECIMAL_PRECISION: Final[int] = 28
DECIMAL_SCALE: Final[int] = 10

SCHEMA: Final[str] = f"""
CREATE TABLE IF NOT EXISTS readings (
    load_id                 VARCHAR   NOT NULL,
    archive_name            VARCHAR   NOT NULL,
    member_name             VARCHAR   NOT NULL,
    source_record_no        BIGINT    NOT NULL,
    household_id            VARCHAR   NOT NULL,
    tariff_group            VARCHAR   NOT NULL,
    source_timestamp_text   VARCHAR   NOT NULL,
    observed_at_naive       TIMESTAMP,
    timezone_status         VARCHAR   NOT NULL,
    interval_anchor_status  VARCHAR   NOT NULL,
    on_half_hour_grid       BOOLEAN,
    consumption_kwh         DECIMAL({DECIMAL_PRECISION},{DECIMAL_SCALE}),
    consumption_raw_text    VARCHAR   NOT NULL,
    value_category          VARCHAR   NOT NULL
);

CREATE TABLE IF NOT EXISTS rejected_records (
    load_id            VARCHAR NOT NULL,
    archive_name       VARCHAR NOT NULL,
    member_name        VARCHAR NOT NULL,
    source_record_no   BIGINT  NOT NULL,
    reason             VARCHAR NOT NULL,
    detail             VARCHAR,
    source_fields      VARCHAR
);

CREATE TABLE IF NOT EXISTS load_registry (
    load_id                VARCHAR PRIMARY KEY,
    archive_name           VARCHAR   NOT NULL,
    archive_sha256         VARCHAR   NOT NULL,
    member_name            VARCHAR   NOT NULL,
    member_content_sha256  VARCHAR   NOT NULL,
    loaded_at_utc          TIMESTAMP NOT NULL,
    records_read           BIGINT    NOT NULL,
    records_published      BIGINT    NOT NULL,
    records_rejected       BIGINT    NOT NULL,
    profiler_source_sha256 VARCHAR,
    pipeline_fingerprint   VARCHAR   NOT NULL,
    status                 VARCHAR   NOT NULL,
    superseded_at_utc      TIMESTAMP
);
"""

#: Duplicate and conflict detection. Nothing is removed at load time; these views make
#: the different cases countable without changing what was recorded.
VIEWS: Final[str] = """
CREATE OR REPLACE VIEW v_candidate_key_collisions AS
SELECT household_id,
       source_timestamp_text,
       COUNT(*)                                   AS rows_at_key,
       COUNT(DISTINCT value_signature)            AS distinct_values,
       COUNT(DISTINCT member_name)                AS members_involved
FROM (
    SELECT household_id,
           source_timestamp_text,
           member_name,
           COALESCE(CAST(consumption_kwh AS VARCHAR), '~' || value_category)
               AS value_signature
    FROM readings
)
GROUP BY household_id, source_timestamp_text
HAVING COUNT(*) > 1;

CREATE OR REPLACE VIEW v_conflicting_keys AS
SELECT * FROM v_candidate_key_collisions WHERE distinct_values > 1;

-- The single definition of "the same recorded reading". Household, source timestamp
-- text, tariff group and the raw consumption text -- deliberately NOT the member, so a
-- reading repeated across two members counts as one duplicate group here and in every
-- total that uses this policy.
CREATE OR REPLACE VIEW v_distinct_readings AS
SELECT DISTINCT household_id, tariff_group, source_timestamp_text,
       consumption_raw_text, consumption_kwh, value_category
FROM readings;

CREATE OR REPLACE VIEW v_exact_duplicates AS
SELECT household_id, tariff_group, source_timestamp_text, consumption_raw_text,
       COUNT(*) AS rows_in_group, COUNT(*) - 1 AS extra_rows
FROM readings
GROUP BY household_id, tariff_group, source_timestamp_text, consumption_raw_text
HAVING COUNT(*) > 1;

CREATE OR REPLACE VIEW v_household_coverage AS
SELECT household_id,
       COUNT(*)                          AS observed_records,
       COUNT(DISTINCT member_name)       AS members,
       MIN(source_timestamp_text)        AS first_timestamp_text,
       MAX(source_timestamp_text)        AS last_timestamp_text,
       SUM(CASE WHEN value_category = 'finite_numeric' THEN 1 ELSE 0 END) AS finite_values,
       SUM(CASE WHEN value_category = 'null_token'     THEN 1 ELSE 0 END) AS null_tokens,
       SUM(CASE WHEN consumption_kwh = 0              THEN 1 ELSE 0 END) AS zero_values
FROM readings
GROUP BY household_id;
"""


def connect(database: Path = DEFAULT_DATABASE, *, read_only: bool = False):
    """Open the warehouse, creating the schema when it does not yet exist."""
    database.parent.mkdir(parents=True, exist_ok=True)
    if read_only and not database.exists():
        msg = f"no warehouse at {database}; run the ingest command first"
        raise FileNotFoundError(msg)
    con = duckdb.connect(str(database), read_only=read_only)
    if not read_only:
        con.execute(SCHEMA)
        con.execute(VIEWS)
    return con
