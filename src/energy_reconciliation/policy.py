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

import re
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

#: The relation the policy queries read when no other is named. Every caller that reads
#: a different one (an attached warehouse, a dbt model) passes it explicitly.
DEFAULT_READINGS_RELATION: Final[str] = "readings"

#: The relation placeholder used by the policy macros.
DBT_RELATION_PLACEHOLDER: Final[str] = "{{ readings }}"

#: dbt substitutes the real relation into a macro at compile time, so a *rendered macro
#: body* carries a placeholder rather than a name. Exactly one shape is accepted: a bare
#: Jinja variable reference, single-spaced, naming a lower-case identifier. That admits
#: ``{{ readings }}``, ``{{ schedule }}`` and ``{{ price }}`` -- the three relations the
#: tariff classification reads -- and admits nothing that could carry SQL: no filter, no
#: call, no attribute, no operator, no second statement.
_PLACEHOLDER_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^\{\{ [a-z_][a-z0-9_]* \}\}$"
)

#: A relation name: dot-separated parts, each a bare identifier or a double-quoted one
#: (``"dev"."main"."stg_readings"``, which is how dbt's ``ref()`` renders). Anchored, so
#: nothing may follow -- a trailing ``WHERE``, a comment or a second statement is refused
#: rather than concatenated into the query.
_RELATION_PART = r'(?:[A-Za-z_][A-Za-z0-9_$]*|"(?:[^"]|"")+")'
_RELATION_PATTERN: Final[re.Pattern[str]] = re.compile(
    rf"^{_RELATION_PART}(?:\.{_RELATION_PART})*$"
)


class PolicyRelationError(ValueError):
    """A relation name was not an identifier, so it was not interpolated into SQL.

    These queries are built by string composition, which is the only way to share one
    SQL definition across DuckDB connections and dbt. A relation name is not a bind
    parameter -- no database accepts one -- so it is validated instead of trusted.
    """


def validated_relation(relation: str) -> str:
    """A relation name, or :class:`PolicyRelationError`. Public because the tariff models
    compose SQL over the same relations and must apply the same rule, not a second one."""
    if _PLACEHOLDER_PATTERN.match(relation):
        return relation
    if not _RELATION_PATTERN.match(relation):
        msg = (
            f"{relation!r} is not a relation name. Expected an identifier, optionally "
            "schema-qualified and optionally quoted, and nothing after it."
        )
        raise PolicyRelationError(msg)
    return relation


def distinct_readings_sql(relation: str = DEFAULT_READINGS_RELATION) -> str:
    """One row per *distinct recorded reading*, read from ``relation``.

    Exact duplicates and equivalent numeric representations both collapse to one row, a
    conflicting label keeps one row per distinct signature, and every row keeps the
    columns a downstream model needs.

    This is the accounting unit for the tariff scenario. Its row count is what the
    reconciliation identity balances:
    ``distinct readings in scope = included in the scenario + excluded, with a reason``.

    ``relation`` exists so that **one** definition serves every caller: the warehouse
    (``readings``), an attached warehouse in a comparison (``base.readings``), and a dbt
    model (the placeholder dbt fills in). It changes where the rows come from and
    nothing else -- the projection, the DISTINCT and the signature are fixed here.
    """
    return f"""
SELECT DISTINCT
       household_id,
       tariff_group,
       source_timestamp_text,
       observed_at_naive,
       {GRID}          AS on_half_hour_grid,
       consumption_kwh,
       value_category,
       {SIGNATURE}     AS value_signature
FROM {validated_relation(relation)}
"""


def conflicting_labels_sql(relation: str = DEFAULT_READINGS_RELATION) -> str:
    """Labels where the source does not agree with itself, read from ``relation``.

    Any aggregate touching one of these is withheld, and every reading at such a label
    is excluded with a reason.
    """
    return f"""
SELECT household_id, source_timestamp_text
FROM {validated_relation(relation)}
GROUP BY household_id, source_timestamp_text
HAVING COUNT(DISTINCT {SIGNATURE}) > 1
"""


#: The default renderings, kept as constants because most callers read the warehouse's
#: own ``readings`` table. **Byte-identical to the pre-parameterisation constants**, so
#: this refactor cannot have changed a stored figure; the equality is asserted in
#: ``tests/test_policy_sql.py``.
DISTINCT_READINGS: Final[str] = distinct_readings_sql()
CONFLICTING_LABELS: Final[str] = conflicting_labels_sql()
