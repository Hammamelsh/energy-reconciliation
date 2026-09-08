"""The tariff views: scope separation, share denominators, empty states, chart shape.

These assert the **rendered Altair specification** and the frames the app hands it, not
a screenshot. A visual check by a person is still required and is recorded separately;
what these tests establish is that the numbers and encodings underneath are right.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from conftest import HEADER, row
from test_tariff import load, make_schedule

from energy_reconciliation.explorer import charts
from energy_reconciliation.tariff import analytics as ta
from energy_reconciliation.tariff.models import build_scenario

SCHEDULE = [
    ("2013-01-01 00:30:00", "High"),
    ("2013-01-01 01:00:00", "Low"),
    ("2013-06-01 00:30:00", "Normal"),
]


def _sample(tmp_path):
    """Two households, three bands, two months, plus one Std household.

    MAC000001: 2 kWh High (Jan) + 4 kWh Low (Jan) + 10 kWh Normal (Jun)
    MAC000002: 1 kWh High (Jan)
    MAC000009: Std, never charged
    """
    body = HEADER + b"".join(
        [
            row("MAC000001", "ToU", "2013-01-01 00:30:00.0000000", " 2 "),
            row("MAC000001", "ToU", "2013-01-01 01:00:00.0000000", " 4 "),
            row("MAC000001", "ToU", "2013-06-01 00:30:00.0000000", " 10 "),
            row("MAC000002", "ToU", "2013-01-01 00:30:00.0000000", " 1 "),
            row("MAC000009", "Std", "2013-01-01 00:30:00.0000000", " 7 "),
        ]
    )
    database = load(tmp_path, body)
    return database, build_scenario(database, make_schedule(SCHEDULE))


# ------------------------------------------------------------- scope separation
def test_the_three_scopes_give_three_different_answers(tmp_path):
    """Selected household, loaded sample and schedule are not the same number."""
    database, run = _sample(tmp_path)
    one = ta.band_summary(database, run.run_id, household="MAC000001")
    everyone = ta.band_summary(database, run.run_id)
    schedule = ta.schedule_totals(database)

    assert Decimal(one.attrs["denominator_kwh_exact"]) == Decimal(16)
    assert Decimal(everyone.attrs["denominator_kwh_exact"]) == Decimal(17)
    assert schedule.attrs["denominator_slots"] == 3
    assert one.attrs["denominator_readings"] == 3
    assert everyone.attrs["denominator_readings"] == 4


def test_the_schedule_view_ignores_household_and_period(tmp_path):
    """The published schedule is a property of the schedule, nothing else."""
    database, _ = _sample(tmp_path)
    totals = ta.schedule_totals(database)
    assert list(totals["band_label"]) == ["Low", "Normal", "High"]
    assert totals.attrs["denominator_slots"] == 3
    assert set(ta.schedule_band_distribution(database)["band_label"]) == {
        "Low",
        "Normal",
        "High",
    }


def test_schedule_bounds_drive_the_period_control(tmp_path):
    database, _ = _sample(tmp_path)
    assert ta.schedule_bounds(database) == (date(2013, 1, 1), date(2013, 6, 1))


def test_the_scenario_period_narrows_every_figure_together(tmp_path):
    """January only: the Normal reading in June leaves, and so does its charge.

    January = 2 kWh High + 4 kWh Low + 1 kWh High
            = 3 x 0.6720 + 4 x 0.0399 = 2.0160 + 0.1596 = 2.1756
    """
    database, run = _sample(tmp_path)
    january = ta.band_summary(
        database, run.run_id, start=date(2013, 1, 1), end=date(2013, 1, 31)
    )
    assert set(january["band_label"]) == {"Low", "High"}
    assert Decimal(january.attrs["denominator_charge_gbp_exact"]) == Decimal("2.1756")
    assert Decimal(january.attrs["denominator_kwh_exact"]) == Decimal(7)
    hours = ta.household_band_distribution(
        database, run.run_id, start=date(2013, 1, 1), end=date(2013, 1, 31)
    )
    assert set(hours["band_label"]) == {"Low", "High"}


def test_both_shares_use_the_same_rows(tmp_path):
    """A share of one scope against a share of another would be meaningless.

    Consumption share and charge share are computed from the same filtered frame, so
    each column sums to 1 before display rounding.
    """
    database, run = _sample(tmp_path)
    for start, end in [(None, None), (date(2013, 1, 1), date(2013, 1, 31))]:
        bands = ta.band_summary(database, run.run_id, start=start, end=end)
        kwh = sum(Decimal(v) for v in bands["kwh_exact"])
        charge = sum(Decimal(v) for v in bands["charge_gbp_exact"])
        assert kwh == Decimal(bands.attrs["denominator_kwh_exact"])
        assert charge == Decimal(bands.attrs["denominator_charge_gbp_exact"])
        assert abs(bands["consumption_share"].sum() - 1.0) < 0.001
        assert abs(bands["charge_share"].sum() - 1.0) < 0.001


# ------------------------------------------------------------- measured reasons
def test_a_std_household_gets_its_measured_reason_not_a_guess(tmp_path):
    database, run = _sample(tmp_path)
    reasons = ta.exclusion_breakdown(database, run.run_id, household="MAC000009")
    assert list(reasons["exclusion_reason"]) == ["ineligible_tariff_group"]
    assert int(reasons["readings"].iloc[0]) == 1
    assert ta.household_tariff_groups(database, "MAC000009") == ["Std"]
    assert ta.band_summary(database, run.run_id, household="MAC000009").empty


def test_an_explicit_switch_target_list_is_offered(tmp_path):
    database, run = _sample(tmp_path)
    assert ta.charged_households(database, run.run_id) == ["MAC000001", "MAC000002"]
    assert ta.charged_households(
        database, run.run_id, start=date(2013, 6, 1), end=date(2013, 6, 30)
    ) == ["MAC000001"]


# -------------------------------------------------------------- empty behaviour
def test_an_empty_selection_produces_no_zero_substitutes(tmp_path):
    database, run = _sample(tmp_path)
    empty = ta.band_summary(
        database, run.run_id, start=date(2013, 3, 1), end=date(2013, 3, 31)
    )
    assert empty.empty
    assert empty.attrs["denominator_readings"] == 0
    assert (
        list(empty.columns) == ta.BAND_SUMMARY_COLUMNS
    )  # shape kept, no rows invented

    spec = charts.band_share_chart(empty).to_dict()
    assert spec["mark"]["type"] == "text"
    assert "layer" not in spec
    assert set(spec["encoding"]) == {"text"}, "an empty state must encode no quantity"
    assert "x" not in spec["encoding"] and "y" not in spec["encoding"]


def test_an_empty_hour_chart_is_a_statement_not_an_axis(tmp_path):
    database, run = _sample(tmp_path)
    hours = ta.household_band_distribution(
        database, run.run_id, start=date(2013, 3, 1), end=date(2013, 3, 31)
    )
    spec = charts.band_kwh_by_hour_chart(hours).to_dict()
    assert spec["mark"]["type"] == "text"
    assert "y" not in spec["encoding"]


# ------------------------------------------------------------------ chart shape
def test_the_share_chart_is_horizontal_grouped_and_pinned_to_0_100(tmp_path):
    database, run = _sample(tmp_path)
    bands = ta.band_summary(database, run.run_id)
    spec = charts.band_share_chart(bands).to_dict()

    assert len(spec["layer"]) == 2, "bars plus their direct percentage labels"
    bars, labels = spec["layer"]
    assert bars["mark"]["type"] == "bar"
    assert labels["mark"]["type"] == "text"
    assert labels["encoding"]["text"]["field"] == "share_label"

    encoding = bars["encoding"]
    assert encoding["y"]["field"] == "band_label", "bands on the vertical axis"
    assert encoding["x"]["field"] == "share", "share on the horizontal axis"
    assert encoding["x"]["scale"]["domain"] == [0, 1], "one shared 0-100% axis"
    assert encoding["x"]["axis"]["format"] == "%"
    assert encoding["yOffset"]["field"] == "series", "grouped, not stacked"
    assert encoding["y"]["sort"] == ["Low", "Normal", "High"]
    assert encoding["yOffset"]["sort"] == list(charts.SERIES_ORDER)
    assert encoding["color"]["legend"]["title"] is None


def test_series_names_are_short_enough_to_sit_beside_a_bar():
    for name in charts.SERIES_ORDER:
        assert len(name) <= 12, f"{name!r} is long enough to collide with its neighbour"


def test_hour_charts_are_tall_enough_to_read(tmp_path):
    database, run = _sample(tmp_path)
    assert (
        charts.schedule_hour_chart(ta.schedule_band_distribution(database)).to_dict()[
            "height"
        ]
        >= 260
    )
    assert (
        charts.band_kwh_by_hour_chart(
            ta.household_band_distribution(database, run.run_id)
        ).to_dict()["height"]
        >= 260
    )


def test_share_labels_are_percentages_not_fractions(tmp_path):
    database, run = _sample(tmp_path)
    frame = charts.share_frame(ta.band_summary(database, run.run_id))
    assert all(label.endswith("%") for label in frame["share_label"])
    assert set(frame["series"]) == set(charts.SERIES_ORDER)
    assert len(frame) == 2 * len(set(frame["band_label"]))


def test_band_colours_and_order_are_cheapest_first():
    assert list(charts.BAND_COLOURS) == ["Low", "Normal", "High"]
    assert charts.BAND_ORDER == ta.BAND_ORDER


# --------------------------------------------------------- formatting contract
def test_display_rounding_matches_the_documented_rule():
    assert ta.round_energy(Decimal("1.23456")) == Decimal("1.235")
    assert ta.round_money(Decimal("1.005")) == Decimal("1.01")
    assert ta.round_share(Decimal("0.123456")) == Decimal("0.1235")


def test_exact_values_are_always_available_beside_the_rounded_ones(tmp_path):
    database, run = _sample(tmp_path)
    bands = ta.band_summary(database, run.run_id)
    for _, band in bands.iterrows():
        assert Decimal(band["kwh_exact"]) == Decimal(str(band["kwh_exact"]))
        assert float(band["kwh_display"]) == float(
            ta.round_energy(Decimal(band["kwh_exact"]))
        )
        assert float(band["charge_gbp_display"]) == float(
            ta.round_money(Decimal(band["charge_gbp_exact"]))
        )


def test_the_charge_scope_makes_no_claim_about_tax_treatment():
    """The publisher gives rates without stating their tax treatment."""
    scope = ta.CHARGE_SCOPE.lower()
    assert "no separate tax adjustment is applied" in scope
    assert "not established" in scope
    assert "excludes vat" not in scope
    assert "excluding vat" not in scope


# ---------------------------------------------- period scope must never leak
def test_the_excluded_household_breakdown_honours_the_scenario_period(tmp_path):
    """A period count must not silently become a whole-history count.

    MAC000009 is Std with one reading on 2013-01-01. Asked about June, the scoped
    breakdown is empty; asked about the whole history it is not. The app shows the
    scoped one, and falls back to whole history only under an explicit label.
    """
    database, run = _sample(tmp_path)
    scoped = ta.exclusion_breakdown(
        database,
        run.run_id,
        household="MAC000009",
        start=date(2013, 6, 1),
        end=date(2013, 6, 30),
    )
    whole = ta.exclusion_breakdown(database, run.run_id, household="MAC000009")
    assert scoped.empty
    assert int(whole["readings"].sum()) == 1


# ---------------------------------------------------------------- insights
def test_insights_come_from_the_selection_and_carry_their_denominators(tmp_path):
    """Hand-derived from the fixture, for the whole sample:
    High 3 kWh x 0.6720 = 2.0160 ; Low 4 x 0.0399 = 0.1596 ; Normal 10 x 0.1176 = 1.1760
    total 17 kWh, 3.3516 GBP; High = 17.6% of kWh, 60.2% of charge; schedule has 3 labels.
    """
    database, run = _sample(tmp_path)
    insights = ta.selection_insights(database, run.run_id)
    assert len(insights) == 3
    text = " ".join(i.headline for i in insights)
    assert "2 households are charged" in text
    assert "of the 3 half-hour labels" in text
    assert (
        "High band carries 17.6% of the charged kWh and 60.2% of the scenario charge"
        in text
    )
    assert "17.000 kWh" in text and "£3.35" in text and "4 charged readings" in text
    assert "does not show anyone responding" in text
    figures = insights[1].supporting
    assert figures["all charged kWh (exact)"] == "17.0000000000"
    assert figures["all scenario charge (exact)"] == "£3.3516000000000000"


def test_insights_update_with_household_and_period_and_vanish_when_empty(tmp_path):
    database, run = _sample(tmp_path)
    one = ta.selection_insights(database, run.run_id, household="MAC000001")
    assert "MAC000001 is charged for 3 of the 3 half-hour labels" in one[0].headline
    assert "limited observed coverage" not in one[0].headline
    assert "observed label coverage" in one[0].headline
    partial = ta.selection_insights(database, run.run_id, household="MAC000002")
    assert "MAC000002 is charged for 1 of the 3 half-hour labels" in partial[0].headline
    assert "not proof that every physical interval was metered" in partial[0].headline
    assert "Limited observed coverage in the loaded members" in partial[0].headline
    assert "not established" in partial[0].headline
    january = ta.selection_insights(
        database, run.run_id, start=date(2013, 1, 1), end=date(2013, 1, 31)
    )
    assert "of the 2 half-hour labels" in january[0].headline
    assert (
        ta.selection_insights(
            database, run.run_id, start=date(2013, 3, 1), end=date(2013, 3, 31)
        )
        == []
    )


def test_insights_never_use_the_language_of_bills_or_causes(tmp_path):
    database, run = _sample(tmp_path)
    text = " ".join(
        i.headline for i in ta.selection_insights(database, run.run_id)
    ).lower()
    for banned in (
        "bill",
        "saving",
        "because of",
        "caused",
        "in response to",
        "led to",
    ):
        assert banned not in text, banned


# ------------------------------------------------------- presentation defects
def test_share_labels_are_drawn_in_the_theme_text_colour(tmp_path):
    """Text marks default to black, which is invisible on the dark theme."""
    database, run = _sample(tmp_path)
    spec = charts.band_share_chart(ta.band_summary(database, run.run_id)).to_dict()
    labels = spec["layer"][1]["mark"]
    assert labels["type"] == "text"
    assert labels["color"] == charts.TEXT


def test_hour_axes_use_typed_number_formats(tmp_path):
    """A bare ',' leaves the type to the renderer; ',.0f' and ',~f' do not."""
    database, run = _sample(tmp_path)
    slots = charts.schedule_hour_chart(
        ta.schedule_band_distribution(database)
    ).to_dict()
    kwh = charts.band_kwh_by_hour_chart(
        ta.household_band_distribution(database, run.run_id)
    ).to_dict()
    assert slots["encoding"]["y"]["axis"]["format"] == ",.0f"
    assert kwh["encoding"]["y"]["axis"]["format"] == ",~f"
    for fmt in (",.0f", ",~f"):
        assert fmt[-1] in "fdeg%", "a d3 format type character must be present"


def test_the_coverage_denominator_bounds_every_household(tmp_path):
    """No household can be charged for more labels than the schedule carries in the period.

    A charged row is one distinct, undisputed reading per household per label, so the
    per-household count is bounded by the label count -- which is what makes "x of y
    labels" a valid statement for one household and for the sample alike.
    """
    database, run = _sample(tmp_path)
    totals = ta.household_totals(database, run.run_id)
    assert int(totals["charged_readings"].max()) <= 3
    sample = ta.selection_insights(database, run.run_id)[0]
    assert "observed label coverage per household" in sample.headline
    january = ta.household_totals(
        database, run.run_id, start=date(2013, 1, 1), end=date(2013, 1, 31)
    )
    assert int(january["charged_readings"].max()) <= 2
