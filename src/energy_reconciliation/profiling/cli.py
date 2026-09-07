"""Command-line entry point for the one-member profiler."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .reader import DEFAULT_ARCHIVE, DEFAULT_MEMBER
from .report import profile_member, write_json_atomically

DEFAULT_OUTPUT = Path("data/profiles/lcl-june2015v2-0-profile.json")
DEFAULT_EXAMPLES = Path("data/sample/lcl-june2015v2-0-profile-examples.json")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="profile-member",
        description=(
            "Stream one CSV member from the Low Carbon London partitioned archive and "
            "write a machine-readable profile. The archive is never extracted or modified."
        ),
    )
    p.add_argument(
        "--archive",
        type=Path,
        default=DEFAULT_ARCHIVE,
        help=f"path to the zip archive (default: {DEFAULT_ARCHIVE})",
    )
    p.add_argument(
        "--member",
        default=DEFAULT_MEMBER,
        help=f"member to profile (default: {DEFAULT_MEMBER})",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"JSON report path (default: {DEFAULT_OUTPUT})",
    )
    p.add_argument(
        "--examples-output",
        type=Path,
        default=DEFAULT_EXAMPLES,
        help=(
            "where row-level diagnostic examples go; this file contains source "
            f"rows and must stay git-ignored (default: {DEFAULT_EXAMPLES})"
        ),
    )
    p.add_argument(
        "--no-examples",
        action="store_true",
        help="skip writing the row-level examples file",
    )
    p.add_argument(
        "--work-dir",
        type=Path,
        default=None,
        help="directory for the temporary SQLite database (default: system temp)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.archive.exists():
        print(f"error: archive not found: {args.archive}", file=sys.stderr)
        return 2

    report, row_examples = profile_member(
        args.archive, args.member, args.work_dir, output=args.output
    )
    write_json_atomically(args.output, report)

    if not args.no_examples and row_examples:
        write_json_atomically(
            args.examples_output,
            {
                "warning": "CONTAINS SOURCE ROWS - keep this path git-ignored.",
                "archive": str(args.archive),
                "member": args.member,
                "examples": row_examples,
            },
        )

    counts = report["counts"]
    recon = report["reconciliation"]
    shape_ok = recon["all_source_shape_checks_hold"]
    print(f"status                : {report['status']}")
    print(f"member                : {args.member}")
    print(f"data records          : {counts['data_records_excluding_header']:,}")
    print(f"structurally valid    : {counts['structurally_valid_records']:,}")
    print(f"malformed             : {counts['malformed_records']:,}")
    print(f"records ok            : {counts['records_ok']:,}")
    print(f"records with issues   : {counts['records_with_issues']:,}")
    print(f"header matches        : {report['header']['matches']}")
    print(f"core partitions hold  : {recon['all_core_partitions_hold']}")
    print(f"one line per record   : {shape_ok}")
    print(f"report written        : {args.output}")

    if not shape_ok:
        # Legal CSV, not an error: a quoted field contains a newline.
        print(
            "note: physical lines differ from logical records for this member; "
            "the logical partitions still reconcile."
        )

    failed = [e["name"] for e in recon["core_partitions"] if not e["holds"]]
    if failed:
        print(f"RECONCILIATION FAILED : {', '.join(failed)}", file=sys.stderr)
    if report["status"] != "COMPLETE":
        print(f"INCOMPLETE            : {report['incomplete_reason']}", file=sys.stderr)
        return 1
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
