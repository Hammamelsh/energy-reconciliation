"""Simple lag-based baselines, and the rules for refusing to predict.

Every model here answers one question at a forecast origin: *given only the usable daily
totals dated on or before this origin, what is the total for a date after it?*

**A model may return no prediction.** If the day a model needs is not usable, it returns
``None`` with a reason instead of substituting a zero, the series mean, or the nearest
available day. Substituting would turn "we cannot say" into a number that is then scored,
which flatters or punishes a model for data quality rather than for forecasting.

None of these models sees a calendar, a temperature, a tariff or a price. They see one
household's earlier daily totals and nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Final, Protocol

from .dataset import HouseholdSeries

WEEK: Final[int] = 7

#: Same-weekday weeks averaged by ``weekday_mean``. Fixed in advance, not searched.
WEEKDAY_MEAN_WEEKS: Final[int] = 4

NO_LAG: Final[str] = "lag_day_not_usable"
NO_WEEKDAY_HISTORY: Final[str] = "insufficient_same_weekday_history"
NO_ORIGIN: Final[str] = "origin_day_not_usable"


@dataclass(frozen=True, slots=True)
class Prediction:
    value: Decimal | None
    reason: str | None = None
    inputs: tuple[date, ...] = ()

    @property
    def made(self) -> bool:
        return self.value is not None


class Model(Protocol):
    name: str
    description: str

    def predict(
        self, series: HouseholdSeries, origin: date, target: date
    ) -> Prediction: ...


def _guard(origin: date, target: date) -> None:
    if target <= origin:
        msg = f"target {target} is not after the forecast origin {origin}"
        raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class SeasonalNaiveWeek:
    """The same source weekday one week earlier.

    For a horizon of 1..7 days the referenced date is ``target - 7``, which is always on
    or before the origin, so the model can never see the future.
    """

    name: str = "seasonal_naive_7"
    description: str = "the same source weekday from the previous week"

    def predict(
        self, series: HouseholdSeries, origin: date, target: date
    ) -> Prediction:
        _guard(origin, target)
        lag = target - timedelta(days=WEEK)
        if lag > origin:
            return Prediction(None, "lag_day_after_origin")
        value = series.at(lag)
        if value is None:
            return Prediction(None, NO_LAG)
        return Prediction(value, None, (lag,))


@dataclass(frozen=True, slots=True)
class WeekdayMean:
    """The mean of the corresponding weekday over the most recent ``weeks`` weeks.

    Uses only dates on or before the origin, and requires the full complement: with
    fewer than ``weeks`` usable same-weekday dates it declines rather than averaging
    whatever happens to be there, which would silently change the estimator between
    households.
    """

    weeks: int = WEEKDAY_MEAN_WEEKS
    name: str = "weekday_mean_4"
    description: str = "average of the corresponding weekday over the previous 4 weeks"

    def __post_init__(self) -> None:
        if self.weeks < 1:
            msg = "weekday mean needs at least one week of history"
            raise ValueError(msg)

    def predict(
        self, series: HouseholdSeries, origin: date, target: date
    ) -> Prediction:
        _guard(origin, target)
        used: list[date] = []
        values: list[Decimal] = []
        day = target - timedelta(days=WEEK)
        while len(values) < self.weeks and day >= series.run_start:
            if day <= origin:
                value = series.at(day)
                if value is not None:
                    values.append(value)
                    used.append(day)
            day -= timedelta(days=WEEK)
        if len(values) < self.weeks:
            return Prediction(None, NO_WEEKDAY_HISTORY)
        total = sum(values, Decimal(0))
        return Prediction(total / Decimal(len(values)), None, tuple(reversed(used)))


@dataclass(frozen=True, slots=True)
class LastObservedDay:
    """The origin day's own total, repeated across the horizon.

    A reference point rather than a candidate: it carries no weekly structure at all, so
    the gap between it and the two weekday models is the value of knowing the weekday.
    """

    name: str = "persistence_1"
    description: str = "the origin day's total, repeated (reference)"

    def predict(
        self, series: HouseholdSeries, origin: date, target: date
    ) -> Prediction:
        _guard(origin, target)
        value = series.at(origin)
        if value is None:
            return Prediction(None, NO_ORIGIN)
        return Prediction(value, None, (origin,))


def default_models() -> tuple[Model, ...]:
    """The two the experiment compares, plus one reference. Fixed before evaluation."""
    return (SeasonalNaiveWeek(), WeekdayMean(), LastObservedDay())
