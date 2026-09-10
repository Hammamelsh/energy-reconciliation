"""The supported read contract: which relations a consumer gets, and whose identity.

The defect these tests exist for was found by review, not by a failure: a sealed candidate
holds **both** scenarios -- the Python one copied from the source warehouse in ``main``,
and dbt's in ``scenario_build`` -- and every analytics query named its relations bare, so
DuckDB resolved them in ``main``. A dashboard pointed at a candidate would have shown the
copied Python figures under the candidate's name and the Python run's identity, with
nothing failing.

So the fixture here is built to **expose** that: the source warehouse's Python scenario is
deliberately doctored before the snapshot, so the two routes cannot agree by accident. Any
read that falls back to ``main`` returns the marker value and fails its test.
"""

from __future__ import annotations

import json
import shutil
import stat
import zipfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest
from conftest import HEADER, MEMBER, row

from energy_reconciliation import candidate as cand
from energy_reconciliation import dbt_run
from energy_reconciliation import publication as pub
from energy_reconciliation.ingest.loader import load_member
from energy_reconciliation.tariff import analytics as ta
from energy_reconciliation.tariff import reads
from energy_reconciliation.tariff import schedule as sch
from energy_reconciliation.tariff.models import build_scenario

pytest.importorskip("dbt.cli.main", reason="dbt is not installed")

SCRATCH_ROOT = Path(__file__).resolve().parent.parent / "data" / "proof-scratch"

#: A charge no correct build can produce, written into the copied Python fact. Any figure
#: derived from it means a read reached ``main`` when it was asked for the dbt build.
MARKER_CHARGE = Decimal("999.0000000000000000")
MARKER_HOUSEHOLD = "MAC0PYTHONONLY"


@pytest.fixture
def work(tmp_path_factory):
    """A disposable working area on the repository's own filesystem (``/tmp`` is tmpfs)."""
    SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
    path = Path(str(tmp_path_factory.mktemp("reads", numbered=True)))
    yield path
    for file in path.rglob("*"):
        if file.is_file():
            file.chmod(stat.S_IRUSR | stat.S_IWUSR)
    shutil.rmtree(path, ignore_errors=True)


#: Readings that are charged (ToU, on the demo schedule's day) and readings that are not
#: (Std, ineligible for the ToU group), so both facts have rows to route.
CHARGED_READINGS = 48
EXCLUDED_READINGS = 9


def _warehouse(work: Path, name: str = "source") -> Path:
    archive = work / f"{name}.zip"
    body = HEADER + b"".join(
        [
            row(
                "MAC000001",
                "ToU",
                f"2013-01-01 {i // 2:02d}:{(i % 2) * 30:02d}:00.0000000",
                " 1 ",
            )
            for i in range(CHARGED_READINGS)
        ]
        + [
            row(
                "MAC000002",
                "Std",
                f"2013-01-01 {i // 2:02d}:{(i % 2) * 30:02d}:00.0000000",
                " 2 ",
            )
            for i in range(EXCLUDED_READINGS)
        ]
    )
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(MEMBER, body)
    database = work / f"{name}.duckdb"
    assert load_member(archive, MEMBER, database).complete
    return database


def _doctored_source(work: Path) -> tuple[Path, str]:
    """A warehouse whose **Python** scenario is deliberately wrong, and its run id.

    The Python tables are built normally, then edited: every charge becomes the marker and
    one household id appears that dbt's build cannot produce. The readings are untouched,
    so dbt still builds the correct answer from them.
    """
    database = _warehouse(work)
    built = build_scenario(database, sch.demo_schedule())
    con = duckdb.connect(str(database))
    try:
        con.execute(
            "UPDATE main.fact_interval_charge_scenario SET energy_charge_gbp = ?",
            [MARKER_CHARGE],
        )
        con.execute(
            "UPDATE main.fact_interval_charge_scenario SET household_id = ? "
            "WHERE rowid = (SELECT MIN(rowid) FROM main.fact_interval_charge_scenario)",
            [MARKER_HOUSEHOLD],
        )
        con.execute(
            "UPDATE main.dim_tariff_price SET price_pence_per_kwh = 42.0000, "
            "price_gbp_per_kwh = 0.420000"
        )
        con.execute(
            "DELETE FROM main.fact_interval_charge_exclusion WHERE rowid < 3"
        )  # two fewer exclusions than the dbt build has
    finally:
        con.close()
    return database, built.run_id


def _candidate(work: Path, source: Path, root: Path) -> cand.Built:
    return cand.build_candidate(source, root=root, schedule="demo")


@pytest.fixture(scope="module")
def doctored(tmp_path_factory):
    """One doctored source, one sealed candidate built from it. Shared: a build is slow."""
    SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
    area = Path(str(tmp_path_factory.mktemp("reads-shared", numbered=True)))
    source, python_run = _doctored_source(area)
    root = area / "pub"
    built = cand.build_candidate(source, root=root, schedule="demo")
    yield {
        "source": source,
        "python_run": python_run,
        "built": built,
        "root": root,
        "area": area,
    }
    for file in area.rglob("*"):
        if file.is_file():
            file.chmod(stat.S_IRUSR | stat.S_IWUSR)
    shutil.rmtree(area, ignore_errors=True)


# ------------------------------------------------------------------ the two routes
def test_the_dbt_route_reads_the_built_tables_and_the_build_identity(doctored):
    context = reads.candidate(doctored["built"].candidate)
    assert context.relations is ta.DBT_RELATIONS
    assert context.relations.fact_scenario.startswith(f"{ta.BUILD_SCHEMA}.")
    assert context.relations.readings == f"{ta.WAREHOUSE_SCHEMA}.readings", (
        "inputs still come from main: a build never writes them"
    )
    assert context.run_id == doctored["built"].seal.run_id
    assert context.run_id != doctored["python_run"], "not the copied Python run"
    assert context.identity.required_build == dbt_run.COMPLETE
    assert context.identity.schedule_source == "synthetic-demo"
    assert context.identity.dbt_core_version == dbt_run.dbt_identity()["dbt-core"]
    assert context.identity.file_sha256 == doctored["built"].seal.sha256


def test_the_legacy_route_still_reads_its_own_main_schema_outputs(doctored):
    """Unchanged behaviour for every existing caller, doctored figures included."""
    context = reads.warehouse(doctored["source"])
    assert context.relations is ta.WAREHOUSE_RELATIONS
    assert context.run_id == doctored["python_run"]
    assert context.run_record is not None
    bands = ta.band_summary(
        doctored["source"], context.run_id, relations=context.relations
    )
    assert {Decimal(v) for v in bands["charge_gbp_exact"]} == {
        MARKER_CHARGE * len(bands.index) / len(bands.index)
    } or all(Decimal(v) % MARKER_CHARGE == 0 for v in bands["charge_gbp_exact"]), (
        "the legacy route returns exactly what main holds, marker and all"
    )
    assert MARKER_HOUSEHOLD in set(
        ta.charged_households(
            doctored["source"], context.run_id, relations=context.relations
        )
    )


def test_a_fallback_to_main_would_be_visible_in_every_routed_function(doctored):
    """Each function, on the dbt route, must miss every marker the copied tables carry."""
    context = reads.candidate(doctored["built"].candidate)
    database, run_id, relations = context.database, context.run_id, context.relations

    bands = ta.band_summary(database, run_id, relations=relations)
    assert not bands.empty
    assert all(Decimal(v) < MARKER_CHARGE for v in bands["charge_gbp_exact"])
    assert all(float(p) != 42.0 for p in bands["price_pence_per_kwh"]), (
        "the doctored main price catalogue is not what priced these rows"
    )

    households = ta.household_totals(database, run_id, relations=relations)
    assert MARKER_HOUSEHOLD not in set(households["household_id"])
    assert MARKER_HOUSEHOLD not in set(
        ta.charged_households(database, run_id, relations=relations)
    )

    prices = ta.price_catalogue(database, relations=relations)
    assert 42.0 not in {float(p) for p in prices["price_pence_per_kwh"]}

    monthly = ta.monthly_charge(database, run_id, relations=relations)
    assert all(Decimal(v) < MARKER_CHARGE for v in monthly["charge_gbp_exact"])

    hours = ta.household_band_distribution(database, run_id, relations=relations)
    assert not hours.empty

    breakdown = ta.exclusion_breakdown(database, run_id, relations=relations)
    examples = ta.exclusion_examples(database, run_id, relations=relations)
    assert int(breakdown["readings"].sum()) == EXCLUDED_READINGS, (
        "the two exclusion rows deleted from main are present in the dbt fact"
    )
    assert len(examples.index) == EXCLUDED_READINGS

    schedule = ta.schedule_totals(database, relations=relations)
    distribution = ta.schedule_band_distribution(database, relations=relations)
    assert int(schedule["slots"].sum()) == 48
    assert int(distribution["slots"].sum()) == 48
    assert ta.schedule_bounds(database, relations=relations) is not None

    insights = ta.selection_insights(database, run_id, relations=relations)
    assert insights and all(str(MARKER_CHARGE) not in i.headline for i in insights)

    # readings-backed functions are the same relation on both routes, by design
    assert ta.household_tariff_groups(database, "MAC000001", relations=relations) == [
        "ToU"
    ]
    assert ta.tariff_group_stability(database, relations=relations).empty
    assert set(ta.charged_households(database, run_id, relations=relations)) == {
        "MAC000001"
    }, "MAC000002 is Std, so the dbt build excludes it -- as the Python build did"


def test_the_report_is_one_pass_over_one_validated_context(doctored):
    context = reads.candidate(doctored["built"].candidate)
    report = reads.tariff_report(context)
    assert report.context is context
    assert report.accounting.reconciles
    assert report.accounting.derived, "counted, and it says so"
    assert report.accounting.raw_rows == CHARGED_READINGS + EXCLUDED_READINGS
    assert report.accounting.included_readings == CHARGED_READINGS
    assert report.accounting.excluded_readings == EXCLUDED_READINGS
    assert (
        report.accounting.included_readings + report.accounting.excluded_readings
        == (report.accounting.distinct_readings)
    )
    assert Decimal(report.total_charge_exact) < MARKER_CHARGE
    assert report.charged_readings == report.accounting.included_readings
    assert not report.prices.empty and not report.schedule.empty


def test_the_dbt_route_refuses_to_answer_from_the_python_run_record(doctored):
    """No scenario_run on this route, and no quiet fall back to the one in main."""
    context = reads.candidate(doctored["built"].candidate)
    assert context.relations.scenario_run is None
    assert not context.relations.has_run_table
    with pytest.raises(ta.ScenarioSchemaError, match="does not have"):
        ta.accounting(context.database, context.run_id, relations=context.relations)
    # ...even though the copied table is right there and would have answered
    assert ta.latest_run(context.database).run_id == doctored["python_run"]


def test_a_relation_outside_the_two_vocabularies_is_refused():
    with pytest.raises(ta.RelationError):
        ta._relation("public", "readings")
    with pytest.raises(ta.RelationError):
        ta._relation("main", "readings; DROP TABLE readings")


# ------------------------------------------------------------------ refusals
def test_an_unsealed_candidate_is_not_readable(work):
    source = _warehouse(work)
    unsealed = work / "unsealed.duckdb"
    con = duckdb.connect(":memory:")
    con.execute(f"ATTACH '{source}' AS s (READ_ONLY)")
    con.execute(f"ATTACH '{unsealed}' AS d")
    con.execute("COPY FROM DATABASE s TO d")
    con.close()
    with pytest.raises(reads.ReadContextError, match="not sealed"):
        reads.candidate(unsealed)


def test_a_file_changed_after_sealing_is_not_readable(work):
    source = _warehouse(work)
    built = _candidate(work, source, work / "pub")
    built.candidate.chmod(stat.S_IRUSR | stat.S_IWUSR)
    con = duckdb.connect(str(built.candidate))
    con.execute("CREATE TABLE main.unrelated AS SELECT 1 AS x")
    con.close()
    with pytest.raises(reads.ReadContextError, match="changed after validation"):
        reads.candidate(built.candidate)


def test_a_seal_that_names_another_run_is_refused(work):
    source = _warehouse(work)
    built = _candidate(work, source, work / "pub")
    seal_path = pub._seal_path(built.candidate)
    seal = json.loads(seal_path.read_text())
    seal["run_id"] = "dbtcand-0000deadbeef@20260101T000000000000"
    seal_path.write_text(json.dumps(seal))
    with pytest.raises(reads.ReadContextError, match="the seal names"):
        reads.candidate(built.candidate)


def test_a_manifest_that_disagrees_with_the_seal_is_refused(work):
    source = _warehouse(work)
    root = work / "pub"
    built = _candidate(work, source, root)
    pub.publish(built.candidate, expected_previous=None, root=root)
    manifest_path = root / pub.MANIFEST
    manifest = json.loads(manifest_path.read_text())
    manifest["run_id"] = "dbtcand-0000deadbeef@20260101T000000000000"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(reads.ReadContextError, match="the manifest names run"):
        reads.published(root)


def test_nothing_published_is_an_explicit_unavailable_state(work):
    with pytest.raises(pub.Unavailable):
        reads.published(work / "empty-root")


def test_a_snapshot_with_no_dbt_tables_is_refused_rather_than_read_from_main(work):
    """A file carrying a build record but no built tables must not answer from main."""
    source = _warehouse(work)
    built = _candidate(work, source, work / "pub")
    stripped = work / "stripped.duckdb"
    con = duckdb.connect(":memory:")
    con.execute(f"ATTACH '{built.candidate}' AS s (READ_ONLY)")
    con.execute(f"ATTACH '{stripped}' AS d")
    con.execute("COPY FROM DATABASE s TO d")
    con.close()
    con = duckdb.connect(str(stripped))
    for table in ("fact_interval_charge_scenario", "fact_interval_charge_exclusion"):
        con.execute(f"DROP TABLE {ta.BUILD_SCHEMA}.{table}")
    con.close()
    shutil.copy(pub._seal_path(built.candidate), pub._seal_path(stripped))
    with pytest.raises(reads.ReadContextError):
        reads.candidate(stripped)


# ------------------------------------------- producer eligibility, at the reader
def test_an_incomplete_but_successful_invocation_can_never_become_readable(work):
    """MEASURED before this gate existed: this exact command was sealed.

    ``build --exclude test_type:singular`` builds every model, skips all eleven singular
    tests -- reconciliation, exact arithmetic, reason precedence -- and exits 0. dbt's own
    run results say which nodes ran, so the attempt records ``required_build=incomplete``
    and neither ``finalise`` nor the reader will accept it.
    """
    source = _warehouse(work)
    partial = work / "partial.duckdb"
    con = duckdb.connect(":memory:")
    con.execute(f"ATTACH '{source}' AS s (READ_ONLY)")
    con.execute(f"ATTACH '{partial}' AS d")
    con.execute("COPY FROM DATABASE s TO d")
    con.close()
    assert (
        dbt_run.main(
            [
                "--database",
                str(partial),
                "--schedule",
                "demo",
                "build",
                "--exclude",
                "test_type:singular",
                "--target-path",
                str(work / "t-partial"),
            ]
        )
        == 0
    ), "the invocation itself succeeds; that is the point"

    con = duckdb.connect(str(partial), read_only=True)
    try:
        status, required, total, missing = con.execute(
            "SELECT status, required_build, required_nodes_total, "
            f"missing_required_nodes FROM {dbt_run.BUILD_RUN_TABLE}"
        ).fetchone()
    finally:
        con.close()
    assert status == dbt_run.SUCCEEDED
    assert required == dbt_run.INCOMPLETE
    skipped = json.loads(missing)
    assert len(skipped) == 11 and total == 54
    assert all(n.startswith("test.") for n in skipped)
    assert any("assert_charged_plus_excluded_equals_distinct" in n for n in skipped)

    with pytest.raises(pub.PromotionRefused, match="did not build the whole project"):
        pub.finalise(partial)
    with pytest.raises(reads.ReadContextError, match="not sealed"):
        reads.candidate(partial)


def test_a_full_build_records_every_required_node_as_passing(work):
    source = _warehouse(work)
    built = _candidate(work, source, work / "pub")
    con = duckdb.connect(str(built.candidate), read_only=True)
    try:
        required, total, missing, nodes, invocation = con.execute(
            "SELECT required_build, required_nodes_total, missing_required_nodes, "
            f"node_results, dbt_invocation_id FROM {dbt_run.BUILD_RUN_TABLE}"
        ).fetchone()
    finally:
        con.close()
    statuses = json.loads(nodes)
    assert (required, total, json.loads(missing)) == (dbt_run.COMPLETE, 54, [])
    assert invocation, "the attempt names dbt's own invocation id"
    assert sum(1 for k in statuses if k.startswith("model.")) == 5
    assert sum(1 for k in statuses if k.startswith("test.")) == 49
    assert set(statuses.values()) <= {"success", "pass"}
    assert reads.candidate(built.candidate).identity.required_nodes_total == 54


def test_stale_run_results_from_an_earlier_invocation_are_not_believed(work):
    """A target directory holding another build's artefacts is reported, not accepted."""
    source = _warehouse(work)
    target = work / "shared-target"
    first = work / "first.duckdb"
    con = duckdb.connect(":memory:")
    con.execute(f"ATTACH '{source}' AS s (READ_ONLY)")
    con.execute(f"ATTACH '{first}' AS d")
    con.execute("COPY FROM DATABASE s TO d")
    con.close()
    assert (
        dbt_run.main(
            [
                "--database",
                str(first),
                "--schedule",
                "demo",
                "build",
                "--target-path",
                str(target),
            ]
        )
        == 0
    )
    started = datetime.now(UTC).replace(tzinfo=None)
    coverage = dbt_run.node_coverage(target, started)
    assert not coverage.complete
    assert "earlier invocation" in coverage.reason


# ------------------------------------------------------------------ version binding
def test_a_context_stays_bound_to_its_version_across_a_promotion(work):
    """Resolved once, threaded through a render: a promotion mid-render is invisible."""
    source = _warehouse(work)
    root = work / "pub"
    first = _candidate(work, source, root)
    pub.publish(first.candidate, expected_previous=None, root=root)
    held = reads.published(root)
    assert held.version == "v0001" and held.is_active_publication

    second = _candidate(work, source, root)
    assert second.candidate != first.candidate
    pub.publish(second.candidate, expected_previous="v0001", root=root)

    # the context obtained before the promotion still reads v0001's file and run
    assert held.database == first.candidate
    assert held.run_id == first.seal.run_id
    assert ta.charged_households(
        held.database, held.run_id, relations=held.relations
    ) == ["MAC000001"]
    # a newly resolved context sees v0002
    fresh = reads.published(root)
    assert fresh.version == "v0002"
    assert fresh.database == second.candidate
    assert fresh.run_id == second.seal.run_id
    assert fresh.run_id != held.run_id


def test_a_candidate_is_never_labelled_as_the_active_publication(work):
    source = _warehouse(work)
    root = work / "pub"
    published_built = _candidate(work, source, root)
    pub.publish(published_built.candidate, expected_previous=None, root=root)
    inspected = _candidate(work, source, root)

    active = reads.published(root)
    looked_at = reads.candidate(inspected.candidate)
    assert active.is_active_publication and active.role == reads.PUBLISHED
    assert not looked_at.is_active_publication and looked_at.role == reads.CANDIDATE
    assert "CANDIDATE" in looked_at.label and "NOT published" in looked_at.label
    assert active.version == "v0001" and looked_at.version is None

    # the legacy route is never an active publication either: it has no manifest at all
    build_scenario(source, sch.demo_schedule())
    legacy = reads.warehouse(source)
    assert legacy.is_active_publication is False and legacy.role == reads.WAREHOUSE
    assert legacy.version is None and legacy.identity is None


def test_the_flat_comparison_is_routed_like_every_other_tariff_query(doctored):
    """ANL-005 must price the dbt facts with the dbt build's own price row.

    The doctored source's ``main`` price catalogue is 42p everywhere and its charges are
    the marker; the dbt build in ``scenario_build`` carries the real catalogue. A fallback
    to ``main`` for either the price or the rows would show up in the figures.
    """
    from energy_reconciliation.tariff import flat_comparison as fc

    context = reads.candidate(doctored["built"].candidate)
    result = fc.compare(context.database, context.run_id, relations=context.relations)
    assert isinstance(result, fc.FlatComparison)
    assert result.route == context.relations.label
    assert result.price.price_gbp_per_kwh == Decimal("0.14228"), (
        "the flat price is the build's, not the doctored main catalogue's 0.42"
    )
    assert MARKER_HOUSEHOLD not in {r["household_id"] for r in result.households}
    assert result.totals.dynamic < MARKER_CHARGE
    assert result.totals.flat == result.totals.kwh * Decimal("0.14228")

    # the same function on the legacy route reads the doctored main tables -- visibly
    legacy = fc.flat_price(doctored["source"], relations=ta.WAREHOUSE_RELATIONS)
    assert isinstance(legacy, fc.FlatPrice) and legacy.price_gbp_per_kwh == Decimal(
        "0.42"
    )
