"""End-to-end profiler tests against synthetic archives with known answers."""

from __future__ import annotations

import json
from decimal import Decimal

from conftest import HEADER as HEADER_BYTES
from conftest import MEMBER, build_archive
from conftest import row as make_row

from energy_reconciliation.profiling import validation as v
from energy_reconciliation.profiling.cli import main
from energy_reconciliation.profiling.report import profile_member, write_json_atomically


def run(tmp_path, payload: bytes, member: str = MEMBER):
    archive = build_archive(tmp_path, {member: payload})
    report, examples = profile_member(archive, member, work_dir=tmp_path)
    return report, examples


# -- categories and counts ----------------------------------------------------


def test_mixed_member_known_counts(tmp_path, mixed_member):
    report, _ = run(tmp_path, mixed_member)
    c = report["counts"]
    assert report["status"] == "COMPLETE"
    assert c["data_records_excluding_header"] == 12
    assert c["malformed_records"] == 0
    assert c["structurally_valid_records"] == 12

    cats = report["consumption"]["categories_mutually_exclusive"]
    assert cats[v.FINITE_NUMERIC] == 6  # 0.143, 0, -1.5, 0.5, 0.2, 0.2
    assert cats[v.NULL_TOKEN_CATEGORY] == 2
    assert cats[v.EMPTY] == 1
    assert cats[v.UNEXPECTED_TOKEN] == 1  # "NULL"
    assert cats[v.NON_FINITE_NUMERIC] == 2  # nan, Infinity

    diag = report["consumption"]["diagnostics_overlapping"]
    assert diag["zeros"] == 1
    assert diag["negatives"] == 1

    ts = report["timestamps"]
    assert ts["invalid_format"] == 1
    assert ts["off_grid"] == 1
    assert ts["valid_format"] == 11
    assert ts["on_grid"] == 10


def test_zeros_are_not_a_separate_category(tmp_path, mixed_member):
    """Zeros must never be added to the partition: they are inside finite_numeric."""
    report, _ = run(tmp_path, mixed_member)
    cats = report["consumption"]["categories_mutually_exclusive"]
    diag = report["consumption"]["diagnostics_overlapping"]
    assert diag["zeros"] <= cats[v.FINITE_NUMERIC]
    assert sum(cats.values()) == report["counts"]["structurally_valid_records"]


def test_all_core_partitions_hold(tmp_path, mixed_member):
    report, _ = run(tmp_path, mixed_member)
    recon = report["reconciliation"]
    assert recon["all_core_partitions_hold"] is True
    for eq in recon["core_partitions"]:
        assert eq["holds"], eq


# -- structure ----------------------------------------------------------------


def test_wrong_field_counts_are_malformed_not_silently_dropped(
    tmp_path, wrong_field_count_member
):
    report, _ = run(tmp_path, wrong_field_count_member)
    c = report["counts"]
    assert c["data_records_excluding_header"] == 4
    assert c["malformed_records"] == 2
    assert c["structurally_valid_records"] == 2
    assert c["malformed_field_count_distribution"] == {"3": 1, "5": 1}
    assert report["reconciliation"]["all_core_partitions_hold"] is True


def test_wrong_header_is_reported_not_accepted(tmp_path, wrong_header_member):
    report, _ = run(tmp_path, wrong_header_member)
    assert report["header"]["matches"] is False
    assert report["header"]["fourth_column_trailing_space_preserved"] is False


# -- lines versus records -----------------------------------------------------


def test_quoted_newline_makes_lines_and_records_differ(tmp_path, multiline_member):
    """The prediction fixture: 4 physical lines, 3 logical records.

    This is why 'raw lines == header + parsed + rejected' cannot be assumed.
    """
    report, _ = run(tmp_path, multiline_member)
    lvr = report["lines_vs_records"]
    assert lvr["physical_lines"] == 5  # header + 4 line breaks in the body
    assert lvr["logical_records_excluding_header"] == 3
    assert lvr["one_line_per_record_holds"] is False
    recon = report["reconciliation"]
    # The physical-shape check does not hold -- and must not be treated as an error.
    assert recon["all_source_shape_checks_hold"] is False
    # Every LOGICAL partition still reconciles. That separation is the whole point.
    assert recon["all_core_partitions_hold"] is True
    for eq in recon["core_partitions"]:
        assert eq["holds"], eq


def test_normal_member_has_one_line_per_record(tmp_path, mixed_member):
    report, _ = run(tmp_path, mixed_member)
    assert report["lines_vs_records"]["one_line_per_record_holds"] is True


# -- duplicates ---------------------------------------------------------------


def test_duplicate_equality_rules_are_distinct(tmp_path, duplicates_member):
    report, _ = run(tmp_path, duplicates_member)
    dup = report["duplicates"]
    assert dup["exact_source_row_equality"]["groups"] == 1
    assert dup["exact_source_row_equality"]["extra_rows"] == 1
    assert dup["candidate_key_collisions"]["colliding_keys"] == 3
    assert dup["candidate_key_collisions"]["extra_rows"] == 3
    assert dup["candidate_key_collisions"]["conflicting_groups"] == 1


def test_same_meaning_different_text_is_not_a_conflict(tmp_path, duplicates_member):
    """' 0.200 ' and ' 0.2 ' share a key but do not conflict: same number."""
    report, _ = run(tmp_path, duplicates_member)
    conflicts = report["duplicates"]["examples_conflicting"]
    assert len(conflicts) == 1
    assert conflicts[0]["timestamp_text"] == "2012-10-12 01:30:00.0000000"


def test_duplicates_do_not_break_the_partition(tmp_path, duplicates_member):
    report, _ = run(tmp_path, duplicates_member)
    assert report["reconciliation"]["all_core_partitions_hold"] is True
    assert report["counts"]["records_ok"] == 6  # every duplicate is still valid


# -- households ---------------------------------------------------------------


def test_no_completeness_claim_for_split_household(tmp_path, split_household_members):
    """MAC000002 spans both members. Neither report may imply the household ends."""
    archive = build_archive(tmp_path, split_household_members)
    names = sorted(split_household_members)
    r0, _ = profile_member(archive, names[0], work_dir=tmp_path)
    r1, _ = profile_member(archive, names[1], work_dir=tmp_path)

    def obs(report, lclid):
        return next(
            h for h in report["households"]["observations"] if h["lclid"] == lclid
        )

    a = obs(r0, "MAC000002")
    b = obs(r1, "MAC000002")
    assert a["last_ts_in_member"] == "2012-10-12 01:00:00.0000000"
    assert b["first_ts_in_member"] == "2012-10-12 01:30:00.0000000"

    for report in (r0, r1):
        keys = set(report["households"]["observations"][0])
        assert "first_ts_in_member" in keys and "last_ts_in_member" in keys
        assert not any("complete" in k for k in keys)
        assert "not a completeness claim" in report["households"]["note"]


def test_tariff_values_are_observed_not_assumed(tmp_path, mixed_member):
    report, _ = run(tmp_path, mixed_member)
    assert report["households"]["tariff_group_values"] == {"Std": 10, "ToU": 2}
    assert report["households"]["distinct_in_member"] == 2


# -- reporting mechanics ------------------------------------------------------


def test_report_is_repeatable(tmp_path, mixed_member):
    """Two runs over the same bytes must agree on every analytical result."""
    archive = build_archive(tmp_path, {MEMBER: mixed_member})
    a, _ = profile_member(archive, MEMBER, work_dir=tmp_path)
    b, _ = profile_member(archive, MEMBER, work_dir=tmp_path)
    volatile = {"invocation"}
    assert {k: v for k, v in a.items() if k not in volatile} == {
        k: v for k, v in b.items() if k not in volatile
    }


def test_atomic_write_leaves_no_partial_file(tmp_path):
    target = tmp_path / "out" / "report.json"
    write_json_atomically(target, {"hello": "world"})
    assert json.loads(target.read_text())["hello"] == "world"
    assert list(target.parent.iterdir()) == [target]  # no .tmp left behind


def test_report_carries_source_and_code_identity(tmp_path, mixed_member):
    report, _ = run(tmp_path, mixed_member)
    src = report["source"]
    assert src["archive_sha256"] and src["member_content_sha256"]
    assert src["member_crc32_hex"]
    code = report["code_identity"]
    assert code["package_source_sha256"] and code["profiler_version"]
    assert "python_version" in report["invocation"]


def test_cli_writes_report_and_returns_zero(tmp_path, mixed_member):
    archive = build_archive(tmp_path, {MEMBER: mixed_member})
    out = tmp_path / "profile.json"
    rc = main(
        [
            "--archive",
            str(archive),
            "--member",
            MEMBER,
            "--output",
            str(out),
            "--no-examples",
            "--work-dir",
            str(tmp_path),
        ]
    )
    assert rc == 0
    assert json.loads(out.read_text())["status"] == "COMPLETE"


def test_encoding_evidence_counts_non_ascii(tmp_path, mixed_member):
    report, _ = run(tmp_path, mixed_member)
    assert report["encoding_evidence"]["non_ascii_bytes_in_member"] == 0


def test_report_survives_json_round_trip_unchanged(tmp_path, wrong_field_count_member):
    """The in-memory report and its JSON form must be identical.

    Integer dict keys would silently become strings on serialisation, so a caller
    reading the file would see different data from a caller using the object.
    """
    report, _ = run(tmp_path, wrong_field_count_member)
    out = tmp_path / "r.json"
    write_json_atomically(out, report)
    assert json.loads(out.read_text()) == report


# -- code identity (3a) -------------------------------------------------------


def test_source_fingerprint_changes_when_source_changes(tmp_path):
    """A digest that ignored file content could not distinguish two dirty runs."""
    from energy_reconciliation.profiling.report import hash_python_sources

    (tmp_path / "a.py").write_text("x = 1\n")
    first, names = hash_python_sources(tmp_path)
    assert names == ["a.py"]

    (tmp_path / "a.py").write_text("x = 2\n")
    second, _ = hash_python_sources(tmp_path)
    assert second != first, "edited source must change the fingerprint"

    (tmp_path / "a.py").write_text("x = 1\n")
    assert hash_python_sources(tmp_path)[0] == first, "same bytes, same fingerprint"


def test_renaming_a_source_file_changes_the_fingerprint(tmp_path):
    from energy_reconciliation.profiling.report import hash_python_sources

    (tmp_path / "a.py").write_text("x = 1\n")
    first, _ = hash_python_sources(tmp_path)
    (tmp_path / "a.py").rename(tmp_path / "b.py")
    assert hash_python_sources(tmp_path)[0] != first


def test_code_identity_states_when_git_commit_is_insufficient(tmp_path, mixed_member):
    """git_commit + dirty flag does not identify uncommitted code; the report must say so."""
    report, _ = run(tmp_path, mixed_member)
    code = report["code_identity"]
    assert code["authoritative_code_fingerprint"] == "package_source_sha256"
    assert code["source_file_count"] == len(code["source_files"])
    assert set(code["source_files"]) >= {
        "reader.py",
        "validation.py",
        "aggregate.py",
        "report.py",
        "cli.py",
    }
    assert code["git_identity_sufficient"] is (not code["git_tree_dirty"])
    assert "ONLY when git_tree_dirty is false" in code["identity_note"]


# -- counter semantics (3c) ---------------------------------------------------


def test_declared_partitions_actually_sum(tmp_path, mixed_member):
    """Every declared partition must sum to its total; declared overlaps must not."""
    report, _ = run(tmp_path, mixed_member)
    total = report["counts"]["structurally_valid_records"]
    parts = report["counter_semantics"]["mutually_exclusive_partitions"]

    assert (
        sum(
            report["consumption"]["categories_mutually_exclusive"][k]
            for k in parts["consumption"]
        )
        == total
    )
    assert sum(report["timestamps"][k] for k in parts["timestamp_format"]) == total
    assert sum(report["counts"][k] for k in parts["outcome"]) == total
    assert (
        report["counts"]["structurally_valid_records"]
        + report["counts"]["malformed_records"]
        == report["counts"]["data_records_excluding_header"]
    )


def test_declared_overlaps_are_genuinely_subsets(tmp_path, mixed_member):
    report, _ = run(tmp_path, mixed_member)
    finite = report["consumption"]["categories_mutually_exclusive"]["finite_numeric"]
    diag = report["consumption"]["diagnostics_overlapping"]
    overlaps = report["counter_semantics"]["overlapping_diagnostics"]
    assert "subset of consumption.finite_numeric" == overlaps["zeros"]
    assert diag["zeros"] <= finite
    assert diag["negatives"] <= finite
    assert report["timestamps"]["off_grid"] <= report["timestamps"]["valid_format"]


def test_cli_succeeds_on_a_multiline_member(tmp_path, multiline_member):
    """A legal quoted newline must not be reported as a failed run."""
    archive = build_archive(tmp_path, {MEMBER: multiline_member})
    out = tmp_path / "p.json"
    rc = main(
        [
            "--archive",
            str(archive),
            "--member",
            MEMBER,
            "--output",
            str(out),
            "--no-examples",
            "--work-dir",
            str(tmp_path),
        ]
    )
    assert rc == 0
    report = json.loads(out.read_text())
    assert report["reconciliation"]["all_core_partitions_hold"] is True
    assert report["reconciliation"]["all_source_shape_checks_hold"] is False


# -- consumption distribution (REP-001 section 6) -----------------------------


def test_distribution_known_answers(tmp_path, distribution_member):
    """Ten values 0.1..1.0: every figure below is computable by hand."""
    report, _ = run(tmp_path, distribution_member)
    d = report["consumption"]["distribution"]

    assert d["finite_value_count"] == 10
    assert d["counts_agree"] is True  # streaming count == SQLite count
    assert d["minimum"] == "0.1"
    assert d["maximum"] == "1.0"
    assert d["range"] == "0.9"
    assert d["sum"] == "5.5"
    assert Decimal(d["mean"]) == Decimal("0.55")
    assert d["interquartile_range"] == "0.5"


def test_percentiles_are_observed_values_not_interpolations(
    tmp_path, distribution_member
):
    """Nearest rank must return a real observation, never a value between two."""
    report, _ = run(tmp_path, distribution_member)
    pct = report["consumption"]["distribution"]["percentiles_nearest_rank"]
    observed = {Decimal(f"0.{i}") for i in range(1, 10)} | {Decimal("1.0")}

    assert pct["p25"]["rank"] == 3 and Decimal(pct["p25"]["value_text"]) == Decimal(
        "0.3"
    )
    assert pct["p50"]["rank"] == 5 and Decimal(pct["p50"]["value_text"]) == Decimal(
        "0.5"
    )
    assert pct["p75"]["rank"] == 8 and Decimal(pct["p75"]["value_text"]) == Decimal(
        "0.8"
    )
    for item in pct.values():
        assert Decimal(item["value_text"].strip()) in observed


def test_distribution_ordering_ignores_row_order(tmp_path, distribution_member):
    """The fixture is written out of order; ranks must follow value, not position."""
    report, _ = run(tmp_path, distribution_member)
    pct = report["consumption"]["distribution"]["percentiles_nearest_rank"]
    ranks = [pct[f"p{p}"]["rank"] for p in (1, 5, 25, 50, 75, 90, 95, 99)]
    values = [
        Decimal(pct[f"p{p}"]["value_text"]) for p in (1, 5, 25, 50, 75, 90, 95, 99)
    ]
    assert ranks == sorted(ranks)
    assert values == sorted(values)


def test_null_token_is_excluded_from_the_distribution(tmp_path, distribution_member):
    """The `Null` row must not become a zero or otherwise enter the statistics."""
    report, _ = run(tmp_path, distribution_member)
    cats = report["consumption"]["categories_mutually_exclusive"]
    d = report["consumption"]["distribution"]
    assert cats["null_token"] == 1
    assert d["finite_value_count"] == cats["finite_numeric"] == 10
    assert report["counts"]["data_records_excluding_header"] == 11


def test_distribution_handles_negative_and_zero(tmp_path, negative_distribution_member):
    """min must not be assumed non-negative; zero is a real observation."""
    report, _ = run(tmp_path, negative_distribution_member)
    d = report["consumption"]["distribution"]
    assert d["minimum"] == "-0.5"
    assert d["maximum"] == "2.75"
    assert d["range"] == "3.25"
    assert d["sum"] == "2.50"
    assert report["consumption"]["diagnostics_overlapping"]["negatives"] == 1
    assert report["consumption"]["diagnostics_overlapping"]["zeros"] == 1


def test_sum_is_exact_decimal_not_float(tmp_path):
    """0.1 + 0.2 + 0.3 is 0.6 exactly in Decimal; in float it is 0.6000000000000001."""
    payload = HEADER_BYTES + b"".join(
        make_row("MAC000001", "Std", f"2012-10-12 0{i}:30:00.0000000", f" {v} ")
        for i, v in enumerate(["0.1", "0.2", "0.3"])
    )
    report, _ = run(tmp_path, payload)
    d = report["consumption"]["distribution"]
    assert d["sum"] == "0.6"
    assert Decimal(d["sum"]) == Decimal("0.6")
    assert 0.1 + 0.2 + 0.3 != 0.6  # the trap being avoided


def test_extreme_examples_are_bounded_and_reference_records(
    tmp_path, distribution_member
):
    report, _ = run(tmp_path, distribution_member)
    ext = report["consumption"]["extreme_values"]
    assert len(ext["smallest"]) == 5 and len(ext["largest"]) == 5
    assert Decimal(ext["smallest"][0]["value_text"]) == Decimal("0.1")
    assert Decimal(ext["largest"][0]["value_text"]) == Decimal("1.0")
    for item in ext["smallest"] + ext["largest"]:
        assert isinstance(item["record_no"], int)
        assert set(item) == {"value_text", "record_no"}  # no household id here


def test_extreme_row_details_go_to_the_ignored_examples_only(
    tmp_path, distribution_member
):
    """Household id and timestamp for extremes must not enter the tracked report."""
    report, examples = run(tmp_path, distribution_member)
    text = json.dumps(report)
    assert "MAC000001" in text  # per-household observations legitimately appear
    categories = {e["category"] for e in examples}
    assert {"smallest_value", "largest_value"} <= categories
    detail = next(e for e in examples if e["category"] == "smallest_value")
    assert detail["fields"][0] == "MAC000001" and detail["fields"][2]


def test_distribution_absent_when_no_finite_values(tmp_path):
    payload = HEADER_BYTES + make_row(
        "MAC000001", "Std", "2012-10-12 00:30:00.0000000", "Null"
    )
    report, _ = run(tmp_path, payload)
    d = report["consumption"]["distribution"]
    assert d["finite_value_count"] == 0
    assert d["counts_agree"] is True
    assert "no finite consumption values" in d["note"]


def test_exactness_is_declared_for_every_reported_statistic(
    tmp_path, distribution_member
):
    report, _ = run(tmp_path, distribution_member)
    ex = report["consumption"]["distribution"]["exactness"]
    assert ex["sum"].startswith("EXACT")
    assert ex["minimum"].startswith("EXACT")
    assert ex["maximum"].startswith("EXACT")
    assert ex["finite_value_count"].startswith("EXACT")
    assert ex["mean"].startswith("DERIVED")  # the one rounded figure
    assert "no interpolation" in ex["percentiles"]
