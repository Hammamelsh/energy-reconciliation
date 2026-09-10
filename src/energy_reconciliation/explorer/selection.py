"""What the dashboard is looking at: one warehouse file, or one published version.

Two modes, kept apart on purpose
--------------------------------

- **Warehouse file** -- the workflow that has always existed. A mutable file under
  ``data/warehouse/``, its tariff tables built by ``build-tariff-scenario`` in Python, its
  identity read from ``main.scenario_run``. Unchanged by this module.
- **Published version** -- the file ``data/published/published.json`` names, resolved
  **once per rerun** through :func:`tariff.reads.published`. Its inputs come from ``main``
  and its tariff outputs and identity from the dbt build the seal certifies.

A :class:`Selection` is made once, at the top of a render, and threaded through every
query. It carries the relations to read through, so no tab can bind a bare relation name
and land in the wrong schema. **There is no fallback between the modes.** If a published
version cannot be resolved and validated, :func:`resolve` returns a selection in the
``unavailable`` state carrying the reason; the caller shows that and renders nothing else.
Quietly showing the local warehouse instead would answer a different question under the
word "published".

Why the identity is adapted rather than unified
-----------------------------------------------

The two routes record genuinely different things. A Python run has a scenario
fingerprint, an ingestion pipeline fingerprint, a model-code digest and a recorded charge
total. A dbt build has none of those, and has instead a dbt version pair, an invocation
id, a project digest, a required-build state and an output digest. :class:`ScenarioHeader`
shows each route what it actually recorded, names what the other route would have shown,
and invents nothing. Where the two agree in meaning -- the tariff group, the schedule
source and digest, the price catalogue version, the policy digest -- the field keeps its
name.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from .. import publication
from ..tariff import analytics as ta
from ..tariff import reads

WAREHOUSE_MODE: Final[str] = "Warehouse file"
PUBLISHED_MODE: Final[str] = "Published version"
MODES: Final[tuple[str, ...]] = (WAREHOUSE_MODE, PUBLISHED_MODE)

#: Where the dashboard looks for a publication. Overridable so a demonstration can run
#: against a disposable root without touching ``data/published``:
#:
#: ``ENERGY_RECONCILIATION_PUBLICATION_ROOT=/tmp/demo uv run streamlit run …``
ROOT_ENV: Final[str] = "ENERGY_RECONCILIATION_PUBLICATION_ROOT"


def publication_root() -> Path:
    return Path(os.environ.get(ROOT_ENV) or publication.DEFAULT_ROOT)


def serving_directory() -> Path | None:
    """A serving snapshot directory, when a deployment configured one."""
    from .. import serving as sv

    value = os.environ.get(sv.SERVING_ENV)
    return Path(value) if value else None


def _serving_key(directory: Path) -> tuple[str, str] | None:
    from .. import serving as sv

    try:
        manifest = sv.load_manifest(directory)
    except (sv.ServingError, OSError, ValueError):
        return None
    return (str((directory / manifest["file"]).resolve()), str(manifest["sha256"]))


def serving(directory: Path) -> Selection:
    """Resolve and validate a serving snapshot. Same cache rule as a publication."""
    from .. import serving as sv

    key = _serving_key(directory)
    if key is not None and key in _VALIDATED:
        context = _VALIDATED[key]
        return Selection(PUBLISHED_MODE, context.database, context.relations, context)
    failed = os.environ.get(sv.SERVING_ERROR_ENV)
    if failed:
        return Selection(
            PUBLISHED_MODE,
            None,
            None,
            unavailable=f"the snapshot download failed: {failed}",
        )
    try:
        context = reads.serving(directory)
    except (reads.ReadContextError, publication.PublicationError) as error:
        return Selection(PUBLISHED_MODE, None, None, unavailable=str(error))
    if key is not None:
        _remember(_VALIDATED, key, context)
    return Selection(PUBLISHED_MODE, context.database, context.relations, context)


#: Validated contexts kept for the life of the process, and the applicability verdicts
#: taken over them.
#:
#: **Identity.** The key is ``(absolute version file, the sha256 the manifest records for
#: it)``. That digest is what promotion compared the file's bytes against, so two runs
#: with the same key are the same bytes -- not the same *name*, and not the same
#: modification time, neither of which is an identity.
#:
#: **Invalidation.** A promotion or a rollback writes a new manifest naming a different
#: file or digest, so the next render misses and validates again. Nothing else can
#: invalidate an entry, because a published version is immutable by construction: sealing
#: drops the write bits, promotion re-hashes against the seal, and the read contract
#: refuses a file whose bytes have moved.
#:
#: **What a hit skips**, stated plainly: on a hit the file's bytes are not re-hashed and
#: the built tables are not re-digested in this render. The guarantee is that *this
#: process* proved that exact digest once. Someone who forces a sealed file writable and
#: edits it mid-session would not be caught until the app restarts. That window is the
#: price of not re-hashing 210 MB and re-digesting three million rows on every widget
#: click (measured: 3.15 s and 1.20 s of a 5.37 s rerun).
#:
#: A **warehouse file is never cached**: it is mutable and has no content identity short
#: of hashing it, and caching one by path would be exactly the defect I-19 removed.
_CACHE_LIMIT: Final[int] = 4
_VALIDATED: dict[tuple[str, str], reads.ReadContext] = {}
_APPLICABILITY: dict[tuple[Any, ...], dict[str, Any]] = {}


def _remember(store: dict, key: Any, value: Any) -> Any:
    store[key] = value
    while len(store) > _CACHE_LIMIT:
        store.pop(next(iter(store)))
    return value


def clear_caches() -> None:
    """Forget every validated context. For tests, and for an explicit re-check."""
    _VALIDATED.clear()
    _APPLICABILITY.clear()


def _manifest_exists(root: Path) -> bool:
    """Is there a publication at all? A corrupt manifest counts as one that is broken."""
    try:
        return publication.read_manifest(root) is not None
    except (OSError, ValueError):  # pragma: no cover - a corrupt manifest
        return True


def _cache_key(root: Path) -> tuple[str, str] | None:
    """The identity of whatever the manifest names now, or None if it cannot be read."""
    try:
        manifest = publication.read_manifest(root)
    except (OSError, ValueError):  # pragma: no cover - a corrupt manifest
        return None
    if not manifest or not manifest.get("file") or not manifest.get("sha256"):
        return None
    path = (root / publication.VERSIONS / manifest["file"]).resolve()
    return (str(path), str(manifest["sha256"]))


@dataclass(frozen=True, slots=True)
class Selection:
    """One resolved thing to read, for one render. Immutable, and passed, never re-derived."""

    mode: str
    database: Path | None
    relations: ta.Relations | None
    context: reads.ReadContext | None = None
    unavailable: str = ""
    #: True only when **nothing has been promoted**. An ordinary state, said neutrally.
    #: A manifest that exists but does not validate is not absent -- it is broken, and
    #: the two must not look the same to a reader.
    absent: bool = False

    @property
    def ready(self) -> bool:
        return self.database is not None and not self.unavailable

    @property
    def is_published(self) -> bool:
        return self.mode == PUBLISHED_MODE

    @property
    def uses_dbt_build(self) -> bool:
        """True when the tariff tables come from the dbt build, not the Python scenario."""
        return self.context is not None and self.context.is_dbt_build


def warehouse(database: Path) -> Selection:
    """The legacy route. No seal, no manifest; the tariff tab reads ``scenario_run``."""
    return Selection(WAREHOUSE_MODE, database, ta.WAREHOUSE_RELATIONS)


def published(root: Path | None = None) -> Selection:
    """Resolve and validate the published version. ONE manifest read, once per rerun.

    Every failure becomes an ``unavailable`` selection with the reason, never a fallback:
    nothing is published, the named file is missing, the seal or build record disagrees
    with it, or its build was not a complete one.
    """
    if root is None and (snapshot := serving_directory()) is not None:
        return serving(snapshot)
    root = root or publication_root()
    key = _cache_key(root)
    if key is not None and key in _VALIDATED:
        context = _VALIDATED[key]
        return Selection(PUBLISHED_MODE, context.database, context.relations, context)
    try:
        context = reads.published(root)
    except publication.Unavailable as error:
        # "nothing promoted" and "the manifest names a file that is gone" both arrive
        # here; only the first is an absence.
        return Selection(
            PUBLISHED_MODE,
            None,
            None,
            unavailable=str(error),
            absent=not _manifest_exists(root),
        )
    except reads.ReadContextError as error:
        return Selection(PUBLISHED_MODE, None, None, unavailable=str(error))
    except publication.PublicationError as error:  # pragma: no cover - defensive
        return Selection(PUBLISHED_MODE, None, None, unavailable=str(error))
    if key is not None:
        _remember(_VALIDATED, key, context)
    return Selection(PUBLISHED_MODE, context.database, context.relations, context)


def forecast_applicability(
    selected: Selection, reports: dict[str, dict[str, Any] | None]
) -> dict[str, Any]:
    """Whether each report describes the selected dataset, cached only when it is sealed.

    Keyed by the version's digest **and** each report's own recorded dataset digest, so a
    regenerated report is assessed again. A warehouse selection is assessed every time:
    the file can change under it between renders.
    """
    from . import forecast_view as fc

    target = selected.context or selected.database
    if not selected.uses_dbt_build:
        return fc.assess_reports(reports, target)
    key = (
        str(selected.database),
        selected.context.identity.file_sha256,
        tuple(
            (label, (report or {}).get("identity", {}).get("dataset_sha256"))
            for label, report in sorted(reports.items())
        ),
    )
    if key in _APPLICABILITY:
        return _APPLICABILITY[key]
    return _remember(_APPLICABILITY, key, fc.assess_reports(reports, target))


def resolve(mode: str, database: Path | None, root: Path | None = None) -> Selection:
    """The selection for this render, from the mode the sidebar is showing."""
    if mode == PUBLISHED_MODE:
        return published(root)
    if database is None:  # pragma: no cover - the picker always has a file
        return Selection(
            WAREHOUSE_MODE, None, None, unavailable="no warehouse selected"
        )
    return warehouse(database)


# ------------------------------------------------------------------ identity
@dataclass(frozen=True, slots=True)
class ScenarioHeader:
    """What the tariff tab says about the run it is showing, on either route."""

    run_id: str
    built_at: str
    assumption_ids: str
    assumption_text: str | None
    schedule_source: str
    schedule_sha256: str
    schedule_rows: int | None
    tariff_group: str
    price_catalogue_version: str | None
    is_synthetic: bool
    route: str
    identity_rows: tuple[tuple[str, str], ...]
    not_recorded: str

    @property
    def synthetic_note(self) -> str:
        return (
            f"**Synthetic evidence.** This scenario uses the `{self.schedule_source}` "
            "schedule — invented band timings for demonstration. The prices are the real "
            "published ones. Do not read any figure on this tab as a measurement of the "
            "real trial."
        )


def _fmt(value: Any) -> str:
    return "—" if value is None else str(value)


def header_from_run(run: ta.RunRecord, database: Path) -> ScenarioHeader:
    """The Python route's identity, exactly the fields it has always shown."""
    return ScenarioHeader(
        run_id=run.run_id,
        built_at=run.run_at_utc,
        assumption_ids=run.assumption_ids,
        assumption_text=run.assumption_text,
        schedule_source=run.schedule_source,
        schedule_sha256=run.schedule_sha256,
        schedule_rows=run.schedule_rows,
        tariff_group=run.scope_tariff_group,
        price_catalogue_version=run.price_catalogue_version,
        is_synthetic=run.is_synthetic,
        route="Python scenario builder (`build-tariff-scenario`), tables in `main`",
        identity_rows=(
            ("Run", f"`{run.run_id}`"),
            ("Built (UTC)", run.run_at_utc),
            (
                "Schedule",
                (
                    f"{run.schedule_source}, {run.schedule_rows:,} labels, "
                    f"`{run.schedule_sha256[:16]}…`"
                ),
            ),
            (
                "Schedule coverage",
                f"{run.schedule_first_label} to {run.schedule_last_label}",
            ),
            (
                "Price catalogue",
                f"{run.price_catalogue_version} (PUBLISHER-DOCUMENTED)",
            ),
            (
                "Calculation code (all first-party files)",
                f"`{run.calculation_code_sha256[:16]}…`",
            ),
            ("Shared policy (`policy.py`)", f"`{run.policy_sha256[:16]}…`"),
            ("Tariff models", f"`{run.model_code_sha256[:16]}…`"),
            ("Ingestion pipeline", f"`{run.ingestion_pipeline_fingerprint[:16]}…`"),
            (
                "Runtime",
                ", ".join(f"{k} {v}" for k, v in sorted(run.runtime.items())),
            ),
            ("Loaded files", str(len(run.source_load_ids.split("|")))),
            ("Whole-run exact charge", f"`£{run.total_energy_charge_gbp_exact}`"),
        ),
        not_recorded=(
            "A fingerprint over a **mutable** warehouse is not historical replay. To "
            "rebuild this result from its recorded inputs alone, capture and replay a "
            f"baseline: `uv run capture-baseline --database {database}` then "
            "`uv run replay-baseline`."
        ),
    )


def header_from_context(
    context: reads.ReadContext,
    *,
    assumption_ids: tuple[str, ...],
    total_charge_exact: str,
    coverage: tuple[Any, Any] | None,
) -> ScenarioHeader:
    """The dbt route's identity, from the build record and the seal.

    Every row here is a value the build recorded, plus two counted from the built tables
    and labelled as counted. Fields only the Python route records are named in
    ``not_recorded`` rather than filled in with something that looks like them.
    """
    identity = context.identity
    first, last = coverage if coverage else (None, None)
    rows: list[tuple[str, str]] = [
        ("dbt build run", f"`{identity.run_id}`"),
        ("Built (UTC)", f"{identity.built_at_utc} (started {identity.started_at_utc})"),
        (
            "Required build",
            (
                f"{identity.required_build} — every one of "
                f"{identity.required_nodes_total} required dbt nodes passed"
            ),
        ),
        (
            "Schedule",
            f"{identity.schedule_source}, "
            + (
                f"{identity.schedule_rows:,} labels, "
                if identity.schedule_rows is not None
                else ""
            )
            + f"`{_fmt(identity.schedule_sha256)[:16]}…` (variant "
            f"`{identity.schedule_variant}`)",
        ),
        ("Schedule coverage", f"{_fmt(first)} to {_fmt(last)}"),
        (
            "Price catalogue",
            f"{_fmt(identity.price_catalogue_version)} (PUBLISHER-DOCUMENTED)",
        ),
        (
            "Calculation code (first-party + `dimensions.py` + dbt project)",
            f"`{identity.calculation_code_sha256[:16]}…`",
        ),
        ("Shared policy (`policy.py`)", f"`{identity.policy_sha256[:16]}…`"),
        ("dbt project", f"`{identity.dbt_project_sha256[:16]}…`"),
        (
            "dbt",
            (
                f"dbt-core {identity.dbt_core_version}, dbt-duckdb "
                f"{identity.dbt_duckdb_version} (invocation "
                f"`{_fmt(identity.dbt_invocation_id)[:8]}…`)"
            ),
        ),
        (
            "Runtime",
            ", ".join(f"{k} {v}" for k, v in sorted(identity.runtime.items())),
        ),
        (
            "Built tables digest",
            f"`{identity.built_output_sha256[:16]}…` ({identity.output_digest_version})",
        ),
        ("Version file (whole-file SHA-256)", f"`{identity.file_sha256[:16]}…`"),
        ("Whole-run exact charge", f"`£{total_charge_exact}` (counted from the fact)"),
    ]
    if context.version:
        rows.insert(
            0, ("Published version", f"{context.version} ({context.version_file})")
        )
        rows.insert(1, ("Promoted (UTC)", _fmt(context.promoted_at_utc)))
    return ScenarioHeader(
        run_id=identity.run_id,
        built_at=identity.built_at_utc,
        assumption_ids="|".join(assumption_ids) if assumption_ids else "—",
        assumption_text=None,
        schedule_source=_fmt(identity.schedule_source),
        schedule_sha256=_fmt(identity.schedule_sha256),
        schedule_rows=identity.schedule_rows,
        tariff_group=identity.tariff_group,
        price_catalogue_version=identity.price_catalogue_version,
        is_synthetic=identity.is_synthetic,
        route="dbt build (`scenario_build`), sealed and promoted",
        identity_rows=tuple(rows),
        not_recorded=(
            "**What a dbt build does not record**, and is therefore not shown: a scenario "
            "fingerprint, an ingestion-pipeline fingerprint, a tariff-model code digest "
            "and the set of loaded file ids. Those belong to the Python scenario builder, "
            "which is what a *warehouse file* selection reads. The charge total above is "
            "**counted** from the built fact rather than read from a recorded row, and "
            "the accounting ladder on this route is counted for the same reason."
        ),
    )
