"""Reading the materialised tariff models. No business logic, no Streamlit.

Every energy and money figure arrives from the database as an exact ``Decimal`` and is
carried as one. Two columns are produced for each:

- ``*_exact`` -- the unrounded value as text, which is the figure of record;
- ``*_display`` -- the same value rounded **once** for presentation, and a float copy
  used only to draw a bar.

**Rounding rule.** Money: 2 decimal places, ``ROUND_HALF_UP``, applied at this stage
and nowhere earlier. Energy: 3 decimal places for display, same rule. Shares: 4
decimal places. No row-level rounding happens anywhere, so no rounding drift can
accumulate across a million rows.

**Three scopes, never mixed**, and every function says which one it answers:

- *Schedule-wide* -- the published band schedule itself, independent of which households
  are loaded.
- *Loaded sample* -- every household charged by the run, across the ingested members,
  which are a handful of 168 and a bounded, non-representative subset.
- *Selected household* -- one household from that sample.

**One period, applied identically.** Every loaded-sample and selected-household function
takes the same optional ``start``/``end`` source-date bounds, and both share denominators
are computed over exactly the rows that period selects. A share is never a ratio of two
differently scoped totals.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Final

import pandas as pd

from ..ingest.warehouse import connect
from .models import EXCLUSION_REASONS

MONEY_DP = Decimal("0.01")
ENERGY_DP = Decimal("0.001")
SHARE_DP = Decimal("0.0001")

#: What the scenario charge does and does not contain. The tax wording is deliberate:
#: the publisher gives rates in pence per kWh without stating their tax treatment, so
#: this says what the calculation does rather than claiming the rates exclude VAT.
CHARGE_SCOPE = (
    "Historical scenario energy charge only: consumption x band price. **No separate "
    "tax adjustment is applied**, and whether the published rates are quoted inclusive "
    "or exclusive of VAT or any levy is not established from the sources reviewed. No "
    "standing charge, discount, capacity or metering charge and no settlement "
    "adjustment is modelled. It is not a bill and was never billed to anyone."
)

#: Band order used in every table and chart: cheapest to dearest, so a reader compares
#: like with like instead of whatever order the database returned.
BAND_ORDER = ("Low", "Normal", "High")


#: Schemas a relation may live in. ``main`` is what ingestion and the Python scenario
#: builder write; ``scenario_build`` is what dbt builds. Nothing else is addressable, and
#: a name is never taken from a caller: :class:`Relations` is built from these two fixed
#: vocabularies, so no query here can be pointed at an arbitrary identifier.
WAREHOUSE_SCHEMA: Final[str] = "main"
BUILD_SCHEMA: Final[str] = "scenario_build"
_SCHEMAS: Final[frozenset[str]] = frozenset({WAREHOUSE_SCHEMA, BUILD_SCHEMA})

_TABLES: Final[frozenset[str]] = frozenset(
    {
        "readings",
        "load_registry",
        "fact_interval_charge_scenario",
        "fact_interval_charge_exclusion",
        "dim_tariff_band_schedule",
        "dim_tariff_price",
        "scenario_run",
    }
)


class RelationError(ValueError):
    """A relation was not one of the fixed schema/table pairs this module may read."""


def _relation(schema: str, table: str) -> str:
    """A fully qualified relation name, checked against the two fixed vocabularies."""
    if schema not in _SCHEMAS or table not in _TABLES:
        raise RelationError(
            f"{schema}.{table} is not a readable relation. Schemas: "
            f"{sorted(_SCHEMAS)}; tables: {sorted(_TABLES)}."
        )
    return f"{schema}.{table}"


@dataclass(frozen=True, slots=True)
class Relations:
    """Which relations a read goes to, fully qualified and fixed at construction.

    Routing is explicit and per query. It is deliberately **not** a session search path:
    a search path is process-wide state that would silently decide, at some later
    statement, which of two schemas a bare ``fact_interval_charge_scenario`` meant -- and
    the two hold different runs of different builders. Every query below names its schema.

    ``scenario_run`` exists only on the Python route. On the dbt route it is ``None``, and
    the functions that need it refuse rather than fall back to ``main``.
    """

    readings: str
    load_registry: str
    fact_scenario: str
    fact_exclusion: str
    dim_schedule: str
    dim_price: str
    scenario_run: str | None
    label: str

    @property
    def has_run_table(self) -> bool:
        return self.scenario_run is not None


#: The Python scenario builder's outputs, all in ``main``. Every existing caller keeps
#: this route by default, so nothing that works today changes.
WAREHOUSE_RELATIONS: Final[Relations] = Relations(
    readings=_relation(WAREHOUSE_SCHEMA, "readings"),
    load_registry=_relation(WAREHOUSE_SCHEMA, "load_registry"),
    fact_scenario=_relation(WAREHOUSE_SCHEMA, "fact_interval_charge_scenario"),
    fact_exclusion=_relation(WAREHOUSE_SCHEMA, "fact_interval_charge_exclusion"),
    dim_schedule=_relation(WAREHOUSE_SCHEMA, "dim_tariff_band_schedule"),
    dim_price=_relation(WAREHOUSE_SCHEMA, "dim_tariff_price"),
    scenario_run=_relation(WAREHOUSE_SCHEMA, "scenario_run"),
    label="python warehouse (main)",
)

#: A validated dbt build. The **inputs** still come from ``main`` -- a build never writes
#: them, and a version file holds one coherent copy -- while every tariff relation comes
#: from ``scenario_build``. There is no ``scenario_run``: the run identity comes from the
#: build record and the seal, never from the copied Python run that shares the file.
DBT_RELATIONS: Final[Relations] = Relations(
    readings=_relation(WAREHOUSE_SCHEMA, "readings"),
    load_registry=_relation(WAREHOUSE_SCHEMA, "load_registry"),
    fact_scenario=_relation(BUILD_SCHEMA, "fact_interval_charge_scenario"),
    fact_exclusion=_relation(BUILD_SCHEMA, "fact_interval_charge_exclusion"),
    dim_schedule=_relation(BUILD_SCHEMA, "dim_tariff_band_schedule"),
    dim_price=_relation(BUILD_SCHEMA, "dim_tariff_price"),
    scenario_run=None,
    label="dbt build (scenario_build)",
)


def _con(database: Path):
    return connect(database, read_only=True)


def round_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_DP, rounding=ROUND_HALF_UP)


def round_energy(value: Decimal) -> Decimal:
    return value.quantize(ENERGY_DP, rounding=ROUND_HALF_UP)


def round_share(value: Decimal) -> Decimal:
    return value.quantize(SHARE_DP, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class RunRecord:
    run_id: str
    run_at_utc: str
    scenario_fingerprint: str
    scope_tariff_group: str
    assumption_ids: str
    assumption_text: str
    schedule_source: str
    schedule_sha256: str
    schedule_rows: int
    schedule_first_label: str
    schedule_last_label: str
    price_catalogue_version: str
    calculation_code_sha256: str
    policy_sha256: str
    model_code_sha256: str
    runtime_fingerprint: str
    runtime_detail: str
    ingestion_pipeline_fingerprint: str
    source_load_ids: str
    distinct_readings: int
    included_readings: int
    excluded_readings: int
    raw_rows: int
    rows_collapsed_by_policy: int
    total_energy_charge_gbp_exact: str

    @property
    def total_charge(self) -> Decimal:
        return Decimal(self.total_energy_charge_gbp_exact)

    @property
    def is_synthetic(self) -> bool:
        return self.schedule_source != "Tariffs.xlsx"

    @property
    def runtime(self) -> dict[str, str]:
        try:
            return json.loads(self.runtime_detail)
        except (TypeError, ValueError):  # pragma: no cover - only on a corrupt row
            return {}


_RUN_COLUMNS = (
    "run_id, CAST(run_at_utc AS VARCHAR), scenario_fingerprint, scope_tariff_group, "
    "assumption_ids, assumption_text, schedule_source, schedule_sha256, schedule_rows, "
    "CAST(schedule_first_label AS VARCHAR), CAST(schedule_last_label AS VARCHAR), "
    "price_catalogue_version, calculation_code_sha256, policy_sha256, "
    "model_code_sha256, runtime_fingerprint, runtime_detail, "
    "ingestion_pipeline_fingerprint, "
    "source_load_ids, distinct_readings, included_readings, excluded_readings, "
    "raw_rows, rows_collapsed_by_policy, total_energy_charge_gbp_exact"
)


#: Exactly the columns ``_RUN_COLUMNS`` reads, in the order ``RunRecord`` expects them.
#: Checked against what is actually persisted **before** the SELECT runs, so a schema
#: this code cannot read is reported as such instead of arriving as a raw
#: ``BinderException`` from the middle of a page.
EXPECTED_RUN_COLUMNS: tuple[str, ...] = (
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
)

#: Read by the WHERE and ORDER BY, and written by the build, but not selected into
#: ``RunRecord``. Required all the same.
_RUN_COLUMNS_ALSO_REQUIRED: tuple[str, ...] = ("status", "superseded_at_utc")

#: Every column this code needs ``scenario_run`` to have. A database holding **more**
#: than this is still readable -- extra columns are simply not selected -- so only a
#: *missing* column makes a schema unreadable. Extra columns are reported because their
#: presence alongside a missing one is what says the two sides are different
#: generations rather than one merely being older.
REQUIRED_RUN_COLUMNS: tuple[str, ...] = (
    *EXPECTED_RUN_COLUMNS,
    *_RUN_COLUMNS_ALSO_REQUIRED,
)

READY, ABSENT, INCOMPATIBLE = "ready", "absent", "incompatible"


class ScenarioSchemaError(RuntimeError):
    """The persisted tariff schema is not the one this code reads.

    Deliberately its own error rather than a ``None`` return. "No scenario has been
    built" and "a scenario exists but this process cannot read it" are different facts,
    and reporting the second as the first would show an empty tab over real data.
    """


@dataclass(frozen=True, slots=True)
class ScenarioAvailability:
    """Whether the tariff artefacts can be read, and what to do when they cannot.

    **Schema compatibility only.** This says whether the columns line up. It says
    nothing about whether the *content* is current -- that is the scenario fingerprint's
    job, and the two are kept apart on purpose.
    """

    state: str
    missing_columns: tuple[str, ...] = ()
    unexpected_columns: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return self.state == READY

    @property
    def diagnosis(self) -> str:
        """What the direction of the mismatch shows, without over-claiming.

        A column this code needs but the database lacks is the only thing that makes a
        schema unreadable. Whether *that* database has columns this code does not know
        about is the extra signal: both together mean the two sides were written by
        different generations of the code, which is what a long-lived process against a
        rebuilt database looks like.
        """
        if self.state != INCOMPATIBLE:
            return ""
        if self.unexpected_columns:
            return (
                "The database and this process were written by different generations "
                "of the code: it needs "
                f"{', '.join(f'`{c}`' for c in self.missing_columns)} and the database "
                "instead holds "
                f"{', '.join(f'`{c}`' for c in self.unexpected_columns)}. The usual "
                "cause is a long-lived server: it keeps the modules it imported at "
                "start-up, the tariff modules are **not** in Streamlit's reload scope, "
                "and a rebuild in another terminal moves the schema underneath it."
            )
        return (
            "The database is missing "
            f"{', '.join(f'`{c}`' for c in self.missing_columns)}, which this code "
            "needs. Its tariff tables predate the current model."
        )

    @property
    def recovery(self) -> str:
        if self.state == ABSENT:
            return "No tariff scenario has been built for this database yet."
        if self.unexpected_columns:
            return (
                "Restart the app first — if the process is the stale side, that alone "
                "fixes it and nothing is rebuilt. If the message persists after a "
                "restart, rebuild with `build-tariff-scenario`."
            )
        return "Rebuild the scenario with `build-tariff-scenario`."


def scenario_columns(database: Path) -> tuple[str, ...] | None:
    """The persisted ``main.scenario_run`` columns, or None if the table is absent.

    The Python route only: ``scenario_run`` is written by ``build-tariff-scenario`` and
    a dbt build creates nothing like it. See :func:`require_run_table`.
    """
    con = _con(database)
    try:
        found = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = ? "
            "AND table_name = 'scenario_run'",
            [WAREHOUSE_SCHEMA],
        ).fetchone()[0]
        if not found:
            return None
        return tuple(
            r[0]
            for r in con.execute(
                "SELECT column_name FROM information_schema.columns WHERE "
                "table_schema = ? AND table_name = 'scenario_run' "
                "ORDER BY ordinal_position",
                [WAREHOUSE_SCHEMA],
            ).fetchall()
        )
    finally:
        con.close()


def require_run_table(relations: Relations, what: str) -> str:
    """The ``scenario_run`` relation, or an explicit refusal.

    A dbt build records its identity in ``scenario_build.dbt_build_run`` and in its seal,
    which is a **different record with different fields**. Falling back to
    ``main.scenario_run`` would answer with the copied Python run that happens to share
    the file, so this raises instead.
    """
    if relations.scenario_run is None:
        raise ScenarioSchemaError(
            f"{what} needs a scenario_run table, which the {relations.label} route does "
            "not have. A dbt build's identity is its build record and seal; read it from "
            "the read context instead of this function. Nothing was read from main."
        )
    return relations.scenario_run


def scenario_availability(database: Path) -> ScenarioAvailability:
    """Can this process read this database's tariff artefacts? Checked, not assumed."""
    columns = scenario_columns(database)
    if columns is None:
        return ScenarioAvailability(ABSENT)
    actual, required = set(columns), set(REQUIRED_RUN_COLUMNS)
    missing = required - actual
    if not missing:
        # Extra columns are harmless: they are simply not selected. Only a column this
        # code needs and cannot find makes the schema unreadable.
        return ScenarioAvailability(READY)
    return ScenarioAvailability(
        INCOMPATIBLE, tuple(sorted(missing)), tuple(sorted(actual - required))
    )


def has_scenario(database: Path) -> bool:
    return scenario_columns(database) is not None


def latest_run(database: Path) -> RunRecord | None:
    """The current published scenario run.

    Returns None only when **no scenario has been built**. A scenario that exists but
    cannot be read raises :class:`ScenarioSchemaError`, so it can never be mistaken for
    an absence of data.
    """
    availability = scenario_availability(database)
    if availability.state == ABSENT:
        return None
    if availability.state == INCOMPATIBLE:
        raise ScenarioSchemaError(
            f"{database}: scenario_run has a schema this code does not read. "
            f"Missing: {availability.missing_columns or '(none)'}. "
            f"Unexpected: {availability.unexpected_columns or '(none)'}. "
            f"{availability.recovery}"
        )
    con = _con(database)
    try:
        row = con.execute(
            f"SELECT {_RUN_COLUMNS} FROM {WAREHOUSE_SCHEMA}.scenario_run "
            "WHERE status = 'published' "
            "ORDER BY run_at_utc DESC LIMIT 1"
        ).fetchone()
    finally:
        con.close()
    return RunRecord(*row) if row else None


# --------------------------------------------------------------- period scope
def _period(
    where: str, params: list, start: date | None, end: date | None, column: str
) -> tuple[str, list]:
    """Add the same source-date bounds to every scenario query.

    One helper, used by every loaded-sample and selected-household function, so the two
    share denominators can never be computed over different windows.
    """
    if start is not None:
        where += f" AND {column} >= ?"
        params = [*params, start]
    if end is not None:
        where += f" AND {column} <= ?"
        params = [*params, end]
    return where, params


def _fact_scope(
    run_id: str, household: str | None, start: date | None, end: date | None
) -> tuple[str, list]:
    where, params = "run_id = ?", [run_id]
    if household is not None:
        where += " AND household_id = ?"
        params.append(household)
    return _period(where, params, start, end, "source_date")


def schedule_bounds(
    database: Path, *, relations: Relations = WAREHOUSE_RELATIONS
) -> tuple[date, date] | None:
    """The schedule's own coverage. The scenario period control is bounded by this."""
    con = _con(database)
    try:
        row = con.execute(
            "SELECT MIN(CAST(schedule_label_naive AS DATE)), "
            f"MAX(CAST(schedule_label_naive AS DATE)) FROM {relations.dim_schedule}"
        ).fetchone()
    finally:
        con.close()
    return (row[0], row[1]) if row and row[0] is not None else None


# ------------------------------------------------------------- what was counted
@dataclass(frozen=True, slots=True)
class Accounting:
    """The reconciliation ladder. Every recorded row ends in exactly one place."""

    raw_rows: int
    rows_collapsed_by_policy: int
    distinct_readings: int
    included_readings: int
    excluded_readings: int
    by_reason: dict[str, int]
    #: True when the figures were counted from the relations rather than read from a
    #: recorded ``scenario_run`` row. Kept visible so a caller never presents a derived
    #: ladder as the one the builder wrote down.
    derived: bool = False

    @property
    def reconciles(self) -> bool:
        return (
            self.raw_rows - self.rows_collapsed_by_policy == self.distinct_readings
            and self.included_readings + self.excluded_readings
            == self.distinct_readings
            and sum(self.by_reason.values()) == self.excluded_readings
        )


def accounting(
    database: Path, run_id: str, *, relations: Relations = WAREHOUSE_RELATIONS
) -> Accounting:
    """WHOLE RUN. The unscoped ladder **recorded** when the Python scenario was built.

    Python route only, because the figures are read from the ``scenario_run`` row. The
    dbt route has :func:`counted_accounting`, which derives the same ladder by counting
    and says so.
    """
    run_table = require_run_table(relations, "accounting()")
    con = _con(database)
    try:
        run = con.execute(
            "SELECT raw_rows, rows_collapsed_by_policy, distinct_readings, "
            f"included_readings, excluded_readings FROM {run_table} WHERE run_id = ?",
            [run_id],
        ).fetchone()
        reasons = dict(
            con.execute(
                "SELECT exclusion_reason, COUNT(*) FROM "
                f"{relations.fact_exclusion} WHERE run_id = ? GROUP BY 1",
                [run_id],
            ).fetchall()
        )
    finally:
        con.close()
    return Accounting(
        raw_rows=int(run[0]),
        rows_collapsed_by_policy=int(run[1]),
        distinct_readings=int(run[2]),
        included_readings=int(run[3]),
        excluded_readings=int(run[4]),
        by_reason={
            r: int(reasons.get(r, 0)) for r in EXCLUSION_REASONS if r in reasons
        },
    )


def assumption_ids(
    database: Path, run_id: str, *, relations: Relations = WAREHOUSE_RELATIONS
) -> tuple[str, ...]:
    """The assumption identifier(s) stamped on this run's charged rows.

    Read from the fact rather than from a constant, so what is displayed is what the
    stored rows actually claim. Both routes carry ``assumption_id`` on every charged row.
    """
    con = _con(database)
    try:
        return tuple(
            r[0]
            for r in con.execute(
                f"SELECT DISTINCT assumption_id FROM {relations.fact_scenario} "
                "WHERE run_id = ? ORDER BY 1",
                [run_id],
            ).fetchall()
        )
    finally:
        con.close()


def total_charge_exact(
    database: Path, run_id: str, *, relations: Relations = WAREHOUSE_RELATIONS
) -> str:
    """The whole run's unrounded charge, summed in the database and carried as text.

    The Python route records this figure when it builds; a dbt build does not, so this
    counts it from the fact. Same rows, same arithmetic, no rounding.
    """
    con = _con(database)
    try:
        total = con.execute(
            f"SELECT COALESCE(SUM(energy_charge_gbp), 0) FROM {relations.fact_scenario} "
            "WHERE run_id = ?",
            [run_id],
        ).fetchone()[0]
    finally:
        con.close()
    return str(total)


def counted_accounting(
    database: Path, run_id: str, *, relations: Relations = WAREHOUSE_RELATIONS
) -> Accounting:
    """WHOLE RUN. The same ladder, **derived by counting** the relations themselves.

    For a dbt build there is no recorded ladder to read, so each figure is counted the
    way ``models._counts`` counts it: ``raw_rows`` from every loaded reading,
    ``included``/``excluded`` from the two facts, and ``rows_collapsed_by_policy`` as
    ``raw_rows - distinct_readings``. ``distinct_readings`` is ``included + excluded``,
    which is exactly what dbt's ``assert_charged_plus_excluded_equals_distinct`` test
    proves against the policy definition -- so this is a count, never an assumption, and
    ``reconciles`` still has to hold. ``derived`` is True so a caller can say which it is.
    """
    con = _con(database)
    try:
        raw_rows = con.execute(f"SELECT COUNT(*) FROM {relations.readings}").fetchone()[
            0
        ]
        included = con.execute(
            f"SELECT COUNT(*) FROM {relations.fact_scenario} WHERE run_id = ?",
            [run_id],
        ).fetchone()[0]
        excluded = con.execute(
            f"SELECT COUNT(*) FROM {relations.fact_exclusion} WHERE run_id = ?",
            [run_id],
        ).fetchone()[0]
        reasons = dict(
            con.execute(
                "SELECT exclusion_reason, COUNT(*) FROM "
                f"{relations.fact_exclusion} WHERE run_id = ? GROUP BY 1",
                [run_id],
            ).fetchall()
        )
    finally:
        con.close()
    distinct = int(included) + int(excluded)
    return Accounting(
        raw_rows=int(raw_rows),
        rows_collapsed_by_policy=int(raw_rows) - distinct,
        distinct_readings=distinct,
        included_readings=int(included),
        excluded_readings=int(excluded),
        by_reason={
            r: int(reasons.get(r, 0)) for r in EXCLUSION_REASONS if r in reasons
        },
        derived=True,
    )


def exclusion_breakdown(
    database: Path,
    run_id: str,
    household: str | None = None,
    start: date | None = None,
    end: date | None = None,
    *,
    relations: Relations = WAREHOUSE_RELATIONS,
) -> pd.DataFrame:
    """Why readings were not charged, **measured** for exactly this selection.

    Used instead of a guess about the likely reason: the caller can state the reason
    that actually applies to the household in front of the reader, with its count.
    """
    where, params = _fact_scope(run_id, household, start, end)
    con = _con(database)
    try:
        frame = con.execute(
            "SELECT exclusion_reason, COUNT(*) AS readings, "
            "MIN(source_date) AS first_date, MAX(source_date) AS last_date "
            f"FROM {relations.fact_exclusion} WHERE {where} "
            "GROUP BY 1 ORDER BY 2 DESC",
            params,
        ).df()
    finally:
        con.close()
    return frame


def exclusion_examples(
    database: Path,
    run_id: str,
    household: str | None = None,
    limit: int = 200,
    *,
    relations: Relations = WAREHOUSE_RELATIONS,
) -> pd.DataFrame:
    """A sample of excluded readings with their reason and every condition flag."""
    where, params = _fact_scope(run_id, household, None, None)
    con = _con(database)
    try:
        return con.execute(
            "SELECT exclusion_reason, household_id, tariff_group, "
            "source_timestamp_text, value_category, on_half_hour_grid, "
            "is_conflicted, is_off_grid, is_missing_value, is_outside_schedule_period, "
            f"is_unmatched_label FROM {relations.fact_exclusion} WHERE {where} "
            "ORDER BY exclusion_reason, household_id, observed_at_naive LIMIT ?",
            [*params, limit],
        ).df()
    finally:
        con.close()


# ----------------------------------------------------------- schedule-wide view
def schedule_band_distribution(
    database: Path, *, relations: Relations = WAREHOUSE_RELATIONS
) -> pd.DataFrame:
    """SCHEDULE-WIDE. Half-hour slots per band by source hour and month.

    Describes the published schedule only. Independent of which households are loaded,
    and therefore not a statement about anyone's consumption.
    """
    con = _con(database)
    try:
        return con.execute(
            "SELECT band_label, "
            "CAST(EXTRACT(hour FROM schedule_label_naive) AS SMALLINT)  AS source_hour, "
            "CAST(EXTRACT(month FROM schedule_label_naive) AS SMALLINT) AS source_month, "
            f"COUNT(*) AS slots FROM {relations.dim_schedule} "
            "GROUP BY 1, 2, 3 ORDER BY 1, 2, 3"
        ).df()
    finally:
        con.close()


def schedule_totals(
    database: Path, *, relations: Relations = WAREHOUSE_RELATIONS
) -> pd.DataFrame:
    """SCHEDULE-WIDE. Slots and hours per band, with the slot-count denominator."""
    con = _con(database)
    try:
        frame = con.execute(
            f"SELECT band_label, COUNT(*) AS slots FROM {relations.dim_schedule} "
            "GROUP BY 1"
        ).df()
    finally:
        con.close()
    total = int(frame["slots"].sum()) if len(frame) else 0
    frame["hours"] = frame["slots"] / 2
    frame["slot_share"] = [
        float(round_share(Decimal(int(s)) / Decimal(total))) if total else 0.0
        for s in frame["slots"]
    ]
    frame = _in_band_order(frame)
    frame.attrs["denominator_slots"] = total
    return frame


def _in_band_order(frame: pd.DataFrame) -> pd.DataFrame:
    """Cheapest band first, so a reader compares like with like."""
    if frame.empty:
        return frame
    rank = {band: i for i, band in enumerate(BAND_ORDER)}
    out = frame.copy()
    out["_rank"] = [rank.get(b, len(rank)) for b in out["band_label"]]
    return out.sort_values("_rank").drop(columns="_rank").reset_index(drop=True)


# --------------------------------------------- loaded sample / one household
BAND_SUMMARY_COLUMNS = [
    "band_label",
    "readings",
    "households",
    "kwh_exact",
    "kwh_display",
    "charge_gbp_exact",
    "charge_gbp_display",
    "price_pence_per_kwh",
    "consumption_share",
    "charge_share",
]


def band_summary(
    database: Path,
    run_id: str,
    household: str | None = None,
    start: date | None = None,
    end: date | None = None,
    *,
    relations: Relations = WAREHOUSE_RELATIONS,
) -> pd.DataFrame:
    """Recorded eligible kWh and scenario charge, by band, for one explicit scope.

    ``household`` of None covers every household charged in this run; a household id
    narrows it to that household. ``start``/``end`` bound the source date.

    **Both shares use the same rows.** ``consumption_share`` is a band's kWh over the
    total kWh of exactly the rows summarised here, and ``charge_share`` is its charge
    over the total charge of those same rows. Both denominators are returned in
    ``frame.attrs`` so a caller can state them rather than leave them to be guessed.
    An empty selection returns an empty frame with zero-valued attrs -- it does not
    manufacture zero-valued bands.
    """
    where, params = _fact_scope(run_id, household, start, end)
    con = _con(database)
    try:
        rows = con.execute(
            "SELECT band_label, COUNT(*) AS readings, "
            "COUNT(DISTINCT household_id) AS households, "
            "SUM(consumption_kwh) AS kwh, SUM(energy_charge_gbp) AS charge, "
            "MIN(price_pence_per_kwh) AS price_pence "
            f"FROM {relations.fact_scenario} WHERE {where} GROUP BY 1",
            params,
        ).fetchall()
    finally:
        con.close()
    if not rows:
        empty = pd.DataFrame(columns=BAND_SUMMARY_COLUMNS)
        empty.attrs["denominator_kwh_exact"] = "0"
        empty.attrs["denominator_charge_gbp_exact"] = "0"
        empty.attrs["denominator_readings"] = 0
        return empty
    total_kwh = sum((Decimal(str(r[3])) for r in rows), Decimal(0))
    total_charge = sum((Decimal(str(r[4])) for r in rows), Decimal(0))
    frame = pd.DataFrame(
        [
            {
                "band_label": r[0],
                "readings": int(r[1]),
                "households": int(r[2]),
                "kwh_exact": str(Decimal(str(r[3]))),
                "kwh_display": float(round_energy(Decimal(str(r[3])))),
                "charge_gbp_exact": str(Decimal(str(r[4]))),
                "charge_gbp_display": float(round_money(Decimal(str(r[4])))),
                "price_pence_per_kwh": float(r[5]),
                "consumption_share": float(round_share(Decimal(str(r[3])) / total_kwh))
                if total_kwh
                else 0.0,
                "charge_share": float(round_share(Decimal(str(r[4])) / total_charge))
                if total_charge
                else 0.0,
            }
            for r in rows
        ]
    )
    frame = _in_band_order(frame)
    frame.attrs["denominator_kwh_exact"] = str(total_kwh)
    frame.attrs["denominator_charge_gbp_exact"] = str(total_charge)
    frame.attrs["denominator_readings"] = int(sum(int(r[1]) for r in rows))
    return frame


def household_band_distribution(
    database: Path,
    run_id: str,
    household: str | None = None,
    start: date | None = None,
    end: date | None = None,
    *,
    relations: Relations = WAREHOUSE_RELATIONS,
) -> pd.DataFrame:
    """LOADED SAMPLE. Charged readings and kWh per band, by source hour."""
    where, params = _fact_scope(run_id, household, start, end)
    con = _con(database)
    try:
        frame = con.execute(
            "SELECT band_label, source_hour, COUNT(*) AS readings, "
            f"SUM(consumption_kwh) AS kwh FROM {relations.fact_scenario} "
            f"WHERE {where} GROUP BY 1, 2 ORDER BY 2, 1",
            params,
        ).df()
    finally:
        con.close()
    if not frame.empty:
        frame["kwh_display"] = [
            float(round_energy(Decimal(str(v)))) for v in frame["kwh"]
        ]
    return frame


def monthly_charge(
    database: Path,
    run_id: str,
    household: str | None = None,
    start: date | None = None,
    end: date | None = None,
    *,
    relations: Relations = WAREHOUSE_RELATIONS,
) -> pd.DataFrame:
    """LOADED SAMPLE. Charged kWh and scenario charge by source month and band."""
    where, params = _fact_scope(run_id, household, start, end)
    con = _con(database)
    try:
        frame = con.execute(
            "SELECT source_month, band_label, COUNT(*) AS readings, "
            "SUM(consumption_kwh) AS kwh, SUM(energy_charge_gbp) AS charge "
            f"FROM {relations.fact_scenario} WHERE {where} "
            "GROUP BY 1, 2 ORDER BY 1, 2",
            params,
        ).df()
    finally:
        con.close()
    if not frame.empty:
        frame["kwh_display"] = [
            float(round_energy(Decimal(str(v)))) for v in frame["kwh"]
        ]
        frame["charge_gbp_display"] = [
            float(round_money(Decimal(str(v)))) for v in frame["charge"]
        ]
        frame["charge_gbp_exact"] = [str(Decimal(str(v))) for v in frame["charge"]]
    return frame


def household_totals(
    database: Path,
    run_id: str,
    start: date | None = None,
    end: date | None = None,
    *,
    relations: Relations = WAREHOUSE_RELATIONS,
) -> pd.DataFrame:
    """LOADED SAMPLE. One row per household charged in this run and period."""
    where, params = _fact_scope(run_id, None, start, end)
    con = _con(database)
    try:
        rows = con.execute(
            "SELECT household_id, COUNT(*) AS readings, MIN(source_date) AS first_date, "
            "MAX(source_date) AS last_date, SUM(consumption_kwh) AS kwh, "
            f"SUM(energy_charge_gbp) AS charge FROM {relations.fact_scenario} "
            f"WHERE {where} GROUP BY 1 ORDER BY 1",
            params,
        ).fetchall()
    finally:
        con.close()
    return pd.DataFrame(
        [
            {
                "household_id": r[0],
                "charged_readings": int(r[1]),
                "first_charged_date": r[2],
                "last_charged_date": r[3],
                "kwh_exact": str(Decimal(str(r[4]))),
                "kwh_display": float(round_energy(Decimal(str(r[4])))),
                "charge_gbp_exact": str(Decimal(str(r[5]))),
                "charge_gbp_display": float(round_money(Decimal(str(r[5])))),
            }
            for r in rows
        ]
    )


def charged_households(
    database: Path,
    run_id: str,
    start: date | None = None,
    end: date | None = None,
    *,
    relations: Relations = WAREHOUSE_RELATIONS,
) -> list[str]:
    """Households with at least one charged reading in this scope, for an explicit pick."""
    where, params = _fact_scope(run_id, None, start, end)
    con = _con(database)
    try:
        return [
            r[0]
            for r in con.execute(
                f"SELECT DISTINCT household_id FROM {relations.fact_scenario} "
                f"WHERE {where} ORDER BY 1",
                params,
            ).fetchall()
        ]
    finally:
        con.close()


def tariff_group_stability(
    database: Path, *, relations: Relations = WAREHOUSE_RELATIONS
) -> pd.DataFrame:
    """Measured, not assumed: households recorded under more than one tariff group.

    AQ-22/AQ-23 ask whether ``stdorToU`` is fixed per household or varies over time.
    This measures it in the loaded data rather than assuming either answer.
    """
    con = _con(database)
    try:
        return con.execute(
            "SELECT household_id, COUNT(DISTINCT tariff_group) AS groups, "
            f"STRING_AGG(DISTINCT tariff_group, '|') AS values FROM {relations.readings} "
            "GROUP BY 1 HAVING COUNT(DISTINCT tariff_group) > 1 ORDER BY 1"
        ).df()
    finally:
        con.close()


def household_tariff_groups(
    database: Path, household: str, *, relations: Relations = WAREHOUSE_RELATIONS
) -> list[str]:
    """The tariff group(s) this household is actually recorded under."""
    con = _con(database)
    try:
        return [
            r[0]
            for r in con.execute(
                f"SELECT DISTINCT tariff_group FROM {relations.readings} "
                "WHERE household_id = ? ORDER BY 1",
                [household],
            ).fetchall()
        ]
    finally:
        con.close()


def price_catalogue(
    database: Path, *, relations: Relations = WAREHOUSE_RELATIONS
) -> pd.DataFrame:
    con = _con(database)
    try:
        return con.execute(
            "SELECT tariff_group, band_label, price_pence_per_kwh, price_gbp_per_kwh, "
            "currency, CAST(effective_from AS VARCHAR) AS effective_from, "
            "CAST(effective_until AS VARCHAR) AS effective_until, "
            "evidence_label, catalogue_version "
            f"FROM {relations.dim_price} ORDER BY tariff_group, band_label"
        ).df()
    finally:
        con.close()


# ------------------------------------------------------------------- insights
@dataclass(frozen=True, slots=True)
class Insight:
    """One deterministic sentence about the current selection, with its figures.

    Every number in ``headline`` carries its unit and its denominator, and the
    ``supporting`` figures are the exact values it was written from. Nothing here is a
    cause, a bill or a saving: the sentences describe where the charged readings and the
    scenario charge sit, and stop there.
    """

    headline: str
    supporting: dict[str, str]


def selection_insights(
    database: Path,
    run_id: str,
    household: str | None = None,
    start: date | None = None,
    end: date | None = None,
    *,
    relations: Relations = WAREHOUSE_RELATIONS,
) -> list[Insight]:
    """Up to three insights for exactly this selection. Empty selection -> no insights.

    Coverage is **observed label coverage**: charged readings against the schedule's
    half-hour labels in the period. The denominator is valid for one household and for
    the sample because a charged row is one distinct, undisputed reading per household
    per label, so no household can exceed it. It is never proof that every physical
    interval was metered: a label present in the data says a row was recorded, not that
    the meter covered the whole half hour, and the timestamp convention is unresolved.
    """
    bands = band_summary(database, run_id, household, start, end, relations=relations)
    if bands.empty:
        return []
    readings = int(bands.attrs["denominator_readings"])
    kwh = Decimal(bands.attrs["denominator_kwh_exact"])
    charge = Decimal(bands.attrs["denominator_charge_gbp_exact"])
    where, params = _period(
        "1 = 1", [], start, end, "CAST(schedule_label_naive AS DATE)"
    )
    con = _con(database)
    try:
        slots = int(
            con.execute(
                f"SELECT COUNT(*) FROM {relations.dim_schedule} WHERE {where}", params
            ).fetchone()[0]
        )
    finally:
        con.close()
    out: list[Insight] = []

    # 1. coverage of the schedule's labels
    if household is not None:
        out.append(
            Insight(
                f"{household} is charged for {readings:,} of the {slots:,} half-hour "
                "labels the schedule carries in this period — observed label coverage, "
                "not proof that every physical interval was metered"
                + (
                    ". Limited observed coverage in the loaded members; why readings "
                    "are absent is not established."
                    if readings < slots
                    else "."
                ),
                {
                    "charged readings": f"{readings:,}",
                    "schedule labels in period": f"{slots:,}",
                },
            )
        )
    else:
        totals = household_totals(database, run_id, start, end, relations=relations)
        lo, hi = (
            totals.iloc[totals["charged_readings"].idxmin()],
            totals.iloc[totals["charged_readings"].idxmax()],
        )
        out.append(
            Insight(
                f"{len(totals):,} households are charged; charged readings per household "
                f"run from {int(lo['charged_readings']):,} ({lo['household_id']}) to "
                f"{int(hi['charged_readings']):,} ({hi['household_id']}) of the {slots:,} "
                "half-hour labels the schedule carries in this period — observed label "
                "coverage per household, not proof of complete physical coverage.",
                {
                    "households": f"{len(totals):,}",
                    "fewest charged readings": f"{int(lo['charged_readings']):,} ({lo['household_id']})",
                    "most charged readings": f"{int(hi['charged_readings']):,} ({hi['household_id']})",
                    "schedule labels in period": f"{slots:,}",
                },
            )
        )

    # 2. the band whose charge share most exceeds its consumption share
    gap = bands.assign(gap=bands["charge_share"] - bands["consumption_share"])
    top = gap.iloc[gap["gap"].idxmax()]
    out.append(
        Insight(
            f"The {top['band_label']} band carries {top['consumption_share']:.1%} of the "
            f"charged kWh and {top['charge_share']:.1%} of the scenario charge, out of "
            f"{round_energy(kwh):,} kWh and £{round_money(charge):,} across {readings:,} "
            "charged readings. The difference follows from its price "
            f"({top['price_pence_per_kwh']:.2f} p/kWh); it does not show anyone "
            "responding to it.",
            {
                "band": str(top["band_label"]),
                "charged kWh in band (exact)": str(top["kwh_exact"]),
                "charge in band (exact)": f"£{top['charge_gbp_exact']}",
                "all charged kWh (exact)": str(kwh),
                "all scenario charge (exact)": f"£{charge}",
            },
        )
    )

    # 3. the hour holding the most charged kWh
    hours = household_band_distribution(
        database, run_id, household, start, end, relations=relations
    )
    if not hours.empty:
        by_hour = hours.groupby("source_hour")["kwh"].sum()
        peak = int(by_hour.idxmax())
        peak_kwh = Decimal(str(by_hour.max()))
        out.append(
            Insight(
                f"Hour {peak:02d} of the source timestamp holds the most charged kWh: "
                f"{round_energy(peak_kwh):,} of {round_energy(kwh):,} kWh "
                f"({round_share(peak_kwh / kwh):.1%}). The hour is read from the label as "
                "recorded; no timezone is applied.",
                {
                    "peak hour": f"{peak:02d}",
                    "kWh in peak hour (exact)": str(peak_kwh),
                    "all charged kWh (exact)": str(kwh),
                },
            )
        )
    return out
