"""Does a recorded forecast report describe the dataset in front of the reader?

The question this answers
-------------------------

A report is a file under ``data/forecasts/``; the dataset is whichever DuckDB file the
reader selected. Until 2026-09-08 the dashboard decided the two matched by comparing
**file names** (``Path(report["database"]).name == database.name``). That accepted a
different warehouse that happened to reuse the name and refused an identical warehouse at
another path -- a published version, a candidate, a renamed copy. Names are not identity.

Identity here is **content**, under the digest definition the report itself was written
with, plus a separate recomputation of every displayed figure that digest does not cover.
Nothing is assumed from the name; the name is kept only as provenance.

What each report depends on -- the mapping this module implements
-----------------------------------------------------------------

**FORE-001** (``fore-001-*.json``). ``identity.dataset_sha256`` is
:data:`dataset.FORE_001_DIGEST`: the selected cohort -- each household's id, run bounds,
usable-day count and every usable daily total inside its run, in id and date order.

- *Prediction targets and scores* (every MAE, horizon curve, per-household figure,
  origin example): fully determined by the digest. The models read nothing else.
- *Eligibility and cohort selection* (``selection.eligible_households``, the "40 of 71"
  denominator): **not** covered -- it counts households outside the cohort. Recomputed.
- *Usable / unusable / absent-day counts* (``feasibility.*``): **not** covered --
  warehouse-wide, over every household. Recomputed from the same daily records.
- *Tariff-group and source-member descriptions* (``selection.cohort_tariff_groups``,
  ``cohort_members``, per-household ``tariff_group`` / ``members``): **not** covered --
  read from ``readings`` columns the digest never sees. Recomputed with the generator's own
  query.
- *Provenance* (``database``, ``generated_at_utc``, ``identity.forecast_code_sha256``,
  ``config_sha256``, ``ingestion_pipeline_fingerprint``, ``runtime``): recorded facts about
  the run that produced the report. Not properties of the selected dataset, so never
  "verified" against it; shown as recorded.

**I-08** (``i-08-*.json``). ``identity.dataset_sha256`` is :data:`dataset.I08_DIGEST`:
every household's every usable daily total.

- *Predictions, declines, scores, coverage, the shared/new overlap*: every decision reads
  the usable map and the shared origin calendar only, so given the digest **and** the
  calendar **and** the household set, they are determined.
- *Households considered* (``universe.households``): **not** covered -- a household with
  no usable day is counted but contributes nothing to the digest. Recomputed.
- *Origin calendar* (``universe.origin_calendar``): **not** covered -- derived from the
  warehouse's full date span, unusable days included. Recomputed with the generator's
  own function.
- *Scheduled and qualifying counts*: recomputed from the calendar and the usable map.
- *Absent versus not-usable targets* (``target_availability``): **not** covered -- the
  split depends on unusable rows existing at all. Recomputed with the generator's own
  classifier. Not displayed by the dashboard, but in the report.
- *Provenance*: as above.

Outcomes
--------

- ``applicable`` -- the core digest **and** every displayed context figure recompute
  identically from the selected dataset. The report describes it.
- ``mismatched`` -- something differs. The reason says what: a differing core digest means
  the predictions and scores are about other data; a differing context figure alone means
  the scores would be unchanged but the page's denominators and descriptions would be
  wrong for this dataset, and it is withheld rather than shown with a footnote.
- ``unverifiable`` -- the report lacks the identity or configuration needed to recompute,
  or names a digest definition this code does not know. Never treated as a match.

Cost, measured on the three-member warehouse (3.0 M readings, 83 households): one
``daily_records`` scan 0.53 s, the FORE-001 cohort composition query 0.56 s, the digests
and counts themselves under 0.1 s. Both reports are assessed from **one** scan
(:class:`DatasetFacts`), once per operation. There is no cache across operations: the
selected file is a mutable ingestion warehouse and a name or a modification time is not a
content identity. A sealed published version would justify one keyed by its seal; that
waits for the dashboard switch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Final

from . import dataset as ds
from . import prior_eligibility as pe

APPLICABLE: Final[str] = "applicable"
MISMATCHED: Final[str] = "mismatched"
UNVERIFIABLE: Final[str] = "unverifiable"

FORE_001: Final[str] = "fore-001"
I08: Final[str] = "i-08"

#: Which digest definition a report of each kind is read under when it names none. See
#: the compatibility rule beside :data:`dataset.FORE_001_DIGEST`.
_DEFAULT_DEFINITION: Final[dict[str, str]] = {
    FORE_001: ds.FORE_001_DIGEST,
    I08: ds.I08_DIGEST,
}

#: ``feasibility`` fields the dashboard displays for FORE-001. Warehouse-wide, so outside
#: the cohort digest; each is recomputed from the same daily records.
_FEASIBILITY_FIELDS: Final[tuple[str, ...]] = (
    "households",
    "household_days",
    "usable_household_days",
    "eligible_households",
    "min_run_days",
    "expected_intervals",
)


class ReportKindError(ValueError):
    """The file is not a report this module knows how to assess."""


@dataclass(frozen=True, slots=True)
class Check:
    """One recorded claim against its recomputation from the selected dataset."""

    field: str
    supports: str
    recorded: str | None
    current: str
    core: bool = False

    @property
    def matches(self) -> bool:
        return self.recorded is not None and self.recorded == self.current

    @property
    def recorded_missing(self) -> bool:
        return self.recorded is None


@dataclass(frozen=True, slots=True)
class Applicability:
    """The verdict, and every check it rests on."""

    outcome: str
    kind: str
    reason: str
    recorded_database: str
    selected_database: str
    definition: str | None
    checks: tuple[Check, ...] = ()

    @property
    def applicable(self) -> bool:
        return self.outcome == APPLICABLE

    @property
    def core_matches(self) -> bool:
        """Whether the predictions and scores are about this dataset's data."""
        return any(c.core and c.matches for c in self.checks)

    @property
    def differing(self) -> tuple[Check, ...]:
        return tuple(c for c in self.checks if not c.matches)

    @property
    def renamed(self) -> bool:
        """The dataset is the recorded one under another name -- provenance, not a fault."""
        return Path(self.recorded_database).name != Path(self.selected_database).name


@dataclass(frozen=True, slots=True)
class DatasetFacts:
    """One scan of the selected dataset, shared by every report assessed against it.

    ``target`` may be a path or any object with a ``database`` attribute -- a tariff
    ``ReadContext`` in particular. A context is used, never re-resolved: this module
    knows nothing about publication manifests and must not.
    """

    database: Path
    records: dict[str, list[ds.DayRecord]] = field(repr=False)

    @classmethod
    def from_target(cls, target: Any) -> DatasetFacts:
        database = Path(getattr(target, "database", target))
        return cls(database=database, records=ds.daily_records(database))


def kind_of(report: dict[str, Any]) -> str:
    if report.get("experiment") == "I-08 prior-data eligibility":
        return I08
    if "selection" in report and "households" in report and "evaluation" in report:
        return FORE_001
    raise ReportKindError(
        "not a FORE-001 or I-08 report: no 'experiment' marker and no "
        "selection/households/evaluation sections"
    )


def _unverifiable(
    kind: str, report: dict[str, Any], facts: DatasetFacts, reason: str
) -> Applicability:
    return Applicability(
        UNVERIFIABLE,
        kind,
        reason,
        str(report.get("database", "")),
        str(facts.database),
        report.get("identity", {}).get("dataset_digest_definition"),
    )


def _definition(kind: str, report: dict[str, Any]) -> str | None:
    """The digest definition to evaluate under, or None when it cannot be known."""
    named = report.get("identity", {}).get("dataset_digest_definition")
    expected = _DEFAULT_DEFINITION[kind]
    if named is None:
        return expected  # compatibility rule, documented in dataset.py
    return expected if named == expected else None


def _verdict(
    kind: str,
    report: dict[str, Any],
    facts: DatasetFacts,
    definition: str,
    checks: list[Check],
) -> Applicability:
    core = [c for c in checks if c.core]
    missing = [c for c in checks if c.recorded_missing]
    differing = [c for c in checks if not c.matches and not c.recorded_missing]
    if missing:
        outcome, reason = (
            UNVERIFIABLE,
            "the report does not record "
            + ", ".join(f"`{c.field}`" for c in missing)
            + ", so that claim cannot be checked against this dataset",
        )
    elif any(not c.matches for c in core):
        outcome, reason = (
            MISMATCHED,
            (
                f"the {core[0].supports} differ: the predictions and scores in this "
                "report were computed from other data"
            ),
        )
    elif differing:
        names = ", ".join(f"`{c.field}`" for c in differing[:6]) + (
            " …" if len(differing) > 6 else ""
        )
        outcome, reason = (
            MISMATCHED,
            (
                "the predictions and scores would be unchanged, but these displayed "
                f"figures describe the recorded dataset, not this one: {names}"
            ),
        )
    else:
        outcome, reason = (
            APPLICABLE,
            f"{len(checks)} checks recompute identically under {definition}",
        )
    return Applicability(
        outcome,
        kind,
        reason,
        str(report.get("database", "")),
        str(facts.database),
        definition,
        tuple(checks),
    )


# ------------------------------------------------------------------ FORE-001
def _assess_fore_001(report: dict[str, Any], facts: DatasetFacts) -> Applicability:
    from .evaluate import _cohort_composition

    identity = report.get("identity", {})
    config = report.get("config", {})
    if "dataset_sha256" not in identity:
        return _unverifiable(FORE_001, report, facts, "no identity.dataset_sha256")
    if "min_run_days" not in config or "household_limit" not in config:
        return _unverifiable(
            FORE_001, report, facts, "config lacks min_run_days / household_limit"
        )
    definition = _definition(FORE_001, report)
    if definition is None:
        return _unverifiable(
            FORE_001,
            report,
            facts,
            f"digest definition {identity.get('dataset_digest_definition')!r} is not "
            f"one this code computes ({ds.FORE_001_DIGEST})",
        )

    records = facts.records
    cohort = ds.series_from_records(
        records, config["min_run_days"], config["household_limit"]
    )
    eligible = ds.series_from_records(records, config["min_run_days"])
    feasibility = ds.feasibility_from_records(records)
    recorded_feasibility = report.get("feasibility", {})
    selection = report.get("selection", {})

    checks = [
        Check(
            "identity.dataset_sha256",
            "cohort series (households, run bounds, usable daily totals)",
            identity["dataset_sha256"],
            ds.cohort_series_digest(cohort),
            core=True,
        )
    ]
    for name in _FEASIBILITY_FIELDS:
        checks.append(
            Check(
                f"feasibility.{name}",
                "warehouse-wide data-quality count",
                _text(recorded_feasibility.get(name)),
                _text(feasibility[name]),
            )
        )
    checks.append(
        Check(
            "selection.eligible_households",
            "eligibility denominator",
            _text(selection.get("eligible_households")),
            _text(len(eligible)),
        )
    )
    checks.append(
        Check(
            "selection.selected_households",
            "cohort size",
            _text(selection.get("selected_households")),
            _text(len(cohort)),
        )
    )
    composition = _cohort_composition(
        facts.database, [one.household_id for one in cohort]
    )
    last = composition.pop("_warehouse_last_date")
    checks.append(
        Check(
            "selection.warehouse_last_date",
            "warehouse span",
            _text(selection.get("warehouse_last_date")),
            _text(last),
        )
    )
    checks.append(
        Check(
            "selection.runs_ending_at_warehouse_end",
            "runs reaching the warehouse end",
            _text(selection.get("runs_ending_at_warehouse_end")),
            _text(
                sum(1 for s in cohort if s.run_end >= last - timedelta(days=1))
                if last is not None
                else None
            ),
        )
    )
    checks.append(
        Check(
            "selection.cohort_tariff_groups",
            "cohort tariff-group mix",
            _text(selection.get("cohort_tariff_groups")),
            _text(composition["tariff_groups"]),
        )
    )
    checks.append(
        Check(
            "selection.cohort_members",
            "cohort source-member mix",
            _text(selection.get("cohort_members")),
            _text(composition["members"]),
        )
    )
    recorded_households = report.get("households")
    current_households = [
        {
            "household_id": one.household_id,
            "tariff_group": composition["per_household"]
            .get(one.household_id, {})
            .get("tariff_group"),
            "members": composition["per_household"]
            .get(one.household_id, {})
            .get("members"),
        }
        for one in cohort
    ]
    checks.append(
        Check(
            "households[].tariff_group/members",
            "per-household group and member labels",
            _text(
                [
                    {k: h.get(k) for k in ("household_id", "tariff_group", "members")}
                    for h in recorded_households
                ]
            )
            if recorded_households is not None
            else None,
            _text(current_households),
        )
    )
    return _verdict(FORE_001, report, facts, definition, checks)


# ------------------------------------------------------------------ I-08
def _assess_i08(report: dict[str, Any], facts: DatasetFacts) -> Applicability:
    identity = report.get("identity", {})
    config = report.get("config", {})
    if "dataset_sha256" not in identity:
        return _unverifiable(I08, report, facts, "no identity.dataset_sha256")
    try:
        prior_config = pe.PriorConfig(**config)
    except TypeError as error:
        return _unverifiable(
            I08, report, facts, f"config is not a PriorConfig: {error}"
        )
    definition = _definition(I08, report)
    if definition is None:
        return _unverifiable(
            I08,
            report,
            facts,
            f"digest definition {identity.get('dataset_digest_definition')!r} is not "
            f"one this code computes ({ds.I08_DIGEST})",
        )

    records = facts.records
    origins = pe.origin_calendar(records, prior_config)
    usable = {h: pe._usable_map(rows) for h, rows in records.items()}
    recorded_dates = {h: {r.source_date for r in rows} for h, rows in records.items()}
    qualifying = sum(
        1
        for household in records
        for origin in origins
        if pe.qualifies_at(usable[household], origin, prior_config)
    )
    unavailable: dict[str, int] = {}
    for household in records:
        for origin in origins:
            for horizon in range(1, prior_config.horizon + 1):
                state, reason, _ = pe.classify_target(
                    origin + timedelta(days=horizon),
                    usable[household],
                    recorded_dates[household],
                )
                if state == pe.UNAVAILABLE and reason:
                    unavailable[reason] = unavailable.get(reason, 0) + 1

    universe = report.get("universe", {})
    calendar = universe.get("origin_calendar", {})
    availability = report.get("target_availability", {})
    scheduled_origins = len(records) * len(origins)
    checks = [
        Check(
            "identity.dataset_sha256",
            "usable daily totals of every household",
            identity["dataset_sha256"],
            ds.usable_days_digest(records),
            core=True,
        ),
        Check(
            "universe.households",
            "households considered",
            _text(universe.get("households")),
            _text(len(records)),
        ),
        Check(
            "universe.origin_calendar",
            "shared origin calendar",
            _text(
                {k: calendar.get(k) for k in ("origins", "first", "last", "step_days")}
            )
            if calendar
            else None,
            _text(
                {
                    "origins": len(origins),
                    "first": str(origins[0]) if origins else None,
                    "last": str(origins[-1]) if origins else None,
                    "step_days": prior_config.origin_step_days,
                }
            ),
        ),
        Check(
            "universe.household_origins_scheduled",
            "scheduled household-origins",
            _text(universe.get("household_origins_scheduled")),
            _text(scheduled_origins),
        ),
        Check(
            "universe.scheduled_cases_per_model",
            "scheduled cases per model",
            _text(universe.get("scheduled_cases_per_model")),
            _text(scheduled_origins * prior_config.horizon),
        ),
        Check(
            "universe.household_origins_qualifying",
            "qualifying household-origins",
            _text(universe.get("household_origins_qualifying")),
            _text(qualifying),
        ),
        Check(
            "target_availability.unavailable_by_reason",
            "absent versus not-usable targets",
            _text(availability.get("unavailable_by_reason")) if availability else None,
            _text(unavailable),
        ),
    ]
    return _verdict(I08, report, facts, definition, checks)


def _text(value: Any) -> str | None:
    """A canonical string for comparison; None stays None so 'not recorded' is visible."""
    if value is None:
        return None
    if isinstance(value, dict):
        return (
            "{" + ", ".join(f"{k}: {_text(v)}" for k, v in sorted(value.items())) + "}"
        )
    if isinstance(value, list):
        return "[" + ", ".join(str(_text(v)) for v in value) + "]"
    return str(value)


# ------------------------------------------------------------------ entry points
def assess(
    report: dict[str, Any], target: Any, facts: DatasetFacts | None = None
) -> Applicability:
    """Assess one report against a dataset (a path, or an object with ``.database``).

    Pass ``facts`` to reuse one scan across several reports; otherwise one is made here.
    """
    facts = facts or DatasetFacts.from_target(target)
    try:
        kind = kind_of(report)
    except ReportKindError as error:
        return Applicability(
            UNVERIFIABLE,
            "unknown",
            str(error),
            str(report.get("database", "")),
            str(facts.database),
            None,
        )
    if kind == I08:
        return _assess_i08(report, facts)
    return _assess_fore_001(report, facts)


def assess_reports(
    reports: dict[str, dict[str, Any] | None], target: Any
) -> dict[str, Applicability | None]:
    """Assess several reports against one dataset from **one** scan.

    ``reports`` maps a caller's label to a report or None. Nothing is scanned when every
    value is None.
    """
    if not any(r is not None for r in reports.values()):
        return dict.fromkeys(reports)
    facts = DatasetFacts.from_target(target)
    return {
        label: (assess(report, target, facts) if report is not None else None)
        for label, report in reports.items()
    }
