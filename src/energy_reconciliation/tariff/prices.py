"""The price catalogue. PUBLISHER-DOCUMENTED, quoted, never inferred.

The tariff workbook contains **a schedule of price bands, not prices** (ANL-001 §4):
no number, unit or currency appears anywhere in it. The prices below come from the
London Datastore dataset page, and the three dToU bands are independently corroborated
by the LCL Summary Report, p9.

Two things are deliberately *not* filled in:

- **The flat-rate effective dates are UNKNOWN.** The page states the price but not the
  period it applied to. They are ``None`` here and stay ``None`` in the warehouse. They
  are never defaulted to the span of the data, because the span of the data is evidence
  about when meters reported, not about when a price was in force. A ``None`` bound is
  **not** an open-ended one: a price with an unknown validity prices nothing.
- **No price is invented for a band or a group the publisher does not price.**
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Final

#: Bumping this forces a rebuild the same way a code change does, so a scenario built
#: from different prices can never be mistaken for one built from these.
PRICE_CATALOGUE_VERSION: Final[str] = "2026-09-08.1"

CITATION_PAGE: Final[str] = (
    "UK Power Networks, 'SmartMeter Energy Consumption Data in London Households', "
    "London Datastore dataset page, accessed 2026-09-06: "
    "https://data.london.gov.uk/dataset/"
    "smartmeter-energy-consumption-data-in-london-households-vqm0d"
)
CITATION_REPORT: Final[str] = (
    "Low Carbon London Summary Report, p9: 'The values of the price bands were: "
    "High price: 67.20 pence/kWh; Mid-price: 11.76 pence/kWh; and Low price: "
    "3.99 pence/kWh.' The page calls the 11.76 band 'normal'; the workbook labels it "
    "'Normal'; the report calls it 'Mid-price'. Same figure, three wordings."
)

#: The dToU trial ran, in the publisher's words, "throughout the 2013 calendar year
#: period". The workbook schedule's labels run from 2013-01-01 00:00 to 2013-12-31 23:30,
#: which agrees.
#:
#: **Validity is a half-open interval: ``[effective_from, effective_until)``.** The end
#: is *exclusive* and is the first instant the price no longer applies. A whole year is
#: therefore ``[2013-01-01, 2014-01-01)``. An inclusive end date of ``2013-12-31`` would
#: be a trap: compared against a timestamp it becomes ``2013-12-31 00:00:00``, and the
#: last 47 half hours of the year silently fall outside it.
TOU_EFFECTIVE_FROM: Final[date] = date(2013, 1, 1)
TOU_EFFECTIVE_UNTIL: Final[date] = date(2014, 1, 1)

#: The tariff group value that the dToU band prices apply to, as recorded in the
#: source's ``stdorToU`` column. Whether that flag is fixed per household or varies
#: over time is **UNKNOWN** (AQ-22/AQ-23) and is measured, not assumed, by
#: ``analytics.tariff_group_stability``.
TOU_GROUP: Final[str] = "ToU"
STD_GROUP: Final[str] = "Std"

#: The band label used for a group that has one price regardless of the schedule.
FLAT_BAND: Final[str] = "flat"


@dataclass(frozen=True, slots=True)
class Price:
    tariff_group: str
    band_label: str
    pence_per_kwh: Decimal
    effective_from: date | None
    effective_until: date | None  # exclusive; None means UNKNOWN, never "open-ended"
    evidence_label: str
    source_citation: str

    @property
    def gbp_per_kwh(self) -> Decimal:
        """The pence price divided by 100, exactly.

        Every documented price has at most three decimal places in pence, so this
        division is exact and introduces no rounding. ``tests/test_tariff.py`` asserts
        that for every row in the catalogue.
        """
        return self.pence_per_kwh / Decimal(100)


CATALOGUE: Final[tuple[Price, ...]] = (
    Price(
        TOU_GROUP,
        "High",
        Decimal("67.20"),
        TOU_EFFECTIVE_FROM,
        TOU_EFFECTIVE_UNTIL,
        "PUBLISHER-DOCUMENTED",
        f"{CITATION_PAGE} | {CITATION_REPORT}",
    ),
    Price(
        TOU_GROUP,
        "Normal",
        Decimal("11.76"),
        TOU_EFFECTIVE_FROM,
        TOU_EFFECTIVE_UNTIL,
        "PUBLISHER-DOCUMENTED",
        f"{CITATION_PAGE} | {CITATION_REPORT}",
    ),
    Price(
        TOU_GROUP,
        "Low",
        Decimal("3.99"),
        TOU_EFFECTIVE_FROM,
        TOU_EFFECTIVE_UNTIL,
        "PUBLISHER-DOCUMENTED",
        f"{CITATION_PAGE} | {CITATION_REPORT}",
    ),
    Price(
        STD_GROUP,
        FLAT_BAND,
        Decimal("14.228"),
        None,  # UNKNOWN -- the page gives the price, not the period
        None,  # UNKNOWN
        "PUBLISHER-DOCUMENTED",
        CITATION_PAGE,
    ),
)

#: Band labels the workbook actually uses, in the order the documentation lists them.
BAND_LABELS: Final[tuple[str, ...]] = ("High", "Normal", "Low")
