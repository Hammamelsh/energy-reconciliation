"""Ingestion behaviour: reruns, failure, cross-file households, duplicates, conflicts."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from conftest import HEADER, build_archive
from conftest import row as make_row

from energy_reconciliation.explorer import queries as q
from energy_reconciliation.ingest import loader
from energy_reconciliation.ingest.loader import load_member
from energy_reconciliation.ingest.warehouse import connect

MEMBER_A = "Small LCL Data/LCL-June2015v2_4.csv"
MEMBER_B = "Small LCL Data/LCL-June2015v2_5.csv"


def simple_member(*rows: tuple[str, str, str, str]) -> bytes:
    return HEADER + b"".join(make_row(*r) for r in rows)


@pytest.fixture
def two_members() -> dict[str, bytes]:
    """MAC000166 ends member 4 and continues into member 5, as the real archive does."""
    a = simple_member(
        ("MAC000131", "Std", "2013-01-01 00:30:00.0000000", " 0.100 "),
        ("MAC000166", "Std", "2013-01-01 00:30:00.0000000", " 0.200 "),
        ("MAC000166", "Std", "2013-01-01 01:00:00.0000000", " 0.300 "),
    )
    b = simple_member(
        ("MAC000166", "Std", "2013-01-01 01:30:00.0000000", " 0.400 "),
        ("MAC000200", "Std", "2013-01-01 00:30:00.0000000", " 0.500 "),
    )
    return {MEMBER_A: a, MEMBER_B: b}


def count(db, table="readings") -> int:
    con = connect(db)
    try:
        return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        con.close()


# -- rerun safety -------------------------------------------------------------


def test_reloading_identical_content_changes_nothing(tmp_path, mixed_member):
    archive = build_archive(tmp_path, {MEMBER_A: mixed_member})
    db = tmp_path / "w.duckdb"

    first = load_member(archive, MEMBER_A, db)
    after_first = count(db)
    assert first.skipped is False
    assert after_first == first.records_published

    second = load_member(archive, MEMBER_A, db)
    assert second.skipped is True, "identical content must not be reloaded"
    assert second.records_published == 0
    assert count(db) == after_first, "row count must not grow on rerun"
    assert count(db, "load_registry") == 1


def test_changed_content_replaces_only_that_member(tmp_path):
    db = tmp_path / "w.duckdb"
    first = build_archive(
        tmp_path,
        {
            MEMBER_A: simple_member(
                ("MAC000001", "Std", "2013-01-01 00:30:00.0000000", " 0.1 ")
            ),
            MEMBER_B: simple_member(
                ("MAC000002", "Std", "2013-01-01 00:30:00.0000000", " 0.2 ")
            ),
        },
        name="first.zip",
    )
    load_member(first, MEMBER_A, db)
    load_member(first, MEMBER_B, db)
    assert count(db) == 2

    # Same archive file name, member A corrected to two rows.
    corrected = build_archive(
        tmp_path,
        {
            MEMBER_A: simple_member(
                ("MAC000001", "Std", "2013-01-01 00:30:00.0000000", " 0.9 "),
                ("MAC000001", "Std", "2013-01-01 01:00:00.0000000", " 0.8 "),
            ),
            MEMBER_B: simple_member(
                ("MAC000002", "Std", "2013-01-01 00:30:00.0000000", " 0.2 ")
            ),
        },
        name="first.zip",
    )
    result = load_member(corrected, MEMBER_A, db)
    assert result.replaced_previous is True
    assert count(db) == 3, "member A replaced (1 -> 2 rows), member B untouched"

    con = connect(db)
    try:
        b_rows = con.execute(
            "SELECT COUNT(*) FROM readings WHERE member_name = ?", [MEMBER_B]
        ).fetchone()[0]
        a_values = [
            r[0]
            for r in con.execute(
                "SELECT consumption_raw_text FROM readings WHERE member_name = ? "
                "ORDER BY source_record_no",
                [MEMBER_A],
            ).fetchall()
        ]
    finally:
        con.close()
    assert b_rows == 1, "loading member A must not disturb member B"
    assert a_values == [" 0.9 ", " 0.8 "], "old member A rows must be gone"


# -- failure during publication ----------------------------------------------


def test_failed_load_preserves_the_previous_published_dataset(
    tmp_path, monkeypatch, mixed_member
):
    """A load that raises mid-publication must leave the last good data intact."""
    db = tmp_path / "w.duckdb"
    archive = build_archive(
        tmp_path,
        {
            MEMBER_A: simple_member(
                ("MAC000001", "Std", "2013-01-01 00:30:00.0000000", " 0.1 ")
            ),
            MEMBER_B: mixed_member,
        },
    )
    load_member(archive, MEMBER_A, db)
    good_rows = count(db)
    good_loads = count(db, "load_registry")
    assert good_rows == 1

    def explode(con, rows):
        raise RuntimeError("simulated failure during publication")

    monkeypatch.setattr(loader, "_insert_readings", explode)
    with pytest.raises(RuntimeError):
        load_member(archive, MEMBER_B, db)

    assert count(db) == good_rows, "previous dataset must survive a failed load"
    assert count(db, "load_registry") == good_loads, "no registry row for a failed load"
    con = connect(db)
    try:
        assert (
            con.execute(
                "SELECT COUNT(*) FROM readings WHERE member_name = ?", [MEMBER_B]
            ).fetchone()[0]
            == 0
        ), "no partial rows from the failed member"
    finally:
        con.close()


# -- cross-file households ----------------------------------------------------


def test_household_spanning_two_members_is_kept_whole(tmp_path, two_members):
    archive = build_archive(tmp_path, two_members)
    db = tmp_path / "w.duckdb"
    load_member(archive, MEMBER_A, db)
    load_member(archive, MEMBER_B, db)

    summary = q.quality_summary(db, "MAC000166")
    assert summary.observed_records == 3
    assert len(summary.members) == 2, "readings must be attributed to both members"

    frame = q.observations(db, "MAC000166")
    assert set(frame["member_name"]) == {MEMBER_A, MEMBER_B}
    assert list(frame["source_record_no"]) == [2, 3, 1], "source references preserved"


# -- missing values -----------------------------------------------------------


def test_missing_values_are_recorded_not_zeroed(tmp_path):
    archive = build_archive(
        tmp_path,
        {
            MEMBER_A: simple_member(
                ("MAC000001", "Std", "2013-01-01 00:30:00.0000000", " 0.5 "),
                ("MAC000001", "Std", "2013-01-01 01:00:00.0000000", "Null"),
                ("MAC000001", "Std", "2013-01-01 01:30:00.0000000", " 0 "),
            )
        },
    )
    db = tmp_path / "w.duckdb"
    load_member(archive, MEMBER_A, db)

    con = connect(db)
    try:
        rows = con.execute(
            "SELECT value_category, consumption_kwh, consumption_raw_text "
            "FROM readings ORDER BY source_record_no"
        ).fetchall()
    finally:
        con.close()

    assert rows[1][0] == "null_token"
    assert rows[1][1] is None, "a Null token must not become a number"
    assert rows[1][2] == "Null", "the source text is kept"
    assert rows[2][0] == "finite_numeric"
    assert rows[2][1] == Decimal(0), "a real zero stays a zero"

    summary = q.quality_summary(db, "MAC000001")
    assert summary.null_tokens == 1
    assert summary.zero_values == 1, "zero and missing are counted separately"

    total = q.period_summary(db, "MAC000001", date(2013, 1, 1), date(2013, 1, 1))
    assert total.total_kwh == Decimal("0.5"), "the Null contributes nothing, not zero"


# -- duplicates and conflicts -------------------------------------------------


def test_exact_duplicates_and_conflicts_are_distinguished(tmp_path):
    archive = build_archive(
        tmp_path,
        {
            MEMBER_A: simple_member(
                ("MAC000001", "Std", "2013-01-01 00:30:00.0000000", " 0.2 "),
                (
                    "MAC000001",
                    "Std",
                    "2013-01-01 00:30:00.0000000",
                    " 0.2 ",
                ),  # exact duplicate
                ("MAC000001", "Std", "2013-01-01 01:00:00.0000000", " 0.3 "),
                (
                    "MAC000001",
                    "Std",
                    "2013-01-01 01:00:00.0000000",
                    " 0.9 ",
                ),  # conflict
            )
        },
    )
    db = tmp_path / "w.duckdb"
    load_member(archive, MEMBER_A, db)

    assert count(db) == 4, "nothing is removed at load time"
    summary = q.quality_summary(db, "MAC000001")
    assert summary.candidate_key_collisions == 2
    assert summary.exact_duplicate_extras == 1
    assert summary.conflicting_keys == 1


def test_total_is_withheld_when_a_conflict_exists(tmp_path):
    archive = build_archive(
        tmp_path,
        {
            MEMBER_A: simple_member(
                ("MAC000001", "Std", "2013-01-01 00:30:00.0000000", " 0.3 "),
                ("MAC000001", "Std", "2013-01-01 00:30:00.0000000", " 0.9 "),
            )
        },
    )
    db = tmp_path / "w.duckdb"
    load_member(archive, MEMBER_A, db)

    total = q.period_summary(db, "MAC000001", date(2013, 1, 1), date(2013, 1, 1))
    assert total.total_kwh is None, "a disputed total must not be published"
    assert "disagreeing readings" in total.withheld_reason


def test_exact_duplicates_are_counted_once_in_the_total(tmp_path):
    archive = build_archive(
        tmp_path,
        {
            MEMBER_A: simple_member(
                ("MAC000001", "Std", "2013-01-01 00:30:00.0000000", " 0.25 "),
                ("MAC000001", "Std", "2013-01-01 00:30:00.0000000", " 0.25 "),
                ("MAC000001", "Std", "2013-01-01 01:00:00.0000000", " 0.75 "),
            )
        },
    )
    db = tmp_path / "w.duckdb"
    load_member(archive, MEMBER_A, db)

    total = q.period_summary(db, "MAC000001", date(2013, 1, 1), date(2013, 1, 1))
    assert total.total_kwh == Decimal("1.00"), "0.25 counted once, plus 0.75"
    assert total.contributing_readings == 2


# -- decimal handling ---------------------------------------------------------


def test_excessive_precision_is_rejected_not_rounded(tmp_path):
    """Rounding a reading to fit the column would silently change a measurement."""
    archive = build_archive(
        tmp_path,
        {
            MEMBER_A: simple_member(
                ("MAC000001", "Std", "2013-01-01 00:30:00.0000000", " 0.12345678901 "),
                ("MAC000001", "Std", "2013-01-01 01:00:00.0000000", " 0.1234567890 "),
            )
        },
    )
    db = tmp_path / "w.duckdb"
    result = load_member(archive, MEMBER_A, db)

    assert result.records_rejected == 1
    assert result.reject_reasons == {"excessive_precision": 1}
    con = connect(db)
    try:
        kept = con.execute("SELECT consumption_raw_text FROM readings").fetchall()
        reason = con.execute(
            "SELECT reason, source_fields FROM rejected_records"
        ).fetchone()
    finally:
        con.close()
    assert kept == [(" 0.1234567890 ",)], "only the representable value is stored"
    assert reason[0] == "excessive_precision"
    assert reason[1] == " 0.12345678901 ", "the source text is preserved for inspection"


def test_every_record_is_either_published_or_rejected(
    tmp_path, wrong_field_count_member
):
    archive = build_archive(tmp_path, {MEMBER_A: wrong_field_count_member})
    db = tmp_path / "w.duckdb"
    result = load_member(archive, MEMBER_A, db)
    assert result.records_published + result.records_rejected == result.records_read
    assert count(db) + count(db, "rejected_records") == result.records_read


# -- transformation changes force a rebuild -----------------------------------


def test_unchanged_source_and_pipeline_skips(tmp_path, mixed_member):
    archive = build_archive(tmp_path, {MEMBER_A: mixed_member})
    db = tmp_path / "w.duckdb"
    load_member(archive, MEMBER_A, db)
    assert load_member(archive, MEMBER_A, db).skipped is True


def test_changed_pipeline_rebuilds_even_when_the_source_is_identical(
    tmp_path, monkeypatch, mixed_member
):
    """Source content alone must not decide that a reload is unnecessary."""
    archive = build_archive(tmp_path, {MEMBER_A: mixed_member})
    db = tmp_path / "w.duckdb"
    first = load_member(archive, MEMBER_A, db)
    assert first.skipped is False

    monkeypatch.setattr(loader, "pipeline_fingerprint", lambda: "a-different-pipeline")
    rebuilt = load_member(archive, MEMBER_A, db)
    assert rebuilt.skipped is False, "changed logic must rebuild"
    assert rebuilt.replaced_previous is True
    assert count(db) == first.records_published, "a rebuild replaces, never appends"


def test_superseded_loads_stay_in_the_registry(tmp_path, monkeypatch, mixed_member):
    archive = build_archive(tmp_path, {MEMBER_A: mixed_member})
    db = tmp_path / "w.duckdb"
    load_member(archive, MEMBER_A, db)
    monkeypatch.setattr(loader, "pipeline_fingerprint", lambda: "second-pipeline")
    load_member(archive, MEMBER_A, db)

    con = connect(db)
    try:
        statuses = dict(
            con.execute(
                "SELECT status, COUNT(*) FROM load_registry GROUP BY 1"
            ).fetchall()
        )
    finally:
        con.close()
    assert statuses == {"published": 1, "superseded": 1}, (
        "the earlier load must remain visible as history"
    )


def test_load_ids_are_unique_per_load_event(tmp_path, monkeypatch, mixed_member):
    """Reverting a code change reproduces an earlier content+pipeline pair."""
    archive = build_archive(tmp_path, {MEMBER_A: mixed_member})
    db = tmp_path / "w.duckdb"
    original = loader.pipeline_fingerprint()
    load_member(archive, MEMBER_A, db)
    monkeypatch.setattr(loader, "pipeline_fingerprint", lambda: "temporary")
    load_member(archive, MEMBER_A, db)
    monkeypatch.setattr(loader, "pipeline_fingerprint", lambda: original)
    load_member(archive, MEMBER_A, db)  # must not collide with the first load

    con = connect(db)
    try:
        ids = [
            r[0] for r in con.execute("SELECT load_id FROM load_registry").fetchall()
        ]
    finally:
        con.close()
    assert len(ids) == len(set(ids)) == 3


def test_decimal_scale_has_headroom_beyond_the_observed_source(tmp_path):
    """Seven decimal places is the observed maximum; storing only seven leaves none."""
    archive = build_archive(
        tmp_path,
        {
            MEMBER_A: simple_member(
                ("MAC000001", "Std", "2013-01-01 00:30:00.0000000", " 6.5279999 "),
                ("MAC000001", "Std", "2013-01-01 01:00:00.0000000", " 0.12345678 "),
            )
        },
    )
    db = tmp_path / "w.duckdb"
    result = load_member(archive, MEMBER_A, db)
    assert result.records_rejected == 0, "an eighth decimal place must now be storable"
    assert result.records_published == 2
