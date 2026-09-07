"""Pure classification of a single source field. No I/O, no state, no interpretation.

These functions decide only what a value *is*, never what it *means*. Nothing here
converts a timezone, fills a gap, or treats an absent reading as zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Final

# The documented source contract, established by evidence in docs/source-data-profile.md.
EXPECTED_HEADER: Final[tuple[str, ...]] = (
    "LCLid",
    "stdorToU",
    "DateTime",
    "KWH/hh (per half hour) ",  # the trailing space is part of the real column name
)
EXPECTED_HEADER_LINE: Final[bytes] = (
    b"LCLid,stdorToU,DateTime,KWH/hh (per half hour) \r\n"
)
EXPECTED_FIELD_COUNT: Final[int] = len(EXPECTED_HEADER)

#: The only missing-value token observed in the source (Phase E). Case-sensitive on
#: purpose: `NULL` and `null` are different strings and must be reported, not absorbed.
NULL_TOKEN: Final[str] = "Null"

#: Observed timestamp format, e.g. "2012-10-12 00:30:00.0000000".
#: %f consumes six fractional digits; the source supplies seven, so a literal 0 follows.
TIMESTAMP_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S.%f0"

#: Half-hourly grid: readings are expected exactly on :00:00 and :30:00.
GRID_MINUTES: Final[frozenset[int]] = frozenset({0, 30})

# Mutually exclusive consumption categories. Together they partition every
# structurally valid record exactly once.
FINITE_NUMERIC: Final[str] = "finite_numeric"
NULL_TOKEN_CATEGORY: Final[str] = "null_token"
EMPTY: Final[str] = "empty"
UNEXPECTED_TOKEN: Final[str] = "unexpected_token"
NON_FINITE_NUMERIC: Final[str] = "non_finite_numeric"

CONSUMPTION_CATEGORIES: Final[tuple[str, ...]] = (
    FINITE_NUMERIC,
    NULL_TOKEN_CATEGORY,
    EMPTY,
    UNEXPECTED_TOKEN,
    NON_FINITE_NUMERIC,
)


@dataclass(frozen=True, slots=True)
class ConsumptionResult:
    """What a raw consumption field is. `value` is set only for finite numbers."""

    category: str
    value: Decimal | None
    raw: str
    had_surrounding_whitespace: bool

    @property
    def is_zero(self) -> bool:
        # A diagnostic flag, not a category: zeros are a subset of finite numbers.
        return self.value is not None and self.value == 0

    @property
    def is_negative(self) -> bool:
        return self.value is not None and self.value < 0


@dataclass(frozen=True, slots=True)
class TimestampResult:
    """What a raw timestamp field is. No timezone is attached at any point."""

    valid: bool
    raw: str
    parsed: datetime | None
    on_grid: bool | None


def classify_consumption(raw: str) -> ConsumptionResult:
    """Classify one raw consumption field into exactly one category.

    Source values are space-padded (`' 0.2 '`), so the field is stripped before
    comparison. `Decimal` is used rather than `float` for exact decimal arithmetic,
    and non-finite values (NaN, Infinity) are rejected into their own category
    instead of being accepted -- a single NaN reaching a SUM silently poisons it.
    """
    stripped = raw.strip()
    padded = raw != stripped

    if stripped == "":
        return ConsumptionResult(EMPTY, None, raw, padded)

    if stripped == NULL_TOKEN:
        return ConsumptionResult(NULL_TOKEN_CATEGORY, None, raw, padded)

    try:
        value = Decimal(stripped)
    except (InvalidOperation, ValueError, ArithmeticError):
        # Includes other casings such as "NULL"/"null", which must surface, not vanish.
        return ConsumptionResult(UNEXPECTED_TOKEN, None, raw, padded)

    if not value.is_finite():
        # Decimal("NaN") and Decimal("Infinity") parse successfully. They must not pass.
        return ConsumptionResult(NON_FINITE_NUMERIC, None, raw, padded)

    return ConsumptionResult(FINITE_NUMERIC, value, raw, padded)


def classify_timestamp(raw: str) -> TimestampResult:
    """Validate the documented timestamp format. Assigns no timezone; converts nothing.

    `on_grid` records whether the instant falls on the half-hourly grid. Off-grid rows
    are flagged and preserved -- never dropped -- because they still occupy a row.
    """
    try:
        # DTZ007 is suppressed deliberately. Ruff warns that strptime without %z
        # produces a naive datetime -- which is exactly what this project requires.
        # The source timestamps carry no offset and their timezone convention is
        # UNKNOWN (see docs/source-data-profile.md section 14). Attaching a timezone
        # here would invent information and silently bake a guess into every result.
        parsed = datetime.strptime(raw, TIMESTAMP_FORMAT)  # noqa: DTZ007
    except ValueError:
        return TimestampResult(False, raw, None, None)

    on_grid = (
        parsed.minute in GRID_MINUTES and parsed.second == 0 and parsed.microsecond == 0
    )
    return TimestampResult(True, raw, parsed, on_grid)


def normalised_value_key(result: ConsumptionResult) -> str:
    """A comparison key for 'do two rows mean the same consumption?'.

    Finite numbers compare by numeric value, so `' 0.2 '` and `'0.200'` are equal.
    Everything else compares by its exact raw text, so an unexpected token never
    silently equals a different unexpected token.
    """
    if result.category == FINITE_NUMERIC and result.value is not None:
        return f"num:{result.value.normalize():f}"
    return f"{result.category}:{result.raw}"


def check_header(observed: list[str]) -> dict[str, object]:
    """Compare an observed header row against the documented contract."""
    return {
        "expected": list(EXPECTED_HEADER),
        "observed": list(observed),
        "matches": tuple(observed) == EXPECTED_HEADER,
        "expected_field_count": EXPECTED_FIELD_COUNT,
        "observed_field_count": len(observed),
        "fourth_column_trailing_space_preserved": (
            len(observed) > 3 and observed[3] != observed[3].rstrip()
        ),
    }
