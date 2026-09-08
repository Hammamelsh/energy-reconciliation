"""The tariff models, and the run that materialises them.

**Where the business logic lives.** Each model below is one named SELECT over the
warehouse. Streamlit reads the resulting tables and computes nothing. The duplicate,
conflict, missing-value and off-grid rules come from :mod:`energy_reconciliation.policy`
-- the same definitions the explorer uses -- so there is one implementation of each
policy, not two.

**Sequencing note.** ``docs/roadmap.md`` places tariff modelling in M3 alongside dbt,
and M3 has not started. These models are written as standalone SELECTs so that a
dbt-duckdb port starts from working, tested SQL rather than from scratch. That port is
**not** a copy-and-paste exercise: dbt would need model boundaries and materialisations
chosen, ``ref``/``source`` wiring, the Python-side schedule read and price catalogue
handled outside SQL, the rerun and supersede policy re-expressed, and the shared policy
kept to one definition rather than duplicated in Jinja. Until it is done, the roadmap's
dbt deliverable is **not** met by this code (ANL-003).

The assumption
--------------

``A1`` is stamped on **every fact row** and on the run record. Nothing produced here
may be read without it.

Arithmetic
----------

``energy_charge_gbp = consumption_kwh * price_pence_per_kwh / 100``

That division is **not** written literally in SQL. DuckDB evaluates a DECIMAL divided
by an integer as DOUBLE: ``1.125 * 67.2000 / 100`` returns the binary float
``0.7559999999999999``, which is exactly the kind of artefact this project refuses to
put into a money-adjacent figure. Instead ``dim_tariff_price`` stores
``price_gbp_per_kwh``, the pence price divided by 100 **once, exactly, in Python
Decimal** (every documented price has at most three decimal places in pence, so the
division is exact), and the fact multiplies by that. The product is
``DECIMAL(37,16)``; sums are ``DECIMAL(38,16)``. Both are exact.

**No row-level rounding, ever.** Rounding happens once, at the output stage, in
:mod:`energy_reconciliation.tariff.analytics`, to 2 decimal places ROUND_HALF_UP, and
the exact unrounded figure is always carried beside the rounded one.

This is a **historical scenario energy charge**: consumption x band price, and nothing
else. **No separate tax adjustment is applied**, and whether the published rates are
quoted inclusive or exclusive of VAT or any levy is **not established** from the sources
reviewed -- so this figure must not be described as either. No standing charge, discount,
capacity or metering charge and no settlement adjustment is modelled. It is not a bill.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

from ..ingest.loader import pipeline_fingerprint
from ..ingest.warehouse import DECIMAL_PRECISION, DECIMAL_SCALE, connect
from ..policy import CONFLICTING_LABELS, DISTINCT_READINGS, FINITE
from . import identity
from . import prices as pr
from .schedule import Schedule, loaded_at

ASSUMPTION_ID: Final[str] = "A1"
ASSUMPTION_TEXT: Final[str] = (
    "A1 -- same-label convention. A consumption timestamp label and a tariff schedule "
    "label denote corresponding half-hour intervals. This is NOT established from the "
    "sources reviewed: the consumption timestamps carry no timezone, and whether a "
    "label marks the start or the end of its interval is unresolved. The schedule's "
    "own regularity (17,520 labels, 1800-second steps, both 2013 clock-change hours "
    "present once) shows only that the schedule is a fixed nominal grid; it is not "
    "evidence about the consumption data. A unique schedule key prevents join "
    "multiplication -- an arithmetic property -- and establishes no semantic time "
    "alignment. Reversible: the join key is one expression, and every output row "
    "carries this identifier."
)

PRICE_SCALE: Final[int] = 4
GBP_SCALE: Final[int] = 6
CHARGE_PRECISION: Final[int] = 38
CHARGE_SCALE: Final[int] = 16

#: Exclusion reasons, in the order they are applied. A reading can satisfy several
#: conditions at once, so ``exclusion_reason`` is the **first** that applies and every
#: condition is *also* stored as its own boolean, so nothing is hidden by the ordering.
#:
#: Eligibility and coverage come first because they say a charge could not exist at
#: all; a Standard-tariff reading from 2011 is out of scope, not a quality defect.
#: Inside scope, a dispute outranks everything, then the structural question of whether
#: the label belongs to the half-hourly series, then whether a number was recorded.
EXCLUSION_ORDER: Final[tuple[tuple[str, str], ...]] = (
    ("is_ineligible_group", "ineligible_tariff_group"),
    ("is_outside_schedule_period", "outside_schedule_period"),
    ("is_conflicted", "conflicting_label"),
    ("is_off_grid", "off_grid_observation"),
    ("is_missing_value", "missing_value"),
    ("is_unmatched_label", "unmatched_schedule_label"),
    ("is_unpriced_band", "unpriced_band"),
)
EXCLUSION_REASONS: Final[tuple[str, ...]] = tuple(r for _, r in EXCLUSION_ORDER)

SCHEMA: Final[str] = f"""
CREATE TABLE IF NOT EXISTS dim_tariff_band_schedule (
    schedule_label_naive  TIMESTAMP NOT NULL,
    schedule_label_text   VARCHAR   NOT NULL,
    band_label            VARCHAR   NOT NULL,
    schedule_year         INTEGER   NOT NULL,
    on_half_hour_grid     BOOLEAN   NOT NULL,
    schedule_source       VARCHAR   NOT NULL,
    source_sha256         VARCHAR   NOT NULL,
    loaded_at_utc         TIMESTAMP NOT NULL,
    PRIMARY KEY (schedule_label_naive)
);

CREATE TABLE IF NOT EXISTS dim_tariff_price (
    tariff_group         VARCHAR NOT NULL,
    band_label           VARCHAR NOT NULL,
    price_pence_per_kwh  DECIMAL(9,{PRICE_SCALE}) NOT NULL,
    price_gbp_per_kwh    DECIMAL(9,{GBP_SCALE})   NOT NULL,
    currency             VARCHAR NOT NULL,
    price_unit           VARCHAR NOT NULL,
    effective_from       DATE,
    effective_until      DATE,
    evidence_label       VARCHAR NOT NULL,
    source_citation      VARCHAR NOT NULL,
    catalogue_version    VARCHAR NOT NULL,
    PRIMARY KEY (tariff_group, band_label)
);

CREATE TABLE IF NOT EXISTS fact_interval_charge_scenario (
    run_id                VARCHAR   NOT NULL,
    household_id          VARCHAR   NOT NULL,
    tariff_group          VARCHAR   NOT NULL,
    source_timestamp_text VARCHAR   NOT NULL,
    observed_at_naive     TIMESTAMP NOT NULL,
    source_date           DATE      NOT NULL,
    source_hour           SMALLINT  NOT NULL,
    source_month          SMALLINT  NOT NULL,
    band_label            VARCHAR   NOT NULL,
    consumption_kwh       DECIMAL({DECIMAL_PRECISION},{DECIMAL_SCALE}) NOT NULL,
    price_pence_per_kwh   DECIMAL(9,{PRICE_SCALE}) NOT NULL,
    energy_charge_gbp     DECIMAL({CHARGE_PRECISION},{CHARGE_SCALE}) NOT NULL,
    assumption_id         VARCHAR   NOT NULL
);

CREATE TABLE IF NOT EXISTS fact_interval_charge_exclusion (
    run_id                     VARCHAR   NOT NULL,
    household_id               VARCHAR   NOT NULL,
    tariff_group               VARCHAR   NOT NULL,
    source_timestamp_text      VARCHAR   NOT NULL,
    observed_at_naive          TIMESTAMP NOT NULL,
    source_date                DATE      NOT NULL,
    on_half_hour_grid          BOOLEAN,
    consumption_kwh            DECIMAL({DECIMAL_PRECISION},{DECIMAL_SCALE}),
    value_category             VARCHAR   NOT NULL,
    exclusion_reason           VARCHAR   NOT NULL,
    is_ineligible_group        BOOLEAN   NOT NULL,
    is_outside_schedule_period BOOLEAN   NOT NULL,
    is_conflicted              BOOLEAN   NOT NULL,
    is_off_grid                BOOLEAN   NOT NULL,
    is_missing_value           BOOLEAN   NOT NULL,
    is_unmatched_label         BOOLEAN   NOT NULL,
    is_unpriced_band           BOOLEAN   NOT NULL
);

CREATE TABLE IF NOT EXISTS scenario_run (
    run_id                         VARCHAR PRIMARY KEY,
    run_at_utc                     TIMESTAMP NOT NULL,
    scenario_fingerprint           VARCHAR   NOT NULL,
    scope_tariff_group             VARCHAR   NOT NULL,
    assumption_ids                 VARCHAR   NOT NULL,
    assumption_text                VARCHAR   NOT NULL,
    schedule_source                VARCHAR   NOT NULL,
    schedule_sha256                VARCHAR   NOT NULL,
    schedule_rows                  BIGINT    NOT NULL,
    schedule_first_label           TIMESTAMP NOT NULL,
    schedule_last_label            TIMESTAMP NOT NULL,
    price_catalogue_version        VARCHAR   NOT NULL,
    calculation_code_sha256        VARCHAR   NOT NULL,
    policy_sha256                  VARCHAR   NOT NULL,
    model_code_sha256              VARCHAR   NOT NULL,
    runtime_fingerprint            VARCHAR   NOT NULL,
    runtime_detail                 VARCHAR   NOT NULL,
    ingestion_pipeline_fingerprint VARCHAR   NOT NULL,
    source_load_ids                VARCHAR   NOT NULL,
    distinct_readings              BIGINT    NOT NULL,
    included_readings              BIGINT    NOT NULL,
    excluded_readings              BIGINT    NOT NULL,
    raw_rows                       BIGINT    NOT NULL,
    rows_collapsed_by_policy       BIGINT    NOT NULL,
    total_energy_charge_gbp_exact  VARCHAR   NOT NULL,
    status                         VARCHAR   NOT NULL,
    superseded_at_utc              TIMESTAMP
);
"""

# --------------------------------------------------------------------- models
#: Model: every distinct recorded reading classified against eligibility, schedule
#: coverage and the four analytical policies. One row in, one row out -- the LEFT JOIN
#: to the schedule cannot multiply, because the schedule label is a primary key and a
#: duplicate is refused at load time (``schedule._validate``).
CLASSIFIED_READINGS: Final[str] = f"""
WITH distinct_readings AS ({DISTINCT_READINGS}),
conflicting AS ({CONFLICTING_LABELS}),
coverage AS (
    SELECT MIN(schedule_label_naive) AS first_label,
           MAX(schedule_label_naive) AS last_label
    FROM dim_tariff_band_schedule
),
banded_group AS (
    SELECT DISTINCT tariff_group FROM dim_tariff_price WHERE band_label <> '{pr.FLAT_BAND}'
)
SELECT r.household_id,
       r.tariff_group,
       r.source_timestamp_text,
       r.observed_at_naive,
       r.on_half_hour_grid,
       r.consumption_kwh,
       r.value_category,
       s.band_label,
       p.price_pence_per_kwh,
       p.price_gbp_per_kwh,
       (g.tariff_group IS NULL OR r.tariff_group <> ?)          AS is_ineligible_group,
       (cov.first_label IS NULL
        OR r.observed_at_naive < cov.first_label
        OR r.observed_at_naive > cov.last_label)                AS is_outside_schedule_period,
       (c.household_id IS NOT NULL)                             AS is_conflicted,
       (NOT COALESCE(r.on_half_hour_grid, FALSE))               AS is_off_grid,
       (r.value_category <> '{FINITE}' OR r.consumption_kwh IS NULL) AS is_missing_value,
       (s.band_label IS NULL)                                   AS is_unmatched_label,
       (s.band_label IS NOT NULL AND p.price_gbp_per_kwh IS NULL) AS is_unpriced_band
FROM distinct_readings r
CROSS JOIN coverage cov
LEFT JOIN banded_group g ON g.tariff_group = r.tariff_group
LEFT JOIN conflicting c
       ON c.household_id = r.household_id
      AND c.source_timestamp_text = r.source_timestamp_text
LEFT JOIN dim_tariff_band_schedule s
       ON s.schedule_label_naive = r.observed_at_naive
-- A price applies only inside its half-open validity [effective_from, effective_until).
-- A NULL bound is UNKNOWN, not open-ended, so it prices nothing. The schedule's
-- coverage and the price's validity are checked independently: a label the schedule
-- carries but no price covers is excluded as unpriced_band, never charged at zero.
LEFT JOIN dim_tariff_price p
       ON p.tariff_group = r.tariff_group
      AND p.band_label = s.band_label
      AND p.effective_from IS NOT NULL
      AND p.effective_until IS NOT NULL
      AND r.observed_at_naive >= CAST(p.effective_from AS TIMESTAMP)
      AND r.observed_at_naive <  CAST(p.effective_until AS TIMESTAMP)
"""

_EXCLUDED = " OR ".join(flag for flag, _ in EXCLUSION_ORDER)
_REASON_CASE = (
    "CASE\n"
    + "\n".join(f"    WHEN {flag} THEN '{reason}'" for flag, reason in EXCLUSION_ORDER)
    + "\n    END"
)

#: Model: the scenario fact. Charged rows only -- one row per included reading.
FACT_SELECT: Final[str] = f"""
INSERT INTO fact_interval_charge_scenario
SELECT ? AS run_id,
       household_id,
       tariff_group,
       source_timestamp_text,
       observed_at_naive,
       CAST(observed_at_naive AS DATE)                 AS source_date,
       CAST(EXTRACT(hour  FROM observed_at_naive) AS SMALLINT) AS source_hour,
       CAST(EXTRACT(month FROM observed_at_naive) AS SMALLINT) AS source_month,
       band_label,
       consumption_kwh,
       price_pence_per_kwh,
       CAST(consumption_kwh * price_gbp_per_kwh
            AS DECIMAL({CHARGE_PRECISION},{CHARGE_SCALE}))     AS energy_charge_gbp,
       '{ASSUMPTION_ID}'                               AS assumption_id
FROM ({CLASSIFIED_READINGS}) classified
WHERE NOT ({_EXCLUDED})
"""

#: Model: everything the scenario did **not** charge, each with one explicit reason and
#: every condition kept as its own flag. Never a zero charge.
EXCLUSION_SELECT: Final[str] = f"""
INSERT INTO fact_interval_charge_exclusion
SELECT ? AS run_id,
       household_id,
       tariff_group,
       source_timestamp_text,
       observed_at_naive,
       CAST(observed_at_naive AS DATE) AS source_date,
       on_half_hour_grid,
       consumption_kwh,
       value_category,
       {_REASON_CASE} AS exclusion_reason,
       is_ineligible_group,
       is_outside_schedule_period,
       is_conflicted,
       is_off_grid,
       is_missing_value,
       is_unmatched_label,
       is_unpriced_band
FROM ({CLASSIFIED_READINGS}) classified
WHERE {_EXCLUDED}
"""


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    run_id: str
    scenario_fingerprint: str
    skipped: bool
    replaced_previous: bool
    distinct_readings: int
    included_readings: int
    excluded_readings: int
    raw_rows: int
    rows_collapsed_by_policy: int
    total_energy_charge_gbp_exact: str
    reasons: dict[str, int]

    @property
    def reconciles(self) -> bool:
        """Every distinct reading is either charged or excluded with a reason."""
        return (
            self.included_readings + self.excluded_readings == self.distinct_readings
            and sum(self.reasons.values()) == self.excluded_readings
        )


def tariff_code_fingerprint() -> str:
    """Identify every first-party file that can change a stored figure.

    Delegates to :mod:`energy_reconciliation.tariff.identity`, which lists the files one
    by one rather than hashing a single package directory. That matters: the models
    import ``policy.py`` from the parent package and the loader's classification rules
    from ``ingest``/``profiling``, so a package-local hash of ``tariff/*.py`` would let a
    changed policy rule through without invalidating anything. The test suite compares
    the covered list against the real import closure of the models.

    Not covered, and stated rather than implied: tests, ``pyproject.toml``, the operating
    system and the DuckDB build. Library versions are covered separately by
    :func:`identity.runtime_fingerprint`.
    """
    return identity.calculation_digest()


#: Columns ``scenario_run`` must have. A warehouse written by an earlier version of this
#: module will not have them, and every tariff table is **derived** -- rebuildable from
#: the source archive and the workbook -- so the safe repair is to drop and rebuild
#: rather than to guess at a migration. Nothing in ``readings`` is touched.
_RUN_COLUMNS_EXPECTED: Final[tuple[str, ...]] = (
    "run_id",
    "run_at_utc",
    "scenario_fingerprint",
    "scope_tariff_group",
    "assumption_ids",
    "assumption_text",
    "schedule_source",
    "schedule_sha256",
    "schedule_rows",
    "schedule_first_label",
    "schedule_last_label",
    "price_catalogue_version",
    "calculation_code_sha256",
    "policy_sha256",
    "model_code_sha256",
    "runtime_fingerprint",
    "runtime_detail",
    "ingestion_pipeline_fingerprint",
    "source_load_ids",
    "distinct_readings",
    "included_readings",
    "excluded_readings",
    "raw_rows",
    "rows_collapsed_by_policy",
    "total_energy_charge_gbp_exact",
    "status",
    "superseded_at_utc",
)

_DERIVED_TABLES: Final[tuple[str, ...]] = (
    "fact_interval_charge_scenario",
    "fact_interval_charge_exclusion",
    "dim_tariff_band_schedule",
    "dim_tariff_price",
    "scenario_run",
)


def ensure_schema(con) -> bool:
    """Create the tariff tables, rebuilding them if an older shape is present.

    Returns True when an outdated shape was dropped, so the caller can say so out loud
    instead of a schema change happening silently.
    """
    existing = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    outdated = False
    if "scenario_run" in existing:
        columns = tuple(r[0] for r in con.execute("DESCRIBE scenario_run").fetchall())
        outdated = columns != _RUN_COLUMNS_EXPECTED
    if not outdated and "fact_interval_charge_exclusion" in existing:
        columns = {
            r[0]
            for r in con.execute("DESCRIBE fact_interval_charge_exclusion").fetchall()
        }
        outdated = "source_date" not in columns
    if not outdated and "dim_tariff_price" in existing:
        columns = {r[0] for r in con.execute("DESCRIBE dim_tariff_price").fetchall()}
        outdated = "effective_until" not in columns
    if outdated:
        for table in _DERIVED_TABLES:
            con.execute(f"DROP TABLE IF EXISTS {table}")
    con.execute(SCHEMA)
    return outdated


def _published_load_ids(con) -> list[str]:
    """Load *events*, for provenance. Recorded, never fingerprinted -- see below."""
    return [
        r[0]
        for r in con.execute(
            "SELECT load_id FROM load_registry WHERE status = 'published' ORDER BY load_id"
        ).fetchall()
    ]


def _published_input_identity(con) -> list[str]:
    """What was loaded, by **content**: member name, decompressed digest, pipeline.

    Deliberately not the load id. A load id carries the moment of loading, so two
    databases holding byte-identical rows would fingerprint differently purely because
    they were built at different times -- which makes the fingerprint impossible to
    reproduce and therefore worthless as a reproducibility claim. This was not
    theoretical: replaying a captured baseline into a fresh database matched every
    figure and still disagreed on the fingerprint, for exactly that reason.

    The **archive file name** is left out for the same reason at one remove: it is where
    the bytes were found, not what they are. The decompressed content digest already
    pins the bytes, and the archive name and digest are both recorded as provenance.
    """
    return [
        f"{r[0]}|{r[1]}|{r[2]}"
        for r in con.execute(
            "SELECT member_name, member_content_sha256, pipeline_fingerprint "
            "FROM load_registry WHERE status = 'published' "
            "ORDER BY member_name, member_content_sha256"
        ).fetchall()
    ]


def scenario_fingerprint(
    schedule: Schedule, inputs: list[str], tariff_group: str
) -> str:
    """What the result depends on. Any change here must rebuild.

    Participating in invalidation, each for a reason:

    - **schedule source, file digest and contents** -- different bands, different answer;
    - **price catalogue version** -- different prices, different answer;
    - **calculation code digest** -- every first-party file that can change a figure,
      the shared ``policy.py`` included, not merely this package;
    - **runtime fingerprint** -- a different decimal engine is a different calculation;
    - **ingestion pipeline fingerprint** -- the rows themselves were parsed by that code;
    - **tariff group scope and assumption id** -- different question, different answer;
    - **input content identity** -- archive, member and decompressed digest of every
      published load, *not* the load event id, so the same bytes loaded on a different
      day fingerprint the same.

    A result that survives a change to any of these was produced by different inputs or
    different logic and must not be presented as current.
    """
    parts = [
        schedule.source,
        schedule.source_sha256,
        schedule.content_digest,
        pr.PRICE_CATALOGUE_VERSION,
        identity.calculation_digest(),
        identity.runtime_fingerprint(),
        pipeline_fingerprint(),
        tariff_group,
        ASSUMPTION_ID,
        "::".join(inputs),
    ]
    return hashlib.sha256("::".join(parts).encode()).hexdigest()


def _load_dimensions(con, schedule: Schedule, when: datetime) -> None:
    con.execute("DELETE FROM dim_tariff_band_schedule")
    con.executemany(
        "INSERT INTO dim_tariff_band_schedule VALUES (?,?,?,?,?,?,?,?)",
        [
            (
                row.label,
                row.label.isoformat(sep=" "),
                row.band_label,
                row.label.year,
                True,
                schedule.source,
                schedule.source_sha256,
                when,
            )
            for row in schedule.rows
        ],
    )
    con.execute("DELETE FROM dim_tariff_price")
    con.executemany(
        "INSERT INTO dim_tariff_price VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                p.tariff_group,
                p.band_label,
                p.pence_per_kwh,
                p.gbp_per_kwh,
                "GBP",
                "pence_per_kwh",
                p.effective_from,
                p.effective_until,
                p.evidence_label,
                p.source_citation,
                pr.PRICE_CATALOGUE_VERSION,
            )
            for p in pr.CATALOGUE
        ],
    )


def build_scenario(
    database: Path,
    schedule: Schedule,
    *,
    tariff_group: str = pr.TOU_GROUP,
    force: bool = False,
) -> ScenarioResult:
    """Materialise the tariff models. Rerunning identical inputs is a no-op.

    Same rerun policy as ingestion, for the same reason: an unchanged rebuild must be
    a provable no-op, and a changed input must supersede rather than accumulate. The
    whole build runs in one transaction, so a failure leaves the previous published
    scenario exactly as it was.
    """
    con = connect(database)
    try:
        rebuilt_schema = ensure_schema(con)
        load_ids = _published_load_ids(con)
        fingerprint = scenario_fingerprint(
            schedule, _published_input_identity(con), tariff_group
        )
        previous = con.execute(
            "SELECT run_id, scenario_fingerprint FROM scenario_run "
            "WHERE status = 'published' ORDER BY run_at_utc DESC LIMIT 1"
        ).fetchone()
        if previous and previous[1] == fingerprint and not force and not rebuilt_schema:
            return _describe(
                con, previous[0], fingerprint, skipped=True, replaced=False
            )

        when = loaded_at()
        run_id = f"{fingerprint[:12]}@{when.strftime('%Y%m%dT%H%M%S%f')}"
        con.begin()
        try:
            _load_dimensions(con, schedule, when)
            con.execute("DELETE FROM fact_interval_charge_scenario")
            con.execute("DELETE FROM fact_interval_charge_exclusion")
            con.execute(
                "UPDATE scenario_run SET status = 'superseded', superseded_at_utc = ? "
                "WHERE status = 'published'",
                [when],
            )
            con.execute(FACT_SELECT, [run_id, tariff_group])
            con.execute(EXCLUSION_SELECT, [run_id, tariff_group])
            counts = _counts(con, run_id, tariff_group)
            con.execute(
                "INSERT INTO scenario_run VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    run_id,
                    when,
                    fingerprint,
                    tariff_group,
                    ASSUMPTION_ID,
                    ASSUMPTION_TEXT,
                    schedule.source,
                    schedule.source_sha256,
                    len(schedule.rows),
                    schedule.first_label,
                    schedule.last_label,
                    pr.PRICE_CATALOGUE_VERSION,
                    identity.calculation_digest(),
                    identity.policy_digest(),
                    identity.model_digest(),
                    identity.runtime_fingerprint(),
                    json.dumps(identity.runtime_identity(), sort_keys=True),
                    pipeline_fingerprint(),
                    "|".join(load_ids),
                    counts["distinct_readings"],
                    counts["included_readings"],
                    counts["excluded_readings"],
                    counts["raw_rows"],
                    counts["rows_collapsed_by_policy"],
                    counts["total_energy_charge_gbp_exact"],
                    "published",
                    None,
                ],
            )
            con.commit()
        except BaseException:
            con.rollback()
            raise
        return _describe(
            con, run_id, fingerprint, skipped=False, replaced=previous is not None
        )
    finally:
        con.close()


def _counts(con, run_id: str, tariff_group: str) -> dict:
    raw_rows = con.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
    distinct = con.execute(f"SELECT COUNT(*) FROM ({DISTINCT_READINGS})").fetchone()[0]
    included = con.execute(
        "SELECT COUNT(*) FROM fact_interval_charge_scenario WHERE run_id = ?", [run_id]
    ).fetchone()[0]
    excluded = con.execute(
        "SELECT COUNT(*) FROM fact_interval_charge_exclusion WHERE run_id = ?", [run_id]
    ).fetchone()[0]
    total = con.execute(
        "SELECT COALESCE(SUM(energy_charge_gbp), 0) FROM fact_interval_charge_scenario "
        "WHERE run_id = ?",
        [run_id],
    ).fetchone()[0]
    return {
        "raw_rows": int(raw_rows),
        "distinct_readings": int(distinct),
        "included_readings": int(included),
        "excluded_readings": int(excluded),
        "rows_collapsed_by_policy": int(raw_rows) - int(distinct),
        "total_energy_charge_gbp_exact": str(total),
        "tariff_group": tariff_group,
    }


def _describe(
    con, run_id: str, fingerprint: str, *, skipped: bool, replaced: bool
) -> ScenarioResult:
    row = con.execute(
        "SELECT distinct_readings, included_readings, excluded_readings, raw_rows, "
        "rows_collapsed_by_policy, total_energy_charge_gbp_exact "
        "FROM scenario_run WHERE run_id = ?",
        [run_id],
    ).fetchone()
    reasons = dict(
        con.execute(
            "SELECT exclusion_reason, COUNT(*) FROM fact_interval_charge_exclusion "
            "WHERE run_id = ? GROUP BY 1 ORDER BY 1",
            [run_id],
        ).fetchall()
    )
    return ScenarioResult(
        run_id=run_id,
        scenario_fingerprint=fingerprint,
        skipped=skipped,
        replaced_previous=replaced,
        distinct_readings=int(row[0]),
        included_readings=int(row[1]),
        excluded_readings=int(row[2]),
        raw_rows=int(row[3]),
        rows_collapsed_by_policy=int(row[4]),
        total_energy_charge_gbp_exact=str(row[5]),
        reasons={k: int(v) for k, v in reasons.items()},
    )
