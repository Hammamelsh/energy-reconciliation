"""What a **candidate** (dbt-built) result depends on, named explicitly.

Two identities, one set of helpers
----------------------------------

The **published** scenario is still built by ``build-tariff-scenario`` in Python. Its
identity is :func:`identity.calculation_files` and :func:`identity.runtime_identity`, and
this module leaves both **untouched** -- it is a sibling of :mod:`identity`, not an edit to
it, so every recorded ``scenario_run`` fingerprint and every format-1 baseline keeps the
meaning it had. (``identity.py`` is itself a covered calculation file; editing it would
move the published digest for a change that cannot alter a published figure.)

A **candidate** is built by dbt (``run-dbt`` / ``build-candidate``). Its outputs depend on
everything the published path depends on **plus**:

- ``tariff/dimensions.py`` -- decides the persisted types of both dimensions
  (``DECIMAL(9,4)`` / ``DECIMAL(9,6)``) and which schedule variant is read;
- the dbt project files -- ``dbt_project.yml``, every model (SQL and Python) and every
  macro, the generated policy macros included: the rendered SQL and its configuration;
- the dbt packages that render and execute that SQL.

:func:`candidate_calculation_files` and :func:`candidate_runtime_identity` are those
supersets, and ``scenario_build.dbt_build_run`` records their digests with every attempt.
Neither is folded into the published identity here: the dashboard does not yet read a
candidate, and claiming the published figures depend on dbt before they do would be the
over-inclusion :mod:`identity` warns against. When the dashboard is switched to published
candidates, the candidate identity **becomes** the published one.

Coverage is guarded rather than trusted, in ``tests/test_tariff_identity.py``: the import
closure of the dbt Python models in a fresh interpreter must be covered, and an
independent walk of the dbt directories must find nothing the globs here miss.
"""

from __future__ import annotations

import hashlib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Final

from . import identity
from .identity import PACKAGE_ROOT, _digest_of

#: The repository root, from the package location: ``src/energy_reconciliation`` → root.
REPOSITORY_ROOT: Final[Path] = PACKAGE_ROOT.parents[1]

#: Files in the tariff package that a candidate build depends on and the published Python
#: path does not.
CANDIDATE_TARIFF_FILES: Final[tuple[str, ...]] = ("dimensions.py",)

#: dbt project files whose bytes shape a candidate output. Not ``target/``, ``logs/`` or
#: ``.user.yml`` (artefacts of running, and a per-machine id); not ``profiles.yml`` (names
#: the database file and the schema, changes no value); not ``tests/`` (they decide whether
#: a build is *accepted*, not what its tables hold).
DBT_PROJECT_GLOBS: Final[tuple[str, ...]] = (
    "dbt_project.yml",
    "models/**/*",
    "macros/*",
)

#: dbt packages recorded with every candidate build: they render and execute the SQL.
DBT_PACKAGES: Final[tuple[str, ...]] = ("dbt-core", "dbt-duckdb")

#: Every library whose version is recorded with a candidate build.
CANDIDATE_RUNTIME_PACKAGES: Final[tuple[str, ...]] = (
    *identity.RUNTIME_PACKAGES,
    *DBT_PACKAGES,
)


def default_dbt_project() -> Path:
    """The repository's dbt project, located without depending on the working directory."""
    return REPOSITORY_ROOT / "dbt"


def dbt_project_files(project: Path | None = None) -> list[Path]:
    """Every dbt project file whose bytes can change a candidate output, sorted."""
    root = project or default_dbt_project()
    paths: set[Path] = set()
    for pattern in DBT_PROJECT_GLOBS:
        paths.update(p.resolve() for p in root.glob(pattern) if p.is_file())
    return sorted(paths)


def dbt_project_digest(project: Path | None = None) -> str:
    """One digest over the dbt project files, keyed by project-relative path."""
    root = (project or default_dbt_project()).resolve()
    return _digest_of(
        {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in dbt_project_files(root)
        }
    )


def candidate_calculation_files(project: Path | None = None) -> list[Path]:
    """Every first-party file a candidate build depends on, sorted.

    A superset of :func:`identity.calculation_files`: the published set, plus
    :data:`CANDIDATE_TARIFF_FILES` and the dbt project files.
    """
    files = set(identity.calculation_files())
    files.update(
        (PACKAGE_ROOT / "tariff" / name).resolve()
        for name in CANDIDATE_TARIFF_FILES
        if (PACKAGE_ROOT / "tariff" / name).is_file()
    )
    files.update(dbt_project_files(project))
    return sorted(files)


def candidate_file_digests(project: Path | None = None) -> dict[str, str]:
    """Repository-relative path → SHA-256 of its bytes, for every candidate file.

    Paths are relative to the **repository** (not the package) because the dbt project
    lives outside ``src/``. A project passed explicitly may live anywhere (tests copy it);
    its files are then keyed relative to that project under ``dbt/`` so a copied project
    with identical bytes digests the same as the real one.
    """
    root = (project or default_dbt_project()).resolve()
    out: dict[str, str] = {}
    for path in candidate_calculation_files(root):
        if path.is_relative_to(root):
            key = str(Path("dbt") / path.relative_to(root))
        else:
            key = str(path.relative_to(REPOSITORY_ROOT))
        out[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def candidate_calculation_digest(project: Path | None = None) -> str:
    """One digest over every candidate calculation file. Renaming a file changes it."""
    return _digest_of(candidate_file_digests(project))


def candidate_runtime_identity() -> dict[str, str]:
    """Python and every library that produces a candidate table, dbt included."""
    found = identity.runtime_identity()
    for name in DBT_PACKAGES:
        try:
            found[name] = version(name)
        except PackageNotFoundError:  # pragma: no cover - only if uninstalled
            found[name] = "absent"
    return found


def candidate_runtime_fingerprint() -> str:
    """A digest of :func:`candidate_runtime_identity`."""
    return _digest_of(candidate_runtime_identity())
