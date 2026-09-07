"""Run the profile over one member and assemble a machine-readable report.

The report is metadata about the source, never a copy of it. Row-level examples
carry record numbers only; any full row text is written to a separate examples
file that lives in a git-ignored location.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path

from . import validation as v
from .aggregate import RecordStore, record_store
from .reader import (
    DEFAULT_ARCHIVE,
    DEFAULT_MEMBER,
    ReadOutcome,
    member_identity,
    stream_records,
)

PROFILER_NAME = "energy_reconciliation.profiling"
PROFILER_VERSION = "1.0.0"
REPORT_SCHEMA_VERSION = 1
MAX_EXAMPLES_PER_CATEGORY = 5
MAX_EXTREME_EXAMPLES = 5
#: Percentiles reported for the consumption distribution: enough to describe the bulk
#: of the data and both tails without inventing values between observations.
REPORTED_PERCENTILES: tuple[int, ...] = (1, 5, 25, 50, 75, 90, 95, 99)
#: Decimal places for the reported mean, which is a ratio of two exact integers and
#: may not terminate.
MEAN_DECIMAL_PLACES = 9


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], capture_output=True, text=True, timeout=10, check=False
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def hash_python_sources(directory: Path) -> tuple[str, list[str]]:
    """Hash every ``*.py`` file in ``directory``; return the digest and the file names.

    Each file contributes its name and then its bytes, in sorted order, so a rename
    changes the digest as surely as an edit does. The names are returned separately
    so a report can state exactly which files the fingerprint covers.
    """
    h = hashlib.sha256()
    names: list[str] = []
    for path in sorted(directory.glob("*.py")):
        names.append(path.name)
        h.update(path.name.encode())
        h.update(path.read_bytes())
    return h.hexdigest(), names


def code_identity() -> dict[str, object]:
    """Identify the code that produced a report.

    A git commit is NOT sufficient on its own. When the working tree is dirty the
    commit describes the last saved state, not the code that actually ran, and every
    dirty run at that commit shares one commit id while the code may differ.
    ``package_source_sha256`` is therefore the authoritative fingerprint: it is
    computed from the bytes of the files listed in ``source_files``.
    """
    digest, names = hash_python_sources(Path(__file__).parent)
    dirty = bool(_git("status", "--porcelain"))
    return {
        "profiler_name": PROFILER_NAME,
        "profiler_version": PROFILER_VERSION,
        "authoritative_code_fingerprint": "package_source_sha256",
        "package_source_sha256": digest,
        "source_files": names,
        "source_file_count": len(names),
        "source_files_scope": (
            "src/energy_reconciliation/profiling/*.py only. Tests, pyproject.toml and "
            "dependency versions are NOT covered by this digest."
        ),
        "git_commit": _git("rev-parse", "HEAD"),
        "git_tree_dirty": dirty,
        "git_identity_sufficient": not dirty,
        "identity_note": (
            "git_commit identifies the code ONLY when git_tree_dirty is false. With a "
            "dirty tree the commit is not a unique identifier of what ran; compare "
            "package_source_sha256 instead. Reproducing a dirty-tree run needs the same "
            "source bytes, not merely the same commit."
        ),
    }


def _distribution(
    store: RecordStore,
    count: int,
    total: Decimal,
    minimum: Decimal | None,
    maximum: Decimal | None,
) -> dict[str, object]:
    """Describe the spread of finite consumption values.

    Count, minimum, maximum and sum are accumulated exactly with ``Decimal`` while
    streaming, so they cost no memory and carry no binary floating-point error. The
    mean is derived from those exact figures and is the only rounded number here.

    Percentiles use the **nearest-rank** method: the reported figure is an actually
    observed value at a computed rank, never an interpolation between two
    observations, so every number reported is a real measurement.
    """
    stored = store.finite_count()
    if count == 0 or minimum is None or maximum is None:
        return {
            "finite_value_count": 0,
            "finite_value_count_cross_check": stored,
            "counts_agree": count == stored,
            "note": "no finite consumption values were observed",
        }

    mean = (total / Decimal(count)).quantize(
        Decimal(1).scaleb(-MEAN_DECIMAL_PLACES), rounding=ROUND_HALF_EVEN
    )
    percentiles: dict[str, object] = {}
    for pct in REPORTED_PERCENTILES:
        rank = max(1, -(-pct * count // 100))  # ceil(pct/100 * count)
        hit = store.value_at_rank(rank)
        if hit is not None:
            percentiles[f"p{pct}"] = {
                "value_text": hit[0],
                "rank": rank,
                "record_no": hit[1],
            }

    def _num(key: str) -> Decimal | None:
        item = percentiles.get(key)
        return Decimal(item["value_text"].strip()) if item else None

    p25, p75 = _num("p25"), _num("p75")
    return {
        "finite_value_count": count,
        "finite_value_count_cross_check": stored,
        "counts_agree": count == stored,
        "minimum": str(minimum),
        "maximum": str(maximum),
        "range": str(maximum - minimum),
        "sum": str(total),
        "mean": str(mean),
        "percentiles_nearest_rank": percentiles,
        "interquartile_range": (
            str(p75 - p25) if p25 is not None and p75 is not None else None
        ),
        "exactness": {
            "finite_value_count": "EXACT - counted while streaming",
            "minimum": "EXACT - Decimal comparison; the original value is reported",
            "maximum": "EXACT - Decimal comparison; the original value is reported",
            "sum": "EXACT - Decimal addition, no floating point",
            "mean": (
                "DERIVED from an exact sum and an exact count, then rounded to "
                f"{MEAN_DECIMAL_PLACES} decimal places (ROUND_HALF_EVEN). The exact "
                "ratio may not terminate, so this is the only rounded figure here."
            ),
            "percentiles": (
                "EXACT SELECTION by nearest rank of an actually observed value; no "
                "interpolation, so no value is invented. Ordering is performed on "
                "IEEE-754 doubles, which represent these magnitudes and precisions "
                "exactly - a property of this data, not a guarantee of the method."
            ),
            "no_standard_deviation": (
                "Deliberately omitted: it would require either a second pass or "
                "floating-point accumulation. Percentiles describe the spread without "
                "either cost."
            ),
        },
    }


def _equation(name: str, lhs_expr: str, lhs: int, rhs_expr: str, rhs: int) -> dict:
    return {
        "name": name,
        "expression": f"{lhs_expr} == {rhs_expr}",
        "left": lhs,
        "right": rhs,
        "holds": lhs == rhs,
    }


def profile_member(
    archive: Path = DEFAULT_ARCHIVE,
    member: str = DEFAULT_MEMBER,
    work_dir: Path | None = None,
) -> tuple[dict, list[dict]]:
    """Stream one member end to end. Returns ``(report, row_level_examples)``."""
    started = time.time()
    identity = member_identity(archive, member)
    outcome = ReadOutcome()

    consumption = Counter()
    zeros = negatives = padded_values = 0
    # Exact, streaming, O(1) memory. No float appears in these accumulators.
    finite_count = 0
    finite_sum = Decimal(0)
    finite_min: Decimal | None = None
    finite_max: Decimal | None = None
    ts_valid = ts_invalid = on_grid = off_grid = 0
    malformed = 0
    field_counts = Counter()
    records_ok = 0
    examples: dict[str, list[dict]] = {}
    row_examples: list[dict] = []

    def remember(category: str, n: int, row: list[str]) -> None:
        bucket = examples.setdefault(category, [])
        if len(bucket) < MAX_EXAMPLES_PER_CATEGORY:
            bucket.append({"record_no": n, "field_count": len(row)})
            row_examples.append(
                {"category": category, "record_no": n, "fields": list(row)}
            )

    tmp_ctx = (
        tempfile.TemporaryDirectory(dir=work_dir)
        if work_dir
        else tempfile.TemporaryDirectory()
    )
    with tmp_ctx as tmp, record_store(Path(tmp) / "records.db") as store:
        for n, row in stream_records(archive, member, outcome):
            if len(row) != v.EXPECTED_FIELD_COUNT:
                malformed += 1
                field_counts[len(row)] += 1
                remember("malformed_field_count", n, row)
                continue

            lclid, tariff, ts_raw, val_raw = row
            cons = v.classify_consumption(val_raw)
            stamp = v.classify_timestamp(ts_raw)

            consumption[cons.category] += 1
            if cons.category == v.FINITE_NUMERIC and cons.value is not None:
                finite_count += 1
                finite_sum += cons.value
                if finite_min is None or cons.value < finite_min:
                    finite_min = cons.value
                if finite_max is None or cons.value > finite_max:
                    finite_max = cons.value
            if cons.is_zero:
                zeros += 1
            if cons.is_negative:
                negatives += 1
                remember("negative_value", n, row)
            if cons.had_surrounding_whitespace:
                padded_values += 1
            if cons.category in (v.UNEXPECTED_TOKEN, v.NON_FINITE_NUMERIC):
                remember(cons.category, n, row)
            elif cons.category == v.EMPTY:
                remember("empty_value", n, row)
            elif cons.category == v.NULL_TOKEN_CATEGORY:
                remember("null_token", n, row)

            if stamp.valid:
                ts_valid += 1
                if stamp.on_grid:
                    on_grid += 1
                else:
                    off_grid += 1
                    remember("off_grid_timestamp", n, row)
            else:
                ts_invalid += 1
                remember("invalid_timestamp", n, row)

            if cons.category == v.FINITE_NUMERIC and stamp.valid:
                records_ok += 1

            store.add(
                n,
                lclid,
                tariff,
                ts_raw,
                val_raw,
                v.normalised_value_key(cons),
                float(cons.value) if cons.value is not None else None,
            )

        store.finalise()
        exact_dup = store.exact_duplicate_stats()
        key_dup = store.key_collision_stats()
        households = [asdict(h) for h in store.households()]
        tariffs = store.tariff_values()
        ts_min, ts_max = store.timestamp_range()
        dup_key_examples = store.duplicate_key_examples()
        conflict_examples = store.conflicting_examples()
        distribution = _distribution(
            store, finite_count, finite_sum, finite_min, finite_max
        )
        smallest = store.extreme_values(MAX_EXTREME_EXAMPLES, largest=False)
        largest = store.extreme_values(MAX_EXTREME_EXAMPLES, largest=True)
        for label, group in (("smallest_value", smallest), ("largest_value", largest)):
            row_examples.extend(
                {
                    "category": label,
                    "record_no": item["record_no"],
                    "fields": [
                        item["lclid"],
                        "",
                        item["timestamp_text"],
                        item["value_text"],
                    ],
                }
                for item in group
            )

    data_records = outcome.records_read
    structurally_valid = data_records - malformed
    issues = structurally_valid - records_ok
    tally = outcome.tally

    header_check = v.check_header(outcome.header)
    lines_match = tally.physical_lines == data_records + 1  # +1 for the header line

    core_partitions = [
        _equation(
            "structure_partition",
            "data_records",
            data_records,
            "structurally_valid + malformed",
            structurally_valid + malformed,
        ),
        _equation(
            "consumption_partition",
            "structurally_valid",
            structurally_valid,
            " + ".join(v.CONSUMPTION_CATEGORIES),
            sum(consumption[c] for c in v.CONSUMPTION_CATEGORIES),
        ),
        _equation(
            "timestamp_partition",
            "structurally_valid",
            structurally_valid,
            "timestamp_valid + timestamp_invalid",
            ts_valid + ts_invalid,
        ),
        _equation(
            "grid_partition",
            "timestamp_valid",
            ts_valid,
            "on_grid + off_grid",
            on_grid + off_grid,
        ),
        _equation(
            "outcome_partition",
            "structurally_valid",
            structurally_valid,
            "records_ok + records_with_issues",
            records_ok + issues,
        ),
    ]

    # A property of THIS file's physical shape, not a correctness requirement. A quoted
    # field may legally contain a newline, in which case physical lines and logical
    # records differ and this check does not hold -- while every partition above still
    # must. Keeping it separate stops legal CSV being reported as a reconciliation
    # failure.
    source_shape_checks = [
        _equation(
            "ticket_raw_line_equation",
            "physical_lines",
            tally.physical_lines,
            "header_lines + logical_records",
            1 + data_records,
        ),
    ]

    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "status": "COMPLETE" if outcome.complete else "INCOMPLETE",
        "incomplete_reason": outcome.failure,
        "code_identity": code_identity(),
        "invocation": {
            "argv": sys.argv,
            "archive": str(archive),
            "member": member,
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "started_at_utc": datetime.fromtimestamp(started, UTC).isoformat(),
            "finished_at_utc": datetime.now(UTC).isoformat(),
            "duration_seconds": round(time.time() - started, 3),
        },
        "source": asdict(identity) | {"member_content_sha256": tally.sha256},
        "encoding_evidence": {
            "decoded_as": "ascii",
            "non_ascii_bytes_in_member": tally.non_ascii_bytes,
            "note": (
                "Zero non-ASCII bytes means the member is ASCII-compatible; it does not "
                "distinguish UTF-8 from Latin-1 or Windows-1252, which agree on ASCII."
            ),
        },
        "header": header_check,
        "lines_vs_records": {
            "physical_lines": tally.physical_lines,
            "lf_terminators": tally.lf_count,
            "crlf_terminators": tally.crlf_count,
            "lone_cr": tally.lone_cr_count,
            "ends_with_newline": tally.ends_with_newline,
            "logical_records_excluding_header": data_records,
            "one_line_per_record_holds": lines_match,
            "note": (
                "A quoted CSV field may contain a newline, so one physical line does not "
                "universally equal one record. Both are measured independently here."
            ),
        },
        "counts": {
            "data_records_excluding_header": data_records,
            "structurally_valid_records": structurally_valid,
            "malformed_records": malformed,
            "malformed_field_count_distribution": {
                str(k): c for k, c in sorted(field_counts.items())
            },  # str keys so the in-memory report matches its JSON form exactly
            "records_ok": records_ok,
            "records_with_issues": issues,
        },
        "consumption": {
            "categories_mutually_exclusive": {
                c: consumption[c] for c in v.CONSUMPTION_CATEGORIES
            },
            "diagnostics_overlapping": {
                "zeros": zeros,
                "negatives": negatives,
                "space_padded_raw_values": padded_values,
            },
            "distribution": distribution,
            "extreme_values": {
                "smallest": [
                    {"value_text": e["value_text"], "record_no": e["record_no"]}
                    for e in smallest
                ],
                "largest": [
                    {"value_text": e["value_text"], "record_no": e["record_no"]}
                    for e in largest
                ],
                "note": (
                    f"Bounded to {MAX_EXTREME_EXAMPLES} each. The household id and "
                    "timestamp for these records go to the git-ignored examples file, "
                    "not here."
                ),
            },
            "note": (
                "zeros and negatives are SUBSETS of finite_numeric and are not additional "
                "categories. They must not be added to the partition above."
            ),
        },
        "timestamps": {
            "valid_format": ts_valid,
            "invalid_format": ts_invalid,
            "on_grid": on_grid,
            "off_grid": off_grid,
            "min_text_in_member": ts_min,
            "max_text_in_member": ts_max,
            "note": (
                "Timestamp text is preserved exactly. No timezone is assigned and no "
                "conversion is performed; the source convention is UNKNOWN."
            ),
        },
        "households": {
            "distinct_in_member": len(households),
            "tariff_group_values": tariffs,
            "observations": households,
            "note": (
                "Ranges are first/last OBSERVED IN THIS MEMBER. Households are known to "
                "span member boundaries, so this is not a completeness claim."
            ),
        },
        "duplicates": {
            "exact_source_row_equality": exact_dup,
            "candidate_key_collisions": key_dup,
            "equality_rules": {
                "exact_source_row": "all four raw field strings identical, whitespace included",
                "candidate_key": "(LCLid, raw DateTime text)",
                "conflicting": "candidate key repeats AND normalised value or tariff differs",
                "normalised_value": "finite numbers compare numerically; all else by exact text",
            },
            "examples_candidate_keys": dup_key_examples,
            "examples_conflicting": conflict_examples,
            "note": (
                "Scoped to this member only; says nothing about archive-wide uniqueness. "
                "A repeated naive timestamp is a candidate key collision whose physical "
                "meaning is unresolved while the timezone convention is UNKNOWN. "
                "Duplicates cut across every category above: a duplicate row may be valid."
            ),
        },
        "counter_semantics": {
            "mutually_exclusive_partitions": {
                "structure": ["structurally_valid_records", "malformed_records"],
                "consumption": list(v.CONSUMPTION_CATEGORIES),
                "timestamp_format": ["valid_format", "invalid_format"],
                "timestamp_grid": ["on_grid", "off_grid"],
                "outcome": ["records_ok", "records_with_issues"],
            },
            "overlapping_diagnostics": {
                "zeros": "subset of consumption.finite_numeric",
                "negatives": "subset of consumption.finite_numeric",
                "space_padded_raw_values": "subset of structurally_valid_records",
                "off_grid": "subset of timestamps.valid_format",
                "duplicates": (
                    "cuts across every partition; a duplicated row may be a perfectly "
                    "valid record and is counted inside records_ok"
                ),
            },
            "note": (
                "Only the partitions may be summed. Adding any overlapping diagnostic "
                "to a partition double-counts rows."
            ),
        },
        "reconciliation": {
            "core_partitions": core_partitions,
            "all_core_partitions_hold": all(e["holds"] for e in core_partitions),
            "source_shape_checks": source_shape_checks,
            "all_source_shape_checks_hold": all(
                e["holds"] for e in source_shape_checks
            ),
            "note": (
                "all_core_partitions_hold is the correctness signal. Source shape checks "
                "describe this file's physical layout: a quoted field containing a "
                "newline makes physical lines differ from logical records, which is "
                "legal CSV and not a reconciliation failure."
            ),
        },
        "examples_by_category": examples,
    }
    return report, row_examples


def write_json_atomically(path: Path, payload: dict) -> None:
    """Write via a temp file in the same directory, then rename.

    A crashed or killed run must never leave a truncated file that looks like a
    finished report.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        # mkstemp creates 0600; a report meant to be read and committed should be 0644.
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
