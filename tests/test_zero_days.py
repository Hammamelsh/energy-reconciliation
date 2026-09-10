"""ANL-004: runs of whole zero days, against hand-counted fixtures.

The fixture is the whole specification. ``ZER0001`` has ten recorded dates: five zero
days at the start, a non-zero day, two zero days, a day made unusable by a ``Null``
reading, and a final zero day -- 8 zero days in 3 runs. ``ZER0002`` has no zero day and
must still appear with zero counts. ``ZER0003`` has one zero day with a non-zero usable
day on each side: the only *bounded* run. ``ZER0004`` has a zero day, then a date with no
rows at all, then a non-zero day: an *absent* neighbour.

What the neighbour states must say, day by day:

- ``ZER0001`` run d1..d5: before = recorded span edge, after = non-zero usable (d6).
- ``ZER0001`` run d7..d8: before = non-zero usable (d6), after = **unusable** (d9 has a
  ``Null``). This run is interior to the usable span and is still *not* bounded -- the
  distinction the wording has to respect.
- ``ZER0001`` run d10: before = unusable (d9), after = recorded span edge.
- ``ZER0003`` run d2: bounded, non-zero usable on both sides.
- ``ZER0004`` run d1: before = recorded span edge, after = absent (d2 has no rows).
"""

from __future__ import annotations

import zipfile
from datetime import date, timedelta
from pathlib import Path

from conftest import HEADER, row

from energy_reconciliation.forecast.dataset import daily_records
from energy_reconciliation.ingest.loader import load_member
from energy_reconciliation.quality import zero_days as zd

D1 = date(2013, 3, 1)
MEMBER = "Small LCL Data/LCL-June2015v2_0.csv"


def _day(
    household: str, day: date, value: str, null_at: int | None = None
) -> list[bytes]:
    """48 on-grid readings for one date; ``null_at`` replaces that slot with ``Null``."""
    out = []
    for slot in range(48):
        h, m = divmod(slot * 30, 60)
        ts = f"{day:%Y-%m-%d} {h:02d}:{m:02d}:00.0000000"
        v = "Null" if slot == null_at else value
        out.append(row(household, "Std", ts, v))
    return out


def _days(household: str, plan: dict[int, tuple[str, int | None]]) -> bytes:
    return b"".join(
        b"".join(_day(household, D1 + timedelta(days=k), v, n))
        for k, (v, n) in plan.items()
    )


def _warehouse(directory: Path) -> Path:
    rows = _days(
        "ZER0001",
        {
            0: (" 0 ", None),
            1: (" 0 ", None),
            2: (" 0 ", None),
            3: (" 0 ", None),
            4: (" 0 ", None),  # d1..d5 zero, from the first recorded date
            5: (" 0.5 ", None),  # d6 non-zero
            6: (" 0 ", None),
            7: (" 0 ", None),  # d7, d8 zero
            8: (" 0 ", 12),  # d9: 47 zeros and a Null -> unusable, not a zero day
            9: (" 0 ", None),  # d10 zero, to the last recorded date
        },
    )
    rows += _days(
        "ZER0002", {0: (" 0.25 ", None), 1: (" 0.25 ", None), 2: (" 0.25 ", None)}
    )
    rows += _days(
        "ZER0003", {0: (" 0.25 ", None), 1: (" 0 ", None), 2: (" 0.25 ", None)}
    )
    rows += _days("ZER0004", {0: (" 0 ", None), 2: (" 0.25 ", None)})  # d2 absent
    archive = directory / "zero.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(MEMBER, HEADER + rows)
    database = directory / "zero.duckdb"
    assert load_member(archive, MEMBER, database).complete
    return database


def test_runs_and_reconciliation_against_the_hand_count(tmp_path):
    records = daily_records(_warehouse(tmp_path))
    report = zd.summarise(records)

    assert report["zero_days"] == 10
    assert report["runs"] == 5
    assert report["households"] == 4
    assert report["households_with_zero_days"] == 3
    assert report["usable_days"] == 9 + 3 + 3 + 2, "d9 unusable; ZER0004's d2 absent"

    runs = [r for r in zd.zero_runs(records) if r.household_id == "ZER0001"]
    assert [(r.start, r.end, r.days) for r in runs] == [
        (D1, D1 + timedelta(days=4), 5),
        (D1 + timedelta(days=6), D1 + timedelta(days=7), 2),
        (D1 + timedelta(days=9), D1 + timedelta(days=9), 1),
    ]
    assert [r.touches_first_usable for r in runs] == [True, False, False]
    assert [r.touches_last_usable for r in runs] == [False, False, True]
    assert report["runs_by_length"] == {"1": 3, "2-6": 2, "7-27": 0, "28+": 0}
    assert report["zero_days_by_run_length"] == {"1": 3, "2-6": 7, "7-27": 0, "28+": 0}
    assert report["longest_run"]["days"] == 5


def test_neighbours_are_measured_not_inferred_from_the_usable_span(tmp_path):
    """The d7..d8 run is interior to the usable span and still not bounded."""
    records = daily_records(_warehouse(tmp_path))
    by = {(r.household_id, r.start): r for r in zd.zero_runs(records)}
    r1 = by["ZER0001", D1]
    r2 = by["ZER0001", D1 + timedelta(days=6)]
    r3 = by["ZER0001", D1 + timedelta(days=9)]
    assert (r1.before, r1.after) == (zd.SPAN_EDGE, zd.NONZERO_USABLE)
    assert (r2.before, r2.after) == (
        zd.NONZERO_USABLE,
        "unusable:missing_value_recorded",
    )
    assert (r3.before, r3.after) == ("unusable:missing_value_recorded", zd.SPAN_EDGE)
    assert not r2.touches_edge and not r2.bounded, "interior is not the same as bounded"

    r_bounded = by["ZER0003", D1 + timedelta(days=1)]
    assert r_bounded.bounded and (r_bounded.before, r_bounded.after) == (
        zd.NONZERO_USABLE,
        zd.NONZERO_USABLE,
    )
    r_absent = by["ZER0004", D1]
    assert (r_absent.before, r_absent.after) == (zd.SPAN_EDGE, zd.ABSENT)

    report = zd.summarise(records)
    assert report["runs_bounded_by_nonzero_usable_days"] == 1
    assert report["zero_days_in_bounded_runs"] == 1
    assert report["runs_at_recorded_span_edge"] == 3
    assert report["runs_with_an_unusable_or_absent_neighbour"] == 3
    assert report["runs_touching_an_edge"] == 3, "usable-span edges: r1, r3, ZER0004"
    assert report["neighbour_states"] == {
        "absent": 1,
        "nonzero_usable": 4,
        "recorded_span_edge": 3,
        "unusable:missing_value_recorded": 2,
    }
    assert sum(report["neighbour_states"].values()) == 2 * report["runs"]


def test_an_unusable_day_neither_counts_nor_bridges(tmp_path):
    """d9 has 47 zeros and a Null. Counting it would give 9; bridging would merge d8/d10."""
    records = daily_records(_warehouse(tmp_path))
    d9 = next(d for d in records["ZER0001"] if d.source_date == D1 + timedelta(days=8))
    assert not d9.usable and d9.unusable_reason == "missing_value_recorded"
    runs = [r for r in zd.zero_runs(records) if r.household_id == "ZER0001"]
    assert len(runs) == 3 and runs[-1].days == 1


def test_every_household_is_listed_even_with_no_zero_days(tmp_path):
    report = zd.summarise(daily_records(_warehouse(tmp_path)))
    by_id = {h["household_id"]: h for h in report["per_household"]}
    assert by_id["ZER0002"] == {
        "household_id": "ZER0002",
        "usable_days": 3,
        "zero_days": 0,
        "runs": 0,
        "longest_run_days": 0,
        "zero_day_share": "0.0000",
    }
    assert by_id["ZER0001"]["zero_day_share"] == "0.8889", "8 of 9 usable days, exact"


def test_buckets_are_the_frozen_ones():
    assert [zd.bucket_of(n) for n in (1, 2, 6, 7, 27, 28, 400)] == [
        "1",
        "2-6",
        "2-6",
        "7-27",
        "7-27",
        "28+",
        "28+",
    ]


def test_the_command_runs_and_writes_the_report(tmp_path, capsys):
    database = _warehouse(tmp_path)
    out = tmp_path / "q" / "zero.json"
    assert zd.main(["--database", str(database), "--output", str(out)]) == 0
    text = capsys.readouterr().out
    assert "zero days     : 10 in 5 runs" in text
    assert "bounded       : 1 runs (1 days)" in text
    assert "cause         : not established" in text
    assert out.exists()
    assert zd.main(["--database", str(tmp_path / "missing.duckdb")]) == 2
