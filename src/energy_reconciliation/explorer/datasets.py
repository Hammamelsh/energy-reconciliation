"""Which warehouse files exist, what each one is *for*, and what to call it.

The problem this solves
-----------------------

``data/warehouse/`` accumulates files that are not alternatives to one another. Beside the
main sample sit a **replayed baseline** and an **expanded sample**, both created by the
REC-001 runbook to be compared against each other. Labelling every file by its contents
produced three near-identical entries -- *Low Carbon London sample (member 135, member 4,
member 5)* twice over, differing only in a trailing file name -- so the ordinary choice
was buried among artefacts of one past investigation.

So the picker shows the two ordinary choices and puts the comparison artefacts behind a
control that names them for what they are.

How a role is decided, and what is deliberately **not** used
------------------------------------------------------------

A role is assigned only from **explicit configuration** or **corroborating metadata**:

- ``MAIN`` -- the file :data:`ingest.warehouse.DEFAULT_DATABASE` names. That constant is
  the project's own statement of which warehouse is the working one.
- ``DEMO`` -- every household id begins with ``DEMO``. That is a property of the data the
  synthetic archive writes, not a guess.
- ``REC001_BASELINE`` -- the file is named ``rec001-baseline-<baseline id>.duckdb``, the
  name the REC-001 runbook tells you to replay into, **and** a baseline record with that
  id exists in ``data/baselines/``. The second half is what makes it evidence rather than
  a name: a file merely *called* ``rec001-baseline-zzz`` is left unclassified.
- ``REC001_COMPARISON`` -- the file is named ``rec001-comparison-*.duckdb``, again the
  runbook's own name. There is no second record to corroborate it against, so this rests
  on the naming convention alone and says so.
- ``UNCLASSIFIED`` -- everything else, labelled by its **file name**, which is true of any
  file whatever it holds.

**Nothing is inferred from how many source members or households a file contains.** Three
members does not mean "baseline" and four does not mean "comparison": the REC-001 files
happen to have those shapes, and a future warehouse with the same shape would be a
different thing entirely. Counts appear only as *detail*, never as evidence of a role.

Only the two REC-001 roles are hidden behind the control. An unclassified file stays in
the ordinary list: hiding a file this module does not understand would be the worse error.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ..tariff.baseline import BASELINE_DIR
from . import queries as q

MAIN: Final[str] = "main"
DEMO: Final[str] = "demo"
REC001_BASELINE: Final[str] = "rec001-baseline"
REC001_COMPARISON: Final[str] = "rec001-comparison"
UNCLASSIFIED: Final[str] = "unclassified"

#: Roles kept out of the ordinary list. Both are artefacts of one past investigation
#: (`docs/rec-001-source-expansion.md`), useful to open deliberately and misleading to
#: offer beside the main sample.
COMPARISON_ROLES: Final[frozenset[str]] = frozenset(
    {REC001_BASELINE, REC001_COMPARISON}
)

#: The names the REC-001 runbook instructs you to create. Explicit configuration: a file
#: earns the role by being named this way, never by what it happens to contain.
_BASELINE_NAME: Final[re.Pattern[str]] = re.compile(
    r"^rec001-baseline-(?P<baseline_id>[0-9a-f]{6,64})\.duckdb$"
)
_COMPARISON_NAME: Final[re.Pattern[str]] = re.compile(r"^rec001-comparison-.+\.duckdb$")

#: The concise label for each configured role. Ordering here is the ordering shown.
_ROLE_LABELS: Final[dict[str, str]] = {
    MAIN: "Main sample",
    DEMO: "Synthetic demo — invented data",
    REC001_BASELINE: "REC-001 replayed baseline",
    REC001_COMPARISON: "REC-001 expanded sample",
}

_ROLE_NOTES: Final[dict[str, str]] = {
    MAIN: "the working warehouse this project builds and reads by default",
    DEMO: (
        "invented households and an invented schedule, for demonstration. Nothing on any "
        "tab is a measurement of the real trial"
    ),
    REC001_BASELINE: (
        "a baseline replayed into a fresh database by REC-001, kept so the expanded "
        "sample has something to be compared against"
    ),
    REC001_COMPARISON: (
        "the same sample with an additional source member loaded, built by REC-001 to "
        "measure what the extra member changed"
    ),
    UNCLASSIFIED: (
        "no role is recorded for this file, so it is named by its file name and nothing "
        "more is claimed about it"
    ),
}

#: Order the picker lists roles in. Unclassified files come after the two ordinary
#: choices, comparisons last.
_ORDER: Final[tuple[str, ...]] = (
    MAIN,
    DEMO,
    UNCLASSIFIED,
    REC001_BASELINE,
    REC001_COMPARISON,
)


@dataclass(frozen=True, slots=True)
class Dataset:
    """One warehouse file, its role, and the detail behind its label."""

    path: Path
    role: str
    label: str
    households: int
    members: tuple[str, ...]

    @property
    def is_comparison(self) -> bool:
        return self.role in COMPARISON_ROLES

    @property
    def note(self) -> str:
        return _ROLE_NOTES[self.role]

    @property
    def detail(self) -> str:
        """Secondary detail: the exact file, its source members and household count."""
        members = (
            ", ".join(
                m.replace("LCL-June2015v2_", "member ").replace(".csv", "")
                for m in self.members
            )
            or "no published source file"
        )
        return (
            f"`{self.path.name}` · {len(self.members)} source "
            f"file{'' if len(self.members) == 1 else 's'} ({members}) · "
            f"{self.households:,} household{'' if self.households == 1 else 's'}"
        )


def _baseline_exists(baseline_id: str, baselines_dir: Path) -> bool:
    """Is there a captured baseline with this id? What turns a name into evidence."""
    return any(baselines_dir.glob(f"{baseline_id}@*.json"))


def role_of(
    path: Path,
    *,
    all_demo: bool,
    default: Path | None = None,
    baselines_dir: Path = BASELINE_DIR,
) -> str:
    """The role of one file, from configuration and corroborating metadata only."""
    if default is not None and path.resolve() == Path(default).resolve():
        return MAIN
    if all_demo:
        return DEMO
    match = _BASELINE_NAME.match(path.name)
    if match and _baseline_exists(match.group("baseline_id"), baselines_dir):
        return REC001_BASELINE
    if _COMPARISON_NAME.match(path.name):
        return REC001_COMPARISON
    return UNCLASSIFIED


def catalogue(
    paths: list[Path],
    *,
    default: Path | None = None,
    baselines_dir: Path = BASELINE_DIR,
) -> list[Dataset]:
    """Every file, described and ordered. One read of each file, once per render."""
    found: list[Dataset] = []
    for path in paths:
        summary = q.dataset_summary(path)
        role = role_of(
            path,
            all_demo=summary.all_demo,
            default=default,
            baselines_dir=baselines_dir,
        )
        found.append(
            Dataset(
                path=path,
                role=role,
                label=_ROLE_LABELS.get(role, path.stem),
                households=summary.households,
                members=summary.members,
            )
        )
    return sorted(found, key=lambda d: (_ORDER.index(d.role), d.path.name))


def display_labels(entries: list[Dataset]) -> dict[Path, str]:
    """Label per path, with the file name appended only where a label would repeat.

    Two files can earn the same label -- two unclassified files, or two comparison files
    built by the same runbook. Identical entries in a picker are ambiguous to select, so
    the file name settles it, and only then.
    """
    seen = Counter(entry.label for entry in entries)
    return {
        entry.path: (
            f"{entry.label} — {entry.path.name}"
            if seen[entry.label] > 1
            else entry.label
        )
        for entry in entries
    }
