"""ANL-003 step 4: the classification and both facts, proved by meaning and by mutation.

Accounting is not meaning. ``charged + excluded = distinct`` closes just as neatly when
two exclusion reasons are swapped, or when a reading is charged that should not have
been and another is excluded that should have been. So this module does three things:

1. **Hand-derived cases.** One reading per policy branch, with the expected outcome and
   the expected charge worked out by hand from the published prices. If a rule moves, a
   named row changes verdict and says which.
2. **Partition, by membership.** Every distinct reading appears in exactly one fact, and
   neither fact holds a key the policy grain does not.
3. **Mutation.** A deliberately broken build must fail the test that is supposed to catch
   it. One mutation breaks the accounting; the other leaves every count identical and
   changes only a reason, which is the case a counting identity cannot see.

Mutations are applied to a **copy of the dbt project** in a temp directory, against a
disposable warehouse. The repository's own project is never edited.
"""

from __future__ import annotations

import shutil
import zipfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest
from conftest import HEADER, MEMBER, row

from energy_reconciliation import dbt_macros, dbt_run
from energy_reconciliation.ingest.loader import load_member

pytest.importorskip("dbt.cli.main", reason="dbt is not installed")

PROJECT = dbt_macros.repository_root() / "dbt"
BUILD = dbt_run.BUILD_SCHEMA

# --------------------------------------------------------------------- the fixture
# A schedule with a deliberate gap and a label beyond the price validity, so every
# exclusion reason is reachable. Coverage is [2013-01-01 00:00, 2014-01-01 00:00].
SCHEDULE_ROWS = [
    (datetime(2013, 1, 1, 0, 0), "Normal"),  # noqa: DTZ001 - naive, as the source is
    (datetime(2013, 1, 1, 0, 30), "Low"),  # noqa: DTZ001
    (datetime(2013, 1, 1, 1, 0), "High"),  # noqa: DTZ001
    # 01:30 deliberately absent -> an on-grid reading there is unmatched
    (datetime(2013, 1, 1, 2, 0), "Normal"),  # noqa: DTZ001
    # inside schedule coverage but outside the ToU price validity [2013-01-01, 2014-01-01)
    (datetime(2014, 1, 1, 0, 0), "Normal"),  # noqa: DTZ001
]

#: Every case, with the verdict and the charge derived by hand.
#: Prices: High 0.6720, Normal 0.1176, Low 0.0399 GBP/kWh.
CASES = """
| label                | rows                    | verdict                             |
| 2013-01-01 00:00     | ' 0 ' (once)            | charged Normal, exactly 0           |
| 2013-01-01 00:30     | ' 2 ' twice (exact dup) | charged Low, 2 * 0.0399 = 0.0798    |
| 2013-01-01 01:00     | ' 4.0 ' and ' 4 '       | charged High, 4 * 0.6720 = 2.6880   |
| 2013-01-01 02:00     | ' 1.5 '                 | charged Normal, 1.5*0.1176 = 0.1764 |
| 2013-01-01 01:30     | ' 1 '                   | unmatched_schedule_label            |
| 2013-01-01 03:00     | ' 0.3 ' and ' 0.9 '     | conflicting_label (two rows)        |
| 2013-01-01 04:00     | ' 0.4 ' and 'Null'      | conflicting_label (two rows)        |
| 2013-01-01 05:00     | 'Null'                  | missing_value                       |
| 2013-01-01 06:37:27  | ' 0.5 '                 | off_grid_observation                |
| 2014-01-01 00:00     | ' 1 '                   | unpriced_band                       |
| 2012-12-31 23:00     | ' 1 '                   | outside_schedule_period             |
| MAC000002 Std 02:00  | ' 7 '                   | ineligible_tariff_group             |
"""

EXPECTED_CHARGED = {
    ("MAC000001", "2013-01-01 00:00:00.0000000"): (
        "Normal",
        Decimal("0.0000000000000000"),
    ),
    ("MAC000001", "2013-01-01 00:30:00.0000000"): (
        "Low",
        Decimal("0.0798000000000000"),
    ),
    ("MAC000001", "2013-01-01 01:00:00.0000000"): (
        "High",
        Decimal("2.6880000000000000"),
    ),
    ("MAC000001", "2013-01-01 02:00:00.0000000"): (
        "Normal",
        Decimal("0.1764000000000000"),
    ),
}

EXPECTED_EXCLUDED = {
    ("MAC000001", "2013-01-01 01:30:00.0000000"): "unmatched_schedule_label",
    ("MAC000001", "2013-01-01 03:00:00.0000000"): "conflicting_label",
    ("MAC000001", "2013-01-01 04:00:00.0000000"): "conflicting_label",
    ("MAC000001", "2013-01-01 05:00:00.0000000"): "missing_value",
    ("MAC000001", "2013-01-01 06:37:27.0000000"): "off_grid_observation",
    ("MAC000001", "2014-01-01 00:00:00.0000000"): "unpriced_band",
    ("MAC000001", "2012-12-31 23:00:00.0000000"): "outside_schedule_period",
    ("MAC000002", "2013-01-01 02:00:00.0000000"): "ineligible_tariff_group",
}

FIXTURE = HEADER + b"".join(
    [
        row("MAC000001", "ToU", "2013-01-01 00:00:00.0000000", " 0 "),
        row("MAC000001", "ToU", "2013-01-01 00:30:00.0000000", " 2 "),
        row(
            "MAC000001", "ToU", "2013-01-01 00:30:00.0000000", " 2 "
        ),  # exact duplicate
        row("MAC000001", "ToU", "2013-01-01 01:00:00.0000000", " 4.0 "),
        row("MAC000001", "ToU", "2013-01-01 01:00:00.0000000", " 4 "),  # equivalent
        row("MAC000001", "ToU", "2013-01-01 02:00:00.0000000", " 1.5 "),
        row(
            "MAC000001", "ToU", "2013-01-01 01:30:00.0000000", " 1 "
        ),  # no schedule label
        row(
            "MAC000001", "ToU", "2013-01-01 03:00:00.0000000", " 0.3 "
        ),  # conflict pair
        row("MAC000001", "ToU", "2013-01-01 03:00:00.0000000", " 0.9 "),
        row(
            "MAC000001", "ToU", "2013-01-01 04:00:00.0000000", " 0.4 "
        ),  # number vs token
        row("MAC000001", "ToU", "2013-01-01 04:00:00.0000000", "Null"),
        row("MAC000001", "ToU", "2013-01-01 05:00:00.0000000", "Null"),  # missing value
        row("MAC000001", "ToU", "2013-01-01 06:37:27.0000000", " 0.5 "),  # off grid
        row(
            "MAC000001", "ToU", "2014-01-01 00:00:00.0000000", " 1 "
        ),  # banded, unpriced
        row(
            "MAC000001", "ToU", "2012-12-31 23:00:00.0000000", " 1 "
        ),  # before coverage
        row(
            "MAC000002", "Std", "2013-01-01 02:00:00.0000000", " 7 "
        ),  # ineligible group
    ]
)

#: 16 raw rows, less one exact duplicate and one equivalent representation.
DISTINCT_READINGS = 14


def _workbook(path: Path, rows=SCHEDULE_ROWS) -> Path:
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = "Sheet1"
    sheet.append(["TariffDateTime", "Tariff"])
    for label, band in rows:
        sheet.append([label, band])
    book.save(path)
    return path


def _warehouse(tmp_path: Path, name: str = "facts") -> Path:
    archive = tmp_path / f"{name}.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(MEMBER, FIXTURE)
    database = tmp_path / f"{name}.duckdb"
    assert load_member(archive, MEMBER, database).complete
    return database


def _build(database: Path, tmp_path: Path, project: Path = PROJECT, *extra: str) -> int:
    return dbt_run.main(
        [
            "--database",
            str(database),
            "--project-dir",
            str(project),
            "--schedule",
            "workbook",
            "--workbook",
            str(_workbook(tmp_path / "schedule.xlsx")),
            *extra,
            "build",
            "--target-path",
            str(tmp_path / "target"),
        ]
    )


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> Path:
    tmp_path = tmp_path_factory.mktemp("dbt_facts")
    database = _warehouse(tmp_path)
    assert _build(database, tmp_path) == 0, "the fixture build must pass every dbt test"
    return database


def _rows(database: Path, sql: str):
    con = duckdb.connect(str(database), read_only=True)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


# ------------------------------------------------------------------- meaning
def test_each_charged_case_has_the_hand_derived_band_and_exact_charge(built):
    """The four charged readings, with charges worked out by hand from the prices."""
    found = {
        (h, t): (band, charge)
        for h, t, band, charge in _rows(
            built,
            "SELECT household_id, source_timestamp_text, band_label, energy_charge_gbp "
            f"FROM {BUILD}.fact_interval_charge_scenario",
        )
    }
    assert found == EXPECTED_CHARGED


def test_a_zero_consumption_reading_is_charged_at_exactly_zero(built):
    """Not excluded, and not absent: a real zero reading earns a real zero charge.

    This is the distinction the exclusion table exists to protect. An excluded reading
    has no charge at all; a charged reading of zero kWh has a charge of zero.
    """
    charge, kwh = _rows(
        built,
        f"SELECT energy_charge_gbp, consumption_kwh FROM {BUILD}"
        ".fact_interval_charge_scenario WHERE source_timestamp_text = "
        "'2013-01-01 00:00:00.0000000'",
    )[0]
    assert kwh == Decimal(0)
    assert charge == Decimal(0)
    excluded = _rows(
        built,
        f"SELECT COUNT(*) FROM {BUILD}.fact_interval_charge_exclusion "
        "WHERE source_timestamp_text = '2013-01-01 00:00:00.0000000'",
    )[0][0]
    assert excluded == 0


def test_each_excluded_case_has_the_hand_derived_reason(built):
    found = {}
    for household, label, reason in _rows(
        built,
        "SELECT household_id, source_timestamp_text, exclusion_reason "
        f"FROM {BUILD}.fact_interval_charge_exclusion",
    ):
        found.setdefault((household, label), set()).add(reason)
    assert {k: next(iter(v)) for k, v in found.items()} == EXPECTED_EXCLUDED
    for key, reasons in found.items():
        assert len(reasons) == 1, f"{key} carries more than one reason: {reasons}"


def test_a_conflicting_label_keeps_one_row_per_signature_and_charges_none(built):
    """Two disagreeing values are two distinct readings, both withheld."""
    counts = dict(
        _rows(
            built,
            "SELECT source_timestamp_text, COUNT(*) FROM "
            f"{BUILD}.fact_interval_charge_exclusion WHERE exclusion_reason = "
            "'conflicting_label' GROUP BY 1",
        )
    )
    assert counts == {
        "2013-01-01 03:00:00.0000000": 2,
        "2013-01-01 04:00:00.0000000": 2,
    }


def test_duplicates_and_equivalent_representations_are_charged_once(built):
    """Two identical rows and two spellings of one value each yield a single charge."""
    for label in ("2013-01-01 00:30:00.0000000", "2013-01-01 01:00:00.0000000"):
        charged = _rows(
            built,
            f"SELECT COUNT(*) FROM {BUILD}.fact_interval_charge_scenario "
            f"WHERE source_timestamp_text = '{label}'",
        )[0][0]
        assert charged == 1, label


# ----------------------------------------------------------------- partition
def test_the_facts_partition_the_distinct_readings(built):
    """Membership, not just counts: nothing omitted, nothing in both, nothing invented."""
    charged, excluded, distinct = _rows(
        built,
        f"SELECT (SELECT COUNT(*) FROM {BUILD}.fact_interval_charge_scenario), "
        f"(SELECT COUNT(*) FROM {BUILD}.fact_interval_charge_exclusion), "
        f"(SELECT COUNT(*) FROM ("
        "  SELECT DISTINCT household_id, tariff_group, source_timestamp_text, "
        "  observed_at_naive, on_half_hour_grid, consumption_kwh, value_category, "
        "  COALESCE(CAST(consumption_kwh AS VARCHAR), '~' || value_category) "
        "  FROM main.readings))",
    )[0]
    assert distinct == DISTINCT_READINGS
    assert charged + excluded == distinct
    overlap = _rows(
        built,
        f"SELECT COUNT(*) FROM {BUILD}.fact_interval_charge_scenario f "
        f"JOIN {BUILD}.fact_interval_charge_exclusion e USING (household_id, "
        "source_timestamp_text)",
    )[0][0]
    assert overlap == 0


def test_the_exclusion_fact_has_no_charge_column(built):
    """Structural: an excluded reading cannot carry a charge, not even zero."""
    columns = {
        c
        for (c,) in _rows(
            built,
            "SELECT column_name FROM information_schema.columns WHERE table_schema = "
            f"'{BUILD}' AND table_name = 'fact_interval_charge_exclusion'",
        )
    }
    assert "energy_charge_gbp" not in columns
    assert "price_pence_per_kwh" not in columns


def test_every_charged_row_carries_the_assumption(built):
    ids = {
        a
        for (a,) in _rows(
            built,
            f"SELECT DISTINCT assumption_id FROM {BUILD}.fact_interval_charge_scenario",
        )
    }
    assert ids == {"A1"}


# ------------------------------------------------------------------ mutation
def _mutated_project(tmp_path: Path, find: str, replace: str, name: str) -> Path:
    """A copy of the dbt project with one deliberate defect. Never the real project."""
    project = tmp_path / name
    shutil.copytree(PROJECT, project, ignore=shutil.ignore_patterns("target", "logs"))
    macro = project / "macros" / "generated_policy.sql"
    text = macro.read_text()
    assert text.count(find) == 1, f"mutation anchor not unique: {find!r}"
    macro.write_text(text.replace(find, replace))
    return project


def _failed_tests(target: Path) -> set[str]:
    """Which dbt tests failed, from the run results dbt writes."""
    import json

    results = json.loads((target / "run_results.json").read_text())["results"]
    return {
        r["unique_id"].split(".")[-1]
        for r in results
        if r["status"] in {"fail", "error"}
    }


def test_an_inverted_exclusion_flag_breaks_the_reconciliation_test(tmp_path):
    """The accounting identity must have teeth.

    Inverting one flag in the exclusion projection alone stops the two facts partitioning
    the input: eligible readings are charged *and* listed as excluded, and ineligible ones
    that carry no other flag fall out of both.
    """
    project = _mutated_project(
        tmp_path,
        "WHERE is_ineligible_group OR",
        "WHERE NOT is_ineligible_group OR",
        "inverted",
    )
    database = _warehouse(tmp_path, "inverted")
    assert _build(database, tmp_path, project) != 0
    failed = _failed_tests(tmp_path / "target")
    assert "assert_charged_plus_excluded_equals_distinct" in failed
    assert "assert_charged_and_excluded_are_disjoint" in failed
    # a row now appears in the exclusion fact with none of its conditions set
    assert "assert_excluded_readings_carry_at_least_one_flag" in failed


def test_a_wrong_reason_is_caught_although_every_count_still_closes(tmp_path):
    """The case a counting identity cannot see.

    Swapping two reasons changes no row, no count and no total: charged + excluded still
    equals the distinct readings, the facts are still disjoint, and the reported reasons
    are still drawn from the accepted list. Only recomputing the precedence from the
    stored flags detects it.
    """
    # Only the copy used by the exclusion FACT is swapped -- identified by its indentation
    # inside that macro. The standalone `exclusion_reason_case` macro, which the singular
    # test uses to recompute precedence from the stored flags, is left correct. That is
    # what makes the disagreement visible: the stored reason and the flags now differ.
    project = _mutated_project(
        tmp_path,
        "           CASE\n"
        "        WHEN is_ineligible_group THEN 'ineligible_tariff_group'\n"
        "        WHEN is_outside_schedule_period THEN 'outside_schedule_period'",
        "           CASE\n"
        "        WHEN is_ineligible_group THEN 'outside_schedule_period'\n"
        "        WHEN is_outside_schedule_period THEN 'ineligible_tariff_group'",
        "swapped",
    )
    database = _warehouse(tmp_path, "swapped")
    assert _build(database, tmp_path, project) != 0
    failed = _failed_tests(tmp_path / "target")
    assert "assert_one_reason_per_exclusion" in failed
    # the counting identity is untouched -- which is the point
    assert "assert_charged_plus_excluded_equals_distinct" not in failed
    assert "assert_charged_and_excluded_are_disjoint" not in failed


def test_a_failed_build_is_not_recorded_as_a_successful_one(tmp_path):
    """A partial build must not leave a record saying the build succeeded."""
    project = _mutated_project(
        tmp_path,
        "WHERE is_ineligible_group OR",
        "WHERE NOT is_ineligible_group OR",
        "unrecorded",
    )
    database = _warehouse(tmp_path, "unrecorded")
    assert _build(database, tmp_path, project) != 0
    attempts = _rows(
        database,
        "SELECT status, dbt_exit_code, built_output_sha256 FROM "
        f"{dbt_run.BUILD_RUN_TABLE}",
    )
    assert len(attempts) == 1, "the attempt is recorded once"
    status, exit_code, digest = attempts[0]
    assert status == dbt_run.FAILED and exit_code not in (None, 0)
    assert digest is None, "a failed attempt records no output digest"
    assert database.exists()
