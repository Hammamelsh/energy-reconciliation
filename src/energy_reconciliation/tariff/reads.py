"""The supported way to read a validated tariff build, and the only validated one.

Why this module exists
----------------------

A sealed candidate is a **whole warehouse snapshot**, so it contains two tariff scenarios
at once: the ``main.*`` tables the Python builder wrote in the source warehouse and copied
in with everything else, and the ``scenario_build.*`` tables dbt built and the seal
certifies. They are different runs, with different run ids, produced by different code.

Every query in :mod:`analytics` used to name its relations bare (``FROM
fact_interval_charge_scenario``), and DuckDB resolves a bare name in ``main``. So pointing
a reader at a sealed candidate would have shown the **copied Python scenario** under the
**candidate's** name, and reported ``main.scenario_run``'s identity for data the seal says
nothing about. Nothing would have failed; the page would simply have been wrong.

This module removes the ambiguity in one place:

- :func:`published` and :func:`candidate` validate a file **once** and return a
  :class:`ReadContext` carrying fully qualified relation names and the identity of the
  build that produced them.
- :func:`warehouse` returns the legacy context, so every existing caller keeps the exact
  route it has today.
- A request for the dbt route that cannot be validated **raises**. There is no fallback to
  ``main``: answering from the wrong scenario is the failure this module exists to prevent.

What is validated, and when
---------------------------

:func:`published` resolves the manifest **once**, then requires the manifest, the seal and
the build record to agree with each other and with the file:

1. the manifest names a file that exists (``publication.resolve``);
2. the file's bytes still hash to the seal's ``sha256``;
3. the seal's ``run_id`` and ``sha256`` are the manifest's;
4. the build record passes every gate in ``publication.build_record`` -- latest attempt
   succeeded, ``required_build`` complete, recorded in this file, one attempt, and the
   built tables still digest as recorded;
5. the record's ``run_id`` and ``built_output_sha256`` are the seal's.

Steps 2 and 4 are the expensive ones: a whole-file SHA-256 and a digest over every built
row. Measured on the three-member candidate (210 MB, ~3.0 M rows): 0.13 s and ~2.2 s. They
run **once per context**, at the boundary, and never inside a query. A caller holds the
context for a whole render and threads it through every read.

Active publication versus inspection
------------------------------------

:attr:`ReadContext.role` is ``published`` only for the file the manifest currently names.
A sealed candidate opened with :func:`candidate` is ``candidate``: the same validation, the
same relations, but :attr:`ReadContext.is_active_publication` is False and
:attr:`ReadContext.label` says so, so an inspected candidate can never be presented as what
readers are seeing. A context is immutable and bound to the file it resolved: promoting a
new version does not change a context already held, and the next :func:`published` call
returns the new one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final

import duckdb
import pandas as pd

from .. import publication
from ..ingest.warehouse import connect
from . import analytics as ta

#: Roles a context can have. ``PUBLISHED`` is the file the manifest names right now;
#: ``CANDIDATE`` is a sealed file being inspected before anyone promotes it; ``WAREHOUSE``
#: is the legacy Python route over a mutable ingestion warehouse.
PUBLISHED: Final[str] = "published"
CANDIDATE: Final[str] = "candidate"
WAREHOUSE: Final[str] = "warehouse"
#: A published version carried to another machine under ``serving.py``'s contract. Not
#: the live manifest: what was published when it was exported.
SERVING: Final[str] = "serving snapshot"


class ReadContextError(RuntimeError):
    """A validated read context could not be built, so nothing was read.

    Deliberately an error rather than a degraded context: every caller of this module
    asked for *validated* data, and returning the copied Python scenario instead would
    answer a different question without saying so.
    """


@dataclass(frozen=True, slots=True)
class BuildIdentity:
    """Who built the tariff tables a context reads, from the build record and the seal.

    Every field here is recorded by the producer. Nothing is renamed to look like a field
    the Python route has: a dbt build has no ``scenario_fingerprint`` and no
    ``ingestion_pipeline_fingerprint``, so neither appears, and ``dbt_project_sha256`` is
    never presented as either. What the two routes genuinely share -- the tariff group, the
    schedule source and digest, the price catalogue version, the policy digest -- keeps its
    name, because the meanings agree.
    """

    run_id: str
    started_at_utc: str
    built_at_utc: str
    dbt_core_version: str
    dbt_duckdb_version: str
    dbt_invocation_id: str | None
    schedule_variant: str
    schedule_source: str | None
    schedule_sha256: str | None
    schedule_rows: int | None
    tariff_group: str
    price_catalogue_version: str | None
    policy_sha256: str
    calculation_code_sha256: str
    runtime_fingerprint: str
    runtime_detail: str
    dbt_project_sha256: str
    required_build: str
    required_nodes_total: int
    output_digest_version: str
    built_output_sha256: str
    file_sha256: str

    @property
    def runtime(self) -> dict[str, str]:
        try:
            return json.loads(self.runtime_detail)
        except (TypeError, ValueError):  # pragma: no cover - only on a corrupt row
            return {}

    @property
    def is_synthetic(self) -> bool:
        """True when the schedule is the project's INVENTED one, not the publisher's."""
        return self.schedule_source != "Tariffs.xlsx"


@dataclass(frozen=True, slots=True)
class ReadContext:
    """One validated file, the relations to read it through, and who built them.

    Immutable and bound to the file it was resolved from. Hold it for a whole render and
    pass it to every read; do not re-resolve between queries, or two queries in one page
    could answer from two different versions.
    """

    database: Path
    relations: ta.Relations
    role: str
    run_id: str
    identity: BuildIdentity | None = None
    run_record: ta.RunRecord | None = None
    version: str | None = None
    version_file: str | None = None
    promoted_at_utc: str | None = None

    @property
    def is_active_publication(self) -> bool:
        """True only for the version the manifest named when this context was resolved."""
        return self.role == PUBLISHED

    @property
    def is_dbt_build(self) -> bool:
        return self.identity is not None

    @property
    def label(self) -> str:
        """One line naming what this context reads, for a header or a log."""
        if self.role == PUBLISHED:
            return (
                f"published {self.version} ({self.version_file}) · dbt run "
                f"{self.run_id} · {self.relations.label}"
            )
        if self.role == SERVING:
            return (
                f"published {self.version} · serving snapshot ({self.version_file}) · "
                f"dbt run {self.run_id} · {self.relations.label}"
            )
        if self.role == CANDIDATE:
            return (
                f"CANDIDATE {self.database.name} — sealed, NOT published · dbt run "
                f"{self.run_id} · {self.relations.label}"
            )
        return (
            f"{self.database.name} · python run {self.run_id} · {self.relations.label}"
        )

    def accounting(self) -> ta.Accounting:
        """The reconciliation ladder for this context, by the route that has one.

        The Python route reads the ladder its builder recorded. The dbt route counts it
        (``Accounting.derived`` is True), because dbt records no such row and inventing
        one would be worse than counting.
        """
        if self.relations.has_run_table:
            return ta.accounting(self.database, self.run_id, relations=self.relations)
        return ta.counted_accounting(
            self.database, self.run_id, relations=self.relations
        )


# ------------------------------------------------------------------ validation
def _connect(path: Path):
    return connect(path, read_only=True)


def _identity(
    record: dict[str, Any], seal: publication.Seal, path: Path
) -> BuildIdentity:
    """Fields the seal does not carry, read back from the attempt that produced them.

    The seal records what promotion must compare; these are display and reproduction
    details that live only in the build record, so they are read from the row the seal
    already names rather than widening the seal contract.
    """
    con = _connect(path)
    try:
        row = con.execute(
            "SELECT policy_sha256, runtime_detail, dbt_project_sha256, schedule_rows "
            f"FROM {publication.BUILD_RUN_TABLE} WHERE run_id = ?",
            [record["run_id"]],
        ).fetchone()
    finally:
        con.close()
    if row is None:  # pragma: no cover - build_record already read this row
        raise ReadContextError(f"{path.name}: attempt {record['run_id']} vanished")
    return BuildIdentity(
        run_id=record["run_id"],
        started_at_utc=str(record["started_at_utc"]),
        built_at_utc=str(record["built_at_utc"]),
        dbt_core_version=record["dbt_core_version"],
        dbt_duckdb_version=record["dbt_duckdb_version"],
        dbt_invocation_id=record["dbt_invocation_id"],
        schedule_variant=record["schedule_variant"],
        schedule_source=record["schedule_source"],
        schedule_sha256=record["schedule_sha256"],
        schedule_rows=row[3],
        tariff_group=record["tariff_group"],
        price_catalogue_version=record["price_catalogue_version"],
        policy_sha256=row[0],
        calculation_code_sha256=record["calculation_code_sha256"],
        runtime_fingerprint=record["runtime_fingerprint"],
        runtime_detail=row[1],
        dbt_project_sha256=row[2],
        required_build=record["required_build"],
        required_nodes_total=int(record["required_nodes_total"] or 0),
        output_digest_version=record["output_digest_version"],
        built_output_sha256=record["built_output_sha256"],
        file_sha256=seal.sha256,
    )


def _validated(
    path: Path,
    role: str,
    *,
    bound_to: str | None = None,
    verify_output_digest: bool = True,
    **version: Any,
) -> ReadContext:
    """Seal, build record and file bytes checked against each other, then bound together.

    Every refusal names which two pieces of evidence disagreed. The expensive checks --
    the whole-file hash and the built-table digest -- happen here and only here.
    ``bound_to`` and ``verify_output_digest`` exist for the serving route only; see
    :func:`serving` and ``publication.build_record``.
    """
    if not path.is_file():
        raise ReadContextError(f"{path} does not exist.")
    try:
        seal = publication.read_seal(path)
        record = publication.build_record(
            path, bound_to=bound_to, verify_output_digest=verify_output_digest
        )
    except publication.PublicationError as error:
        raise ReadContextError(
            f"{path.name} is not a validated dbt build: {error}"
        ) from error
    except duckdb.Error as error:
        raise ReadContextError(
            f"{path.name} could not be read as a database ({type(error).__name__}: "
            f"{error}). A damaged or partial file; refusing."
        ) from error

    digest = publication._sha256(path)
    if digest != seal.sha256:
        raise ReadContextError(
            f"{path.name}: bytes {digest[:12]}… differ from the sealed "
            f"{seal.sha256[:12]}…. The file changed after validation; refusing to read it."
        )
    if record["run_id"] != seal.run_id:
        raise ReadContextError(
            f"{path.name}: the build record names run {record['run_id']} but the seal "
            f"names {seal.run_id}. Refusing: the two describe different builds."
        )
    if record["built_output_sha256"] != seal.built_output_sha256:
        raise ReadContextError(
            f"{path.name}: the build record's output digest is not the sealed one. "
            "Refusing."
        )
    if not _has_build_schema(path):
        raise ReadContextError(
            f"{path.name} carries a build record but no {ta.BUILD_SCHEMA} tariff tables. "
            "Refusing: there is nothing validated to read, and main holds a different "
            "scenario."
        )
    return ReadContext(
        database=path,
        relations=ta.DBT_RELATIONS,
        role=role,
        run_id=record["run_id"],
        identity=_identity(record, seal, path),
        **version,
    )


def _has_build_schema(path: Path) -> bool:
    con = _connect(path)
    try:
        found = {
            name
            for (name,) in con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = ?",
                [ta.BUILD_SCHEMA],
            ).fetchall()
        }
    finally:
        con.close()
    required = {
        ta.DBT_RELATIONS.fact_scenario,
        ta.DBT_RELATIONS.fact_exclusion,
        ta.DBT_RELATIONS.dim_schedule,
        ta.DBT_RELATIONS.dim_price,
    }
    return {r.split(".", 1)[1] for r in required} <= found


# ------------------------------------------------------------------ entry points
def published(root: Path = publication.DEFAULT_ROOT) -> ReadContext:
    """The active published version, validated once. ONE manifest read.

    Raises :class:`publication.Unavailable` when nothing is published -- an explicit
    absence, never an empty dataset -- and :class:`ReadContextError` when the manifest,
    the seal, the build record and the file do not all describe the same build.
    """
    path, manifest = publication.resolve(root)
    context = _validated(
        path,
        PUBLISHED,
        version=manifest["version"],
        version_file=manifest["file"],
        promoted_at_utc=manifest.get("promoted_at_utc"),
    )
    if manifest.get("sha256") != context.identity.file_sha256:
        raise ReadContextError(
            f"{path.name}: the manifest records a different sha256 from the seal. "
            "Refusing: the published version is not the file that was validated."
        )
    if manifest.get("run_id") != context.run_id:
        raise ReadContextError(
            f"{path.name}: the manifest names run {manifest.get('run_id')} but the file "
            f"was built by {context.run_id}. Refusing."
        )
    return context


def serving(directory: Path, *, expected_sha256: str | None = None) -> ReadContext:
    """A serving snapshot, verified: bytes against the pin and the seal, then every
    attempt-record gate with the record bound to the exported origin, not to this path.

    ``expected_sha256`` lets a deployment pass the digest it pinned in the repository, so
    the directory's own manifest cannot quietly point at a different file.
    """
    from .. import serving as sv  # function-local: serving imports publication

    try:
        manifest = sv.load_manifest(Path(directory))
    except sv.ServingError as error:
        raise ReadContextError(str(error)) from error
    path = Path(directory) / manifest["file"]
    if expected_sha256 is not None and manifest["sha256"] != expected_sha256:
        raise ReadContextError(
            f"{path.name}: the snapshot manifest pins {manifest['sha256'][:12]}… but the "
            f"deployment expects {expected_sha256[:12]}…. Refusing."
        )
    if not path.is_file():
        raise ReadContextError(
            f"{path} is missing: the snapshot was not fetched, or the download did not "
            "complete. Nothing is shown in its place."
        )
    if path.stat().st_size != manifest["size_bytes"]:
        raise ReadContextError(
            f"{path.name}: {path.stat().st_size:,} bytes on disk, {manifest['size_bytes']:,} "
            "pinned. A partial file is not a version; refusing."
        )
    digest = publication._sha256(path)
    if digest != manifest["sha256"]:
        raise ReadContextError(
            f"{path.name}: bytes {digest[:12]}… differ from the sealed and pinned "
            f"{manifest['sha256'][:12]}…. The file is not the one that was validated; "
            "refusing to open it."
        )
    context = _validated(
        path,
        SERVING,
        bound_to=manifest["build_origin_path"],
        verify_output_digest=False,
        version=manifest["version"],
        version_file=manifest["file"],
        promoted_at_utc=manifest.get("promoted_at_utc"),
    )
    if manifest["sha256"] != context.identity.file_sha256:
        raise ReadContextError(
            f"{path.name}: the snapshot manifest pins {manifest['sha256'][:12]}… but the "
            f"seal certifies {context.identity.file_sha256[:12]}…. Refusing."
        )
    if manifest["run_id"] != context.run_id:
        raise ReadContextError(
            f"{path.name}: the manifest names run {manifest['run_id']} but the file was "
            f"built by {context.run_id}. Refusing."
        )
    return context


def candidate(path: Path) -> ReadContext:
    """A sealed candidate, for inspection before anyone promotes it.

    Validated exactly as a published version is. The context's role is ``candidate`` and
    :attr:`ReadContext.is_active_publication` is False, so what a reader sees cannot be
    mistaken for what is published.
    """
    return _validated(Path(path), CANDIDATE)


def warehouse(database: Path) -> ReadContext:
    """The legacy route: the Python scenario in a mutable ingestion warehouse.

    Unchanged behaviour for every existing caller. There is no seal and no build record
    here, so nothing is validated beyond the schema check ``analytics`` already does; the
    context exists so that both routes can be threaded through the same code.
    """
    run = ta.latest_run(database)
    if run is None:
        raise ReadContextError(
            f"{database}: no tariff scenario has been built. Run build-tariff-scenario."
        )
    return ReadContext(
        database=database,
        relations=ta.WAREHOUSE_RELATIONS,
        role=WAREHOUSE,
        run_id=run.run_id,
        run_record=run,
    )


# ------------------------------------------------------------------ reading
@dataclass(frozen=True, slots=True)
class TariffReport:
    """One complete analytical operation over a single context.

    Everything here comes from the **same** validated file, through the same relations,
    filtered by the same run id, in one pass. It exists so that a caller cannot assemble a
    page from two contexts by accident.
    """

    context: ReadContext
    accounting: ta.Accounting
    bands: pd.DataFrame
    households: pd.DataFrame
    exclusions: pd.DataFrame
    schedule: pd.DataFrame
    prices: pd.DataFrame
    insights: list[ta.Insight]
    period: tuple[date | None, date | None]
    household: str | None

    @property
    def total_charge_exact(self) -> str:
        return str(self.bands.attrs.get("denominator_charge_gbp_exact", "0"))

    @property
    def charged_readings(self) -> int:
        return int(self.bands.attrs.get("denominator_readings", 0))


def tariff_report(
    context: ReadContext,
    household: str | None = None,
    start: date | None = None,
    end: date | None = None,
) -> TariffReport:
    """Read one complete tariff view through a context that is already validated.

    The context is not re-validated and the manifest is not re-read: both happened once,
    at the boundary. Every query names its schema through ``context.relations``.
    """
    relations = context.relations
    return TariffReport(
        context=context,
        accounting=context.accounting(),
        bands=ta.band_summary(
            context.database,
            context.run_id,
            household,
            start,
            end,
            relations=relations,
        ),
        households=ta.household_totals(
            context.database, context.run_id, start, end, relations=relations
        ),
        exclusions=ta.exclusion_breakdown(
            context.database,
            context.run_id,
            household,
            start,
            end,
            relations=relations,
        ),
        schedule=ta.schedule_totals(context.database, relations=relations),
        prices=ta.price_catalogue(context.database, relations=relations),
        insights=ta.selection_insights(
            context.database,
            context.run_id,
            household,
            start,
            end,
            relations=relations,
        ),
        period=(start, end),
        household=household,
    )
