"""ANL-003 step 5(b)/(c'): building one candidate, and the attempt lifecycle that seals it.

Two defects were measured before the command existed, and both are regression-tested
here rather than described:

1. **Inherited history.** ``COPY FROM DATABASE`` copies ``scenario_build`` whole, build
   record included. A snapshot of a warehouse that had itself been built therefore
   arrived carrying a record saying it had been built, and ``finalise`` accepted it.
2. **A stale record outliving its tables.** dbt fails per model. A second attempt in the
   same file replaced some tables, skipped others, and left the first attempt's record
   standing; ``finalise`` accepted that too.

A third was measured after the first fix: a failed rebuild that left the tables
**identical** was invisible to the output digest, so an earlier success sealed a file
whose latest attempt had failed. The lifecycle now records every ``run-dbt`` attempt
before dbt runs -- ``started``, then ``succeeded`` or ``failed`` -- and ``finalise``
requires the **latest** attempt to have succeeded, in this file, with the tables still
digesting as it recorded. Output equality and attempt success are checked separately.
"""

from __future__ import annotations

import shutil
import stat
import subprocess
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path

import duckdb
import pytest
from conftest import HEADER, MEMBER, row

from energy_reconciliation import candidate as cand
from energy_reconciliation import dbt_run
from energy_reconciliation import publication as pub
from energy_reconciliation.ingest.loader import load_member

pytest.importorskip("dbt.cli.main", reason="dbt is not installed")

SCRATCH_ROOT = Path(__file__).resolve().parent.parent / "data" / "proof-scratch"


@pytest.fixture
def work(tmp_path_factory):
    """A disposable working area on the repository's own filesystem."""
    SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
    path = Path(str(tmp_path_factory.mktemp("candidate", numbered=True)))
    yield path
    for file in path.rglob("*"):
        if file.is_file():
            file.chmod(stat.S_IRUSR | stat.S_IWUSR)
    shutil.rmtree(path, ignore_errors=True)


def _warehouse(work: Path, name: str = "source") -> Path:
    archive = work / f"{name}.zip"
    body = HEADER + b"".join(
        row(
            "MAC000001",
            "ToU",
            f"2013-01-01 {i // 2:02d}:{(i % 2) * 30:02d}:00.0000000",
            " 1 ",
        )
        for i in range(48)
    )
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(MEMBER, body)
    database = work / f"{name}.duckdb"
    assert load_member(archive, MEMBER, database).complete
    return database


def _unknown_band_workbook(path: Path) -> Path:
    """A schedule that is structurally valid but uses a band the project does not price.

    It builds -- `schedule._validate` only refuses duplicates, off-grid labels and blanks
    -- so `dim_tariff_band_schedule` is rebuilt with **different contents**, and then the
    accepted_values test on `band_label` fails the run. That is the shape of failure the
    digest exists to catch: the tables moved, the record did not.
    """
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = "Sheet1"
    sheet.append(["TariffDateTime", "Tariff"])
    sheet.append([datetime(2013, 1, 1, 0, 0), "Peak"])  # noqa: DTZ001 - naive, as the source is
    sheet.append([datetime(2013, 1, 1, 0, 30), "Peak"])  # noqa: DTZ001
    book.save(path)
    return path


def _bad_workbook(path: Path) -> Path:
    """A schedule that repeats one label with two bands: refused by `schedule._validate`."""
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = "Sheet1"
    sheet.append(["TariffDateTime", "Tariff"])
    sheet.append([datetime(2013, 1, 1, 0, 0), "Normal"])  # noqa: DTZ001 - naive, as the source is
    sheet.append([datetime(2013, 1, 1, 0, 30), "High"])  # noqa: DTZ001
    sheet.append([datetime(2013, 1, 1, 0, 30), "Low"])  # noqa: DTZ001
    book.save(path)
    return path


def _build(work: Path, source: Path, **kw):
    return cand.build_candidate(
        source, root=work / "pub", schedule=kw.pop("schedule", "demo"), **kw
    )


def _digest_of_outputs(database: Path) -> str:
    con = duckdb.connect(str(database), read_only=True)
    try:
        return dbt_run.build_output_digest(con)
    finally:
        con.close()


# ------------------------------------------------------------------ success
def test_a_demo_candidate_builds_seals_and_is_not_published(work):
    source = _warehouse(work)
    source_before = pub._sha256(source)
    built = _build(work, source)

    assert built.candidate.is_file()
    assert built.models == 5 and built.tests == 49
    assert built.seal.schedule_variant == "demo" and built.seal.tariff_group == "ToU"
    assert not built.candidate.stat().st_mode & stat.S_IWUSR, (
        "sealed files are read-only"
    )
    # nothing was published
    assert pub.read_manifest(work / "pub") is None
    with pytest.raises(pub.Unavailable):
        pub.resolve(work / "pub")
    assert [v.role for v in pub.inventory(work / "pub")] == ["sealed-unpublished"]
    # the source is untouched
    assert pub._sha256(source) == source_before


def test_the_recorded_identity_agrees_with_the_seal_and_the_build(work):
    source = _warehouse(work)
    built = _build(work, source)
    con = duckdb.connect(str(built.candidate), read_only=True)
    try:
        run_id, digest = con.execute(
            f"SELECT run_id, built_output_sha256 FROM {dbt_run.BUILD_RUN_TABLE}"
        ).fetchone()
    finally:
        con.close()
    assert built.seal.run_id == run_id
    assert (
        built.seal.built_output_sha256 == digest == _digest_of_outputs(built.candidate)
    )
    assert built.seal.sha256 == pub._sha256(built.candidate)
    assert built.seal.dbt_core_version == dbt_run.dbt_identity()["dbt-core"]
    assert built.seal.output_digest_version == dbt_run.OUTPUT_DIGEST_VERSION


def test_the_recorded_identity_covers_what_produces_the_tables(work):
    """dbt, DuckDB, PyArrow, pandas, dimensions.py and the dbt project, all on the record."""
    import json

    from energy_reconciliation.tariff import candidate_identity as cid

    source = _warehouse(work)
    built = _build(work, source)
    con = duckdb.connect(str(built.candidate), read_only=True)
    try:
        record = dict(
            zip(
                dbt_run._BUILD_RUN_COLUMNS,
                con.execute(f"SELECT * FROM {dbt_run.BUILD_RUN_TABLE}").fetchone(),
                strict=True,
            )
        )
    finally:
        con.close()
    runtime = json.loads(record["runtime_detail"])
    assert set(runtime) >= {"duckdb", "pyarrow", "pandas", "dbt-core", "dbt-duckdb"}
    assert runtime == cid.candidate_runtime_identity()
    covered = json.loads(record["covered_files"])
    assert "src/energy_reconciliation/tariff/dimensions.py" in covered
    assert "dbt/macros/generated_policy.sql" in covered
    assert "dbt/models/tariff/fact_interval_charge_scenario.sql" in covered
    assert "src/energy_reconciliation/policy.py" in covered
    assert record["calculation_code_sha256"] == cid.candidate_calculation_digest()
    assert record["database_path"] == str(built.candidate.resolve())
    assert record["status"] == dbt_run.SUCCEEDED and record["dbt_exit_code"] == 0
    # resolved configuration and the schedule identity of what was actually built
    assert json.loads(record["dbt_vars"])["schedule"] == "demo"
    assert (
        record["schedule_source"] == "synthetic-demo" and record["schedule_rows"] == 48
    )
    assert record["price_catalogue_version"]
    assert built.seal.schedule_source == "synthetic-demo"
    assert built.seal.calculation_code_sha256 == record["calculation_code_sha256"]


def test_each_invocation_writes_a_fresh_file(work):
    source = _warehouse(work)
    first = _build(work, source)
    second = _build(work, source)
    assert first.candidate != second.candidate
    assert first.seal.run_id != second.seal.run_id
    assert first.candidate.is_file() and second.candidate.is_file()


# ------------------------------------------------------------------ refusals
def test_a_missing_source_is_refused_and_not_created(work):
    missing = work / "not-there.duckdb"
    with pytest.raises(cand.CandidateError) as error:
        _build(work, missing)
    assert error.value.stage == cand.VALIDATE
    assert not missing.exists(), "validating a source must never create it"


def test_a_source_that_is_not_a_warehouse_is_refused(work):
    empty = work / "blank.duckdb"
    duckdb.connect(str(empty)).close()
    with pytest.raises(cand.CandidateError, match="no main.readings"):
        _build(work, empty)


def test_an_existing_candidate_destination_is_refused(work):
    source = _warehouse(work)
    taken = work / "pub" / pub.VERSIONS / "taken.duckdb"
    taken.parent.mkdir(parents=True)
    taken.write_bytes(b"not a database")
    before = taken.read_bytes()
    with pytest.raises(cand.CandidateError, match="already exists"):
        _build(work, source, candidate=taken)
    assert taken.read_bytes() == before, "the existing file is left exactly as it was"


def test_the_candidate_may_not_be_the_source(work):
    source = _warehouse(work)
    with pytest.raises(cand.CandidateError, match="same file"):
        _build(work, source, candidate=source)


def test_a_candidate_may_not_be_written_into_the_warehouse_directory(work, monkeypatch):
    source = _warehouse(work)
    warehouse = work / "warehouse"
    warehouse.mkdir()
    monkeypatch.setattr(cand, "WAREHOUSE_DIR", warehouse)
    with pytest.raises(cand.CandidateError, match="where ingestion writes"):
        _build(work, source, candidate=warehouse / "energy.duckdb")


def test_a_published_version_may_not_be_overwritten(work):
    source = _warehouse(work)
    built = _build(work, source)
    pub.publish(built.candidate, expected_previous=None, root=work / "pub")
    with pytest.raises(cand.CandidateError, match="published version"):
        _build(work, source, candidate=built.candidate)


# ------------------------------------------------------- failure leaves evidence
def test_a_failed_build_is_unsealed_unpromotable_and_changes_nothing(work):
    source = _warehouse(work)
    first = _build(work, source)
    published = pub.publish(first.candidate, expected_previous=None, root=work / "pub")
    source_before = pub._sha256(source)

    with pytest.raises(cand.CandidateError) as error:
        _build(
            work,
            source,
            schedule="workbook",
            workbook=str(_bad_workbook(work / "bad.xlsx")),
        )
    failed = error.value.candidate
    assert error.value.stage == cand.BUILD
    assert failed is not None and failed.is_file(), "the failed candidate is kept"
    assert not pub._seal_path(failed).exists(), "and is not sealed"
    with pytest.raises(pub.PromotionRefused):
        pub.finalise(failed)
    with pytest.raises(pub.PromotionRefused, match="not sealed"):
        pub.publish(failed, expected_previous=published["version"], root=work / "pub")
    # the publication and the source are exactly as they were
    assert pub.read_manifest(work / "pub") == published
    assert pub.resolve(work / "pub")[0] == first.candidate
    assert pub._sha256(source) == source_before


def test_the_cli_reports_the_failed_stage_and_the_candidate_path(work, capsys):
    source = _warehouse(work)
    code = cand.main(
        [
            "--source",
            str(source),
            "--root",
            str(work / "pub"),
            "--schedule",
            "workbook",
            "--workbook",
            str(_bad_workbook(work / "bad.xlsx")),
        ]
    )
    assert code == 1
    message = capsys.readouterr().err
    assert f"[{cand.BUILD}]" in message
    assert "candidate: " in message


def test_the_cli_reports_success_as_ready_for_promotion_not_active(work, capsys):
    source = _warehouse(work)
    assert (
        cand.main(
            ["--source", str(source), "--root", str(work / "pub"), "--schedule", "demo"]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "READY FOR PROMOTION" in out and "not published" in out
    assert "uv run publication" in out, (
        "it tells you how to promote, rather than doing it"
    )
    assert pub.read_manifest(work / "pub") is None


# --------------------------------------------- inherited and stale build records
def test_a_source_carrying_build_history_does_not_confuse_the_candidate(work):
    """Measured defect: the snapshot inherited the record and finalise accepted it."""
    source = _warehouse(work)
    # dirty the source exactly as someone experimenting with run-dbt would
    assert (
        dbt_run.main(
            [
                "--database",
                str(source),
                "--schedule",
                "demo",
                "build",
                "--target-path",
                str(work / "t0"),
            ]
        )
        == 0
    )
    con = duckdb.connect(str(source), read_only=True)
    inherited_run = con.execute(
        f"SELECT run_id FROM {dbt_run.BUILD_RUN_TABLE}"
    ).fetchone()[0]
    con.close()

    built = _build(work, source)
    con = duckdb.connect(str(built.candidate), read_only=True)
    try:
        records = con.execute(
            f"SELECT run_id FROM {dbt_run.BUILD_RUN_TABLE}"
        ).fetchall()
    finally:
        con.close()
    assert records == [(built.seal.run_id,)], "exactly this candidate's own build"
    assert built.seal.run_id != inherited_run, "not the source's build"


def test_a_bare_snapshot_of_a_built_warehouse_cannot_be_sealed(work):
    """The inherited record must not authorise a file that was never built as a candidate.

    Before the attempt record carried the path it was written in, this passed only
    because `_clear_inherited_build` removed the record first: the inherited tables and
    the inherited record agreed with each other -- they were simply not this file's
    build. Now `finalise` sees that the attempt names the source, not the copy.
    """
    source = _warehouse(work)
    assert (
        dbt_run.main(
            [
                "--database",
                str(source),
                "--schedule",
                "demo",
                "build",
                "--target-path",
                str(work / "t0"),
            ]
        )
        == 0
    )
    bare = work / "bare.duckdb"
    con = duckdb.connect(":memory:")
    con.execute(f"ATTACH '{source}' AS s (READ_ONLY)")
    con.execute(f"ATTACH '{bare}' AS d")
    con.execute("COPY FROM DATABASE s TO d")
    con.close()
    # the inherited record is a real success whose digest matches the copied tables...
    con = duckdb.connect(str(bare), read_only=True)
    try:
        status, path, digest = con.execute(
            f"SELECT status, database_path, built_output_sha256 FROM {dbt_run.BUILD_RUN_TABLE}"
        ).fetchone()
        assert status == dbt_run.SUCCEEDED
        assert digest == dbt_run.build_output_digest(con)
    finally:
        con.close()
    # ...but it names the source file, so it does not authorise the copy
    assert Path(path) == source.resolve()
    with pytest.raises(pub.PromotionRefused, match="not this file"):
        pub.finalise(bare)
    # and the supported command clears the whole inherited schema before building anyway
    assert "dbt_build_run" in cand._clear_inherited_build(bare)
    with pytest.raises(pub.PromotionRefused, match="no successful build record"):
        pub.finalise(bare)


def _reusable_candidate(work: Path, source: Path, name: str) -> tuple[Path, str, str]:
    """A candidate built directly with run-dbt and left unsealed: the unsupported path."""
    candidate = work / name
    con = duckdb.connect(":memory:")
    con.execute(f"ATTACH '{source}' AS s (READ_ONLY)")
    con.execute(f"ATTACH '{candidate}' AS d")
    con.execute("COPY FROM DATABASE s TO d")
    con.close()
    assert (
        dbt_run.main(
            [
                "--database",
                str(candidate),
                "--schedule",
                "demo",
                "build",
                "--target-path",
                str(work / f"{name}-t1"),
            ]
        )
        == 0
    )
    con = duckdb.connect(str(candidate), read_only=True)
    run_id = con.execute(f"SELECT run_id FROM {dbt_run.BUILD_RUN_TABLE}").fetchone()[0]
    con.close()
    return candidate, run_id, _digest_of_outputs(candidate)


def test_a_failed_rebuild_that_moved_the_tables_cannot_be_sealed(work):
    """The regression this slice exists for, on the unsupported path.

    Built with `run-dbt` and left unsealed, then rebuilt with a schedule that builds but
    fails its band test. The old record survives, the schedule dimension now holds the
    second attempt's rows, and `finalise` must refuse: the record no longer describes the
    file.
    """
    source = _warehouse(work)
    candidate, first_run, good_digest = _reusable_candidate(
        work, source, "moved.duckdb"
    )

    assert (
        dbt_run.main(
            [
                "--database",
                str(candidate),
                "--schedule",
                "workbook",
                "--workbook",
                str(_unknown_band_workbook(work / "peak.xlsx")),
                "build",
                "--target-path",
                str(work / "t2"),
            ]
        )
        != 0
    )
    con = duckdb.connect(str(candidate), read_only=True)
    try:
        still = con.execute(f"SELECT run_id FROM {dbt_run.BUILD_RUN_TABLE}").fetchall()
        bands = con.execute(
            "SELECT DISTINCT band_label FROM scenario_build.dim_tariff_band_schedule"
        ).fetchall()
    finally:
        con.close()
    assert [r for (r,) in still if r == first_run], (
        "the first attempt is still recorded"
    )
    assert bands == [("Peak",)], (
        "and the failed attempt did replace the schedule dimension"
    )
    assert _digest_of_outputs(candidate) != good_digest
    # Refused for the most specific cause first: the latest attempt failed. The digest
    # mismatch is a second, independent reason -- proved separately below.
    with pytest.raises(pub.PromotionRefused, match="latest attempt .* failed"):
        pub.finalise(candidate)
    con = duckdb.connect(str(candidate), read_only=True)
    try:
        latest = con.execute(
            f"SELECT status FROM {dbt_run.BUILD_RUN_TABLE} ORDER BY started_at_utc DESC"
        ).fetchone()[0]
    finally:
        con.close()
    assert latest == dbt_run.FAILED


def test_a_failed_rebuild_leaving_tables_identical_is_refused_by_the_attempt_record(
    work,
):
    """The case the digest cannot see, closed by the attempt lifecycle.

    When the second attempt fails on the very first model, dbt rebuilds the independent
    models to identical contents and skips the rest. Nothing moved, so the digest cannot
    object -- and before attempts were recorded, `finalise` sealed the file on the
    strength of the first success. Now the failed attempt is on record, it is the latest,
    and that alone refuses the seal. Output equality and attempt success are two facts.
    """
    source = _warehouse(work)
    candidate, first_run, good_digest = _reusable_candidate(work, source, "same.duckdb")

    assert (
        dbt_run.main(
            [
                "--database",
                str(candidate),
                "--schedule",
                "workbook",
                "--workbook",
                str(_bad_workbook(work / "dup.xlsx")),
                "build",
                "--target-path",
                str(work / "t2"),
            ]
        )
        != 0
    )
    assert _digest_of_outputs(candidate) == good_digest, (
        "measured: a first-model failure leaves the built tables unchanged"
    )
    con = duckdb.connect(str(candidate), read_only=True)
    try:
        attempts = con.execute(
            f"SELECT run_id, status, dbt_exit_code FROM {dbt_run.BUILD_RUN_TABLE} "
            "ORDER BY started_at_utc"
        ).fetchall()
    finally:
        con.close()
    assert [a[1] for a in attempts] == [dbt_run.SUCCEEDED, dbt_run.FAILED]
    assert attempts[0][0] == first_run and attempts[1][2] not in (None, 0)
    with pytest.raises(pub.PromotionRefused, match="latest attempt .* failed"):
        pub.finalise(candidate)
    assert not pub._seal_path(candidate).exists()


def test_a_direct_edit_after_a_success_is_caught_by_the_digest_not_the_record(work):
    """Outside the lifecycle: no attempt is recorded, so content is the only witness."""
    source = _warehouse(work)
    candidate, _first_run, good_digest = _reusable_candidate(
        work, source, "edited.duckdb"
    )
    con = duckdb.connect(str(candidate))
    con.execute(
        "UPDATE scenario_build.dim_tariff_price SET price_pence_per_kwh = "
        "price_pence_per_kwh + 1 WHERE band_label = 'Low'"
    )
    con.close()
    con = duckdb.connect(str(candidate), read_only=True)
    try:
        statuses = con.execute(
            f"SELECT status FROM {dbt_run.BUILD_RUN_TABLE}"
        ).fetchall()
    finally:
        con.close()
    assert statuses == [(dbt_run.SUCCEEDED,)], "the edit left no attempt behind"
    assert _digest_of_outputs(candidate) != good_digest
    with pytest.raises(pub.PromotionRefused, match="changed them after that build"):
        pub.finalise(candidate)


def test_an_interrupted_attempt_stays_started_and_cannot_be_sealed(work):
    """A real interruption: the run-dbt process is killed while dbt runs.

    dbt is a child process and survives its parent, so it finishes the build, closes the
    file cleanly (no `.wal`) and leaves tables that would digest exactly as a success
    would have recorded. Nobody is left to record the outcome, so the attempt stays
    `started`, and that alone makes the candidate ineligible.
    """
    source = _warehouse(work)
    candidate = work / "interrupted.duckdb"
    con = duckdb.connect(":memory:")
    con.execute(f"ATTACH '{source}' AS s (READ_ONLY)")
    con.execute(f"ATTACH '{candidate}' AS d")
    con.execute("COPY FROM DATABASE s TO d")
    con.close()
    target = work / "t-interrupted"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "energy_reconciliation.dbt_run",
            "--database",
            str(candidate),
            "--schedule",
            "demo",
            "build",
            "--target-path",
            str(target),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # The target directory appears once dbt is running, which is after the started row
    # was written and the recording connection closed.
    deadline = time.monotonic() + 120
    while not target.exists():
        assert process.poll() is None, "run-dbt exited before dbt started"
        assert time.monotonic() < deadline, "dbt did not start in time"
        time.sleep(0.05)
    process.kill()  # SIGKILL the orchestrator only; dbt keeps running
    process.wait()

    # wait for the orphaned dbt to finish and release the file
    deadline = time.monotonic() + 300
    while True:
        assert time.monotonic() < deadline, "dbt did not finish in time"
        if (target / "run_results.json").is_file():
            try:
                con = duckdb.connect(str(candidate), read_only=True)
                break
            except duckdb.Error:
                pass
        time.sleep(0.2)
    try:
        attempts = con.execute(
            f"SELECT status, finished_at_utc, dbt_exit_code FROM {dbt_run.BUILD_RUN_TABLE}"
        ).fetchall()
        facts = con.execute(
            "SELECT COUNT(*) FROM scenario_build.fact_interval_charge_scenario"
        ).fetchone()[0]
    finally:
        con.close()
    assert not pub._wal(candidate).exists(), "dbt closed the file cleanly"
    assert facts > 0, "the orphaned dbt did complete the build"
    assert attempts == [(dbt_run.STARTED, None, None)]
    with pytest.raises(pub.PromotionRefused, match="never finished"):
        pub.finalise(candidate)
    assert not pub._seal_path(candidate).exists()


def test_a_sealing_failure_is_retried_by_finalise_while_the_attempt_is_still_latest(
    work, monkeypatch
):
    """The build succeeded and is recorded; only the sidecar write failed.

    The directory is made unwritable for the duration of the seal, so the sidecar cannot
    be created. `build-candidate` reports the SEAL stage and how to retry; a later
    `finalise` re-runs every check and seals the same attempt.
    """
    source = _warehouse(work)
    real_finalise = pub.finalise

    def finalise_with_unwritable_directory(candidate: Path):
        candidate.parent.chmod(0o555)
        try:
            return real_finalise(candidate)
        finally:
            candidate.parent.chmod(0o755)

    monkeypatch.setattr(
        cand.publication, "finalise", finalise_with_unwritable_directory
    )
    with pytest.raises(cand.CandidateError) as error:
        _build(work, source)
    monkeypatch.undo()
    assert error.value.stage == cand.SEAL
    assert "retry" in str(error.value) and "publication finalise" in str(error.value)
    failed = error.value.candidate
    assert failed is not None and failed.is_file()
    assert not pub._seal_path(failed).exists(), "nothing was sealed"
    assert failed.stat().st_mode & stat.S_IWUSR, "and the file was not made read-only"

    seal = pub.finalise(failed)  # the retry
    con = duckdb.connect(str(failed), read_only=True)
    try:
        (run_id, status) = con.execute(
            f"SELECT run_id, status FROM {dbt_run.BUILD_RUN_TABLE}"
        ).fetchone()
    finally:
        con.close()
    assert (seal.run_id, status) == (run_id, dbt_run.SUCCEEDED)
    assert seal.built_output_sha256 == _digest_of_outputs(failed)
    assert not failed.stat().st_mode & stat.S_IWUSR


def test_a_legacy_build_record_is_refused_with_a_rebuild_message(work):
    """A record in the pre-attempt shape is neither migrated nor reinterpreted."""
    source = _warehouse(work)
    legacy = work / "legacy.duckdb"
    con = duckdb.connect(":memory:")
    con.execute(f"ATTACH '{source}' AS s (READ_ONLY)")
    con.execute(f"ATTACH '{legacy}' AS d")
    con.execute("COPY FROM DATABASE s TO d")
    con.close()
    con = duckdb.connect(str(legacy))
    con.execute("CREATE SCHEMA scenario_build")
    con.execute(
        f"CREATE TABLE {dbt_run.BUILD_RUN_TABLE} (run_id VARCHAR, built_at_utc TIMESTAMP, "
        "built_output_sha256 VARCHAR)"
    )
    con.execute(
        f"INSERT INTO {dbt_run.BUILD_RUN_TABLE} VALUES ('old-run', now(), 'abc')"
    )
    con.close()
    before = pub._sha256(legacy)

    with pytest.raises(pub.PromotionRefused, match="shape this version does not write"):
        pub.finalise(legacy)
    assert (
        dbt_run.main(
            [
                "--database",
                str(legacy),
                "--schedule",
                "demo",
                "build",
                "--target-path",
                str(work / "t-legacy"),
            ]
        )
        == 2
    ), "run-dbt refuses before building, so nothing is dropped or rewritten"
    assert pub._sha256(legacy) == before, "the legacy file is left exactly as it was"


def test_the_supported_command_refuses_a_rebuild_before_touching_the_file(work):
    """On the supported path the refusal comes earlier still: the file is never reused.

    A sealed candidate is read-only, so even a direct `run-dbt` at it is refused before
    it can mutate anything. Both the bytes and the built-table digest are unchanged.
    """
    source = _warehouse(work)
    built = _build(work, source)
    before_bytes = pub._sha256(built.candidate)
    before_digest = _digest_of_outputs(built.candidate)

    # the supported command will not reuse the file at all
    with pytest.raises(cand.CandidateError, match="already has a seal") as error:
        _build(work, source, candidate=built.candidate)
    assert error.value.stage == cand.VALIDATE

    # and the unsupported route cannot open it for writing
    code = dbt_run.main(
        [
            "--database",
            str(built.candidate),
            "--schedule",
            "demo",
            "build",
            "--target-path",
            str(work / "t3"),
        ]
    )
    assert code == 2, "refused as unusable, before any attempt began"
    assert pub._sha256(built.candidate) == before_bytes, (
        "no attempt row was written: a refusal before a build is not an attempt"
    )
    assert _digest_of_outputs(built.candidate) == before_digest
    assert pub.read_seal(built.candidate).run_id == built.seal.run_id
