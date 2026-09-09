"""Format 2: recording a published dbt result, and genuinely rebuilding it.

Every rebuild here runs the supported ``build-candidate`` path -- a real dbt build with
every model and every test -- into a destination that did not exist. Nothing is copied
from the publication being checked, so a comparison that passes has actually re-derived
the figures.

The fixture is hand-checkable: two households, one day, the invented demo schedule. Its
one charged ToU household and its excluded Std readings are small enough to verify by
reading the numbers.
"""

from __future__ import annotations

import json
import shutil
import stat
import zipfile
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest
from conftest import HEADER, MEMBER, row

from energy_reconciliation import candidate as cand
from energy_reconciliation import publication as pub
from energy_reconciliation.ingest.loader import load_member
from energy_reconciliation.tariff import baseline as fmt1
from energy_reconciliation.tariff import baseline_cli as cli
from energy_reconciliation.tariff import published_baseline as pub2
from energy_reconciliation.tariff import reads

pytest.importorskip("dbt.cli.main", reason="dbt is not installed")

SCRATCH_ROOT = Path(__file__).resolve().parent.parent / "data" / "proof-scratch"
CHARGED = 48
EXCLUDED = 9


def _archive(directory: Path, name: str = "source.zip", value: str = " 1 ") -> Path:
    """One ToU household charged across a day, plus Std readings that cannot be."""
    directory.mkdir(parents=True, exist_ok=True)
    body = HEADER + b"".join(
        [
            row(
                "MAC000001",
                "ToU",
                f"2013-01-01 {i // 2:02d}:{(i % 2) * 30:02d}:00.0000000",
                value,
            )
            for i in range(CHARGED)
        ]
        + [
            row(
                "MAC000002",
                "Std",
                f"2013-01-01 {i // 2:02d}:{(i % 2) * 30:02d}:00.0000000",
                " 2 ",
            )
            for i in range(EXCLUDED)
        ]
    )
    path = directory / name
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(MEMBER, body)
    return path


def _warehouse(archive: Path, database: Path) -> Path:
    assert load_member(archive, MEMBER, database).complete
    return database


@pytest.fixture(scope="module")
def recorded(tmp_path_factory):
    """A published demo build and the format-2 baseline recorded from it."""
    SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
    area = Path(str(tmp_path_factory.mktemp("published-baseline")))
    archive = _archive(area / "src")
    source = _warehouse(archive, area / "src" / "warehouse.duckdb")
    root = area / "published"
    built = cand.build_candidate(source, root=root, schedule="demo")
    manifest = pub.publish(built.candidate, expected_previous=None, root=root)
    path = pub2.capture(root, area / "baselines")
    yield {
        "area": area,
        "archive": archive,
        "source": source,
        "root": root,
        "built": built,
        "manifest": manifest,
        "path": path,
        "baseline": json.loads(path.read_text()),
    }
    for file in area.rglob("*"):
        if file.is_file():
            file.chmod(stat.S_IRUSR | stat.S_IWUSR)
    shutil.rmtree(area, ignore_errors=True)


# ------------------------------------------------------------------ recording
def test_the_record_comes_from_the_attested_build_not_the_copied_python_tables(
    recorded,
):
    baseline = recorded["baseline"]
    assert baseline["format_version"] == "2"
    assert baseline["execution"]["run_id"] == recorded["built"].seal.run_id
    assert baseline["execution"]["run_id"].startswith("dbtcand-")
    assert baseline["calculation"]["required_build"] == "complete"
    assert baseline["calculation"]["required_nodes_total"] == 54
    assert baseline["outputs"]["accounting"]["included_readings"] == CHARGED
    assert baseline["outputs"]["accounting"]["excluded_readings"] == EXCLUDED
    assert baseline["outputs"]["accounting"]["reconciles"] is True
    assert set(baseline["outputs"]["relations"]) == {
        "fact_interval_charge_scenario",
        "fact_interval_charge_exclusion",
        "dim_tariff_band_schedule",
        "dim_tariff_price",
    }
    assert baseline["outputs"]["assumption_ids"] == ["A1"]
    # the run the copied main.scenario_run would have named is not what was recorded
    con = duckdb.connect(str(recorded["built"].candidate), read_only=True)
    try:
        copied = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = 'main' AND table_name = 'scenario_run'"
        ).fetchone()[0]
    finally:
        con.close()
    assert copied == 0, "this fixture has no Python scenario at all, so none was read"


def test_the_recorded_totals_are_exact_and_hand_checkable(recorded):
    outputs = recorded["baseline"]["outputs"]
    # 48 half-hours of 1 kWh, all charged; the demo schedule prices them by band
    assert Decimal(outputs["total_consumption_kwh_exact"]) == Decimal(CHARGED)
    bands = {b["band_label"]: b for b in outputs["per_band"]}
    assert sum(b["readings"] for b in bands.values()) == CHARGED
    total = sum(Decimal(b["charge_exact"]) for b in bands.values())
    assert total == Decimal(outputs["total_energy_charge_gbp_exact"])
    for band in bands.values():
        # charge = kWh x pence / 100, exactly
        expected = Decimal(band["kwh_exact"]) * Decimal(band["price_pence"]) / 100
        assert Decimal(band["charge_exact"]) == expected
    assert {r["exclusion_reason"] for r in outputs["per_exclusion_reason"]} == {
        "ineligible_tariff_group"
    }


def test_the_baseline_names_what_replay_still_needs(recorded):
    baseline = recorded["baseline"]
    assert baseline["inputs"]["member_count"] == 1
    member = baseline["inputs"]["members"][0]
    assert member["member_content_sha256"] and member["archive_sha256"]
    assert baseline["inputs"]["schedule"]["variant"] == "demo"
    assert baseline["inputs"]["tariff_group"] == "ToU"
    assert "publication root" in baseline["note"]


def test_a_baseline_is_never_overwritten(recorded):
    with pytest.raises(fmt1.BaselineError, match="never overwritten"):
        pub2.capture(
            recorded["root"],
            recorded["path"].parent,
            when=None
            if False
            else __import__("datetime").datetime.fromisoformat(
                recorded["baseline"]["captured_at_utc"]
            ),
        )


# ------------------------------------------------------------------ the rebuild
@pytest.fixture(scope="module")
def rebuilt(recorded, tmp_path_factory):
    """One genuine rebuild, reused by the assertions below."""
    into = Path(str(tmp_path_factory.mktemp("rebuild"))) / "fresh"
    result = pub2.replay(recorded["path"], into, archive=recorded["archive"])
    yield result
    for file in into.rglob("*"):
        if file.is_file():
            file.chmod(stat.S_IRUSR | stat.S_IWUSR)
    shutil.rmtree(into, ignore_errors=True)


def test_a_fresh_rebuild_reproduces_the_published_result(recorded, rebuilt):
    assert rebuilt.reproduced, [(d.field, d.baseline, d.replay) for d in rebuilt.failed]
    assert len(rebuilt.differences) > 20, "inputs, identity and every output compared"


def test_a_new_destination_and_run_identity_are_not_a_mismatch(recorded, rebuilt):
    """Execution provenance is new by construction and must never fail a comparison."""
    assert rebuilt.run_id != recorded["built"].seal.run_id
    assert rebuilt.candidate != recorded["built"].candidate
    assert rebuilt.warehouse != recorded["source"]
    assert rebuilt.reproduced
    fields = {d.field for d in rebuilt.differences}
    assert not any("run_id" in f for f in fields)
    assert not any("sealed" in f or "file_sha256" in f for f in fields)


def test_the_rebuild_is_a_real_dbt_build_not_a_copy(recorded, rebuilt):
    context = reads.candidate(rebuilt.candidate)
    assert context.identity.required_build == "complete"
    assert context.identity.required_nodes_total == 54
    assert context.identity.run_id == rebuilt.run_id
    assert (
        context.identity.dbt_invocation_id
        != recorded["baseline"]["execution"]["dbt_invocation_id"]
    ), "a different dbt invocation actually ran"


def test_the_rebuild_does_not_touch_the_original_publication(recorded, rebuilt):
    manifest = pub.read_manifest(recorded["root"])
    assert manifest == recorded["manifest"]
    seal = pub.read_seal(recorded["built"].candidate)
    assert seal.run_id == recorded["built"].seal.run_id
    assert not recorded["built"].candidate.stat().st_mode & stat.S_IWUSR


# ------------------------------------------------- material differences are caught
def _tampered(recorded, tmp_path, mutate) -> Path:
    baseline = json.loads(recorded["path"].read_text())
    mutate(baseline)
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(baseline))
    return path


@pytest.mark.parametrize(
    ("name", "mutate", "field"),
    [
        (
            "row content",
            lambda b: b["outputs"]["relations"][
                "fact_interval_charge_scenario"
            ].__setitem__("row_digest", "0" * 64),
            "output fact_interval_charge_scenario.row_digest",
        ),
        (
            "row count",
            lambda b: b["outputs"]["relations"][
                "fact_interval_charge_exclusion"
            ].__setitem__("rows", 999),
            "output fact_interval_charge_exclusion.rows",
        ),
        (
            "relation schema",
            lambda b: b["outputs"]["relations"]["dim_tariff_price"].__setitem__(
                "schema", [["band_label", "VARCHAR"]]
            ),
            "output dim_tariff_price.schema",
        ),
        (
            "exact charge",
            lambda b: b["outputs"].__setitem__(
                "total_energy_charge_gbp_exact", "0.0000000000000001"
            ),
            "output total_energy_charge_gbp_exact",
        ),
        (
            "accounting",
            lambda b: b["outputs"]["accounting"].__setitem__("excluded_readings", 0),
            "output accounting",
        ),
        (
            "per band",
            lambda b: b["outputs"]["per_band"][0].__setitem__("charge_exact", "1.0"),
            "output per_band",
        ),
        (
            "per household",
            lambda b: b["outputs"]["per_household"][0].__setitem__("readings", 1),
            "output per_household",
        ),
        (
            "calculation identity",
            lambda b: b["calculation"].__setitem__("calculation_code_sha256", "f" * 64),
            "calculation calculation_code_sha256",
        ),
        (
            "policy identity",
            lambda b: b["calculation"].__setitem__("policy_sha256", "f" * 64),
            "calculation policy_sha256",
        ),
        (
            "runtime",
            lambda b: b["runtime"].__setitem__("duckdb", "0.0.0"),
            "runtime",
        ),
        (
            "price catalogue",
            lambda b: b["inputs"].__setitem__(
                "price_catalogue_version", "1999-01-01.1"
            ),
            "input price_catalogue_version",
        ),
    ],
)
def test_a_material_difference_cannot_silently_pass(
    recorded, rebuilt, tmp_path, name, mutate, field
):
    """Each of these is compared, and each one fails rather than passing.

    Compared against the **genuine rebuild** made once by the ``rebuilt`` fixture rather
    than rebuilding eleven more times: the unit under test here is the comparison, and
    the rebuild it is given is a real one. ``test_a_fresh_rebuild_reproduces_the_
    published_result`` is what establishes that an untampered baseline passes.
    """
    baseline = json.loads(recorded["path"].read_text())
    mutate(baseline)
    context = reads.candidate(rebuilt.candidate)
    differences = pub2.compare(baseline, context)
    failed = {d.field for d in differences if not d.matches}
    assert failed, f"{name} passed silently"
    assert field in failed, (name, sorted(failed))


def test_a_changed_source_member_is_refused_before_any_build(recorded, tmp_path):
    """A different input is not a mismatch to be reported; it cannot be replayed at all."""
    other = _archive(tmp_path / "other", value=" 2 ")
    into = tmp_path / "never-created"
    with pytest.raises(fmt1.BaselineError, match="not the same input"):
        pub2.replay(recorded["path"], into, archive=other)
    assert not into.exists(), "refused before the destination was created"


def test_a_changed_recorded_scope_changes_the_build_and_fails_on_the_outputs(
    recorded, tmp_path
):
    """Replay honours the **recorded** scope, so a tampered setting is really applied.

    Changing the recorded tariff group to `Std` does not produce an input mismatch --
    the rebuild dutifully uses the scope it was given, so the inputs agree. What it
    produces is a different result, and that is where it is caught. Recording a setting
    and then ignoring it would be the dangerous behaviour; this shows it is obeyed.
    """
    path = _tampered(
        recorded, tmp_path, lambda b: b["inputs"].__setitem__("tariff_group", "Std")
    )
    result = pub2.replay(path, tmp_path / "group", archive=recorded["archive"])
    assert not result.reproduced
    failed = {d.field for d in result.failed}
    assert "input tariff_group" not in failed, "the rebuild used the recorded scope"
    assert "output accounting" in failed, "and it really did change what was built"
    assert "output per_band" in failed


# ------------------------------------------------------------------ refusals
def test_a_missing_archive_is_refused_and_names_the_artifact(recorded, tmp_path):
    with pytest.raises(fmt1.BaselineError, match="not available"):
        pub2.replay(
            recorded["path"], tmp_path / "no-archive", archive=tmp_path / "gone.zip"
        )
    assert not (tmp_path / "no-archive").exists()


def test_a_missing_workbook_is_refused_rather_than_substituted(recorded, tmp_path):
    path = _tampered(
        recorded,
        tmp_path,
        lambda b: b["inputs"]["schedule"].update(
            {"variant": "workbook", "source": "Tariffs.xlsx", "source_sha256": "a" * 64}
        ),
    )
    with pytest.raises(fmt1.BaselineError, match="never substituted for it"):
        pub2.replay(
            path,
            tmp_path / "no-workbook",
            archive=recorded["archive"],
            workbook=tmp_path / "absent.xlsx",
        )


def test_an_existing_destination_is_refused(recorded, tmp_path):
    into = tmp_path / "taken"
    into.mkdir()
    with pytest.raises(fmt1.BaselineError, match="already exists"):
        pub2.replay(recorded["path"], into, archive=recorded["archive"])


def test_an_incomplete_dbt_build_cannot_produce_a_replay(recorded, tmp_path):
    """A project whose tests fail never reaches a comparison."""
    project = tmp_path / "broken-project"
    shutil.copytree(
        Path("dbt"), project, ignore=shutil.ignore_patterns("target", "logs")
    )
    macro = project / "macros" / "generated_policy.sql"
    macro.write_text(
        macro.read_text().replace(
            "WHERE is_ineligible_group OR", "WHERE NOT is_ineligible_group OR"
        )
    )
    with pytest.raises(fmt1.BaselineError, match="rebuild failed"):
        pub2.replay(
            recorded["path"],
            tmp_path / "incomplete",
            archive=recorded["archive"],
            project_dir=project,
        )


def test_an_unsupported_or_incomplete_format_is_refused(recorded, tmp_path):
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps({"format_version": "1", "inputs": {}}))
    with pytest.raises(fmt1.BaselineError, match="reads only format '2'"):
        pub2.load(legacy)

    partial = tmp_path / "partial.json"
    data = json.loads(recorded["path"].read_text())
    del data["outputs"]
    partial.write_text(json.dumps(data))
    with pytest.raises(fmt1.BaselineError, match="incomplete"):
        pub2.load(partial)

    stale = tmp_path / "stale.json"
    data = json.loads(recorded["path"].read_text())
    data["outputs"]["comparison_digest_version"] = "compare-rows-99"
    stale.write_text(json.dumps(data))
    with pytest.raises(fmt1.BaselineError, match="Not comparable"):
        pub2.load(stale)


# ------------------------------------------------- the digest's own properties
def _digest(statements: list[str], key: str = "probe") -> str:
    con = duckdb.connect(":memory:")
    try:
        for statement in statements:
            con.execute(statement)
        return pub2.relation_evidence(con, key, "main.probe")["row_digest"]
    finally:
        con.close()


def test_duplicate_multiplicity_survives_recording_and_comparison():
    base = ["CREATE TABLE probe(x INTEGER)", "INSERT INTO probe VALUES (1), (1), (2)"]
    same_order_swapped = [
        "CREATE TABLE probe(x INTEGER)",
        "INSERT INTO probe VALUES (2), (1), (1)",
    ]
    fewer = ["CREATE TABLE probe(x INTEGER)", "INSERT INTO probe VALUES (1), (2)"]
    other = ["CREATE TABLE probe(x INTEGER)", "INSERT INTO probe VALUES (2), (3), (3)"]
    assert _digest(base) == _digest(same_order_swapped), "physical order is irrelevant"
    assert _digest(base) != _digest(fewer), "a lost duplicate is seen"
    assert _digest(base) != _digest(other), "equal counts cannot cancel"


def test_decimal_scale_and_nulls_survive_the_digest():
    scaled = [
        "CREATE TABLE probe(v DECIMAL(9,6))",
        "INSERT INTO probe VALUES (0.006720)",
    ]
    rounded = [
        "CREATE TABLE probe(v DECIMAL(9,3))",
        "INSERT INTO probe VALUES (0.007)",
    ]
    assert _digest(scaled) != _digest(rounded)
    null = ["CREATE TABLE probe(v VARCHAR)", "INSERT INTO probe VALUES (NULL)"]
    empty = ["CREATE TABLE probe(v VARCHAR)", "INSERT INTO probe VALUES ('')"]
    assert _digest(null) != _digest(empty)


def test_only_the_two_named_execution_columns_are_excluded():
    assert pub2._EXECUTION_COLUMNS["fact_interval_charge_scenario"] == ("run_id",)
    assert pub2._EXECUTION_COLUMNS["fact_interval_charge_exclusion"] == ("run_id",)
    assert pub2._EXECUTION_COLUMNS["dim_tariff_band_schedule"] == ("loaded_at_utc",)
    assert pub2._EXECUTION_COLUMNS["dim_tariff_price"] == ()


def test_the_recorded_relations_say_what_was_excluded(recorded):
    relations = recorded["baseline"]["outputs"]["relations"]
    assert relations["fact_interval_charge_scenario"]["excluded_columns"] == ["run_id"]
    assert relations["dim_tariff_price"]["excluded_columns"] == []
    compared = relations["fact_interval_charge_scenario"]["compared_columns"]
    assert "assumption_id" in compared and "energy_charge_gbp" in compared
    assert "run_id" not in compared


# ------------------------------------------------------------------ format 1
def test_format_one_is_untouched_and_the_two_refuse_each_other(recorded, tmp_path):
    assert fmt1.FORMAT_VERSION == "1" and pub2.FORMAT_VERSION == "2"
    assert pub2.COMPARISON_DIGEST_VERSION != fmt1.FORMAT_VERSION

    # a format-2 file handed to the format-1 replay
    with pytest.raises(fmt1.BaselineError, match="format version '2', expected '1'"):
        fmt1.replay(recorded["path"], tmp_path / "wrong.duckdb")
    # and the reverse
    legacy = tmp_path / "fmt1.json"
    legacy.write_text(json.dumps({"format_version": "1"}))
    with pytest.raises(fmt1.BaselineError, match="reads only format '2'"):
        pub2.load(legacy)


def test_the_two_formats_do_not_share_file_names(recorded):
    assert recorded["path"].name.startswith(pub2.FILE_PREFIX)
    assert "@" in recorded["path"].name


# ------------------------------------------------------------------ the commands
def test_the_capture_and_replay_commands_report_and_exit_meaningfully(
    recorded, tmp_path, capsys
):
    directory = tmp_path / "cli-baselines"
    assert (
        cli.capture_published_main(
            ["--root", str(recorded["root"]), "--directory", str(directory)]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "format 2" in out and "complete, 54 required nodes" in out
    assert "replay-published-baseline" in out
    path = next(directory.glob("pub2-*.json"))

    assert (
        cli.replay_published_main(
            [
                "--baseline",
                str(path),
                "--into",
                str(tmp_path / "cli-into"),
                "--archive",
                str(recorded["archive"]),
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "REBUILD REPRODUCED THE PUBLISHED RESULT EXACTLY." in out
    assert "expected to differ, never compared" in out
    assert "Reproduced means:" in out

    # a mismatch exits 1, a missing baseline exits 2
    tampered = _tampered(
        recorded,
        tmp_path,
        lambda b: b["outputs"].__setitem__("total_energy_charge_gbp_exact", "0"),
    )
    assert (
        cli.replay_published_main(
            [
                "--baseline",
                str(tampered),
                "--into",
                str(tmp_path / "cli-bad"),
                "--archive",
                str(recorded["archive"]),
            ]
        )
        == 1
    )
    assert "REBUILD DID NOT REPRODUCE THE BASELINE." in capsys.readouterr().out
    assert cli.replay_published_main(["--baseline", str(tmp_path / "nope.json")]) == 2
