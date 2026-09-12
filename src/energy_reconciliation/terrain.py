"""One year of half hours: the terrain behind the comparison. Contract ``energy-terrain-1``.

What it is
----------

For every date label and half-hour label the published schedule covers, the pooled charged
kWh and dynamic scenario charge of the households in the comparison, with the number of
charged readings and households that contributed and the band the schedule assigned to
that half hour. It is read from the same certified charged facts as the comparison, through
the same validated context, and :func:`build_terrain` refuses to return a payload unless its
sums reproduce the comparison's exact totals and the band summary, row for row.

What a cell is
--------------

A cell is one (date label, half-hour label) pair. Labels are the timestamps as written in
the source; no timezone or interval convention is applied (assumption A1). A cell with no
charged reading is ``null``, never zero: nothing is filled. A cell whose readings sum to
zero is ``0``. Cells are discrete; nothing is smoothed or interpolated between them.

Coverage
--------

Every cell carries how many charged readings and households it pools. A pooled height
therefore moves when coverage changes as well as when recorded usage does, and the file
says so rather than normalising or extrapolating anything.

Values
------

Per-cell values are display values rounded once here in ``Decimal`` (kWh to 3 dp, charge
to 2 dp), for heights and readouts. They are not exact and must not be summed in the
browser; every total in the file (grid, band, month) is an exact decimal string computed
here from the unrounded sums. Reading and household counts are exact integers.

Nothing here is household-level: no household id appears in the file.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Final

from .tariff import analytics as ta
from .tariff import flat_comparison as fc
from .tariff import reads

DEFINITION: Final[str] = "energy-terrain-1"
TERRAIN_NAME: Final[str] = "terrain.json"
SLOTS: Final[int] = 48
BAND_CODES: Final[dict[str, str]] = {"Low": "L", "Normal": "N", "High": "H"}
BAND_ORDER: Final[tuple[str, ...]] = ("Low", "Normal", "High")

CAVEATS: Final[tuple[str, ...]] = (
    (
        "Labels, not clock time: each cell is a timestamp label as written in the source. "
        "No timezone or interval convention is applied (assumption A1)."
    ),
    (
        "Pooled, with coverage: a cell adds the charged readings of the households present "
        "in that half hour. A height also moves when coverage changes, not only when "
        "recorded usage does; the readout shows how many households each cell pools."
    ),
    (
        "Discrete cells: nothing is smoothed or interpolated between labels. A cell with no "
        "charged reading is empty, not zero."
    ),
    (
        "Cell values are display values rounded once in the export (kWh to 3 decimal places, "
        "charge to 2). The totals shown are exact, computed in the export from the unrounded "
        "sums; the browser never adds cells."
    ),
    (
        "A historical fixed-consumption scenario under assumption A1, not a bill and not "
        "evidence of any response to price."
    ),
)


class TerrainError(RuntimeError):
    """The terrain cannot be produced from this context, or does not reconcile. Never a
    fallback: a payload that failed to reconcile is not returned."""


def _slot(hour: int, minute: int) -> int:
    return hour * 2 + minute // 30


def _slot_labels() -> list[str]:
    return [f"{s // 2:02d}:{(s % 2) * 30:02d}" for s in range(SLOTS)]


def _energy(value: Decimal) -> dict[str, Any]:
    return {
        "exact": str(value),
        "unit": "kWh",
        "display": float(ta.round_energy(value)),
    }


def _money(value: Decimal) -> dict[str, Any]:
    return {"exact": str(value), "unit": "GBP", "display": float(ta.round_money(value))}


def _schedule_cells(
    context: reads.ReadContext,
) -> tuple[dict[tuple[date, int], str], int]:
    """Band per (date, slot) from the schedule dimension, and how many schedule labels
    were not on the half-hour grid (they cannot be cells and are counted, not dropped
    silently)."""
    con = ta._con(context.database)
    try:
        rows = con.execute(
            "SELECT CAST(schedule_label_naive AS DATE), "
            "CAST(EXTRACT(hour FROM schedule_label_naive) AS INTEGER), "
            "CAST(EXTRACT(minute FROM schedule_label_naive) AS INTEGER), "
            "CAST(EXTRACT(second FROM schedule_label_naive) AS INTEGER), "
            "band_label, on_half_hour_grid "
            f"FROM {context.relations.dim_schedule} ORDER BY 1, 2, 3"
        ).fetchall()
    finally:
        con.close()
    bands: dict[tuple[date, int], str] = {}
    off_grid = 0
    for d, h, m, s, band, on_grid in rows:
        if not on_grid or m not in (0, 30) or s != 0:
            off_grid += 1
            continue
        key = (d, _slot(h, m))
        if key in bands and bands[key] != band:
            raise TerrainError(
                f"the schedule assigns two bands to {d} slot {key[1]}: "
                f"{bands[key]} and {band}. Refusing."
            )
        bands[key] = band
    return bands, off_grid


def _fact_cells(context: reads.ReadContext) -> tuple[list[tuple], int]:
    """Pooled charged readings per (date, hour, minute) of the timestamp label, and the
    distinct households across the whole run."""
    where, params = ta._fact_scope(context.run_id, None, None, None)
    con = ta._con(context.database)
    try:
        rows = con.execute(
            "SELECT CAST(observed_at_naive AS DATE) AS d, "
            "CAST(EXTRACT(hour FROM observed_at_naive) AS INTEGER) AS h, "
            "CAST(EXTRACT(minute FROM observed_at_naive) AS INTEGER) AS m, "
            "COUNT(*) AS readings, COUNT(DISTINCT household_id) AS households, "
            "SUM(consumption_kwh) AS kwh, SUM(energy_charge_gbp) AS charge, "
            "MIN(band_label), MAX(band_label), "
            "COUNT(*) FILTER (WHERE EXTRACT(second FROM observed_at_naive) <> 0 "
            "OR source_date <> CAST(observed_at_naive AS DATE)) AS irregular "
            f"FROM {context.relations.fact_scenario} WHERE {where} "
            "GROUP BY 1, 2, 3 ORDER BY 1, 2, 3",
            params,
        ).fetchall()
        households = con.execute(
            f"SELECT COUNT(DISTINCT household_id) FROM {context.relations.fact_scenario} "
            f"WHERE {where}",
            params,
        ).fetchone()[0]
    finally:
        con.close()
    return rows, int(households)


def build_terrain(context: reads.ReadContext) -> dict[str, Any]:
    """The terrain payload for one validated context, reconciled or refused."""
    if context.identity is None:
        raise TerrainError("the terrain needs a validated dbt build (a publication)")
    bounds = ta.schedule_bounds(context.database, relations=context.relations)
    if bounds is None:
        raise TerrainError("the schedule dimension is empty; there are no cells")
    first, last = bounds
    dates = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    date_index = {d: i for i, d in enumerate(dates)}
    n_cells = len(dates) * SLOTS

    schedule, schedule_off_grid = _schedule_cells(context)
    band_codes: list[str] = []
    for d in dates:
        for s in range(SLOTS):
            band = schedule.get((d, s))
            band_codes.append(BAND_CODES.get(band, "?") if band else "-")
    if "?" in band_codes:
        raise TerrainError("the schedule carries a band outside Low, Normal and High")

    stamped = ta.assumption_ids(
        context.database, context.run_id, relations=context.relations
    )
    if not stamped:
        raise TerrainError("the charged rows carry no assumption id")
    rows, households_total = _fact_cells(context)
    readings = [0] * n_cells
    households = [0] * n_cells
    kwh_exact: list[Decimal | None] = [None] * n_cells
    charge_exact: list[Decimal | None] = [None] * n_cells
    for d, h, m, n, hh, kwh, charge, band_min, band_max, irregular in rows:
        if irregular:
            raise TerrainError(
                f"{irregular} charged reading(s) on {d} carry seconds or a source_date "
                "that disagrees with the label. Refusing: charged facts must be on-grid."
            )
        if m not in (0, 30):
            raise TerrainError(
                f"charged readings on {d} at minute {m}: not a half-hour label. Refusing."
            )
        if d not in date_index:
            raise TerrainError(
                f"charged readings on {d}, outside the schedule's {first} to {last}. "
                "Refusing: the comparison excludes readings outside the schedule."
            )
        slot = _slot(h, m)
        if band_min != band_max:
            raise TerrainError(f"{d} slot {slot} charges under two bands. Refusing.")
        expected = schedule.get((d, slot))
        if expected != band_min:
            raise TerrainError(
                f"{d} slot {slot} is charged as {band_min} but the schedule says "
                f"{expected}. Refusing."
            )
        i = date_index[d] * SLOTS + slot
        readings[i] = int(n)
        households[i] = int(hh)
        kwh_exact[i] = Decimal(str(kwh))
        charge_exact[i] = Decimal(str(charge))

    present = [i for i in range(n_cells) if readings[i]]
    total_readings = sum(readings)
    total_kwh = sum((kwh_exact[i] for i in present), Decimal(0))
    total_charge = sum((charge_exact[i] for i in present), Decimal(0))

    # ------------------------------------------------------------ reconciliation
    comparison = fc.compare(
        context.database, context.run_id, relations=context.relations
    )
    if isinstance(comparison, fc.Unavailable):
        raise TerrainError(
            f"flat-price comparison unavailable ({comparison.kind}): {comparison.reason}"
        )
    t = comparison.totals
    checks = {
        "charged_readings": total_readings == t.readings,
        "households": households_total == t.households,
        "kwh_exact": total_kwh == t.kwh,
        "charge_exact": total_charge == t.dynamic,
    }
    band_frame = ta.band_summary(
        context.database, context.run_id, relations=context.relations
    )
    band_rows = {r["band_label"]: r for r in band_frame.to_dict(orient="records")}
    by_band = []
    for band in BAND_ORDER:
        code = BAND_CODES[band]
        cells_in_band = [i for i in range(n_cells) if band_codes[i] == code]
        idx = [i for i in cells_in_band if readings[i]]
        b_readings = sum(readings[i] for i in idx)
        b_kwh = sum((kwh_exact[i] for i in idx), Decimal(0))
        b_charge = sum((charge_exact[i] for i in idx), Decimal(0))
        ref = band_rows.get(band)
        if ref is None:
            ok = b_readings == 0
            price = None
        else:
            ok = (
                b_readings == int(ref["readings"])
                and str(b_kwh) == ref["kwh_exact"]
                and str(b_charge) == ref["charge_gbp_exact"]
            )
            price = str(Decimal(str(ref["price_pence_per_kwh"])))
        checks[f"band_{band}"] = ok
        by_band.append(
            {
                "band": band,
                "price_pence_per_kwh": price,
                "cells": len(cells_in_band),
                "cells_with_readings": len(idx),
                "charged_readings": b_readings,
                "kwh": _energy(b_kwh),
                "charge": _money(b_charge),
            }
        )
    if not all(checks.values()):
        failed = sorted(k for k, v in checks.items() if not v)
        raise TerrainError(
            f"the terrain does not reconcile with the comparison: {', '.join(failed)}. "
            "Nothing is written."
        )

    # ------------------------------------------------------------------ months
    by_month: list[dict[str, Any]] = []
    for i_month, month in enumerate(sorted({d.strftime("%Y-%m") for d in dates})):
        cells_in_month = [
            di * SLOTS + s
            for di, d in enumerate(dates)
            if d.strftime("%Y-%m") == month
            for s in range(SLOTS)
        ]
        idx = [i for i in cells_in_month if readings[i]]
        m_kwh = sum((kwh_exact[i] for i in idx), Decimal(0))
        m_charge = sum((charge_exact[i] for i in idx), Decimal(0))
        bands: dict[str, Any] = {}
        for band in BAND_ORDER:
            code = BAND_CODES[band]
            b_idx = [i for i in idx if band_codes[i] == code]
            bands[band] = {
                "cells": sum(1 for i in cells_in_month if band_codes[i] == code),
                "charged_readings": sum(readings[i] for i in b_idx),
                "kwh": _energy(sum((kwh_exact[i] for i in b_idx), Decimal(0))),
                "charge": _money(sum((charge_exact[i] for i in b_idx), Decimal(0))),
            }
        by_month.append(
            {
                "month": month,
                "index": i_month,
                "cells": len(cells_in_month),
                "cells_with_readings": len(idx),
                "charged_readings": sum(readings[i] for i in idx),
                "households_min": min((households[i] for i in idx), default=0),
                "households_max": max((households[i] for i in idx), default=0),
                "kwh": _energy(m_kwh),
                "charge": _money(m_charge),
                "bands": bands,
            }
        )

    # ------------------------------------------------------------------- peaks
    def _cell(i: int) -> dict[str, Any]:
        di, s = divmod(i, SLOTS)
        return {
            "date": str(dates[di]),
            "slot": s,
            "slot_label": _slot_labels()[s],
            "band": next(b for b, c in BAND_CODES.items() if c == band_codes[i]),
            "kwh": _energy(kwh_exact[i]),
            "charge": _money(charge_exact[i]),
            "charged_readings": readings[i],
            "households": households[i],
        }

    peak_kwh = max(present, key=lambda i: (kwh_exact[i], -i), default=None)
    peak_charge = max(present, key=lambda i: (charge_exact[i], -i), default=None)
    max_kwh = kwh_exact[peak_kwh] if peak_kwh is not None else Decimal(0)
    max_charge = charge_exact[peak_charge] if peak_charge is not None else Decimal(0)

    hh_present = [households[i] for i in present]
    return {
        "definition": DEFINITION,
        "title": "One year, 17,520 half-hours"
        if n_cells == 17520
        else f"{len(dates)} date label{'s' if len(dates) != 1 else ''}, "
        f"{n_cells:,} half-hours",
        "source": {
            "run_id": context.run_id,
            "version": context.version,
            "file_sha256": context.identity.file_sha256,
            "tariff_group": context.identity.tariff_group,
            "schedule_source": context.identity.schedule_source,
            "comparison_definition": comparison.definition,
        },
        # The assumption stamped on the charged rows these cells pool (A1 on both routes).
        # The flat-price comparison the file reconciles with carries its own list, A2
        # included; that list is recorded under ``reconciliation`` where it belongs.
        "assumption_ids": list(stamped),
        "assumption_scope": (
            "the assumption(s) stamped on every charged row these cells pool; the "
            "flat-price comparison's assumptions are listed under reconciliation"
        ),
        "grid": {
            "dates": len(dates),
            "slots": SLOTS,
            "cells": n_cells,
            "order": "date-major: index = date_index * 48 + slot",
            "first_date": str(first),
            "last_date": str(last),
            "date_labels": [str(d) for d in dates],
            "slot_labels": _slot_labels(),
            "label_meaning": (
                "the date and half hour of the timestamp label as written in the source; "
                "no timezone or interval convention applied"
            ),
            "schedule_labels_off_grid": schedule_off_grid,
        },
        "cells": {
            "band": "".join(band_codes),
            "band_codes": {v: k for k, v in BAND_CODES.items()},
            "readings": readings,
            "households": households,
            "kwh": [
                None if v is None else float(ta.round_energy(v)) for v in kwh_exact
            ],
            "charge": [
                None if v is None else float(ta.round_money(v)) for v in charge_exact
            ],
        },
        "cell_values": {
            "kwh": {"unit": "kWh", "decimals": 3},
            "charge": {"unit": "GBP", "decimals": 2},
            "rounding": "half up, once, in Decimal, in the export",
            "null_means": "no charged reading in that cell; distinct from a recorded 0",
            "not_additive": (
                "cell values are rounded for display; totals come from the exact sums "
                "below, never from adding cells"
            ),
        },
        "scale": {
            "kwh": {"min": 0, "max": float(ta.round_energy(max_kwh)), "unit": "kWh"},
            "charge": {
                "min": 0,
                "max": float(ta.round_money(max_charge)),
                "unit": "GBP",
            },
            "zero_based": True,
        },
        "coverage": {
            "households_in_comparison": households_total,
            "cells_with_readings": len(present),
            "cells_without_readings": n_cells - len(present),
            "households_per_cell_min": min(hh_present, default=0),
            "households_per_cell_max": max(hh_present, default=0),
            "readings_per_cell_min": min((readings[i] for i in present), default=0),
            "readings_per_cell_max": max((readings[i] for i in present), default=0),
        },
        "totals": {
            "charged_readings": total_readings,
            "households": households_total,
            "kwh": _energy(total_kwh),
            "charge": _money(total_charge),
        },
        "by_band": by_band,
        "by_month": by_month,
        "peaks": {
            "kwh": _cell(peak_kwh) if peak_kwh is not None else None,
            "charge": _cell(peak_charge) if peak_charge is not None else None,
        },
        "reconciliation": {
            "compared_with": comparison.definition,
            "compared_with_assumption_ids": list(comparison.assumption_ids),
            "checks": checks,
            "all_hold": True,
        },
        "caveats": list(CAVEATS),
    }


def summary(terrain: dict[str, Any]) -> dict[str, Any]:
    """The part of the terrain the bundle carries: enough to introduce the section and
    name its file, without the cell arrays."""
    return {
        "definition": terrain["definition"],
        "file": TERRAIN_NAME,
        "title": terrain["title"],
        "grid": {
            k: terrain["grid"][k]
            for k in ("dates", "slots", "cells", "first_date", "last_date")
        },
        "coverage": dict(terrain["coverage"]),
        "totals": dict(terrain["totals"]),
        "scale": dict(terrain["scale"]),
        "peaks": dict(terrain["peaks"]),
        "reconciliation": dict(terrain["reconciliation"]),
    }
