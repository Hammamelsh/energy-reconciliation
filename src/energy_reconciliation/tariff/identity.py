"""What a scenario result depends on, named explicitly.

A result is only reproducible if everything that can change it is identified. Three
things are identified here:

1. **Calculation code** -- every first-party Python file whose bytes can change a stored
   figure, listed one by one. A package-local hash is *not* enough: the tariff models
   import ``policy.py`` from the parent package and the loader's rules from
   ``ingest``/``profiling``, and a hash of ``tariff/*.py`` alone would miss a changed
   policy rule entirely. :func:`calculation_files` names every file; the coverage guard
   in the tests compares that list against the **real import closure** of the models,
   taken in a fresh interpreter, so a new first-party import cannot slip past silently.
2. **Runtime** -- the Python and library versions that evaluated the arithmetic. A
   different decimal engine is a different calculation, even with identical source.
3. **Configuration and data** -- the price catalogue version, the schedule contents, the
   assumption identifier and the set of published loads. Those live in
   :mod:`energy_reconciliation.tariff.models`, which composes them with the digests here.

Scope limits, stated rather than implied: these digests cover **source bytes and library
versions**. They do not cover the operating system, the CPU, locale, or the DuckDB build
flags. Two runs agreeing on every digest here can still, in principle, differ.
"""

from __future__ import annotations

import hashlib
import platform
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Final

PACKAGE_ROOT: Final[Path] = Path(__file__).resolve().parent.parent

#: Directories whose ``*.py`` files can change a stored scenario figure. ``ingest`` and
#: ``profiling`` are taken whole, deliberately: they define how a source row becomes a
#: stored reading, and the ingestion fingerprint already treats them as one unit.
CALCULATION_DIRECTORIES: Final[tuple[str, ...]] = ("ingest", "profiling")

#: Files at the package root that can change a stored scenario figure.
CALCULATION_ROOT_FILES: Final[tuple[str, ...]] = ("__init__.py", "policy.py")

#: Files in the tariff package that can change a **stored** figure, named one by one.
#:
#: The tariff package also holds code that reads results back -- ``analytics.py``
#: (display rounding and shares), ``cli.py``, ``baseline.py``, ``baseline_cli.py``. None
#: of those can change a value in ``fact_interval_charge_scenario``, so none of them is
#: here. That distinction was not free: an earlier version globbed ``tariff/*.py``, and
#: adding the replay tooling changed the fingerprint of a scenario whose every figure
#: was identical -- a false invalidation that would make the mechanism noisy enough to
#: be ignored. Over-inclusion is not the safe direction when the cost is that nobody
#: trusts the signal.
#:
#: Under-inclusion is caught rather than trusted: ``tests/test_tariff_identity.py``
#: takes the **real import closure of the models in a fresh interpreter** and fails if
#: anything in it is missing from this list.
CALCULATION_TARIFF_FILES: Final[tuple[str, ...]] = (
    "__init__.py",
    "identity.py",
    "models.py",
    "prices.py",
    "schedule.py",
)

#: Libraries whose version is recorded with every run.
RUNTIME_PACKAGES: Final[tuple[str, ...]] = ("duckdb", "pyarrow", "pandas", "openpyxl")


def calculation_files() -> list[Path]:
    """Every first-party file whose content participates in invalidation, sorted."""
    files = [PACKAGE_ROOT / name for name in CALCULATION_ROOT_FILES]
    files += [PACKAGE_ROOT / "tariff" / name for name in CALCULATION_TARIFF_FILES]
    for directory in CALCULATION_DIRECTORIES:
        files.extend((PACKAGE_ROOT / directory).glob("*.py"))
    return sorted({f.resolve() for f in files if f.is_file()})


def file_digests() -> dict[str, str]:
    """Package-relative path → SHA-256 of its bytes. The unit of invalidation."""
    return {
        str(path.relative_to(PACKAGE_ROOT)): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in calculation_files()
    }


def _digest_of(mapping: dict[str, str]) -> str:
    h = hashlib.sha256()
    for key in sorted(mapping):
        h.update(key.encode())
        h.update(b"\0")
        h.update(mapping[key].encode())
        h.update(b"\n")
    return h.hexdigest()


def calculation_digest() -> str:
    """One digest over every calculation file. Renaming a file changes it too."""
    return _digest_of(file_digests())


def policy_digest() -> str:
    """The shared policy module on its own, so a policy change is visible by itself."""
    return hashlib.sha256((PACKAGE_ROOT / "policy.py").read_bytes()).hexdigest()


def model_digest() -> str:
    """The tariff modelling files on their own, separate from the shared policy."""
    return _digest_of(
        {
            f"tariff/{name}": hashlib.sha256(
                (PACKAGE_ROOT / "tariff" / name).read_bytes()
            ).hexdigest()
            for name in CALCULATION_TARIFF_FILES
        }
    )


def runtime_identity() -> dict[str, str]:
    """Python and library versions that evaluated the arithmetic."""
    identity = {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
    }
    for name in RUNTIME_PACKAGES:
        try:
            identity[name] = version(name)
        except PackageNotFoundError:  # pragma: no cover - only if uninstalled
            identity[name] = "absent"
    return identity


def runtime_fingerprint() -> str:
    """A digest of :func:`runtime_identity`.

    Folded into the scenario fingerprint on purpose. It makes the fingerprint
    machine-specific -- two machines on different DuckDB patch versions produce
    different run ids for identical source -- and that is the honest behaviour: a
    result produced by a different arithmetic engine has not been shown to be the same
    result. The versions are also recorded in full, so a difference can be explained
    rather than merely detected.
    """
    return _digest_of(runtime_identity())


def import_closure() -> dict[str, str]:
    """First-party modules currently imported → their package-relative paths.

    Called from a **fresh interpreter that has imported only the tariff models**, this
    is the true set of first-party files the calculation depends on. The test suite
    compares it against :func:`calculation_files` so that adding an import of a module
    outside the covered directories fails a test instead of silently escaping
    invalidation.
    """
    found: dict[str, str] = {}
    for name, module in list(sys.modules.items()):
        if not name.startswith("energy_reconciliation"):
            continue
        origin = getattr(module, "__file__", None)
        if not origin:
            continue
        path = Path(origin).resolve()
        try:
            found[name] = str(path.relative_to(PACKAGE_ROOT))
        except ValueError:  # pragma: no cover - a module outside the package tree
            found[name] = str(path)
    return found
