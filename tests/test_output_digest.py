"""The canonical output digest: what it must see, and what it must not.

The digest it replaces summarised each table as a row count plus ``bit_xor`` of a row
hash. That summary is commutative, and two rows cancel: ``{1, 1, 2}`` and ``{2, 3, 3}``
produced the same count and the same XOR (measured, 2026-09-08). This one hashes the
**sorted stream of per-row hashes** over a self-delimiting text encoding, with the relation
name, ordered column names and types, and the row count in front. Every case below is a
property the contract promises; none is a proof that two equal digests mean equal tables.
"""

from __future__ import annotations

import duckdb
import pytest

from energy_reconciliation import dbt_run

SCHEMA = dbt_run.BUILD_SCHEMA


def _digest(*statements: str) -> str:
    con = duckdb.connect(":memory:")
    try:
        con.execute(f"CREATE SCHEMA {SCHEMA}")
        for statement in statements:
            con.execute(statement)
        return dbt_run.build_output_digest(con)
    finally:
        con.close()


def _table(name: str, columns: str, *rows: str) -> tuple[str, ...]:
    create = f"CREATE TABLE {SCHEMA}.{name}({columns})"
    if not rows:
        return (create,)
    return (create, f"INSERT INTO {SCHEMA}.{name} VALUES {', '.join(rows)}")


def test_the_digest_is_versioned_and_deterministic():
    assert dbt_run.OUTPUT_DIGEST_VERSION == "canonical-rows-1"
    a = _digest(*_table("a", "x INTEGER", "(1)", "(1)", "(2)"))
    assert a == _digest(*_table("a", "x INTEGER", "(1)", "(1)", "(2)"))
    assert len(a) == 64


def test_physical_row_order_does_not_matter():
    assert _digest(*_table("a", "x INTEGER", "(1)", "(1)", "(2)")) == _digest(
        *_table("a", "x INTEGER", "(2)", "(1)", "(1)")
    )


def test_the_measured_xor_collision_now_digests_differently():
    """{1,1,2} and {2,3,3}: equal count, equal bit_xor(hash) -- and now unequal digests."""
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE a AS SELECT * FROM (VALUES (1), (1), (2)) v(x)")
    con.execute("CREATE TABLE b AS SELECT * FROM (VALUES (2), (3), (3)) v(x)")
    xor = "SELECT COUNT(*), CAST(bit_xor(hash(t)) AS VARCHAR) FROM {} t"
    assert (
        con.execute(xor.format("a")).fetchone()
        == con.execute(xor.format("b")).fetchone()
    ), "the old summary really cannot tell them apart"
    con.close()
    assert _digest(*_table("a", "x INTEGER", "(1)", "(1)", "(2)")) != _digest(
        *_table("a", "x INTEGER", "(2)", "(3)", "(3)")
    )


def test_duplicate_multiplicity_is_seen():
    assert _digest(*_table("a", "x INTEGER", "(1)", "(1)", "(2)")) != _digest(
        *_table("a", "x INTEGER", "(1)", "(2)")
    )
    assert _digest(*_table("a", "x INTEGER", "(1)", "(2)")) != _digest(
        *_table("a", "x INTEGER", "(1)", "(2)", "(2)")
    )


def test_a_single_changed_value_is_seen():
    assert _digest(*_table("a", "x DECIMAL(9,4)", "(0.6720)", "(0.0399)")) != _digest(
        *_table("a", "x DECIMAL(9,4)", "(0.6720)", "(0.0398)")
    )


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("x INTEGER", "x BIGINT"),  # type
        ("x INTEGER", "y INTEGER"),  # column name
        ("x DECIMAL(9,4)", "x DECIMAL(9,6)"),  # scale
    ],
)
def test_a_schema_change_with_identical_values_is_seen(before, after):
    assert _digest(*_table("a", before, "(1)", "(2)")) != _digest(
        *_table("a", after, "(1)", "(2)")
    )


def test_the_relation_name_and_the_set_of_relations_are_seen():
    assert _digest(*_table("a", "x INTEGER", "(1)")) != _digest(
        *_table("b", "x INTEGER", "(1)")
    )
    assert _digest(*_table("a", "x INTEGER", "(1)")) != _digest(
        *_table("a", "x INTEGER", "(1)"), *_table("b", "x INTEGER")
    )


def test_null_is_distinct_from_every_string():
    null = _digest(*_table("a", "x VARCHAR", "(NULL)"))
    assert null != _digest(*_table("a", "x VARCHAR", "('')"))
    assert null != _digest(*_table("a", "x VARCHAR", "('N')"))
    assert null != _digest(*_table("a", "x VARCHAR", "('NULL')"))


def test_null_position_is_seen():
    assert _digest(*_table("a", "x VARCHAR, y VARCHAR", "(NULL, 'v')")) != _digest(
        *_table("a", "x VARCHAR, y VARCHAR", "('v', NULL)")
    )


def test_column_boundaries_are_unambiguous():
    """'ab'|'c' and 'a'|'bc' concatenate to the same text; the length prefix keeps them apart."""
    assert _digest(*_table("a", "x VARCHAR, y VARCHAR", "('ab', 'c')")) != _digest(
        *_table("a", "x VARCHAR, y VARCHAR", "('a', 'bc')")
    )
    # a value that itself looks like an encoded token
    assert _digest(*_table("a", "x VARCHAR, y VARCHAR", "('V1:a', 'b')")) != _digest(
        *_table("a", "x VARCHAR, y VARCHAR", "('V1:', 'ab')")
    )


def test_decimals_dates_timestamps_and_booleans_keep_their_exact_text():
    """0.6720 as DECIMAL(9,4) must never be read as the float 0.672."""
    con = duckdb.connect(":memory:")
    con.execute(
        "CREATE TABLE t(a DECIMAL(9,4), b DECIMAL(9,6), c DATE, d TIMESTAMP, e BOOLEAN)"
    )
    con.execute(
        "INSERT INTO t VALUES (0.6720, 0.006720, '2013-01-01', '2013-01-01 00:30:00', true)"
    )
    sql = dbt_run._canonical_rows_sql("main", "t", ["a", "b", "c", "d", "e"]).replace(
        "sha256(", "("
    )
    (text,) = con.execute(sql).fetchone()
    con.close()
    assert text == ("V6:0.6720V8:0.006720V10:2013-01-01V19:2013-01-01 00:30:00V4:true")


def test_the_attempt_record_and_views_are_not_part_of_the_digest():
    base = _table("a", "x INTEGER", "(1)", "(2)")
    assert _digest(*base) == _digest(
        *base,
        f"CREATE TABLE {SCHEMA}.{dbt_run._RECORD_TABLE}(z INTEGER)",
        f"INSERT INTO {SCHEMA}.{dbt_run._RECORD_TABLE} VALUES (9)",
    )
    assert _digest(*base) == _digest(
        *base, f"CREATE VIEW {SCHEMA}.v AS SELECT 1 AS one"
    )


def test_an_empty_table_still_contributes_its_schema():
    assert _digest(*_table("a", "x INTEGER")) != _digest(*_table("a", "x BIGINT"))
    assert _digest(*_table("a", "x INTEGER")) != _digest()


def test_the_subcommand_of_a_recorded_command_skips_flags():
    assert dbt_run.subcommand_of("build --target-path /x") == "build"
    assert dbt_run.subcommand_of("--debug build") == "build"
    assert dbt_run.subcommand_of("show --inline 'select 1'") == "show"
    assert dbt_run.subcommand_of("") == ""
