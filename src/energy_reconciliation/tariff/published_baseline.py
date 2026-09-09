"""Baseline format 2: record a **published dbt result**, and genuinely rebuild it.

What this adds to format 1
--------------------------

Format 1 (:mod:`tariff.baseline`) records what ``build-tariff-scenario`` computed in
Python and replays it by calling that same builder. It is untouched here, and every
format-1 file keeps its meaning.

Format 2 records what a **sealed, promoted dbt build** computed, taken from the validated
:class:`tariff.reads.ReadContext` and the attempt the seal attests -- never from the
``main.scenario_run`` row or the ``main`` tariff tables that a whole-warehouse snapshot
also carries. Those describe the Python scenario of the warehouse the candidate was built
from: a different run, by a different builder, and recording them here would be recording
the wrong thing under the right name.

Replay re-ingests the recorded members from the archive, then runs the **supported
candidate-building path** (``build-candidate``) end to end -- a real dbt build with every
model and every test -- into a destination that must not already exist. Nothing is copied
from the publication. A comparison is only ever reported after that build has run.

The comparison contract
-----------------------

Three groups, kept apart because they answer different questions.

**Reproduction inputs — must match.** The archive and each member's decompressed content
digest; the schedule variant, source name, file digest and row count; the price catalogue
version; the tariff group; the resolved dbt variables. A material input that cannot be
verified is a **refusal**, never a substitution of whatever the current defaults happen to
be.

**Calculation and runtime — must match.** The policy digest, the candidate calculation
digest (which covers ``tariff/dimensions.py`` and the dbt project as well as the Python
calculation files), the dbt project and macro digests, and the versions of Python, DuckDB,
PyArrow, pandas, openpyxl, dbt-core and dbt-duckdb.

**Logical outputs — must match.** For all four built relations: the ordered column names
and types, the row count, and a digest over **every row occurrence** so duplicate
multiplicity cannot cancel. Plus the accounting ladder, the exact unrounded charge and
kWh totals, and the per-band, per-household and per-exclusion-reason results, every
decimal carried as text so nothing is rounded on the way in or out.

**Execution provenance — expected to differ, and recorded for explanation only.** The dbt
run id, the attempt's start and finish times, dbt's invocation id, the destination paths,
the publication version, the whole-file SHA-256 and the seal. A fresh rebuild is a new
attempt in a new file; requiring those to match would make reproduction impossible by
definition. They are recorded so a reader can see *which* run produced the record.

Two columns are excluded from row comparison, and only these two:

- ``run_id`` on both facts -- it **is** the execution identity, new per attempt by
  construction, and every other column of the row is compared.
- ``loaded_at_utc`` on ``dim_tariff_band_schedule`` -- the wall-clock instant the
  dimension was materialised. The schedule's own identity is compared through
  ``schedule_source``, ``source_sha256`` and every band row.

Nothing else is excluded. In particular ``assumption_id``, every price column and every
band label are compared.

What must still exist to reproduce a result
--------------------------------------------

A format-2 baseline is **not** self-contained, and says so rather than pretending. To
replay one you need, on disk: the source archive naming each recorded member with matching
content digests, and -- for the workbook schedule -- ``data/raw/Tariffs.xlsx`` with the
recorded digest. You do **not** need the publication root, the version file, the candidate
or any demonstration directory: none of them is read by replay. Delete them and the
baseline still reproduces.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from ..ingest.loader import load_member, member_content_digest
from ..ingest.warehouse import connect
from ..profiling.reader import DEFAULT_ARCHIVE, member_identity
from . import analytics as ta
from . import reads
from .baseline import BASELINE_DIR, BaselineError, Difference, _rows
from .schedule import DEFAULT_WORKBOOK, file_sha256

#: This file's own format. Deliberately distinct from ``output_digest_version`` (how the
#: build's integrity digest is computed) and from the seal, which are recorded separately
#: inside it: three versioned things that change for different reasons.
FORMAT_VERSION: Final[str] = "2"

#: How the row-level comparison digests below are computed. Distinct from
#: ``dbt_run.OUTPUT_DIGEST_VERSION``: that one covers **integrity** and deliberately
#: includes ``run_id``, so it can never match across two builds; this one covers
#: **equivalence** and excludes execution provenance.
COMPARISON_DIGEST_VERSION: Final[str] = "compare-rows-1"

#: Prefix on every format-2 file, so a directory holding both formats is unambiguous and
#: neither reader can be handed the other's file by a glob.
FILE_PREFIX: Final[str] = "pub2-"

#: Execution provenance excluded from row comparison, with its justification in the module
#: docstring. Anything not named here is compared.
_EXECUTION_COLUMNS: Final[dict[str, tuple[str, ...]]] = {
    "fact_interval_charge_scenario": ("run_id",),
    "fact_interval_charge_exclusion": ("run_id",),
    "dim_tariff_band_schedule": ("loaded_at_utc",),
    "dim_tariff_price": (),
}


def _relation_names(relations: ta.Relations) -> dict[str, str]:
    """Comparison key → the qualified relation to read it from."""
    return {
        "fact_interval_charge_scenario": relations.fact_scenario,
        "fact_interval_charge_exclusion": relations.fact_exclusion,
        "dim_tariff_band_schedule": relations.dim_schedule,
        "dim_tariff_price": relations.dim_price,
    }


def _columns(con, qualified: str) -> list[tuple[str, str]]:
    schema, table = qualified.split(".", 1)
    return [
        (name, kind)
        for name, kind in con.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position",
            [schema, table],
        ).fetchall()
    ]


def relation_evidence(con, key: str, qualified: str) -> dict[str, Any]:
    """Schema, row count and an order-independent digest over every row occurrence.

    Rendered in Python from a streamed cursor so the ordering and the text of every value
    are ours: a ``DECIMAL(9,4)`` keeps its scale, and ``NULL`` is distinguishable from the
    empty string. Sorting the rows rather than combining them means two rows can never
    cancel, so duplicate multiplicity is part of what is compared.
    """
    columns = _columns(con, qualified)
    excluded = set(_EXECUTION_COLUMNS.get(key, ()))
    compared = [name for name, _ in columns if name not in excluded]
    quoted = ", ".join(f'CAST("{name}" AS VARCHAR)' for name in compared)
    order = ", ".join(str(i + 1) for i in range(len(compared)))
    digest = hashlib.sha256()
    digest.update(f"{COMPARISON_DIGEST_VERSION}|{key}|{','.join(compared)}\n".encode())
    rows = 0
    cursor = con.execute(f"SELECT {quoted} FROM {qualified} ORDER BY {order}")
    while chunk := cursor.fetchmany(50_000):
        for row in chunk:
            rows += 1
            digest.update(
                "|".join("\x00" if v is None else v for v in row).encode() + b"\n"
            )
    return {
        "schema": [[name, kind] for name, kind in columns],
        "compared_columns": compared,
        "excluded_columns": sorted(excluded),
        "rows": rows,
        "row_digest": digest.hexdigest(),
    }


def outputs_of(context: reads.ReadContext) -> dict[str, Any]:
    """Every logical output this contract compares, from one validated context."""
    relations = context.relations
    con = connect(context.database, read_only=True)
    try:
        evidence = {
            key: relation_evidence(con, key, qualified)
            for key, qualified in _relation_names(relations).items()
        }
        totals = con.execute(
            "SELECT CAST(COALESCE(SUM(consumption_kwh), 0) AS VARCHAR), "
            "CAST(COALESCE(SUM(energy_charge_gbp), 0) AS VARCHAR) "
            f"FROM {relations.fact_scenario} WHERE run_id = ?",
            [context.run_id],
        ).fetchone()
        per_band = _rows(
            con,
            "SELECT band_label, COUNT(*) AS readings, "
            "CAST(SUM(consumption_kwh) AS VARCHAR) AS kwh_exact, "
            "CAST(SUM(energy_charge_gbp) AS VARCHAR) AS charge_exact, "
            "CAST(MIN(price_pence_per_kwh) AS VARCHAR) AS price_pence "
            f"FROM {relations.fact_scenario} WHERE run_id = ? GROUP BY 1 ORDER BY 1",
            [context.run_id],
        )
        per_household = _rows(
            con,
            "SELECT household_id, COUNT(*) AS readings, "
            "CAST(MIN(source_date) AS VARCHAR) AS first_date, "
            "CAST(MAX(source_date) AS VARCHAR) AS last_date, "
            "CAST(SUM(consumption_kwh) AS VARCHAR) AS kwh_exact, "
            "CAST(SUM(energy_charge_gbp) AS VARCHAR) AS charge_exact "
            f"FROM {relations.fact_scenario} WHERE run_id = ? GROUP BY 1 ORDER BY 1",
            [context.run_id],
        )
        per_reason = _rows(
            con,
            "SELECT exclusion_reason, COUNT(*) AS readings "
            f"FROM {relations.fact_exclusion} WHERE run_id = ? GROUP BY 1 ORDER BY 1",
            [context.run_id],
        )
        assumptions = [
            r[0]
            for r in con.execute(
                f"SELECT DISTINCT assumption_id FROM {relations.fact_scenario} "
                "WHERE run_id = ? ORDER BY 1",
                [context.run_id],
            ).fetchall()
        ]
    finally:
        con.close()
    ladder = context.accounting()
    return {
        "comparison_digest_version": COMPARISON_DIGEST_VERSION,
        "relations": evidence,
        "accounting": {
            "raw_rows": ladder.raw_rows,
            "rows_collapsed_by_policy": ladder.rows_collapsed_by_policy,
            "distinct_readings": ladder.distinct_readings,
            "included_readings": ladder.included_readings,
            "excluded_readings": ladder.excluded_readings,
            "derived_by_counting": ladder.derived,
            "reconciles": ladder.reconciles,
        },
        "total_consumption_kwh_exact": totals[0],
        "total_energy_charge_gbp_exact": totals[1],
        "assumption_ids": assumptions,
        "per_band": per_band,
        "per_household": per_household,
        "per_exclusion_reason": per_reason,
    }


def _inputs_of(context: reads.ReadContext) -> dict[str, Any]:
    """The recorded input scope: which members, which schedule, which settings."""
    identity = context.identity
    con = connect(context.database, read_only=True)
    try:
        loads = _rows(
            con,
            "SELECT archive_name, archive_sha256, member_name, member_content_sha256, "
            "records_read, records_published, records_rejected, pipeline_fingerprint "
            f"FROM {context.relations.load_registry} WHERE status = 'published' "
            "ORDER BY member_name",
        )
    finally:
        con.close()
    if not loads:
        raise BaselineError(
            f"{context.database.name}: no published loads recorded, so there is no input "
            "scope to replay from."
        )
    return {
        "members": loads,
        "member_count": len(loads),
        "schedule": {
            "variant": identity.schedule_variant,
            "source": identity.schedule_source,
            "source_sha256": identity.schedule_sha256,
            "rows": identity.schedule_rows,
        },
        "price_catalogue_version": identity.price_catalogue_version,
        "tariff_group": identity.tariff_group,
    }


def capture(
    root: Path,
    directory: Path = BASELINE_DIR,
    *,
    when: datetime | None = None,
) -> Path:
    """Record the **published** result at ``root`` as a format-2 baseline.

    Resolves and validates the publication through the ordinary read contract, so a
    version whose seal, build record and bytes do not agree is refused before anything is
    written -- there is no separate, weaker path into a baseline.
    """
    context = reads.published(root)
    if context.identity is None:  # pragma: no cover - published() always attests one
        raise BaselineError(f"{root}: the published version has no attested dbt build.")
    identity = context.identity
    when = when or datetime.now(UTC).replace(tzinfo=None)
    fingerprint = identity.run_id.split("-", 1)[-1].split("@", 1)[0]
    baseline = {
        "format_version": FORMAT_VERSION,
        "kind": (
            "a sealed, promoted dbt build, recorded from the validated read contract. "
            "NOT the Python scenario that the snapshotted warehouse also carries."
        ),
        "baseline_id": f"{fingerprint}@{when.strftime('%Y%m%dT%H%M%S')}",
        "captured_at_utc": when.isoformat(sep=" "),
        "note": (
            "Replay re-ingests the members named below from the archive and runs the "
            "supported build-candidate path. The publication root, the version file and "
            "the candidate are NOT needed to replay: only the archive and, for the "
            "workbook schedule, the workbook."
        ),
        "inputs": _inputs_of(context),
        "calculation": {
            "policy_sha256": identity.policy_sha256,
            "calculation_code_sha256": identity.calculation_code_sha256,
            "dbt_project_sha256": identity.dbt_project_sha256,
            "required_build": identity.required_build,
            "required_nodes_total": identity.required_nodes_total,
            "output_digest_version": identity.output_digest_version,
            "built_output_sha256": identity.built_output_sha256,
        },
        "runtime": identity.runtime,
        "outputs": outputs_of(context),
        "execution": {
            "expected_to_differ": (
                "A fresh rebuild is a new attempt in a new file. Nothing in this block is "
                "compared; it is here so a reader can see which run produced the record."
            ),
            "run_id": identity.run_id,
            "started_at_utc": identity.started_at_utc,
            "built_at_utc": identity.built_at_utc,
            "dbt_invocation_id": identity.dbt_invocation_id,
            "dbt_core_version": identity.dbt_core_version,
            "dbt_duckdb_version": identity.dbt_duckdb_version,
            "publication_root": str(root),
            "publication_version": context.version,
            "version_file": context.version_file,
            "version_file_sha256": identity.file_sha256,
        },
    }
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{FILE_PREFIX}{baseline['baseline_id']}.json"
    if path.exists():
        raise BaselineError(f"{path} already exists; a baseline is never overwritten")
    path.write_text(json.dumps(baseline, indent=2, default=str) + "\n")
    return path


def load(path: Path) -> dict[str, Any]:
    """Read a format-2 baseline, refusing any other format explicitly."""
    try:
        baseline = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise BaselineError(f"{path}: cannot be read as JSON ({error})") from error
    found = baseline.get("format_version")
    if found != FORMAT_VERSION:
        raise BaselineError(
            f"{path}: baseline format {found!r}, and this command reads only format "
            f"{FORMAT_VERSION!r}. Format 1 records a Python scenario and is replayed with "
            "`uv run replay-baseline`; it is not upgraded in place."
        )
    for section in ("inputs", "calculation", "runtime", "outputs"):
        if section not in baseline:
            raise BaselineError(
                f"{path}: incomplete format-{FORMAT_VERSION} baseline, {section!r} is "
                "missing. Refusing rather than comparing part of a result."
            )
    if (
        baseline["outputs"].get("comparison_digest_version")
        != COMPARISON_DIGEST_VERSION
    ):
        raise BaselineError(
            f"{path}: row digests were computed as "
            f"{baseline['outputs'].get('comparison_digest_version')!r}; this code computes "
            f"{COMPARISON_DIGEST_VERSION!r}. Not comparable; record a fresh baseline."
        )
    return baseline


def verify_inputs(
    baseline: dict[str, Any],
    archive: Path = DEFAULT_ARCHIVE,
    workbook: Path = DEFAULT_WORKBOOK,
) -> None:
    """Check every source artifact **before** any expensive work or destination is made.

    A missing or changed artifact is named and refused. Nothing is substituted: replaying
    against whatever happens to be on disk now would produce a different result wearing
    this baseline's name.
    """
    inputs = baseline["inputs"]
    if not archive.is_file():
        raise BaselineError(
            f"{archive} is not available, and it holds every member this baseline names. "
            "Cannot reproduce; nothing was created."
        )
    for member in inputs["members"]:
        name = member["member_name"]
        try:
            content = member_content_digest(archive, name)
            found_archive = member_identity(archive, name).archive_sha256
        except (KeyError, OSError) as error:
            raise BaselineError(
                f"{name} could not be read from {archive} ({error}). Cannot reproduce."
            ) from error
        if content != member["member_content_sha256"]:
            raise BaselineError(
                f"{name}: content digest {content[:12]}… does not match the baseline's "
                f"{member['member_content_sha256'][:12]}…. These are not the same input."
            )
        if found_archive != member["archive_sha256"]:
            raise BaselineError(
                f"{archive}: digest {found_archive[:12]}… does not match the baseline's "
                f"{member['archive_sha256'][:12]}…."
            )
    schedule = inputs["schedule"]
    if schedule["variant"] == "workbook":
        if not workbook.is_file():
            raise BaselineError(
                f"{workbook} is not available, and this baseline was built from the "
                "publisher's workbook. Cannot reproduce; the demo schedule is invented "
                "data and is never substituted for it."
            )
        found = file_sha256(workbook)
        if found != schedule["source_sha256"]:
            raise BaselineError(
                f"{workbook}: digest {found[:12]}… does not match the baseline's "
                f"{schedule['source_sha256'][:12]}…. This is a different schedule."
            )


@dataclass(frozen=True, slots=True)
class Replay:
    """One rebuild and its comparison."""

    baseline: dict[str, Any]
    differences: tuple[Difference, ...]
    warehouse: Path
    candidate: Path
    run_id: str

    @property
    def reproduced(self) -> bool:
        return all(d.matches for d in self.differences)

    @property
    def failed(self) -> tuple[Difference, ...]:
        return tuple(d for d in self.differences if not d.matches)


def replay(
    baseline_path: Path,
    into: Path,
    archive: Path = DEFAULT_ARCHIVE,
    workbook: Path = DEFAULT_WORKBOOK,
    project_dir: Path | None = None,
) -> Replay:
    """Rebuild the recorded result from its inputs, and compare. Nothing is copied.

    The destination must not exist. Every input is verified first, so a baseline that
    cannot be reproduced costs a few digests rather than a build. The rebuild runs the
    supported ``build-candidate`` path, which requires a complete dbt build -- every model
    and every test -- and seals the result before it can be read.
    """
    from .. import candidate as cand

    baseline = load(baseline_path)
    if into.exists():
        raise BaselineError(
            f"{into} already exists. Replay builds into a fresh destination: reusing one "
            "proves nothing about rebuilding from the recorded inputs."
        )
    verify_inputs(baseline, archive, workbook)

    into.mkdir(parents=True)
    warehouse = into / "replay-warehouse.duckdb"
    for member in baseline["inputs"]["members"]:
        load_member(archive, member["member_name"], warehouse)

    schedule = baseline["inputs"]["schedule"]
    try:
        built = cand.build_candidate(
            warehouse,
            schedule=schedule["variant"],
            workbook=str(workbook) if schedule["variant"] == "workbook" else "",
            tariff_group=baseline["inputs"]["tariff_group"],
            root=into / "publication",
            project_dir=project_dir,
        )
    except cand.CandidateError as error:
        raise BaselineError(
            f"the rebuild failed at the {error.stage} stage: {error}. A replay is only "
            "ever reported after a complete dbt build, so nothing is compared."
        ) from error

    context = reads.candidate(built.candidate)
    return Replay(
        baseline=baseline,
        differences=tuple(compare(baseline, context)),
        warehouse=warehouse,
        candidate=built.candidate,
        run_id=context.run_id,
    )


def _difference(field: str, recorded: Any, rebuilt: Any) -> Difference:
    return Difference(
        field,
        json.dumps(recorded, default=str, sort_keys=True),
        json.dumps(rebuilt, default=str, sort_keys=True),
    )


def compare(baseline: dict[str, Any], context: reads.ReadContext) -> list[Difference]:
    """Field by field: inputs, calculation, runtime and every logical output."""
    identity = context.identity
    rebuilt_inputs = _inputs_of(context)
    rebuilt_outputs = outputs_of(context)
    recorded_inputs = baseline["inputs"]
    recorded_outputs = baseline["outputs"]
    recorded_calculation = baseline["calculation"]

    differences: list[Difference] = []

    # --- reproduction inputs
    for member, rebuilt in zip(
        recorded_inputs["members"], rebuilt_inputs["members"], strict=False
    ):
        name = member["member_name"]
        for field in ("archive_sha256", "member_content_sha256", "records_published"):
            differences.append(
                _difference(f"input {name}.{field}", member[field], rebuilt.get(field))
            )
    differences.append(
        _difference(
            "input member_count",
            recorded_inputs["member_count"],
            rebuilt_inputs["member_count"],
        )
    )
    for field in ("variant", "source", "source_sha256", "rows"):
        differences.append(
            _difference(
                f"input schedule.{field}",
                recorded_inputs["schedule"][field],
                rebuilt_inputs["schedule"][field],
            )
        )
    for field in ("price_catalogue_version", "tariff_group"):
        differences.append(
            _difference(f"input {field}", recorded_inputs[field], rebuilt_inputs[field])
        )

    # --- calculation and runtime identity
    differences.append(
        _difference(
            "calculation policy_sha256",
            recorded_calculation["policy_sha256"],
            identity.policy_sha256,
        )
    )
    differences.append(
        _difference(
            "calculation calculation_code_sha256",
            recorded_calculation["calculation_code_sha256"],
            identity.calculation_code_sha256,
        )
    )
    differences.append(
        _difference(
            "calculation dbt_project_sha256",
            recorded_calculation["dbt_project_sha256"],
            identity.dbt_project_sha256,
        )
    )
    differences.append(
        _difference(
            "calculation required_build",
            [
                recorded_calculation["required_build"],
                recorded_calculation["required_nodes_total"],
            ],
            [identity.required_build, identity.required_nodes_total],
        )
    )
    differences.append(_difference("runtime", baseline["runtime"], identity.runtime))

    # --- logical outputs
    for key in sorted(recorded_outputs["relations"]):
        recorded = recorded_outputs["relations"][key]
        rebuilt = rebuilt_outputs["relations"].get(key, {})
        for field in ("schema", "rows", "row_digest", "excluded_columns"):
            differences.append(
                _difference(
                    f"output {key}.{field}", recorded[field], rebuilt.get(field)
                )
            )
    for field in (
        "accounting",
        "total_consumption_kwh_exact",
        "total_energy_charge_gbp_exact",
        "assumption_ids",
        "per_band",
        "per_household",
        "per_exclusion_reason",
    ):
        differences.append(
            _difference(
                f"output {field}", recorded_outputs[field], rebuilt_outputs[field]
            )
        )
    return differences
