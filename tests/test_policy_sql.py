"""ANL-003 step 1: the policy SQL is parameterised by relation and by nothing else.

The refactor that introduced ``distinct_readings_sql`` had one job beyond making the
relation configurable: **not to change what the queries return**. The first test here is
the one that matters most — the default rendering must still be the exact text the
constants have always held, because a byte-identical query cannot have moved a figure.

The second concern is the interpolation itself. A relation name cannot be a bind
parameter in any database, so it is composed into the SQL as text. That makes validation
the only defence, and these tests exercise it with the strings that would matter.
"""

from __future__ import annotations

import pytest

from energy_reconciliation import policy


# ------------------------------------------------------- the default cannot have moved
def test_the_default_rendering_is_the_published_constant():
    assert policy.distinct_readings_sql() == policy.DISTINCT_READINGS
    assert policy.conflicting_labels_sql() == policy.CONFLICTING_LABELS


def test_the_default_relation_is_the_warehouse_table():
    assert policy.DEFAULT_READINGS_RELATION == "readings"
    assert "FROM readings\n" in policy.DISTINCT_READINGS
    assert "FROM readings\n" in policy.CONFLICTING_LABELS


def test_naming_a_relation_changes_the_from_clause_and_nothing_else():
    """The whole point of the parameter: where the rows come from, not what they are."""
    for render, default in (
        (policy.distinct_readings_sql, policy.DISTINCT_READINGS),
        (policy.conflicting_labels_sql, policy.CONFLICTING_LABELS),
    ):
        qualified = render("base.readings")
        assert qualified == default.replace("FROM readings", "FROM base.readings")
        # the parts that define the policy are untouched
        assert policy.SIGNATURE in qualified


def test_the_projection_and_grain_are_fixed_here_not_by_the_caller():
    sql = policy.distinct_readings_sql("anything.readings")
    assert "SELECT DISTINCT" in sql
    for column in (
        "household_id",
        "tariff_group",
        "source_timestamp_text",
        "observed_at_naive",
        "on_half_hour_grid",
        "consumption_kwh",
        "value_category",
        "value_signature",
    ):
        assert column in sql


# ------------------------------------------------------------- relation validation
@pytest.mark.parametrize(
    "relation",
    [
        "readings",
        "base.readings",
        "comp.readings",
        "memory.main.readings",
        '"dev"."scenario_build"."stg_readings"',  # how dbt's ref() renders
        '"odd ""quoted"" name"',
    ],
)
def test_a_relation_name_is_accepted(relation):
    assert f"FROM {relation}" in policy.distinct_readings_sql(relation)


@pytest.mark.parametrize(
    "hostile",
    [
        "readings; DROP TABLE readings",
        "readings WHERE 1=1",
        "readings --",
        "readings UNION ALL SELECT * FROM other",
        "(SELECT 1)",
        "",
        " ",
        "readings\nWHERE 1=1",
        "read ings",
    ],
)
def test_anything_that_is_not_a_relation_name_is_refused(hostile):
    """Refused, not escaped. There is no legitimate caller passing these."""
    with pytest.raises(policy.PolicyRelationError):
        policy.distinct_readings_sql(hostile)
    with pytest.raises(policy.PolicyRelationError):
        policy.conflicting_labels_sql(hostile)


@pytest.mark.parametrize(
    "placeholder",
    ["{{ readings }}", "{{ schedule }}", "{{ price }}", "{{ classified }}"],
)
def test_a_bare_jinja_variable_is_permitted_as_a_relation(placeholder):
    """dbt fills the relation in at compile time, so a macro body carries a token.

    The accepted shape is a **bare Jinja variable reference**, single-spaced, naming a
    lower-case identifier -- widened from the single ``{{ readings }}`` token in step 1
    because the tariff classification reads three relations, not one. It is still not a
    licence for arbitrary text: everything below is refused.
    """
    assert f"FROM {placeholder}" in policy.distinct_readings_sql(placeholder)


@pytest.mark.parametrize(
    "hostile",
    [
        "{{ readings }} WHERE 1=1",  # SQL after the reference
        "{{ readings|upper }}",  # a filter
        "{{ ref('x') }}",  # a call
        "{{ a.b }}",  # an attribute
        "{{readings}}",  # not the single-spaced form
        "{{ Readings }}",  # not lower case
        "{{ 1 }}",  # not an identifier
    ],
)
def test_anything_beyond_a_bare_jinja_variable_is_refused(hostile):
    with pytest.raises(policy.PolicyRelationError):
        policy.distinct_readings_sql(hostile)
