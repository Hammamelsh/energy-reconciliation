"""The tariff dimensions as **explicitly typed** Arrow tables.

Why this module exists
----------------------

``models._load_dimensions`` inserts these rows into tables whose types are declared by
``models.SCHEMA``, so DuckDB does the typing. A dbt Python model has no such declaration
to lean on: whatever the model returns is what the adapter creates. So the types have to
travel *with the data*, and that is what this module produces -- a ``pyarrow.Table`` whose
schema names ``decimal128(9, 4)`` and ``decimal128(9, 6)`` outright.

**Why not a pandas frame.** A pandas column of Python ``Decimal`` objects has dtype
``object``. Handing that to DuckDB invites it to infer, and the plausible inference is
``DOUBLE`` -- which is precisely the binary-float artefact the whole tariff calculation is
built to keep out of a money-adjacent figure. Arrow lets the scale be stated rather than
guessed, so nothing has to be trusted.

**The division is still done once, in Python.** ``price_gbp_per_kwh`` comes from
:attr:`energy_reconciliation.tariff.prices.Price.gbp_per_kwh`, an exact ``Decimal``
quotient. It is placed into a decimal column as a ``Decimal``: at no point is there a
float. This module performs no arithmetic of its own.

**Scales come from one place.** ``PRICE_SCALE`` and ``GBP_SCALE`` are imported from
:mod:`energy_reconciliation.tariff.models`, the same constants ``SCHEMA`` uses, so the
Arrow schema and the SQL schema cannot drift apart.

What this module does *not* carry
---------------------------------

``CREATE TABLE AS SELECT`` -- which is how dbt materialises a table -- copies column names
and types and **drops constraints**. So a dimension built through dbt has the same column
types as ``models.SCHEMA`` but not its ``PRIMARY KEY`` or ``NOT NULL``. That is a real
difference, not an oversight: uniqueness is asserted by dbt tests instead, and the
schedule's duplicate-label refusal happens earlier still, in ``schedule._validate``.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pyarrow as pa

from . import prices as pr
from . import schedule as sch
from .models import GBP_SCALE, PRICE_SCALE
from .schedule import Schedule

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

#: Decimal precision for both price columns, matching ``models.SCHEMA``.
PRICE_PRECISION: Final[int] = 9

#: Column order and types for ``dim_tariff_band_schedule``, mirroring ``models.SCHEMA``.
#: ``timestamp("us")`` because DuckDB's TIMESTAMP is microsecond-resolution.
SCHEDULE_SCHEMA: Final[pa.Schema] = pa.schema(
    [
        pa.field("schedule_label_naive", pa.timestamp("us"), nullable=False),
        pa.field("schedule_label_text", pa.string(), nullable=False),
        pa.field("band_label", pa.string(), nullable=False),
        pa.field("schedule_year", pa.int32(), nullable=False),
        pa.field("on_half_hour_grid", pa.bool_(), nullable=False),
        pa.field("schedule_source", pa.string(), nullable=False),
        pa.field("source_sha256", pa.string(), nullable=False),
        pa.field("loaded_at_utc", pa.timestamp("us"), nullable=False),
    ]
)

#: Column order and types for ``dim_tariff_price``, mirroring ``models.SCHEMA``. The two
#: decimal fields are the reason this module exists.
PRICE_SCHEMA: Final[pa.Schema] = pa.schema(
    [
        pa.field("tariff_group", pa.string(), nullable=False),
        pa.field("band_label", pa.string(), nullable=False),
        pa.field(
            "price_pence_per_kwh",
            pa.decimal128(PRICE_PRECISION, PRICE_SCALE),
            nullable=False,
        ),
        pa.field(
            "price_gbp_per_kwh",
            pa.decimal128(PRICE_PRECISION, GBP_SCALE),
            nullable=False,
        ),
        pa.field("currency", pa.string(), nullable=False),
        pa.field("price_unit", pa.string(), nullable=False),
        # Nullable on purpose: a price whose validity is UNKNOWN carries NULL bounds and
        # prices nothing. NULL here is "not established", never "open-ended".
        pa.field("effective_from", pa.date32(), nullable=True),
        pa.field("effective_until", pa.date32(), nullable=True),
        pa.field("evidence_label", pa.string(), nullable=False),
        pa.field("source_citation", pa.string(), nullable=False),
        pa.field("catalogue_version", pa.string(), nullable=False),
    ]
)


#: The two schedule sources a build may use. The values are the *variant names* a caller
#: passes; the resulting ``Schedule.source`` is ``Tariffs.xlsx`` or ``synthetic-demo``,
#: and that string is written onto **every row** of the dimension, so a table built from
#: the invented schedule can never be mistaken for one built from the publisher's
#: workbook by looking at the data.
WORKBOOK_VARIANT: Final[str] = "workbook"
DEMO_VARIANT: Final[str] = "demo"
SCHEDULE_VARIANTS: Final[tuple[str, ...]] = (WORKBOOK_VARIANT, DEMO_VARIANT)


class ScheduleVariantError(ValueError):
    """An unrecognised schedule variant. Never silently treated as the demo one."""


def default_workbook() -> Path:
    """The publisher's workbook, found without depending on the working directory.

    dbt is invoked with ``--project-dir dbt``, so a path relative to the caller's cwd is
    not dependable. This resolves against the installed package's own location instead.
    """
    relative = sch.DEFAULT_WORKBOOK
    if relative.is_file():
        return relative
    # src/energy_reconciliation/tariff/dimensions.py -> repository root
    return Path(__file__).resolve().parents[3] / relative


def resolve_schedule(
    variant: str = WORKBOOK_VARIANT, workbook: str | Path | None = None
) -> Schedule:
    """The schedule a build should use, by variant name.

    An unknown variant raises. It is never resolved to the demo schedule as a fallback:
    silently substituting invented data for the publisher's would be the single worst
    failure this project could have.
    """
    if variant == DEMO_VARIANT:
        return sch.demo_schedule()
    if variant == WORKBOOK_VARIANT:
        return sch.read_workbook(Path(workbook) if workbook else default_workbook())
    msg = (
        f"unknown schedule variant {variant!r}; expected one of {SCHEDULE_VARIANTS}. "
        "Refusing rather than defaulting: the demo schedule is invented data."
    )
    raise ScheduleVariantError(msg)


def schedule_table(schedule: Schedule, loaded_at: datetime) -> pa.Table:
    """The validated band schedule as a typed Arrow table.

    ``schedule`` has already passed ``schedule._validate``: a duplicated label or an
    off-grid label raised before this function was reachable. Nothing is re-checked here,
    because a second check in a second place is a second definition.
    """
    rows = schedule.rows
    return pa.table(
        {
            "schedule_label_naive": pa.array(
                [r.label for r in rows], pa.timestamp("us")
            ),
            "schedule_label_text": pa.array(
                [r.label.isoformat(sep=" ") for r in rows], pa.string()
            ),
            "band_label": pa.array([r.band_label for r in rows], pa.string()),
            "schedule_year": pa.array([r.label.year for r in rows], pa.int32()),
            "on_half_hour_grid": pa.array([True] * len(rows), pa.bool_()),
            "schedule_source": pa.array([schedule.source] * len(rows), pa.string()),
            "source_sha256": pa.array(
                [schedule.source_sha256] * len(rows), pa.string()
            ),
            "loaded_at_utc": pa.array([loaded_at] * len(rows), pa.timestamp("us")),
        },
        schema=SCHEDULE_SCHEMA,
    )


def price_table(catalogue: Sequence[pr.Price] | None = None) -> pa.Table:
    """The price catalogue as a typed Arrow table.

    Every value is taken from :data:`energy_reconciliation.tariff.prices.CATALOGUE`.
    ``price_gbp_per_kwh`` is the exact ``Decimal`` quotient computed there; this function
    divides nothing and rounds nothing.
    """
    entries = list(pr.CATALOGUE if catalogue is None else catalogue)
    return pa.table(
        {
            "tariff_group": pa.array([p.tariff_group for p in entries], pa.string()),
            "band_label": pa.array([p.band_label for p in entries], pa.string()),
            "price_pence_per_kwh": pa.array(
                [p.pence_per_kwh for p in entries],
                pa.decimal128(PRICE_PRECISION, PRICE_SCALE),
            ),
            "price_gbp_per_kwh": pa.array(
                [p.gbp_per_kwh for p in entries],
                pa.decimal128(PRICE_PRECISION, GBP_SCALE),
            ),
            "currency": pa.array(["GBP"] * len(entries), pa.string()),
            "price_unit": pa.array(["pence_per_kwh"] * len(entries), pa.string()),
            "effective_from": pa.array(
                [p.effective_from for p in entries], pa.date32()
            ),
            "effective_until": pa.array(
                [p.effective_until for p in entries], pa.date32()
            ),
            "evidence_label": pa.array(
                [p.evidence_label for p in entries], pa.string()
            ),
            "source_citation": pa.array(
                [p.source_citation for p in entries], pa.string()
            ),
            "catalogue_version": pa.array(
                [pr.PRICE_CATALOGUE_VERSION] * len(entries), pa.string()
            ),
        },
        schema=PRICE_SCHEMA,
    )
