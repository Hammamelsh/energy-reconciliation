"""ANL-003 step 5(b): building one candidate, and the stale-record risk it closes.

Two defects were measured before this command existed, and both are regression-tested
here rather than described:

1. **Inherited history.** ``COPY FROM DATABASE`` copies ``scenario_build`` whole, build
   record included. A snapshot of a warehouse that had itself been built therefore
   arrived carrying a record saying it had been built, and ``finalise`` accepted it.
2. **A stale record outliving its tables.** dbt fails per model. A second attempt in the
   same file replaced some tables, skipped others, and left the first attempt's record
   standing; ``finalise`` accepted that too.

The lifecycle closes the first by clearing the build schema at creation, and the second
two ways: the supported command refuses to reuse a file at all (so a rebuild is refused
**before** any mutation), and the build record now carries a digest of the built tables
that ``finalise`` recomputes, so a record that no longer describes its file is refused
whatever path produced it.
"""

from __future__ import annotations

import shutil
import stat
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

    Before the digest check this passed, because the inherited tables and the inherited
    record agreed with each other -- they were simply not this candidate's build. The
    row-count guard catches it here; `_clear_inherited_build` is what stops it arising.
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
    assert cand._clear_inherited_build(bare), "the snapshot did inherit a build schema"
    with pytest.raises(pub.PromotionRefused):
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
    assert still == [(first_run,)], "the failed attempt recorded nothing, as designed"
    assert bands == [("Peak",)], "but it did replace the schedule dimension"
    assert _digest_of_outputs(candidate) != good_digest
    with pytest.raises(pub.PromotionRefused, match="changed them after that build"):
        pub.finalise(candidate)


def test_a_failed_rebuild_leaving_tables_identical_is_not_detectable_by_digest(work):
    """The honest limit of the digest, measured rather than assumed.

    When the second attempt fails on the very first model, dbt rebuilds the independent
    models to identical contents and skips the rest. Nothing moved, so the digest cannot
    object -- and should not: the record does still describe the file. What protects the
    supported path here is the lifecycle, which the next test proves.
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
    seal = pub.finalise(candidate)
    assert seal.run_id == first_run, (
        "so sealing succeeds, over contents that are genuinely unchanged"
    )


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
    assert code != 0, "a sealed candidate cannot be rebuilt"
    assert pub._sha256(built.candidate) == before_bytes
    assert _digest_of_outputs(built.candidate) == before_digest
    assert pub.read_seal(built.candidate).run_id == built.seal.run_id
