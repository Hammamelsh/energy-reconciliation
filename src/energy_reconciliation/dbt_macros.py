"""Render the dbt macros from the authoritative policy definition.

**Why generate rather than write Jinja by hand.** The four analytical policies have one
definition, :mod:`energy_reconciliation.policy`. dbt needs the same SQL, and a second
hand-maintained copy in Jinja would be the "same rule written twice in two languages"
that ANL-003 exists to avoid. So the macro file is *generated* from the Python
definition, committed (dbt has to find it on disk), and guarded by a drift check.

**The check never regenerates.** ``render-dbt-macros --check`` and the test suite compare
the committed bytes against a fresh render and *fail* on a difference. A check that
silently rewrote the file would report success for a repository that had just been
changed underneath the reader, which is the opposite of a guard.

**Deterministic by construction.** The output is a pure function of ``policy.py``: no
timestamp, no path, no digest, no environment. Rendering twice on two machines gives the
same bytes, which is what makes the drift check meaningful.

**Not a calculation file.** This module writes a macro; it does not evaluate one. It is
deliberately outside :mod:`energy_reconciliation.tariff.identity`'s digest, for the same
reason the reporting and replay modules are: over-inclusion makes the invalidation signal
noisy. The *rendered macro* comes under that digest when dbt first produces a stored
figure (design D6, ticket step 5) -- not while it produces none.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Final

from .policy import (
    DBT_RELATION_PLACEHOLDER,
    conflicting_labels_sql,
    distinct_readings_sql,
)

#: Where the rendered macros are committed, relative to the repository root.
MACRO_PATH: Final[Path] = Path("dbt/macros/generated_policy.sql")

#: The command that regenerates the file. Named in the file itself, so whoever opens it
#: and wonders why their edit was reverted is told what to run instead.
REGENERATE_COMMAND: Final[str] = "uv run render-dbt-macros"

_HEADER: Final[str] = f"""\
{{#
  GENERATED FILE -- DO NOT EDIT.

  Rendered from src/energy_reconciliation/policy.py, which is the single definition of
  this project's analytical policies. To change a rule, edit that module and run:

      {REGENERATE_COMMAND}

  `uv run render-dbt-macros --check` and tests/test_dbt_macros.py fail if this file and
  policy.py disagree. Neither of them rewrites the file.

  The `readings` argument is the relation to read: pass `ref('stg_readings')` or any
  other dbt relation. The SQL body is otherwise fixed by policy.py.
#}}
"""


def _macro(name: str, body: str) -> str:
    """One macro taking the relation to read. Body indented, so the file is readable."""
    indented = "\n".join(
        f"    {line}" if line else "" for line in body.strip("\n").splitlines()
    )
    return f"{{% macro {name}(readings) %}}\n{indented}\n{{% endmacro %}}\n"


def render() -> str:
    """The exact bytes ``dbt/macros/generated_policy.sql`` must contain."""
    placeholder = DBT_RELATION_PLACEHOLDER
    return (
        _HEADER
        + "\n"
        + _macro("distinct_readings", distinct_readings_sql(placeholder))
        + "\n"
        + _macro("conflicting_labels", conflicting_labels_sql(placeholder))
    )


def repository_root() -> Path:
    """The repository root, from this file's location. No search, no cwd dependence."""
    return Path(__file__).resolve().parent.parent.parent


def macro_file(root: Path | None = None) -> Path:
    return (root or repository_root()) / MACRO_PATH


def drift(root: Path | None = None) -> str | None:
    """``None`` when the committed file matches a fresh render, else why it does not."""
    path = macro_file(root)
    if not path.is_file():
        return f"{MACRO_PATH} does not exist; run `{REGENERATE_COMMAND}`"
    current = path.read_text()
    expected = render()
    if current == expected:
        return None
    return (
        f"{MACRO_PATH} does not match a fresh render of policy.py "
        f"({len(current)} bytes on disk, {len(expected)} rendered). "
        f"Run `{REGENERATE_COMMAND}` if policy.py is the change you intended; "
        "otherwise revert the macro file -- it is generated, not source."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="render-dbt-macros",
        description="Render dbt/macros/generated_policy.sql from policy.py.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed file matches; never write it",
    )
    args = parser.parse_args(argv)

    path = macro_file()
    if args.check:
        problem = drift()
        if problem:
            print(f"drift: {problem}", file=sys.stderr)
            return 1
        print(f"{MACRO_PATH} matches policy.py")
        return 0

    path.parent.mkdir(parents=True, exist_ok=True)
    text = render()
    unchanged = path.is_file() and path.read_text() == text
    path.write_text(text)
    print(f"{'unchanged' if unchanged else 'written'}: {MACRO_PATH}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
