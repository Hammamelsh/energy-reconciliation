"""Command-line entry point for loading a member into the warehouse."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..profiling.reader import DEFAULT_ARCHIVE
from .loader import load_member
from .warehouse import DEFAULT_DATABASE

DEMO_ARCHIVE = Path("data/demo/demo-lcl-sample.zip")
DEMO_MEMBER = "Small LCL Data/DEMO-sample_0.csv"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ingest-member",
        description=(
            "Load one archive member into the local DuckDB warehouse. Re-running an "
            "unchanged member is a no-op; changed content replaces that member's rows."
        ),
    )
    p.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    p.add_argument(
        "--member",
        action="append",
        dest="members",
        default=None,
        help="member to load; repeat to load several",
    )
    p.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    p.add_argument(
        "--demo",
        action="store_true",
        help="load the committed synthetic demo archive instead",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    archive = DEMO_ARCHIVE if args.demo else args.archive
    members = [DEMO_MEMBER] if args.demo else args.members

    if not members:
        print("error: give at least one --member, or use --demo", file=sys.stderr)
        return 2
    if not archive.exists():
        print(f"error: archive not found: {archive}", file=sys.stderr)
        return 2

    failures = 0
    for member in members:
        result = load_member(archive, member, args.database)
        if not result.complete:
            print(f"FAILED   {member}: {result.failure}", file=sys.stderr)
            failures += 1
            continue
        if result.skipped:
            print(
                f"skipped  {member}: identical content already loaded "
                f"({result.records_read:,} records, no rows changed)"
            )
            continue
        action = "replaced" if result.replaced_previous else "loaded  "
        print(
            f"{action} {member}: {result.records_published:,} readings, "
            f"{result.records_rejected:,} rejected"
        )
        if result.reject_reasons:
            for reason, count in sorted(result.reject_reasons.items()):
                print(f"           rejected {count:,} for {reason}")
    print(f"database : {args.database}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
