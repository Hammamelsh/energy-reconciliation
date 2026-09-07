"""The committed demo archive, and the counts it must produce.

Every expected number here was worked out by hand from `demo_fixture.RECORDS`
before the profiler was run over it. If the profiler changes behaviour, these
fail rather than silently agreeing with whatever it now does.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path

import pytest
from demo_fixture import DEMO_ARCHIVE, DEMO_MEMBER, RECORDS, archive_bytes, csv_bytes

from energy_reconciliation.profiling.cli import main
from energy_reconciliation.profiling.report import profile_member

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMITTED = REPO_ROOT / DEMO_ARCHIVE


@pytest.fixture(scope="module")
def demo_report() -> dict:
    report, _ = profile_member(COMMITTED, DEMO_MEMBER)
    return report


# -- the committed artefact ---------------------------------------------------


def test_committed_archive_exists_and_is_small():
    assert COMMITTED.is_file(), (
        "the demo archive must be committed, not generated on demand"
    )
    assert COMMITTED.stat().st_size < 5_000, "the demo must stay tiny enough to commit"


def test_committed_archive_matches_the_generator_byte_for_byte():
    """Regenerating must reproduce the committed bytes exactly, on any platform."""
    assert COMMITTED.read_bytes() == archive_bytes()


def test_generator_is_deterministic():
    assert (
        hashlib.sha256(archive_bytes()).hexdigest()
        == hashlib.sha256(archive_bytes()).hexdigest()
    )


def test_demo_data_is_obviously_synthetic():
    """Household ids must not resemble the real dataset's MAC000000 form."""
    ids = {lclid for lclid, _, _, _ in RECORDS}
    assert ids == {"DEMO0001", "DEMO0002"}
    assert not any(i.startswith("MAC") for i in ids)


def test_demo_uses_the_real_schema():
    """The fixture is only useful if it has the same header as the real source."""
    from energy_reconciliation.profiling.validation import EXPECTED_HEADER_LINE

    assert csv_bytes().startswith(EXPECTED_HEADER_LINE)


# -- hand-computed counts -----------------------------------------------------


def test_record_and_structure_counts(demo_report):
    counts = demo_report["counts"]
    assert demo_report["status"] == "COMPLETE"
    assert counts["data_records_excluding_header"] == len(RECORDS) == 12
    assert counts["malformed_records"] == 0
    assert counts["structurally_valid_records"] == 12
    assert counts["records_ok"] == 11  # all but the Null row
    assert counts["records_with_issues"] == 1


def test_consumption_categories(demo_report):
    cats = demo_report["consumption"]["categories_mutually_exclusive"]
    assert cats == {
        "finite_numeric": 11,
        "null_token": 1,
        "empty": 0,
        "unexpected_token": 0,
        "non_finite_numeric": 0,
    }
    diag = demo_report["consumption"]["diagnostics_overlapping"]
    assert diag["zeros"] == 1  # record 2 only
    assert diag["negatives"] == 0


def test_timestamps(demo_report):
    stamps = demo_report["timestamps"]
    assert stamps["valid_format"] == 12
    assert stamps["invalid_format"] == 0
    assert stamps["on_grid"] == 11
    assert stamps["off_grid"] == 1  # record 10, 04:17:23


def test_households_and_tariffs(demo_report):
    households = demo_report["households"]
    assert households["distinct_in_member"] == 2
    assert households["tariff_group_values"] == {"Std": 10, "ToU": 2}


def test_duplicate_rules_are_distinguished(demo_report):
    """Records 6/7 are identical; 8/9 share a key but disagree on the value."""
    dup = demo_report["duplicates"]
    assert dup["exact_source_row_equality"]["groups"] == 1
    assert dup["exact_source_row_equality"]["extra_rows"] == 1
    assert dup["candidate_key_collisions"]["colliding_keys"] == 2
    assert dup["candidate_key_collisions"]["extra_rows"] == 2
    assert dup["candidate_key_collisions"]["conflicting_groups"] == 1


def test_distribution_values(demo_report):
    """Sorted finite values: 0, .125, .250, .375, .500, .500, .625, .750, .875, 1.000, 1.125"""
    dist = demo_report["consumption"]["distribution"]
    assert dist["finite_value_count"] == 11
    assert dist["counts_agree"] is True
    assert dist["minimum"] == "0"
    assert dist["maximum"] == "1.125"
    assert dist["range"] == "1.125"
    assert dist["sum"] == "6.125"
    assert Decimal(dist["mean"]) == Decimal("0.556818182")  # 6.125/11 to 9dp
    assert dist["interquartile_range"] == "0.625"


def test_percentile_ranks_and_values(demo_report):
    """Nearest rank over 11 values: ceil(p/100 * 11)."""
    pct = demo_report["consumption"]["distribution"]["percentiles_nearest_rank"]
    assert (pct["p25"]["rank"], pct["p25"]["value_text"].strip()) == (3, "0.250")
    assert (pct["p50"]["rank"], pct["p50"]["value_text"].strip()) == (6, "0.500")
    assert (pct["p75"]["rank"], pct["p75"]["value_text"].strip()) == (9, "0.875")


def test_lines_and_reconciliation(demo_report):
    lines = demo_report["lines_vs_records"]
    assert lines["physical_lines"] == 13  # 1 header + 12 records
    assert lines["one_line_per_record_holds"] is True
    assert demo_report["reconciliation"]["all_core_partitions_hold"] is True


# -- the documented command ---------------------------------------------------


def test_readme_demo_command_succeeds(tmp_path):
    """Exactly the invocation the README documents, minus the output location."""
    out = tmp_path / "demo-profile.json"
    exit_status = main(
        [
            "--archive",
            str(COMMITTED),
            "--member",
            DEMO_MEMBER,
            "--output",
            str(out),
            "--no-examples",
            "--work-dir",
            str(tmp_path),
        ]
    )
    assert exit_status == 0, "a clean demo run must exit 0"
    assert out.is_file()
