"""The publication core, exercised the way the proof exercised its primitives.

These scenarios were first run against proof code in the step-5 review and are now run
against :mod:`energy_reconciliation.publication`. Where a scenario needs another process
-- a reader holding a file, a builder dying mid-write, two promoters racing, a promoter
dying between fsync and rename, a live lock holder -- it uses a **real** child process,
not a thread and not a mock. Where it needs a build, it writes the same
``scenario_build.dbt_build_run`` record that ``run-dbt`` writes, through the same function.

Two boundaries this file keeps visible:

- **Tested interruption recovery** (a process dies at a chosen point; the module recovers)
  is not **power-loss durability** (the disk loses what was not flushed). The fsyncs are
  called; nothing here removes power.
- The guarantees are **filesystem properties**. The fixtures live under the repository on
  ext4 because ``/tmp`` here is tmpfs, and the first test asserts that.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import time
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest
from conftest import HEADER, MEMBER, row

from energy_reconciliation import dbt_macros, dbt_run
from energy_reconciliation import publication as pub
from energy_reconciliation.ingest.loader import load_member

pytest.importorskip("dbt.cli.main", reason="dbt is not installed")

REPO = dbt_macros.repository_root()
SCRATCH_ROOT = REPO / "data" / "proof-scratch"


# ------------------------------------------------------------------ fixtures
def _filesystem(path: Path) -> str:
    return subprocess.run(
        ["stat", "-f", "-c", "%T", str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@pytest.fixture
def root():
    """A disposable publication root under the repository, on the real filesystem."""
    SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
    assert _filesystem(SCRATCH_ROOT).startswith("ext"), (
        "the rename and O_EXCL guarantees are ext4 properties; refusing to prove them "
        f"on {_filesystem(SCRATCH_ROOT)}"
    )
    path = SCRATCH_ROOT / uuid.uuid4().hex[:8]
    (path / pub.VERSIONS).mkdir(parents=True)
    yield path
    # sealed files are read-only; make them deletable before removing the tree
    for file in path.rglob("*"):
        if file.is_file():
            file.chmod(stat.S_IRUSR | stat.S_IWUSR)
    shutil.rmtree(path, ignore_errors=True)


def _source_warehouse(root: Path) -> Path:
    archive = root / "source.zip"
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
    database = root / "source.duckdb"
    assert load_member(archive, MEMBER, database).complete
    return database


def _snapshot(source: Path, target: Path) -> None:
    con = duckdb.connect(":memory:")
    try:
        con.execute(f"ATTACH '{source}' AS src (READ_ONLY)")
        con.execute(f"ATTACH '{target}' AS dst")
        con.execute("COPY FROM DATABASE src TO dst")
    finally:
        con.close()


def _stand_in_build(candidate: Path, run_id: str, rows: int) -> None:
    """What a successful build leaves behind: a fact and THE real build record."""
    con = duckdb.connect(str(candidate))
    try:
        con.execute("CREATE SCHEMA IF NOT EXISTS scenario_build")
        con.execute(
            "CREATE OR REPLACE TABLE scenario_build.fact AS "
            f"SELECT range AS i, '{run_id}' AS run_id FROM range({rows})"
        )
    finally:
        con.close()
    dbt_run.record_build(
        candidate,
        "demo",
        ["build"],
        REPO / "dbt",
        run_id,
        datetime.now(UTC).replace(tzinfo=None),
        "ToU",
    )


def _candidate(root: Path, source: Path, n: str, rows: int = 20) -> Path:
    candidate = root / pub.VERSIONS / f"cand-{n}.duckdb"
    _snapshot(source, candidate)
    _stand_in_build(candidate, f"run-{n}", rows)
    return candidate


def _publish_v1(root: Path, source: Path) -> dict:
    candidate = _candidate(root, source, "0001", rows=10)
    pub.finalise(candidate)
    return pub.publish(candidate, expected_previous=None, root=root)


def _read(path: Path) -> dict:
    con = duckdb.connect(str(path), read_only=True)
    try:
        return {
            "rows": con.execute("select count(*) from scenario_build.fact").fetchone()[
                0
            ],
            "run_id": con.execute(
                f"select run_id from {dbt_run.BUILD_RUN_TABLE}"
            ).fetchone()[0],
        }
    finally:
        con.close()


# ------------------------------------------------------------ child processes
_PRELUDE = "import sys; sys.path.insert(0, {src!r}); sys.path.insert(0, {tests!r})\n"

READER = (
    _PRELUDE
    + """
import json, time
from pathlib import Path
from energy_reconciliation import publication as pub
from test_publication import _read
root = Path({root!r}); signal = Path({signal!r}) if {signal!r} else None
path, manifest = pub.resolve(root)                      # ONE resolve per render
first = {{**_read(path), "file": path.name, "version": manifest["version"]}}
if signal is not None:
    signal.touch()
    deadline = time.time() + 20
    while not signal.with_suffix(".go").exists() and time.time() < deadline:
        time.sleep(0.05)
second = {{**_read(path), "file": path.name, "version": manifest["version"]}}
print(json.dumps({{"first": first, "second": second}}))
"""
)

SLOW_BUILDER = (
    _PRELUDE
    + """
import duckdb, os, time
from pathlib import Path
from test_publication import _snapshot, _stand_in_build
cand = Path({candidate!r})
_snapshot(Path({source!r}), cand)
con = duckdb.connect(str(cand))
con.execute("CREATE SCHEMA IF NOT EXISTS scenario_build")
con.execute("CREATE TABLE scenario_build.fact AS SELECT range AS i FROM range(5)")
Path({started!r}).touch()
time.sleep({hold})
if {crash}:
    con.execute("INSERT INTO scenario_build.fact SELECT range FROM range(5, 100)")
    os._exit(1)                                          # no close, no checkpoint
con.close()
_stand_in_build(cand, "run-0002", 20)
"""
)

PROMOTER = (
    _PRELUDE
    + """
import json, os, time
from pathlib import Path
from energy_reconciliation import publication as pub
root = Path({root!r})
if {crash}:
    pub._BEFORE_RENAME = lambda: os._exit(3)             # die between fsync and rename
while not Path({go!r}).exists():
    time.sleep(0.01)
try:
    m = pub.publish(root / "versions" / {candidate!r}, expected_previous={expected!r}, root=root)
    print(json.dumps({{"won": True, "version": m["version"]}}))
except pub.PublicationError as e:
    print(json.dumps({{"won": False, "why": type(e).__name__}}))
"""
)

LOCK_HOLDER = (
    _PRELUDE
    + """
import time
from pathlib import Path
from energy_reconciliation import publication as pub
pub._acquire_lock(Path({root!r}))
Path({held!r}).touch()
time.sleep(30)
"""
)


def _child(script: str, **kw) -> subprocess.Popen:
    code = script.format(src=str(REPO / "src"), tests=str(REPO / "tests"), **kw)
    return subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _finish(proc: subprocess.Popen, timeout: float = 60):
    out, err = proc.communicate(timeout=timeout)
    return proc.returncode, out, err


def _wait_for(path: Path, timeout: float = 20) -> None:
    deadline = time.time() + timeout
    while not path.exists() and time.time() < deadline:
        time.sleep(0.05)
    assert path.exists(), f"{path} never appeared"


# ================================================================ scenarios
def test_fixtures_are_on_ext4_and_tmp_is_tmpfs(root):
    assert _filesystem(root).startswith("ext")
    assert _filesystem(Path("/tmp")) == "tmpfs", (
        "update the module docstring if this changes"
    )


def test_nothing_published_is_an_explicit_unavailable_state(root):
    with pytest.raises(pub.Unavailable, match="explicit absence"):
        pub.resolve(root)
    assert pub.main(["--root", str(root), "status"]) == 1


# ----------------------------------------------------------- finalise / seal
def test_finalise_refuses_an_unbuilt_candidate(root):
    source = _source_warehouse(root)
    candidate = root / pub.VERSIONS / "cand-raw.duckdb"
    _snapshot(source, candidate)
    with pytest.raises(pub.PromotionRefused, match="no successful build record"):
        pub.finalise(candidate)


def test_finalise_seals_and_makes_the_file_read_only(root):
    source = _source_warehouse(root)
    candidate = _candidate(root, source, "0001")
    assert os.access(candidate, os.W_OK), "writable during construction"
    seal = pub.finalise(candidate)
    assert seal.run_id == "run-0001" and seal.sha256 == pub._sha256(candidate)
    assert (candidate.with_name(candidate.name + pub.SEAL_SUFFIX)).is_file()
    assert not os.access(candidate, os.W_OK), "immutable after finalisation"
    with pytest.raises(duckdb.Error):
        duckdb.connect(str(candidate))  # read-write open must now fail
    duckdb.connect(str(candidate), read_only=True).close()  # read-only still fine
    assert pub.finalise(candidate) == seal, "sealing again is a no-op"


def test_a_candidate_reused_for_two_builds_is_refused(root):
    source = _source_warehouse(root)
    candidate = _candidate(root, source, "0001")
    _stand_in_build(candidate, "run-0001b", 5)  # a second attempt in the same file
    with pytest.raises(pub.PromotionRefused, match="2 build records"):
        pub.finalise(candidate)


# ------------------------------------------------------------- reader/builder
def test_a_reader_reads_the_published_version_while_a_candidate_builds(root):
    source = _source_warehouse(root)
    _publish_v1(root, source)
    started = root / "started"
    builder = _child(
        SLOW_BUILDER,
        candidate=str(root / pub.VERSIONS / "cand-0002.duckdb"),
        source=str(source),
        started=str(started),
        hold=2.0,
        crash=False,
    )
    _wait_for(started)
    reader = _child(READER, root=str(root), signal="")
    code, out, err = _finish(reader)
    assert code == 0, err
    assert json.loads(out)["first"] == {
        "rows": 10,
        "run_id": "run-0001",
        "file": "cand-0001.duckdb",
        "version": "v0001",
    }
    code, _, err = _finish(builder)
    assert code == 0, err
    assert not (root / pub.VERSIONS / "cand-0002.duckdb.wal").exists()


def test_failure_midway_leaves_the_published_version_readable_and_unpromotable(root):
    source = _source_warehouse(root)
    before = pub.read_manifest(root) or _publish_v1(root, source)
    candidate = root / pub.VERSIONS / "cand-0002.duckdb"
    builder = _child(
        SLOW_BUILDER,
        candidate=str(candidate),
        source=str(source),
        started=str(root / "started"),
        hold=0.2,
        crash=True,
    )
    assert _finish(builder)[0] == 1
    assert pub.read_manifest(root) == before
    path, _ = pub.resolve(root)
    assert _read(path)["rows"] == 10
    assert candidate.exists() and candidate.with_name(candidate.name + ".wal").exists()
    with pytest.raises(pub.PromotionRefused, match="wal"):
        pub.finalise(candidate)
    with pytest.raises(pub.PromotionRefused, match="not sealed"):
        pub.publish(candidate, expected_previous="v0001", root=root)
    assert pub.read_manifest(root) == before
    assert [v.role for v in pub.inventory(root) if v.file == candidate.name] == [
        "broken"
    ]


# ------------------------------------------------------------------ the gate
def test_promotion_requires_the_exact_sealed_bytes(root):
    source = _source_warehouse(root)
    _publish_v1(root, source)
    candidate = _candidate(root, source, "0002")
    with pytest.raises(pub.PromotionRefused, match="not sealed"):
        pub.publish(candidate, expected_previous="v0001", root=root)
    seal = pub.finalise(candidate)
    # someone forces the file writable and changes it after validation
    candidate.chmod(stat.S_IRUSR | stat.S_IWUSR)
    con = duckdb.connect(str(candidate))
    con.execute("INSERT INTO scenario_build.fact VALUES (999, 'run-0002')")
    con.close()
    with pytest.raises(pub.PromotionRefused, match="changed after validation"):
        pub.publish(candidate, expected_previous="v0001", root=root)
    assert pub.read_manifest(root)["version"] == "v0001"
    with pytest.raises(pub.PromotionRefused, match="changed after sealing"):
        pub.finalise(candidate)
    assert seal.sha256 != pub._sha256(candidate)


def test_a_file_outside_versions_is_not_publishable(root):
    source = _source_warehouse(root)
    _publish_v1(root, source)
    elsewhere = root / "elsewhere.duckdb"
    _snapshot(source, elsewhere)
    _stand_in_build(elsewhere, "run-x", 3)
    pub.finalise(elsewhere)
    with pytest.raises(pub.PromotionRefused, match="not under"):
        pub.publish(elsewhere, expected_previous="v0001", root=root)


def test_a_real_run_dbt_build_on_a_snapshot_can_be_sealed_and_promoted(root):
    source = _source_warehouse(root)
    _publish_v1(root, source)
    candidate = root / pub.VERSIONS / "cand-dbt.duckdb"
    _snapshot(source, candidate)
    assert (
        dbt_run.main(
            [
                "--database",
                str(candidate),
                "--schedule",
                "demo",
                "build",
                "--target-path",
                str(root / "target"),
            ]
        )
        == 0
    )
    seal = pub.finalise(candidate)
    assert seal.run_id.startswith(dbt_run.CANDIDATE_PREFIX)
    assert seal.dbt_core_version == dbt_run.dbt_identity()["dbt-core"]
    manifest = pub.publish(candidate, expected_previous="v0001", root=root)
    assert manifest["run_id"] == seal.run_id
    assert manifest["dbt_duckdb_version"] == dbt_run.dbt_identity()["dbt-duckdb"]
    path, _ = pub.resolve(root)
    con = duckdb.connect(str(path), read_only=True)
    charged = con.execute(
        "select count(*) from scenario_build.fact_interval_charge_scenario"
    ).fetchone()[0]
    con.close()
    assert charged == 48


# --------------------------------------------------------------- coherence
def test_a_reader_spanning_a_promotion_sees_one_version_and_its_metadata(root):
    source = _source_warehouse(root)
    _publish_v1(root, source)
    candidate = _candidate(root, source, "0002")
    pub.finalise(candidate)
    signal = root / "read-once"
    reader = _child(READER, root=str(root), signal=str(signal))
    _wait_for(signal)
    pub.publish(candidate, expected_previous="v0001", root=root)  # mid-render
    signal.with_suffix(".go").touch()
    code, out, err = _finish(reader)
    assert code == 0, err
    seen = json.loads(out)
    assert seen["first"] == seen["second"]
    assert seen["first"]["version"] == "v0001" and seen["first"]["run_id"] == "run-0001"
    assert pub.resolve(root)[1]["version"] == "v0002"


# ----------------------------------------------------- interruption/recovery
def test_dying_between_fsync_and_rename_is_recoverable_and_never_edits_the_manifest(
    root,
):
    source = _source_warehouse(root)
    before = _publish_v1(root, source)
    candidate = _candidate(root, source, "0002")
    pub.finalise(candidate)
    go = root / "go"
    promoter = _child(
        PROMOTER,
        root=str(root),
        go=str(go),
        candidate="cand-0002.duckdb",
        expected="v0001",
        crash=True,
    )
    go.touch()
    assert _finish(promoter)[0] == 3
    assert pub.read_manifest(root) == before
    assert (root / pub.MANIFEST_TMP).exists() and (root / pub.PROMOTE_LOCK).exists()
    with pytest.raises(pub.StalePromotion, match="holds"):
        pub.publish(candidate, expected_previous="v0001", root=root)
    actions = pub.recover(root)
    assert len(actions) == 2 and pub.read_manifest(root) == before
    assert (
        pub.publish(candidate, expected_previous="v0001", root=root)["version"]
        == "v0002"
    )
    history = [json.loads(l) for l in (root / pub.HISTORY).read_text().splitlines()]
    assert [h["version"] for h in history] == ["v0001", "v0002"]


def test_recovery_refuses_to_remove_a_live_processs_lock(root):
    source = _source_warehouse(root)
    _publish_v1(root, source)
    held = root / "held"
    holder = _child(LOCK_HOLDER, root=str(root), held=str(held))
    _wait_for(held)
    try:
        with pytest.raises(pub.RecoveryRefused, match="still running"):
            pub.recover(root)
        assert (root / pub.PROMOTE_LOCK).exists(), "the live lock was left alone"
    finally:
        holder.kill()
        holder.wait()
    assert pub.recover(root) == [f"removed lock left by dead pid {holder.pid}"]


def test_recovery_never_touches_candidates_or_versions(root):
    source = _source_warehouse(root)
    _publish_v1(root, source)
    partial = root / pub.VERSIONS / "cand-partial.duckdb"
    _snapshot(source, partial)
    (root / pub.MANIFEST_TMP).write_text("{}")
    assert pub.recover(root) == [f"removed orphan {pub.MANIFEST_TMP}"]
    assert partial.exists(), "a partial build is evidence; recovery leaves it"


# -------------------------------------------------------- competing / stale
def test_competing_promotions_exactly_one_wins(root):
    source = _source_warehouse(root)
    _publish_v1(root, source)
    for n in ("0002", "0003"):
        pub.finalise(_candidate(root, source, n))
    go = root / "go"
    racers = [
        _child(
            PROMOTER,
            root=str(root),
            go=str(go),
            candidate=f"cand-{n}.duckdb",
            expected="v0001",
            crash=False,
        )
        for n in ("0002", "0003")
    ]
    time.sleep(0.3)
    go.touch()
    outcomes = [json.loads(_finish(r)[1]) for r in racers]
    assert sorted(o["won"] for o in outcomes) == [False, True], outcomes
    assert next(o for o in outcomes if not o["won"])["why"] == "StalePromotion"
    assert pub.read_manifest(root)["version"] == "v0002"


def test_a_stale_request_is_refused_and_changes_nothing(root):
    source = _source_warehouse(root)
    _publish_v1(root, source)
    two, three = (_candidate(root, source, n) for n in ("0002", "0003"))
    pub.finalise(two)
    pub.finalise(three)
    pub.publish(two, expected_previous="v0001", root=root)
    with pytest.raises(pub.StalePromotion, match="expected 'v0001'"):
        pub.publish(three, expected_previous="v0001", root=root)
    assert pub.read_manifest(root)["file"] == "cand-0002.duckdb"


# ------------------------------------------------------------------ rollback
def test_rollback_is_a_manifest_change_that_keeps_old_versions(root):
    source = _source_warehouse(root)
    _publish_v1(root, source)
    two = _candidate(root, source, "0002")
    pub.finalise(two)
    pub.publish(two, expected_previous="v0001", root=root)
    started = time.time()
    manifest = pub.rollback("cand-0001.duckdb", expected_previous="v0002", root=root)
    assert time.time() - started < 5
    assert manifest["version"] == "v0003" and manifest["file"] == "cand-0001.duckdb"
    path, _ = pub.resolve(root)
    assert _read(path)["run_id"] == "run-0001"
    roles = {v.file: v.role for v in pub.inventory(root)}
    assert roles == {"cand-0001.duckdb": "published", "cand-0002.duckdb": "previous"}
    assert all(f.exists() for f in (root / pub.VERSIONS).glob("cand-*.duckdb"))


def test_inventory_is_a_dry_run_and_deletes_nothing(root):
    source = _source_warehouse(root)
    _publish_v1(root, source)
    sealed = _candidate(root, source, "0002")
    pub.finalise(sealed)
    unsealed = _candidate(root, source, "0003")
    before = sorted(p.name for p in (root / pub.VERSIONS).iterdir())
    roles = {v.file: v.role for v in pub.inventory(root)}
    assert roles == {
        "cand-0001.duckdb": "published",
        "cand-0002.duckdb": "sealed-unpublished",
        "cand-0003.duckdb": "unsealed",
    }
    assert sorted(p.name for p in (root / pub.VERSIONS).iterdir()) == before
    assert pub.main(["--root", str(root), "inventory"]) == 0
    assert unsealed.exists()


def test_the_cli_promotes_and_reports(root, capsys):
    source = _source_warehouse(root)
    _publish_v1(root, source)
    two = _candidate(root, source, "0002")
    assert pub.main(["--root", str(root), "finalise", str(two)]) == 0
    assert (
        pub.main(
            ["--root", str(root), "promote", str(two), "--expect-published", "v0001"]
        )
        == 0
    )
    assert "published v0002" in capsys.readouterr().out
    assert (
        pub.main(
            ["--root", str(root), "promote", str(two), "--expect-published", "v0001"]
        )
        == 2
    )
    assert "StalePromotion" in capsys.readouterr().err
    assert pub.main(["--root", str(root), "status"]) == 0
    assert "published v0002" in capsys.readouterr().out
