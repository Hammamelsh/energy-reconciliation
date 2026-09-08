"""The single definition of the analytical policies used everywhere in this project.

Every rule here is **ours**, decided by this project. None of it is a publisher rule,
and none of it is evidence about what the meter did. It exists so that the explorer,
the tariff models and any future model layer resolve repetition, missing values and
off-grid timestamps the *same* way, rather than each re-deciding it in its own SQL.

The four rules, in the words used throughout the documentation:

- *Exact duplicate rows* -- identical raw text at one household and source timestamp
  label. Collapsed everywhere; the number collapsed is always reported.
- *Equivalent representations* -- different raw texts, one numeric value (``' 0.5 '``
  and ``' 0.50 '``). Both rows are kept as evidence; the value enters a total **once**.
- *Conflicts* -- more than one distinct value signature at one label, including a
  number beside a non-numeric token such as ``Null``. Any aggregate containing one is
  **withheld**. Nothing here infers which row the meter produced.
- *Off-grid observations* -- timestamps not on the half-hour grid. Excluded from
  half-hour analytical totals, never deleted, always counted and listed.

**Repeated naive labels remain semantically unresolved.** Collapsing two rows that
carry the same label and the same value is an analytical resolution, not proof that
they represent one physical interval: the timezone convention and the interval anchor
are unresolved, so a repeated label could in principle be two different half hours.
"""

from __future__ import annotations

from typing import Final

#: Consecutive grid readings are half an hour apart. A longer step between two
#: consecutive distinct grid labels is a gap -- including across midnight. It is an
#: observed step, not a confirmed missing interval or a meter failure: neither can be
#: established while the timezone and interval convention are unresolved.
EXPECTED_STEP_SECONDS: Final[int] = 1800

DUPLICATE_POLICY: Final[str] = (
    "identical source rows collapsed; equivalent numeric representations counted once"
)

#: Exact-source identity of a recorded row. Matches v_exact_duplicates in the warehouse.
TEXT_KEY: Final[str] = (
    "household_id, tariff_group, source_timestamp_text, consumption_raw_text"
)

#: What a reading *means*. The DECIMAL cast normalises scale, so ' 0.5 ' and ' 0.50 '
#: share a signature; non-numeric categories are kept distinct from every number.
SIGNATURE: Final[str] = (
    "COALESCE(CAST(consumption_kwh AS VARCHAR), '~' || value_category)"
)

#: The column that says whether a reading sits on the half-hour grid.
GRID: Final[str] = "on_half_hour_grid"

#: The value category that carries a usable number.
FINITE: Final[str] = "finite_numeric"

#: One row per *distinct recorded reading*: exact duplicates and equivalent numeric
#: representations both collapse to one row, a conflicting label keeps one row per
#: distinct signature, and every row keeps the columns a downstream model needs.
#:
#: This is the accounting unit for the tariff scenario. Its row count is what the
#: reconciliation identity balances:
#: ``distinct readings in scope = included in the scenario + excluded, with a reason``.
DISTINCT_READINGS: Final[str] = f"""
SELECT DISTINCT
       household_id,
       tariff_group,
       source_timestamp_text,
       observed_at_naive,
       {GRID}          AS on_half_hour_grid,
       consumption_kwh,
       value_category,
       {SIGNATURE}     AS value_signature
FROM readings
"""

#: Labels where the source does not agree with itself. Any aggregate touching one of
#: these is withheld, and every reading at such a label is excluded with a reason.
CONFLICTING_LABELS: Final[str] = f"""
SELECT household_id, source_timestamp_text
FROM readings
GROUP BY household_id, source_timestamp_text
HAVING COUNT(DISTINCT {SIGNATURE}) > 1
"""
