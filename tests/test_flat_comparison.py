"""ANL-005: the same charged readings priced two ways, against hand-derived figures.

The fixture is the specification. The schedule has three labels: 2013-01-01 00:30 is
``Low`` (3.99p), 01:00 is ``High`` (67.20p), and 2013-01-02 00:30 is ``Normal``
(11.76p). The flat price is the catalogue's 14.228p. Every household below was chosen for
what it proves, and every expected figure is written out by hand:

| Household | Readings | Dynamic £ | Flat £ | Flat − dynamic | Proves |
|---|---|---|---|---|---|
| MAC000001 | 10 kWh Low | 0.399 | 1.4228 | +1.0238 | favours dynamic |
| MAC000002 | 10 kWh High | 6.72 | 1.4228 | −5.2972 | favours flat |
| MAC000003 | 529.72 Low + 102.38 High | 89.935188 | 89.935188 | 0, exactly | an exact tie |
| MAC000005 | 1 kWh Normal, 2013-01-02 | 0.1176 | 0.14228 | +0.02468 | period selection |
| MAC000006 | 0 kWh Low | 0 | 0 | 0 | zero denominator |
| MAC000007 | 0.01 kWh Normal, 2013-01-02 | 0.001176 | 0.0014228 | +0.0002468 | rounds to £0.00, still "lower" |
| MAC000009 | Std, 7 kWh | excluded | excluded | — | never priced |

The tie: 529.72 × 0.0399 + 102.38 × 0.672 = 21.135828 + 68.79936 = 89.935188, and
632.10 × 0.14228 = 89.935188. Chosen so the two prices agree to the last digit; a
threshold or a rounded comparison would get it wrong in one direction or the other.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import duckdb
import pytest
from conftest import HEADER, row
from test_tariff import load, make_schedule

from energy_reconciliation.tariff import analytics as ta
from energy_reconciliation.tariff import flat_comparison as fc
from energy_reconciliation.tariff.models import build_scenario

SCHEDULE = [
    ("2013-01-01 00:30:00", "Low"),
    ("2013-01-01 01:00:00", "High"),
    ("2013-01-02 00:30:00", "Normal"),
]
FLAT = Decimal("0.14228")
D1, D2 = date(2013, 1, 1), date(2013, 1, 2)

HAND = {  # household -> (kwh, dynamic, flat)
    "MAC000001": (Decimal(10), Decimal("0.399"), Decimal(10) * FLAT),
    "MAC000002": (Decimal(10), Decimal("6.72"), Decimal(10) * FLAT),
    "MAC000003": (Decimal("632.10"), Decimal("89.935188"), Decimal("632.10") * FLAT),
    "MAC000005": (Decimal(1), Decimal("0.1176"), Decimal(1) * FLAT),
    "MAC000006": (Decimal(0), Decimal(0), Decimal(0)),
    "MAC000007": (Decimal("0.01"), Decimal("0.001176"), Decimal("0.01") * FLAT),
}


@pytest.fixture
def sample(tmp_path):
    body = HEADER + b"".join(
        [
            row("MAC000001", "ToU", "2013-01-01 00:30:00.0000000", " 10 "),
            row("MAC000002", "ToU", "2013-01-01 01:00:00.0000000", " 10 "),
            row("MAC000003", "ToU", "2013-01-01 00:30:00.0000000", " 529.72 "),
            row("MAC000003", "ToU", "2013-01-01 01:00:00.0000000", " 102.38 "),
            row("MAC000005", "ToU", "2013-01-02 00:30:00.0000000", " 1 "),
            row("MAC000006", "ToU", "2013-01-01 00:30:00.0000000", " 0 "),
            row("MAC000007", "ToU", "2013-01-02 00:30:00.0000000", " 0.01 "),
            row("MAC000009", "Std", "2013-01-01 00:30:00.0000000", " 7 "),
        ]
    )
    database = load(tmp_path, body)
    built = build_scenario(database, make_schedule(SCHEDULE))
    return database, built.run_id


def _by_household(result: fc.FlatComparison) -> dict[str, dict]:
    return {r["household_id"]: r for r in result.households}


# ------------------------------------------------------------ the hand figures
def test_every_household_matches_the_hand_arithmetic(sample):
    database, run_id = sample
    result = fc.compare(database, run_id)
    assert isinstance(result, fc.FlatComparison)
    rows = _by_household(result)
    assert set(rows) == set(HAND), "the Std household is never priced"
    for hh, (kwh, dyn, flat) in HAND.items():
        r = rows[hh]
        assert Decimal(r["kwh_exact"]) == kwh, hh
        assert Decimal(r["dynamic_charge_gbp_exact"]) == dyn, hh
        assert Decimal(r["flat_charge_gbp_exact"]) == flat, hh
        assert Decimal(r["difference_exact"]) == flat - dyn, hh


def test_outcomes_are_classified_on_exact_differences(sample):
    database, run_id = sample
    result = fc.compare(database, run_id)
    rows = _by_household(result)
    assert rows["MAC000003"]["outcome_under_dynamic"] == fc.EQUAL
    assert Decimal(rows["MAC000003"]["difference_exact"]) == 0, "an exact tie, not near"
    assert rows["MAC000002"]["outcome_under_dynamic"] == fc.HIGHER
    assert rows["MAC000001"]["outcome_under_dynamic"] == fc.LOWER
    # +0.0002468 displays as £0.00. A rounded classifier would call this equal.
    assert rows["MAC000007"]["outcome_under_dynamic"] == fc.LOWER
    assert float(ta.round_money(Decimal(rows["MAC000007"]["difference_exact"]))) == 0.0
    assert result.outcomes == {fc.LOWER: 3, fc.HIGHER: 1, fc.EQUAL: 2}


def test_the_zero_consumption_household_has_an_undefined_percentage(sample):
    database, run_id = sample
    rows = _by_household(fc.compare(database, run_id))
    z = rows["MAC000006"]
    assert Decimal(z["flat_charge_gbp_exact"]) == 0
    assert z["pct_of_flat_exact"] is None, "0/0 is undefined, never 0%"
    assert z["outcome_under_dynamic"] == fc.EQUAL
    # and selecting only that household gives a defined comparison with an undefined %
    only = fc.compare(database, run_id, household="MAC000006")
    assert isinstance(only, fc.FlatComparison)
    assert only.totals.flat == 0 and only.totals.pct_of_flat is None


# --------------------------------------------------------------- reconciliation
def test_households_reconcile_to_the_pooled_totals_three_ways(sample):
    database, run_id = sample
    result = fc.compare(database, run_id)
    t = result.totals
    kwh = sum(k for k, _, _ in HAND.values())
    dyn = sum(d for _, d, _ in HAND.values())
    assert t.households == 6 and t.readings == 7
    assert t.kwh == kwh == Decimal("653.11")
    assert t.dynamic == dyn == Decimal("97.172964")
    assert t.flat == kwh * FLAT == Decimal("92.9244908"), (
        "sum of products = product of sums"
    )
    assert t.flat == sum(Decimal(r["flat_charge_gbp_exact"]) for r in result.households)
    assert t.difference == t.flat - t.dynamic
    assert t.pct_of_flat == (t.flat - t.dynamic) / t.flat * 100
    assert t.pct_of_flat < 0, "pooled: the dynamic scenario is higher for this fixture"


def test_the_dynamic_total_is_the_scenario_total_the_tab_already_shows(sample):
    """The comparison must not recompute the dynamic charge -- it reads the fact."""
    database, run_id = sample
    result = fc.compare(database, run_id)
    assert str(result.totals.dynamic) == ta.total_charge_exact(database, run_id)


# -------------------------------------------------------------------- selection
def test_period_and_household_selection_use_the_tab_scope(sample):
    database, run_id = sample
    jan2 = fc.compare(database, run_id, start=D2, end=D2)
    assert isinstance(jan2, fc.FlatComparison)
    assert set(_by_household(jan2)) == {"MAC000005", "MAC000007"}
    assert jan2.schedule_slots_in_period == 1, "one schedule label on 2013-01-02"
    assert jan2.totals.kwh == Decimal("1.01")

    one = fc.compare(database, run_id, household="MAC000002", start=D1, end=D1)
    assert isinstance(one, fc.FlatComparison)
    assert one.totals.households == 1 and one.totals.dynamic == Decimal("6.72")
    assert one.outcomes == {fc.LOWER: 0, fc.HIGHER: 1, fc.EQUAL: 0}
    assert one.household == "MAC000002" and one.period == (D1, D1)


def test_coverage_is_observed_labels_against_the_periods_schedule_labels(sample):
    database, run_id = sample
    rows = _by_household(fc.compare(database, run_id))
    assert rows["MAC000003"]["schedule_slots_in_period"] == 3
    assert Decimal(rows["MAC000003"]["coverage_share"]) == Decimal(2) / Decimal(3)
    assert Decimal(rows["MAC000001"]["coverage_share"]) == Decimal(1) / Decimal(3)
    assert rows["MAC000005"]["first_charged_date"] == "2013-01-02"
    assert rows["MAC000001"]["last_charged_date"] == "2013-01-01"
    # narrowing the period narrows the denominator with it -- never annualised
    jan1 = _by_household(fc.compare(database, run_id, start=D1, end=D1))
    assert jan1["MAC000003"]["schedule_slots_in_period"] == 2
    assert Decimal(jan1["MAC000003"]["coverage_share"]) == 1


def test_an_empty_selection_is_an_explicit_state_with_no_zero(sample):
    database, run_id = sample
    empty = fc.compare(database, run_id, start=date(2013, 3, 1), end=date(2013, 3, 1))
    assert isinstance(empty, fc.Unavailable) and empty.kind == fc.EMPTY
    assert "nothing is zero" in empty.reason
    nobody = fc.compare(database, run_id, household="MAC000009")
    assert isinstance(nobody, fc.Unavailable) and nobody.kind == fc.EMPTY


# -------------------------------------------------------------- unavailable prices
def _edit_prices(database, sql):
    con = duckdb.connect(str(database))
    try:
        con.execute(sql)
    finally:
        con.close()


def test_a_missing_flat_price_is_named_and_hides_nothing_else(sample):
    database, run_id = sample
    _edit_prices(
        database, "DELETE FROM main.dim_tariff_price WHERE tariff_group = 'Std'"
    )
    result = fc.compare(database, run_id)
    assert isinstance(result, fc.Unavailable) and result.kind == fc.NO_PRICE
    assert not ta.band_summary(database, run_id).empty, "the dynamic figures still read"


def test_a_non_unique_flat_price_is_refused_not_chosen(sample):
    database, run_id = sample
    _edit_prices(
        database,
        "INSERT INTO main.dim_tariff_price SELECT tariff_group, 'flat2', "
        "price_pence_per_kwh, price_gbp_per_kwh, currency, price_unit, effective_from, "
        "effective_until, evidence_label, source_citation, catalogue_version "
        "FROM main.dim_tariff_price WHERE tariff_group = 'Std'",
    )
    result = fc.compare(database, run_id)
    assert isinstance(result, fc.Unavailable) and result.kind == fc.NON_UNIQUE_PRICE
    assert "flat2" in result.reason


def test_a_zero_flat_price_is_invalid_not_a_zero_charge(sample):
    database, run_id = sample
    _edit_prices(
        database,
        "UPDATE main.dim_tariff_price SET price_gbp_per_kwh = 0, "
        "price_pence_per_kwh = 0 WHERE tariff_group = 'Std'",
    )
    result = fc.compare(database, run_id)
    assert isinstance(result, fc.Unavailable) and result.kind == fc.INVALID_PRICE


def test_the_price_comes_from_the_build_not_from_todays_catalogue(sample):
    """A historical version priced by a different catalogue keeps its own price."""
    database, run_id = sample
    _edit_prices(
        database,
        "UPDATE main.dim_tariff_price SET price_gbp_per_kwh = 0.200000, "
        "price_pence_per_kwh = 20.0000, catalogue_version = 'older' "
        "WHERE tariff_group = 'Std'",
    )
    result = fc.compare(database, run_id)
    assert isinstance(result, fc.FlatComparison)
    assert result.price.price_gbp_per_kwh == Decimal("0.2")
    assert result.price.catalogue_version == "older"
    assert result.totals.flat == Decimal("653.11") * Decimal("0.2")


# ------------------------------------------------------------------ identity
def test_the_output_carries_both_assumptions_and_the_price_identity(sample):
    database, run_id = sample
    result = fc.compare(database, run_id)
    assert result.assumption_ids == ("A1", "A2")
    assert result.price.validity == "UNKNOWN"
    assert result.price.evidence_label == "PUBLISHER-DOCUMENTED"
    payload = result.to_json()
    assert payload["definition"] == fc.DEFINITION
    assert payload["totals"]["pct_denominator"] == "flat_charge_gbp_exact"
    assert payload["assumptions"]["A2"] == fc.A2_TEXT
    assert payload["variation"]["largest_household"] == "MAC000002"


def test_the_command_reports_and_writes_the_json(sample, tmp_path, capsys):
    database, run_id = sample
    out = tmp_path / "r" / "flat.json"
    assert fc.main(["--database", str(database), "--output", str(out)]) == 0
    text = capsys.readouterr().out
    assert "flat - dynamic: GBP -4.2484732" in text
    assert "3 lower under dynamic, 1 higher, 2 equal" in text
    written = json.loads(out.read_text())
    assert written["run_id"] == run_id and written["source"]["label"]
    assert fc.main(["--database", str(database), "--household", "MAC000009"]) == 1
