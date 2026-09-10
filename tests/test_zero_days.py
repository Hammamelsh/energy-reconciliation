"""ANL-004: runs of whole zero days, against hand-counted fixtures.

The fixture below is the whole specification. Household ``ZER0001`` has ten recorded
dates: five zero days at the start, a non-zero day, two zero days, a day made unusable by
a ``Null`` reading, and a final zero day. Hand count: 8 zero days in 3 runs -- ``[d1..d5]``
touching the first usable date, ``[d7, d8]`` interior, ``[d10]`` touching the last usable
date. The ``Null`` day (d9) is not usable, so it is neither a zero day nor a bridge: d8
and d10 are separate runs even though no non-zero day lies between them. ``ZER0002`` has
no zero day at all and must still appear, with zero counts.
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


def _warehouse(directory: Path) -> Path:
    plan = {  # date offset -> (value, null slot)
        0: (" 0 ", None),
        1: (" 0 ", None),
        2: (" 0 ", None),
        3: (" 0 ", None),
        4: (" 0 ", None),  # d1..d5 zero, touching the first usable date
        5: (" 0.5 ", None),  # d6 non-zero
        6: (" 0 ", None),
        7: (" 0 ", None),  # d7, d8 zero, interior
        8: (" 0 ", 12),  # d9: 47 zeros and a Null -> unusable, not a zero day
        9: (" 0 ", None),  # d10 zero, touching the last usable date
    }
    rows = b"".join(
        b"".join(_day("ZER0001", D1 + timedelta(days=k), v, n))
        for k, (v, n) in plan.items()
    )
    rows += b"".join(
        b"".join(_day("ZER0002", D1 + timedelta(days=k), " 0.25 ")) for k in range(3)
    )
    archive = directory / "zero.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("Small LCL Data/LCL-June2015v2_0.csv", HEADER + rows)
    database = directory / "zero.duckdb"
    assert load_member(
        archive, "Small LCL Data/LCL-June2015v2_0.csv", database
    ).complete
    return database


def test_runs_edges_and_reconciliation_against_the_hand_count(tmp_path):
    records = daily_records(_warehouse(tmp_path))
    report = zd.summarise(records)

    assert report["zero_days"] == 8
    assert report["runs"] == 3
    assert report["households"] == 2
    assert report["households_with_zero_days"] == 1
    assert report["usable_days"] == 9 + 3, (
        "d9 is unusable; ZER0002 has three usable days"
    )

    runs = zd.zero_runs(records)
    assert [(r.start, r.end, r.days) for r in runs] == [
        (D1, D1 + timedelta(days=4), 5),
        (D1 + timedelta(days=6), D1 + timedelta(days=7), 2),
        (D1 + timedelta(days=9), D1 + timedelta(days=9), 1),
    ]
    assert [r.touches_first_usable for r in runs] == [True, False, False]
    assert [r.touches_last_usable for r in runs] == [False, False, True]
    assert report["runs_touching_an_edge"] == 2
    assert report["zero_days_in_edge_runs"] == 6
    assert report["runs_by_length"] == {"1": 1, "2-6": 2, "7-27": 0, "28+": 0}
    assert report["zero_days_by_run_length"] == {"1": 1, "2-6": 7, "7-27": 0, "28+": 0}
    assert report["longest_run"]["days"] == 5


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
    assert "zero days     : 8 in 3 runs" in text
    assert "cause         : not established" in text
    assert out.exists()
    assert zd.main(["--database", str(tmp_path / "missing.duckdb")]) == 2
