"""Pure classifier tests. Known input, known category, no I/O."""

from decimal import Decimal

import pytest

from energy_reconciliation.profiling import validation as v


@pytest.mark.parametrize(
    ("raw", "category", "value"),
    [
        (" 0.143 ", v.FINITE_NUMERIC, Decimal("0.143")),
        (" 0 ", v.FINITE_NUMERIC, Decimal(0)),
        (" -1.5 ", v.FINITE_NUMERIC, Decimal("-1.5")),
        ("0.2", v.FINITE_NUMERIC, Decimal("0.2")),
        ("Null", v.NULL_TOKEN_CATEGORY, None),
        ("", v.EMPTY, None),
        ("    ", v.EMPTY, None),
        ("NULL", v.UNEXPECTED_TOKEN, None),  # different casing must NOT be absorbed
        ("null", v.UNEXPECTED_TOKEN, None),
        ("N/A", v.UNEXPECTED_TOKEN, None),
        ("abc", v.UNEXPECTED_TOKEN, None),
        (" nan ", v.NON_FINITE_NUMERIC, None),
        ("NaN", v.NON_FINITE_NUMERIC, None),
        (" Infinity ", v.NON_FINITE_NUMERIC, None),
        ("-inf", v.NON_FINITE_NUMERIC, None),
    ],
)
def test_classify_consumption(raw, category, value):
    result = v.classify_consumption(raw)
    assert result.category == category
    assert result.value == value


def test_non_finite_never_becomes_a_number():
    """A NaN reaching a SUM silently poisons it, so it must never be a finite value."""
    for raw in ("nan", "NaN", "Infinity", "-Infinity"):
        assert v.classify_consumption(raw).value is None


def test_zero_and_negative_are_subsets_of_finite():
    zero = v.classify_consumption(" 0 ")
    neg = v.classify_consumption(" -0.5 ")
    assert zero.category == neg.category == v.FINITE_NUMERIC
    assert zero.is_zero and not zero.is_negative
    assert neg.is_negative and not neg.is_zero


def test_padding_is_detected_but_not_stripped_from_raw():
    result = v.classify_consumption(" 0.2 ")
    assert result.had_surrounding_whitespace
    assert result.raw == " 0.2 "  # original preserved
    assert result.value == Decimal("0.2")


@pytest.mark.parametrize(
    ("raw", "valid", "on_grid"),
    [
        ("2012-10-12 00:30:00.0000000", True, True),
        ("2012-10-12 00:00:00.0000000", True, True),
        ("2012-12-19 12:37:27.0000000", True, False),  # off-grid seconds
        ("2012-10-12 00:15:00.0000000", True, False),  # off-grid minutes
        ("not-a-timestamp", False, None),
        ("2012-10-12T00:30:00Z", False, None),  # ISO form is not this format
        ("2012-13-45 00:30:00.0000000", False, None),
        ("", False, None),
    ],
)
def test_classify_timestamp(raw, valid, on_grid):
    result = v.classify_timestamp(raw)
    assert result.valid is valid
    assert result.on_grid is on_grid
    assert result.raw == raw


def test_timestamp_carries_no_timezone():
    result = v.classify_timestamp("2012-10-12 00:30:00.0000000")
    assert result.parsed is not None
    assert result.parsed.tzinfo is None  # naive on purpose: convention is UNKNOWN


def test_normalised_value_key_matches_same_number_different_text():
    a = v.classify_consumption(" 0.2 ")
    b = v.classify_consumption("0.200")
    assert v.normalised_value_key(a) == v.normalised_value_key(b)


def test_normalised_value_key_separates_unlike_tokens():
    a = v.classify_consumption("Null")
    b = v.classify_consumption("NULL")
    assert v.normalised_value_key(a) != v.normalised_value_key(b)


def test_header_check_detects_missing_trailing_space():
    good = list(v.EXPECTED_HEADER)
    bad = good[:3] + ["KWH/hh (per half hour)"]  # trailing space removed
    assert v.check_header(good)["matches"] is True
    assert v.check_header(bad)["matches"] is False
    assert v.check_header(good)["fourth_column_trailing_space_preserved"] is True
    assert v.check_header(bad)["fourth_column_trailing_space_preserved"] is False
