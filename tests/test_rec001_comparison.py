"""REC-001: does the comparison explain every difference, including decreases?

Every expectation is worked out by hand in the docstring before the code runs, from the
published prices: High 67.20 p/kWh -> 0.6720 GBP/kWh, Normal 11.76 -> 0.1176,
Low 3.99 -> 0.0399.

The case that matters most is the one an "additions only" mental model gets wrong: a row
in the *added* member can disagree with a reading the baseline already charged, and the
conflict policy then **withholds** that charge. The comparison must report it as a
removal with its reason and its source rows on both sides, and the reconciliation must
still close to exactly zero.
"""

from __future__ import annotations

import zipfile
from decimal import Decimal

import pytest
from conftest import HEADER, row
from test_tariff import make_schedule

from energy_reconciliation.ingest.loader import load_member
from energy_reconciliation.tariff.compare import ComparisonError, compare_scenarios
from energy_reconciliation.tariff.models import build_scenario

MEMBER_A = "Small LCL Data/LCL-June2015v2_0.csv"
MEMBER_B = "Small LCL Data/LCL-June2015v2_1.csv"

SCHEDULE = make_schedule(
    [
        ("2013-01-01 00:30:00", "High"),
        ("2013-01-01 01:00:00", "Low"),
        ("2013-01-01 01:30:00", "Normal"),
        ("2013-01-01 02:00:00", "High"),
    ]
)

#: MAC000001: 2 kWh High + 4 kWh Low = 1.3440 + 0.1596 = 1.5036
BASELINE_ROWS = [
    row("MAC000001", "ToU", "2013-01-01 00:30:00.0000000", " 2 "),
    row("MAC000001", "ToU", "2013-01-01 01:00:00.0000000", " 4 "),
]


def _archive(tmp_path, name, members):
    path = tmp_path / name
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for member, rows in members.items():
            z.writestr(member, HEADER + b"".join(rows))
    return path


def _build(tmp_path, name, members):
    """A warehouse holding exactly `members`, with the scenario built."""
    archive = _archive(tmp_path, f"{name}.zip", members)
    database = tmp_path / f"{name}.duckdb"
    for member in members:
        result = load_member(archive, member, database)
        assert result.complete
    build_scenario(database, SCHEDULE)
    return database


def _pair(tmp_path, added_rows):
    baseline = _build(tmp_path, "base", {MEMBER_A: BASELINE_ROWS})
    comparison = _build(
        tmp_path, "comp", {MEMBER_A: BASELINE_ROWS, MEMBER_B: added_rows}
    )
    return baseline, comparison, compare_scenarios(baseline, comparison)


def _dec(report, *path):
    node = report
    for key in path:
        node = node[key]
    return Decimal(node)


# ------------------------------------------------------------- the mixed case
@pytest.fixture
def mixed(tmp_path):
    """Added member carries one of each kind of change.

    - 01:30, 1 kWh, MAC000001 -- NEW reading, existing household: +1 x 0.1176 = +0.1176
    - 00:30, 2 kWh, MAC000001 -- EXACT DUPLICATE of a baseline row: adds nothing
    - 01:00, 9 kWh, MAC000001 -- CONFLICTS with the baseline's 4 kWh: the baseline's
      0.1596 is WITHHELD, so -0.1596
    - 02:00, 10 kWh, MAC000002 -- NEW household: +10 x 0.6720 = +6.7200

    baseline 1.5036 + 0.1176 - 0.1596 + 6.7200 = 8.1816
    """
    return _pair(
        tmp_path,
        [
            row("MAC000001", "ToU", "2013-01-01 01:30:00.0000000", " 1 "),
            row("MAC000001", "ToU", "2013-01-01 00:30:00.0000000", " 2 "),
            row("MAC000001", "ToU", "2013-01-01 01:00:00.0000000", " 9 "),
            row("MAC000002", "ToU", "2013-01-01 02:00:00.0000000", " 10 "),
        ],
    )


def test_the_hand_computed_totals_hold(mixed):
    _b, _c, report = mixed
    assert _dec(report, "reconciliation", "baseline_charge_gbp_exact") == Decimal(
        "1.5036"
    )
    assert _dec(report, "reconciliation", "comparison_charge_gbp_exact") == Decimal(
        "8.1816"
    )


def test_each_kind_of_change_is_separated(mixed):
    _b, _c, report = mixed
    charged = report["charged_output"]
    assert charged["added_existing_households"]["rows"] == 1
    assert Decimal(charged["added_existing_households"]["charge_gbp_exact"]) == Decimal(
        "0.1176"
    )
    assert charged["added_new_households"]["rows"] == 1
    assert Decimal(charged["added_new_households"]["charge_gbp_exact"]) == Decimal(
        "6.7200"
    )
    assert charged["removed"]["rows"] == 1
    assert Decimal(charged["removed"]["charge_gbp_exact"]) == Decimal("0.1596")
    assert charged["changed"]["rows"] == 0


def test_a_decrease_is_explained_as_a_withholding_with_its_evidence(mixed):
    """The added member removed a charge. It must be reported, reasoned and traceable."""
    _b, _c, report = mixed
    affected = {h["household_id"]: h for h in report["affected_households"]}
    existing = affected["MAC000001"]
    assert existing["status"] == "existing"
    assert existing["removed_charged"] == 1
    detail = existing["removed_detail"][0]
    assert detail["source_timestamp_text"].startswith("2013-01-01 01:00")
    assert Decimal(detail["baseline_charge_gbp"]) == Decimal("0.1596")
    assert detail["reason_in_comparison"] == ["conflicting_label"]
    # both sides of the dispute are traceable to their member and record number
    texts = {r["raw_text"].strip() for r in detail["source_rows"]}
    members = {r["member"] for r in detail["source_rows"]}
    assert texts == {"4", "9"}
    assert members == {MEMBER_A, MEMBER_B}
    assert all(isinstance(r["record_no"], int) for r in detail["source_rows"])
    # net for this household is negative even though a reading was added
    assert Decimal(existing["net_gbp_exact"]) == Decimal("0.1176") - Decimal("0.1596")
    assert Decimal(existing["net_gbp_exact"]) < 0


def test_the_reconciliation_closes_to_exactly_zero(mixed):
    _b, _c, report = mixed
    r = report["reconciliation"]
    total = (
        Decimal(r["baseline_charge_gbp_exact"])
        + Decimal(r["plus_added_existing_households"])
        + Decimal(r["plus_added_new_households"])
        - Decimal(r["minus_removed"])
        + Decimal(r["plus_changed"])
    )
    assert total == Decimal(r["comparison_charge_gbp_exact"])
    assert Decimal(r["residual_gbp_exact"]) == 0
    assert r["residual_is_zero"] is True


def test_the_overlapping_exact_duplicate_adds_no_quantity(mixed):
    """It is counted as a duplicate, and it moves no total."""
    _b, _c, report = mixed
    d = report["distinct_readings"]
    assert d["already_in_baseline_exact_duplicate"] == 1
    assert d["already_in_baseline_equivalent_representation"] == 0
    assert (
        d["new_for_existing_households"] == 2
    )  # the 01:30 reading and the 9 kWh dispute
    assert d["new_for_new_households"] == 1
    assert d["identity_holds"] is True
    assert d["comparison"] == d["baseline"] + 3


def test_the_new_conflict_is_reported(mixed):
    _b, _c, report = mixed
    conflicts = report["disagreements"]["new_conflicting_labels"]
    assert len(conflicts) == 1
    assert conflicts[0]["household_id"] == "MAC000001"
    assert conflicts[0]["source_timestamp_text"].startswith("2013-01-01 01:00")
    assert report["disagreements"]["resolved_conflicting_labels"] == 0


def test_new_and_existing_households_are_distinguished(mixed):
    _b, _c, report = mixed
    assert report["households"]["new"] == ["MAC000002"]
    assert report["households"]["lost"] == []
    statuses = {h["household_id"]: h["status"] for h in report["affected_households"]}
    assert statuses == {"MAC000001": "existing", "MAC000002": "new"}


# ------------------------------------------------------- a pure decrease
def test_a_member_that_only_disputes_lowers_the_charge(tmp_path):
    """Added member carries one conflicting row and nothing else.

    baseline 1.5036 - 0.1596 (01:00 withheld) = 1.3440, and the comparison charge falls.
    """
    _b, _c, report = _pair(
        tmp_path, [row("MAC000001", "ToU", "2013-01-01 01:00:00.0000000", " 9 ")]
    )
    r = report["reconciliation"]
    assert Decimal(r["comparison_charge_gbp_exact"]) == Decimal("1.3440")
    assert Decimal(r["comparison_charge_gbp_exact"]) < Decimal(
        r["baseline_charge_gbp_exact"]
    )
    assert Decimal(r["minus_removed"]) == Decimal("0.1596")
    assert Decimal(r["plus_added_existing_households"]) == 0
    assert Decimal(r["residual_gbp_exact"]) == 0


# ------------------------------------------------------- a pure no-op
def test_a_member_of_only_duplicates_changes_nothing(tmp_path):
    _b, _c, report = _pair(tmp_path, BASELINE_ROWS)
    r = report["reconciliation"]
    assert Decimal(r["comparison_charge_gbp_exact"]) == Decimal(
        r["baseline_charge_gbp_exact"]
    )
    assert Decimal(r["residual_gbp_exact"]) == 0
    assert report["charged_output"]["added_existing_households"]["rows"] == 0
    assert report["charged_output"]["removed"]["rows"] == 0
    assert report["distinct_readings"]["already_in_baseline_exact_duplicate"] == 2
    assert report["distinct_readings"]["new_for_existing_households"] == 0
    assert report["affected_households"] == []


# ------------------------------------------------------- a changed value
def test_an_equivalent_representation_is_not_a_change(tmp_path):
    """' 2 ' and ' 2.00 ' are one value: no charge moves, and it is not a conflict."""
    _b, _c, report = _pair(
        tmp_path, [row("MAC000001", "ToU", "2013-01-01 00:30:00.0000000", " 2.00 ")]
    )
    assert (
        report["distinct_readings"]["already_in_baseline_equivalent_representation"]
        == 1
    )
    assert report["disagreements"]["new_conflicting_labels"] == []
    assert report["charged_output"]["changed"]["rows"] == 0
    assert Decimal(report["reconciliation"]["residual_gbp_exact"]) == 0


# ------------------------------------------------------- the identity guard
def test_the_comparison_refuses_warehouses_that_differ_in_more_than_source(tmp_path):
    """A code or price change would make the difference uninterpretable as coverage."""
    baseline = _build(tmp_path, "gbase", {MEMBER_A: BASELINE_ROWS})
    other_schedule = make_schedule([("2013-01-01 00:30:00", "Low")])
    comparison = _build(
        tmp_path, "gcomp", {MEMBER_A: BASELINE_ROWS, MEMBER_B: BASELINE_ROWS}
    )
    build_scenario(comparison, other_schedule, force=True)
    with pytest.raises(ComparisonError, match="more than loaded source"):
        compare_scenarios(baseline, comparison)


def test_the_comparison_refuses_when_no_member_was_added(tmp_path):
    baseline = _build(tmp_path, "nbase", {MEMBER_A: BASELINE_ROWS})
    same = _build(tmp_path, "nsame", {MEMBER_A: BASELINE_ROWS})
    with pytest.raises(ComparisonError, match="no member was added"):
        compare_scenarios(baseline, same)


def test_the_comparison_refuses_a_changed_baseline_member(tmp_path):
    """If a baseline member's bytes changed, the difference is not added coverage."""
    baseline = _build(tmp_path, "cbase", {MEMBER_A: BASELINE_ROWS})
    tampered = [
        *BASELINE_ROWS[:1],
        row("MAC000001", "ToU", "2013-01-01 01:00:00.0000000", " 5 "),
    ]
    comparison = _build(
        tmp_path, "ccomp", {MEMBER_A: tampered, MEMBER_B: BASELINE_ROWS}
    )
    with pytest.raises(ComparisonError, match="content differs"):
        compare_scenarios(baseline, comparison)
