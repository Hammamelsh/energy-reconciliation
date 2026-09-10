"""The same charged readings priced two ways: the dynamic scenario and the flat price.

A **fixed-consumption historical price comparison** (ANL-005). The recorded consumption
is held constant and priced under the dynamic band schedule -- which is what the scenario
fact already stores -- and, hypothetically, under the publisher-documented flat price.
It establishes nothing about what anyone paid or saved, about behaviour, or about London;
the households on the dynamic tariff might have consumed differently on a flat one, and
no standing charge, levy or tax is modelled.

Two assumptions travel with every output. **A1** is the scenario's own (a consumption
label and a schedule label denote the same half hour). **A2** is this comparison's: the
flat price is applied to every selected charged reading throughout the period, even
though its effective dates are UNKNOWN. A2 is why the comparison exists as a labelled
*what-if* rather than as a stored figure.

Everything here is reporting code: it reads the certified facts through ``Relations`` and
prices them with the flat row of the **same build's** price dimension, never with
today's ``prices.py``, so a published version is compared under the catalogue it was
built with. Nothing in this module can change a stored figure, and it is deliberately
outside the calculation identity (``identity.py``).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Final

import pandas as pd

from . import analytics as ta
from . import prices as pr
from . import reads

DEFINITION: Final[str] = "flat-comparison-1"

A2_ID: Final[str] = "A2"
A2_TEXT: Final[str] = (
    "The publisher-documented flat price is hypothetically applied to every selected "
    "charged reading throughout the scenario period. Its effective dates are UNKNOWN; "
    "this is a comparison assumption, not a claim about when the price was in force."
)

#: How a household's exact difference (flat minus dynamic) is classified.
LOWER, HIGHER, EQUAL = "lower", "higher", "equal"

#: Why a comparison could not be made. Each is a distinct state the caller can name.
EMPTY, NO_PRICE, NON_UNIQUE_PRICE, INVALID_PRICE = (
    "empty",
    "no_price",
    "non_unique_price",
    "invalid_price",
)

ZERO: Final[Decimal] = Decimal(0)
HUNDRED: Final[Decimal] = Decimal(100)


@dataclass(frozen=True, slots=True)
class Unavailable:
    """The comparison cannot be made. The dynamic-tariff figures are unaffected."""

    kind: str
    reason: str


@dataclass(frozen=True, slots=True)
class FlatPrice:
    """The flat price row as this build stored it, with everything that identifies it."""

    tariff_group: str
    band_label: str
    price_pence_per_kwh: Decimal
    price_gbp_per_kwh: Decimal
    catalogue_version: str
    evidence_label: str
    source_citation: str
    effective_from: date | None
    effective_until: date | None

    @property
    def validity(self) -> str:
        if self.effective_from is None or self.effective_until is None:
            return "UNKNOWN"
        return f"[{self.effective_from}, {self.effective_until})"


@dataclass(frozen=True, slots=True)
class Totals:
    """Pooled figures for one selection. Every value exact; nothing rounded."""

    households: int
    readings: int
    kwh: Decimal
    dynamic: Decimal
    flat: Decimal

    @property
    def difference(self) -> Decimal:
        """Flat minus dynamic: positive means the dynamic scenario is lower."""
        return self.flat - self.dynamic

    @property
    def pct_of_flat(self) -> Decimal | None:
        """The difference as a percentage of the flat-price charge; None if that is 0."""
        return None if self.flat == ZERO else self.difference / self.flat * HUNDRED


@dataclass(frozen=True, slots=True)
class FlatComparison:
    definition: str
    run_id: str
    route: str
    price: FlatPrice
    assumption_ids: tuple[str, ...]
    household: str | None
    period: tuple[date | None, date | None]
    schedule_slots_in_period: int
    totals: Totals
    households: list[dict]  # one per charged household: exact strings + outcome
    outcomes: dict[str, int]  # LOWER / HIGHER / EQUAL -> households

    @property
    def households_frame(self) -> pd.DataFrame:
        """The same rows as a frame, for charts and tables. Values stay as text."""
        return pd.DataFrame(self.households, dtype=object)

    @property
    def variation(self) -> dict[str, str]:
        """How the pooled difference is spread, stated only as measured."""
        if not self.households:
            return {}
        diffs = [Decimal(r["difference_exact"]) for r in self.households]
        largest_i = max(range(len(diffs)), key=lambda i: abs(diffs[i]))
        largest = self.households[largest_i]
        pooled = self.totals.difference
        share = None if pooled == ZERO else diffs[largest_i] / pooled * HUNDRED
        ordered = sorted(diffs)
        n = len(ordered)
        median = (
            ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2
        )
        return {
            "largest_household": str(largest["household_id"]),
            "largest_difference_exact": str(diffs[largest_i]),
            "largest_share_of_pooled_pct": None if share is None else str(share),
            "median_household_difference_exact": str(median),
        }

    def to_json(self) -> dict:
        s, e = self.period
        return {
            "definition": self.definition,
            "run_id": self.run_id,
            "route": self.route,
            "assumption_ids": list(self.assumption_ids),
            "assumptions": {"A1": ta_assumption_text(), A2_ID: A2_TEXT},
            "price": {
                **{
                    k: str(v) if isinstance(v, Decimal) else v
                    for k, v in asdict(self.price).items()
                },
                "effective_from": None
                if self.price.effective_from is None
                else str(self.price.effective_from),
                "effective_until": None
                if self.price.effective_until is None
                else str(self.price.effective_until),
                "validity": self.price.validity,
            },
            "selection": {
                "household": self.household,
                "start": None if s is None else str(s),
                "end": None if e is None else str(e),
                "schedule_slots_in_period": self.schedule_slots_in_period,
            },
            "totals": {
                "households": self.totals.households,
                "charged_readings": self.totals.readings,
                "kwh_exact": str(self.totals.kwh),
                "dynamic_charge_gbp_exact": str(self.totals.dynamic),
                "flat_charge_gbp_exact": str(self.totals.flat),
                "flat_minus_dynamic_gbp_exact": str(self.totals.difference),
                "pct_of_flat_exact": (
                    None
                    if self.totals.pct_of_flat is None
                    else str(self.totals.pct_of_flat)
                ),
                "pct_denominator": "flat_charge_gbp_exact",
            },
            "outcomes_under_dynamic": dict(self.outcomes),
            "variation": self.variation,
            "households": list(self.households),
        }


def ta_assumption_text() -> str:
    from .models import ASSUMPTION_TEXT

    return ASSUMPTION_TEXT


# ------------------------------------------------------------------ the price
def flat_price(
    database: Path, *, relations: ta.Relations = ta.WAREHOUSE_RELATIONS
) -> FlatPrice | Unavailable:
    """The flat row of this build's price dimension, or why there is not exactly one."""
    con = ta._con(database)
    try:
        rows = con.execute(
            "SELECT tariff_group, band_label, price_pence_per_kwh, price_gbp_per_kwh, "
            "catalogue_version, evidence_label, source_citation, effective_from, "
            f"effective_until FROM {relations.dim_price} WHERE tariff_group = ? "
            "ORDER BY band_label",
            [pr.STD_GROUP],
        ).fetchall()
    finally:
        con.close()
    if not rows:
        return Unavailable(
            NO_PRICE,
            f"this build's price dimension ({relations.dim_price}) holds no "
            f"`{pr.STD_GROUP}` price, so there is no flat price to apply",
        )
    if len(rows) > 1:
        return Unavailable(
            NON_UNIQUE_PRICE,
            f"this build's price dimension holds {len(rows)} `{pr.STD_GROUP}` rows "
            f"({', '.join(r[1] for r in rows)}); which one is the flat price is not "
            "decidable here",
        )
    r = rows[0]
    gbp = None if r[3] is None else Decimal(str(r[3]))
    if gbp is None or not gbp.is_finite() or gbp <= ZERO:
        return Unavailable(
            INVALID_PRICE, f"the stored flat price is {r[3]!r}, which prices nothing"
        )
    return FlatPrice(
        tariff_group=r[0],
        band_label=r[1],
        price_pence_per_kwh=Decimal(str(r[2])),
        price_gbp_per_kwh=gbp,
        catalogue_version=r[4],
        evidence_label=r[5],
        source_citation=r[6],
        effective_from=r[7],
        effective_until=r[8],
    )


# ------------------------------------------------------------- the comparison
def compare(
    database: Path,
    run_id: str,
    household: str | None = None,
    start: date | None = None,
    end: date | None = None,
    *,
    relations: ta.Relations = ta.WAREHOUSE_RELATIONS,
) -> FlatComparison | Unavailable:
    """Price exactly the selected charged rows two ways. Same scope helper as the tab."""
    price = flat_price(database, relations=relations)
    if isinstance(price, Unavailable):
        return price
    where, params = ta._fact_scope(run_id, household, start, end)
    slot_where, slot_params = ta._period(
        "1 = 1", [], start, end, "CAST(schedule_label_naive AS DATE)"
    )
    con = ta._con(database)
    try:
        rows = con.execute(
            "SELECT household_id, COUNT(*), MIN(source_date), MAX(source_date), "
            "SUM(consumption_kwh), SUM(energy_charge_gbp), "
            "SUM(CAST(consumption_kwh * CAST(? AS DECIMAL(9,6)) AS DECIMAL(38,16))) "
            f"FROM {relations.fact_scenario} WHERE {where} GROUP BY 1 ORDER BY 1",
            [str(price.price_gbp_per_kwh), *params],
        ).fetchall()
        pooled = con.execute(
            "SELECT COUNT(*), COALESCE(SUM(consumption_kwh), 0), "
            "COALESCE(SUM(energy_charge_gbp), 0), "
            "COALESCE(SUM(CAST(consumption_kwh * CAST(? AS DECIMAL(9,6)) "
            "AS DECIMAL(38,16))), 0) "
            f"FROM {relations.fact_scenario} WHERE {where}",
            [str(price.price_gbp_per_kwh), *params],
        ).fetchone()
        slots = int(
            con.execute(
                f"SELECT COUNT(*) FROM {relations.dim_schedule} WHERE {slot_where}",
                slot_params,
            ).fetchone()[0]
        )
    finally:
        con.close()
    if not rows:
        scope = household or "the selected households"
        return Unavailable(
            EMPTY,
            f"no charged readings for {scope} in this period -- there is nothing to "
            "price, and nothing is zero",
        )

    records = []
    outcomes = {LOWER: 0, HIGHER: 0, EQUAL: 0}
    for hh, n, first, last, kwh, dyn, flat in rows:
        kwh, dyn, flat = Decimal(str(kwh)), Decimal(str(dyn)), Decimal(str(flat))
        diff = flat - dyn
        outcome = LOWER if diff > ZERO else HIGHER if diff < ZERO else EQUAL
        outcomes[outcome] += 1
        records.append(
            {
                "household_id": hh,
                "charged_readings": int(n),
                "first_charged_date": str(first),
                "last_charged_date": str(last),
                "schedule_slots_in_period": slots,
                "coverage_share": str(Decimal(int(n)) / Decimal(slots))
                if slots
                else None,
                "kwh_exact": str(kwh),
                "dynamic_charge_gbp_exact": str(dyn),
                "flat_charge_gbp_exact": str(flat),
                "difference_exact": str(diff),
                "pct_of_flat_exact": None
                if flat == ZERO
                else str(diff / flat * HUNDRED),
                "outcome_under_dynamic": outcome,
            }
        )
    totals = Totals(
        households=len(rows),
        readings=int(pooled[0]),
        kwh=Decimal(str(pooled[1])),
        dynamic=Decimal(str(pooled[2])),
        flat=Decimal(str(pooled[3])),
    )
    # Reconciliation, asserted: households sum to the pooled figures, and the per-row
    # exact arithmetic equals SUM(kWh) x price because nothing was rounded anywhere.
    assert sum(Decimal(r["flat_charge_gbp_exact"]) for r in records) == totals.flat
    assert (
        sum(Decimal(r["dynamic_charge_gbp_exact"]) for r in records) == totals.dynamic
    )
    assert sum(r["charged_readings"] for r in records) == totals.readings
    assert totals.flat == totals.kwh * price.price_gbp_per_kwh, (
        "per-row exact products must sum to the product of the sums"
    )
    return FlatComparison(
        definition=DEFINITION,
        run_id=run_id,
        route=relations.label,
        price=price,
        assumption_ids=(
            *ta.assumption_ids(database, run_id, relations=relations),
            A2_ID,
        ),
        household=household,
        period=(start, end),
        schedule_slots_in_period=slots,
        totals=totals,
        households=records,
        outcomes=outcomes,
    )


# --------------------------------------------------------------------- report
def render(result: FlatComparison | Unavailable) -> str:
    if isinstance(result, Unavailable):
        return f"flat-price comparison unavailable ({result.kind}): {result.reason}"
    t = result.totals
    s, e = result.period
    pct = (
        "undefined (flat-price charge is 0)"
        if t.pct_of_flat is None
        else f"{t.pct_of_flat}"
    )
    lines = [
        (
            f"ANL-005 fixed-consumption price comparison ({result.definition}) · run "
            f"{result.run_id} · route {result.route}"
        ),
        (
            f"  selection     : {result.household or 'all charged households'}, "
            f"{s or 'schedule start'} to {e or 'schedule end'} · "
            f"{t.households} household(s), {t.readings:,} charged readings, {t.kwh} kWh"
        ),
        (
            f"  flat price    : {result.price.price_pence_per_kwh} p/kWh "
            f"(£{result.price.price_gbp_per_kwh}/kWh), catalogue "
            f"{result.price.catalogue_version}, {result.price.evidence_label}, "
            f"validity {result.price.validity}"
        ),
        f"  assumptions   : {', '.join(result.assumption_ids)}",
        f"  dynamic charge: GBP {t.dynamic}",
        f"  flat charge   : GBP {t.flat}",
        f"  flat - dynamic: GBP {t.difference}  (positive = dynamic scenario lower)",
        f"  % of flat     : {pct}",
        (
            f"  households    : {result.outcomes[LOWER]} lower under dynamic, "
            f"{result.outcomes[HIGHER]} higher, {result.outcomes[EQUAL]} equal "
            "(exact differences)"
        ),
    ]
    v = result.variation
    if v:
        share = v["largest_share_of_pooled_pct"]
        lines.append(
            f"  variation     : largest household difference GBP "
            f"{v['largest_difference_exact']} ({v['largest_household']})"
            + (f", {Decimal(share):.1f}% of the pooled difference" if share else "")
            + f"; median household difference GBP {v['median_household_difference_exact']}"
        )
    lines.append(
        "  not shown     : what anyone paid or saved, behaviour, tariff advice, or "
        "anything beyond the loaded sample"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="compare-flat-price",
        description=(
            "Price exactly the same charged readings under the dynamic scenario and the "
            "publisher-documented flat price (ANL-005). A fixed-consumption historical "
            "comparison under assumptions A1 and A2; not a bill, a saving or advice."
        ),
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--database", type=Path, help="a warehouse (Python scenario)")
    source.add_argument(
        "--published-root", type=Path, help="a publication root (certified dbt build)"
    )
    parser.add_argument("--household")
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument(
        "--output", type=Path, help="write the JSON report (names household ids)"
    )
    args = parser.parse_args(argv)
    try:
        context = (
            reads.published(args.published_root)
            if args.published_root
            else reads.warehouse(args.database or Path("data/warehouse/energy.duckdb"))
        )
    except (reads.ReadContextError, FileNotFoundError) as error:
        print(f"compare-flat-price: {error}", file=sys.stderr)
        return 2
    result = compare(
        context.database,
        context.run_id,
        args.household,
        args.start,
        args.end,
        relations=context.relations,
    )
    print(render(result))
    if isinstance(result, Unavailable):
        return 1
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        payload = result.to_json()
        payload["source"] = {
            "label": context.label,
            "database": str(context.database),
            "version": context.version,
            "version_file": context.version_file,
        }
        args.output.write_text(json.dumps(payload, indent=1))
        print(f"  report        : {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
