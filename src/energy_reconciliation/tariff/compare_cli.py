"""Explain the difference between two scenario warehouses that differ only in source.

uv run compare-scenarios --baseline-db <replayed>.duckdb --comparison-db <plus136>.duckdb
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .compare import ComparisonError, compare_scenarios, summarise, write_report

REPORT_DIR = Path("data/comparisons")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="compare-scenarios", description=__doc__)
    p.add_argument("--baseline-db", type=Path, required=True)
    p.add_argument("--comparison-db", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, default=REPORT_DIR)
    args = p.parse_args(argv)
    for path in (args.baseline_db, args.comparison_db):
        if not path.exists():
            print(f"error: not found: {path}", file=sys.stderr)
            return 2
    try:
        report = compare_scenarios(args.baseline_db, args.comparison_db)
    except ComparisonError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    json_path, md_path = write_report(report, args.output_dir)
    print(summarise(report))
    print(f"json : {json_path}\nmd   : {md_path}")
    return 0 if report["reconciliation"]["residual_is_zero"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
