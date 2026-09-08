"""ANL-003 step 5 proof: immutable versioned databases and an atomically replaced manifest.

**What this is.** A small, executable proof of the publication design chosen in
``docs/anl-003-dbt-design.md`` (D5). It runs **separate reader and builder processes**
against disposable databases on the repository's own filesystem (ext4 — ``/tmp`` here is
tmpfs, and the rename and ``O_EXCL`` guarantees the design leans on are filesystem
properties, so the proof refuses to run on anything else).

**What this is not.** The primitives below (``publish``, ``resolve``, ``rollback``,
``sweep``) are *proof code*: the smallest thing that demonstrates the mechanism. They are
not the production publisher, they are not imported by the application, and the dashboard
is not switched to them. The real dbt build is exercised once, to show the wrapper works
against a snapshot file; every other scenario stands in for a build with direct writes,
because the mechanics under proof are the file, the manifest and the lock, not dbt.

The design's requirements, and which scenario carries each:

- a failed candidate build leaves the last published result readable — *failure midway*;
- partial candidate tables never become published — *failure midway*, *promotion gate*;
- one render uses one coherent version including its metadata — *reader spanning*;
- promotion uses the exact candidate that passed validation — *promotion gate*;
- no published version is an explicit unavailable state — *unavailable*;
- competing or stale promotions cannot both win — *competing*, *stale*;
- interruption at the boundary is recoverable — *boundary interruption*;
- rollback is a manifest change, not a rebuild — *rollback*;
- a reader mid-render must not lose its version to retention — *retention*.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
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
from energy_reconciliation.ingest.loader import load_member

pytest.importorskip("dbt.cli.main", reason="dbt is not installed")

REPO = dbt_macros.repository_root()
SCRATCH_ROOT = REPO / "data" / "proof-scratch"

MANIFEST = "published.json"
MANIFEST_TMP = "published.json.tmp"
PROMOTE_LOCK = "promote.lock"
VERSIONS = "versions"


# ============================================================ proof primitives
class Unavailable(RuntimeError):
    """No published version. Deliberately an error, never an empty dataset."""


class StalePromotion(RuntimeError):
    """The manifest no longer names the version the request expected to replace."""


class PromotionRefused(RuntimeError):
    """The candidate is not a closed, validated file."""


def _fsync_dir(directory: Path) -> None:
    fd = os.open(str(directory), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def read_manifest(root: Path) -> dict | None:
    path = root / MANIFEST
    return json.loads(path.read_text()) if path.is_file() else None


def resolve(root: Path) -> tuple[Path, dict]:
    """The published database and its metadata, from ONE read of the manifest.

    A reader calls this once per render and threads the returned path through every
    query, so every connection it opens is to the same file. It never consults the
    manifest again mid-render.
    """
    manifest = read_manifest(root)
    if manifest is None:
        raise Unavailable(f"{root}: nothing has been published")
    path = root / VERSIONS / manifest["file"]
    if not path.is_file():
        raise Unavailable(
            f"{root}: manifest names {manifest['file']} but it is missing"
        )
    return path, manifest


def validated_record(candidate: Path) -> dict:
    """The candidate's own build record, or a refusal. Read-only; never creates a file."""
    if candidate.with_name(candidate.name + ".wal").exists():
        raise PromotionRefused(
            f"{candidate.name} has a .wal sidecar: the writer did not close and "
            "checkpoint it. Its contents may live partly in the WAL; refusing."
        )
    con = duckdb.connect(str(candidate), read_only=True)
    try:
        rows = con.execute(
            "SELECT run_id, status FROM proof_build_record ORDER BY built_at DESC LIMIT 1"
        ).fetchall()
    except duckdb.Error as error:
        raise PromotionRefused(
            f"{candidate.name}: no build record ({error})"
        ) from error
    finally:
        con.close()
    if not rows or rows[0][1] != "validated":
        raise PromotionRefused(f"{candidate.name}: build record is not 'validated'")
    return {"run_id": rows[0][0], "status": rows[0][1]}


def publish(
    root: Path,
    candidate: Path,
    *,
    expected_previous: str | None,
    expected_run_id: str,
    crash_before_rename: bool = False,
) -> dict:
    """Make ``candidate`` the published version, atomically, if nothing moved underneath.

    Order matters and every step is there for a reason:

    1. ``O_EXCL`` lock file — two promoters cannot both be inside this function.
    2. Compare-and-swap — the manifest must still name ``expected_previous``; a request
       formed against an older state is refused as stale rather than winning.
    3. Gate — the candidate must be closed (no ``.wal``), carry a ``validated`` record,
       and that record's run_id must be the one the caller validated. The exact file,
       not "whatever is at that path now": its digest is recorded.
    4. Write ``published.json.tmp``, fsync it, **rename** over ``published.json``, fsync
       the directory. The rename is the atomic visibility boundary; the fsyncs are the
       power-loss durability, which is a different property.
    """
    (root / VERSIONS).mkdir(parents=True, exist_ok=True)
    lock = root / PROMOTE_LOCK
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise StalePromotion("another promotion holds the lock") from error
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    try:
        current = read_manifest(root)
        current_id = current["version"] if current else None
        if current_id != expected_previous:
            raise StalePromotion(
                f"manifest names {current_id!r}, request expected {expected_previous!r}"
            )
        record = validated_record(candidate)
        if record["run_id"] != expected_run_id:
            raise PromotionRefused(
                f"candidate run_id {record['run_id']} is not the validated {expected_run_id}"
            )
        version = f"v{(current['sequence'] + 1) if current else 1:04d}"
        manifest = {
            "version": version,
            "sequence": (current["sequence"] + 1) if current else 1,
            "file": candidate.name,
            "sha256": _sha256(candidate),
            "run_id": record["run_id"],
            "previous": current_id,
            "previous_file": current["file"] if current else None,
            "promoted_at_utc": datetime.now(UTC).replace(tzinfo=None).isoformat(" "),
        }
        tmp = root / MANIFEST_TMP
        with tmp.open("w") as handle:
            json.dump(manifest, handle, indent=1)
            handle.flush()
            os.fsync(handle.fileno())
        if crash_before_rename:
            os._exit(3)  # simulate dying between durability and visibility
        os.replace(tmp, root / MANIFEST)  # atomic on POSIX, same filesystem
        _fsync_dir(root)
        return manifest
    finally:
        lock.unlink(missing_ok=True)


def recover(root: Path) -> list[str]:
    """After an interruption: remove an orphan tmp manifest and a dead lock. Nothing else.

    The manifest itself is never touched: either the rename happened (new version is
    published) or it did not (old version is published). There is no third state.
    """
    actions = []
    tmp = root / MANIFEST_TMP
    if tmp.exists():
        tmp.unlink()
        actions.append("removed orphan published.json.tmp")
    lock = root / PROMOTE_LOCK
    if lock.exists():
        pid = int(lock.read_text() or 0)
        alive = pid and Path(f"/proc/{pid}").exists()
        if not alive:
            lock.unlink()
            actions.append(f"removed lock left by dead pid {pid}")
    return actions


def rollback(root: Path, to_file: str, *, expected_previous: str) -> dict:
    """Point the manifest at a retained version. Seconds, no rebuild."""
    target = root / VERSIONS / to_file
    return publish(
        root,
        target,
        expected_previous=expected_previous,
        expected_run_id=validated_record(target)["run_id"],
    )


def sweep(root: Path, keep: int, grace_seconds: float) -> list[str]:
    """Delete versions beyond the newest ``keep``, and only if older than ``grace``.

    The published and immediately previous versions are never deleted. The grace window
    exists because a render opens a fresh connection per query to the path it resolved
    at its start; deleting that path mid-render would fail the next query.
    """
    manifest = read_manifest(root)
    protected = {manifest["file"], manifest.get("previous_file")} if manifest else set()
    files = sorted((root / VERSIONS).glob("*.duckdb"), key=lambda p: p.stat().st_mtime)
    removed = []
    for path in files[:-keep] if keep else files:
        if path.name in protected:
            continue
        if time.time() - path.stat().st_mtime < grace_seconds:
            continue
        path.unlink()
        removed.append(path.name)
    return removed


# ============================================================ fixtures
def _assert_real_filesystem(path: Path) -> None:
    kind = subprocess.run(
        ["stat", "-f", "-c", "%T", str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert kind.startswith("ext"), (
        f"{path} is on {kind}; this proof must run on the repository's ext4 filesystem"
    )


@pytest.fixture
def root():
    """A disposable publication root under the repository, removed afterwards."""
    SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
    _assert_real_filesystem(SCRATCH_ROOT)
    path = SCRATCH_ROOT / uuid.uuid4().hex[:8]
    (path / VERSIONS).mkdir(parents=True)
    yield path
    shutil.rmtree(path, ignore_errors=True)


def _source_warehouse(root: Path) -> Path:
    """A small loaded warehouse standing in for data/warehouse/energy.duckdb."""
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
    """The supported consistent copy: source opened READ_ONLY, so it cannot be written."""
    con = duckdb.connect(":memory:")
    try:
        con.execute(f"ATTACH '{source}' AS src (READ_ONLY)")
        con.execute(f"ATTACH '{target}' AS dst")
        con.execute("COPY FROM DATABASE src TO dst")
    finally:
        con.close()


def _stand_in_build(
    candidate: Path, run_id: str, *, rows: int, validated: bool
) -> None:
    """What a build leaves behind, without dbt: a fact table and a build record."""
    con = duckdb.connect(str(candidate))
    try:
        con.execute("CREATE SCHEMA IF NOT EXISTS scenario_build")
        con.execute(
            "CREATE OR REPLACE TABLE scenario_build.fact AS "
            f"SELECT range AS i, '{run_id}' AS run_id FROM range({rows})"
        )
        con.execute(
            "CREATE TABLE IF NOT EXISTS proof_build_record "
            "(run_id VARCHAR, status VARCHAR, built_at TIMESTAMP)"
        )
        con.execute(
            "INSERT INTO proof_build_record VALUES (?, ?, now())",
            [run_id, "validated" if validated else "failed"],
        )
    finally:
        con.close()


def _publish_v1(root: Path, source: Path) -> dict:
    candidate = root / VERSIONS / "cand-0001.duckdb"
    _snapshot(source, candidate)
    _stand_in_build(candidate, "run-0001", rows=10, validated=True)
    return publish(root, candidate, expected_previous=None, expected_run_id="run-0001")


# ---------------------------------------------------------- child processes
READER = """
import duckdb, json, sys, time
from pathlib import Path
sys.path.insert(0, {tests!r}); sys.path.insert(0, {src!r})
from test_publication_proof import resolve
root = Path({root!r}); signal = Path({signal!r}) if {signal!r} else None
path, manifest = resolve(root)               # ONE resolve per render
def read():
    con = duckdb.connect(str(path), read_only=True)   # fresh connection, as the app does
    try:
        n = con.execute("select count(*) from scenario_build.fact").fetchone()[0]
        rid = con.execute("select run_id from proof_build_record").fetchone()[0]
    finally:
        con.close()
    return {{"file": path.name, "rows": n, "run_id": rid, "manifest_version": manifest["version"]}}
first = read()
if signal is not None:
    signal.touch()                             # tell the test we have read once
    deadline = time.time() + 20
    while not (signal.with_suffix(".go")).exists() and time.time() < deadline:
        time.sleep(0.05)
second = read()
print(json.dumps({{"first": first, "second": second}}))
"""

SLOW_BUILDER = """
import duckdb, os, sys, time
sys.path.insert(0, {tests!r}); sys.path.insert(0, {src!r})
from test_publication_proof import _snapshot, _stand_in_build
from pathlib import Path
cand = Path({candidate!r})
_snapshot(Path({source!r}), cand)
con = duckdb.connect(str(cand))
con.execute("CREATE SCHEMA IF NOT EXISTS scenario_build")
con.execute("CREATE TABLE scenario_build.fact AS SELECT range AS i, 'run-0002' AS run_id FROM range(5)")
Path({started!r}).touch()                     # the reader may now try to read v1
time.sleep({hold})                            # hold the WRITE lock on the candidate file
if {crash}:
    con.execute("INSERT INTO scenario_build.fact SELECT range, 'run-0002' FROM range(5, 100)")
    os._exit(1)                               # die mid-build: no close, no checkpoint
con.close()
_stand_in_build(cand, "run-0002", rows=20, validated=True)
"""

PROMOTER = """
import sys, json
sys.path.insert(0, {tests!r}); sys.path.insert(0, {src!r})
from pathlib import Path
from test_publication_proof import publish, StalePromotion, PromotionRefused
import time
root = Path({root!r})
while not Path({go!r}).exists(): time.sleep(0.01)  # start together
try:
    m = publish(root, root / "versions" / {candidate!r}, expected_previous={expected!r},
                expected_run_id={run_id!r}, crash_before_rename={crash})
    print(json.dumps({{"won": True, "version": m["version"]}}))
except (StalePromotion, PromotionRefused) as e:
    print(json.dumps({{"won": False, "why": type(e).__name__}}))
"""


def _child(script: str, **kw) -> subprocess.Popen:
    code = script.format(tests=str(REPO / "tests"), src=str(REPO / "src"), **kw)
    return subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _finish(proc: subprocess.Popen, timeout: float = 60):
    out, err = proc.communicate(timeout=timeout)
    return proc.returncode, out, err


# ============================================================ scenarios
def test_the_proof_runs_on_the_real_filesystem_not_tmpfs(root):
    _assert_real_filesystem(root)
    assert (
        subprocess.run(
            ["stat", "-f", "-c", "%T", "/tmp"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        == "tmpfs"
    ), "if /tmp stops being tmpfs, this note in the design is stale"


def test_no_published_version_is_an_explicit_unavailable_state(root):
    with pytest.raises(Unavailable):
        resolve(root)


def test_a_reader_reads_the_published_version_while_a_candidate_builds(root):
    """Different files, so the builder's write lock never touches the reader."""
    source = _source_warehouse(root)
    _publish_v1(root, source)
    started = root / "started"
    builder = _child(
        SLOW_BUILDER,
        candidate=str(root / VERSIONS / "cand-0002.duckdb"),
        source=str(source),
        started=str(started),
        hold=2.0,
        crash=False,
    )
    deadline = time.time() + 20
    while not started.exists() and time.time() < deadline:
        time.sleep(0.05)
    assert started.exists(), _finish(builder)
    reader = _child(READER, root=str(root), signal="")
    code, out, err = _finish(reader)
    assert code == 0, err
    seen = json.loads(out)["first"]
    assert seen == {
        "file": "cand-0001.duckdb",
        "rows": 10,
        "run_id": "run-0001",
        "manifest_version": "v0001",
    }
    code, _, err = _finish(builder)
    assert code == 0, err
    assert not (root / VERSIONS / "cand-0002.duckdb.wal").exists(), (
        "clean close checkpoints"
    )


def test_failure_midway_leaves_the_published_version_readable_and_unreferenced(root):
    source = _source_warehouse(root)
    before = _publish_v1(root, source)
    candidate = root / VERSIONS / "cand-0002.duckdb"
    builder = _child(
        SLOW_BUILDER,
        candidate=str(candidate),
        source=str(source),
        started=str(root / "started"),
        hold=0.2,
        crash=True,
    )
    code, _, _ = _finish(builder)
    assert code == 1
    # published: unchanged and readable
    assert read_manifest(root) == before
    path, _ = resolve(root)
    con = duckdb.connect(str(path), read_only=True)
    assert con.execute("select count(*) from scenario_build.fact").fetchone()[0] == 10
    con.close()
    # candidate: exists, partial, carries a WAL, and cannot be promoted
    assert candidate.exists()
    assert candidate.with_name(candidate.name + ".wal").exists()
    with pytest.raises(PromotionRefused, match="wal"):
        publish(root, candidate, expected_previous="v0001", expected_run_id="run-0002")
    assert read_manifest(root) == before


def test_promotion_uses_the_exact_validated_candidate(root):
    """A record that is not 'validated', or a different run_id, is refused."""
    source = _source_warehouse(root)
    _publish_v1(root, source)
    failed = root / VERSIONS / "cand-failed.duckdb"
    _snapshot(source, failed)
    _stand_in_build(failed, "run-x", rows=3, validated=False)
    with pytest.raises(PromotionRefused, match="validated"):
        publish(root, failed, expected_previous="v0001", expected_run_id="run-x")
    good = root / VERSIONS / "cand-0002.duckdb"
    _snapshot(source, good)
    _stand_in_build(good, "run-0002", rows=20, validated=True)
    with pytest.raises(PromotionRefused, match="run_id"):
        publish(root, good, expected_previous="v0001", expected_run_id="run-0009")
    manifest = publish(
        root, good, expected_previous="v0001", expected_run_id="run-0002"
    )
    assert manifest["sha256"] == _sha256(good), "the exact file, by digest"


def test_a_real_dbt_build_on_a_snapshot_then_promotion(root):
    """The bridge to the real wrapper: run-dbt builds into a snapshot file; then publish."""
    source = _source_warehouse(root)
    _publish_v1(root, source)
    candidate = root / VERSIONS / "cand-dbt.duckdb"
    _snapshot(source, candidate)
    code = dbt_run.main(
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
    assert code == 0
    con = duckdb.connect(str(candidate), read_only=True)
    run_id, group = con.execute(
        f"SELECT run_id, tariff_group FROM {dbt_run.BUILD_RUN_TABLE}"
    ).fetchone()
    charged = con.execute(
        "SELECT COUNT(*) FROM scenario_build.fact_interval_charge_scenario"
    ).fetchone()[0]
    con.close()
    assert run_id.startswith(dbt_run.CANDIDATE_PREFIX) and group == "ToU"
    assert charged == 48, "48 ToU half-hours inside the one-day demo schedule"
    # stand-in validation record, since the production publisher does not exist yet
    _stand_in_build(candidate, run_id, rows=charged, validated=True)
    manifest = publish(
        root, candidate, expected_previous="v0001", expected_run_id=run_id
    )
    assert manifest["run_id"] == run_id


def test_a_reader_spanning_a_promotion_sees_one_version_and_its_metadata(root):
    source = _source_warehouse(root)
    _publish_v1(root, source)
    good = root / VERSIONS / "cand-0002.duckdb"
    _snapshot(source, good)
    _stand_in_build(good, "run-0002", rows=20, validated=True)
    signal = root / "read-once"
    reader = _child(READER, root=str(root), signal=str(signal))
    deadline = time.time() + 20
    while not signal.exists() and time.time() < deadline:
        time.sleep(0.05)
    assert signal.exists(), _finish(reader)
    publish(
        root, good, expected_previous="v0001", expected_run_id="run-0002"
    )  # mid-render
    signal.with_suffix(".go").touch()
    code, out, err = _finish(reader)
    assert code == 0, err
    seen = json.loads(out)
    assert seen["first"] == seen["second"], (
        "both reads from the version resolved at start"
    )
    assert (
        seen["first"]["run_id"] == "run-0001"
        and seen["first"]["manifest_version"] == "v0001"
    )
    # and a new render sees the promotion
    assert resolve(root)[1]["version"] == "v0002"


def test_interruption_between_durability_and_visibility_is_recoverable(root):
    source = _source_warehouse(root)
    before = _publish_v1(root, source)
    good = root / VERSIONS / "cand-0002.duckdb"
    _snapshot(source, good)
    _stand_in_build(good, "run-0002", rows=20, validated=True)
    go = root / "go"
    promoter = _child(
        PROMOTER,
        root=str(root),
        go=str(go),
        candidate="cand-0002.duckdb",
        expected="v0001",
        run_id="run-0002",
        crash=True,
    )
    go.touch()
    code, _, _ = _finish(promoter)
    assert code == 3
    # the old version is still published; the tmp and the dead lock are left behind
    assert read_manifest(root) == before
    assert (root / MANIFEST_TMP).exists()
    assert (root / PROMOTE_LOCK).exists()
    with pytest.raises(StalePromotion, match="lock"):
        publish(root, good, expected_previous="v0001", expected_run_id="run-0002")
    actions = recover(root)
    assert len(actions) == 2
    assert read_manifest(root) == before, "recovery never edits the manifest"
    assert (
        publish(root, good, expected_previous="v0001", expected_run_id="run-0002")[
            "version"
        ]
        == "v0002"
    )


def test_competing_promotions_exactly_one_wins(root):
    source = _source_warehouse(root)
    _publish_v1(root, source)
    for n in ("0002", "0003"):
        cand = root / VERSIONS / f"cand-{n}.duckdb"
        _snapshot(source, cand)
        _stand_in_build(cand, f"run-{n}", rows=20, validated=True)
    go = root / "go"
    racers = [
        _child(
            PROMOTER,
            root=str(root),
            go=str(go),
            candidate=f"cand-{n}.duckdb",
            expected="v0001",
            run_id=f"run-{n}",
            crash=False,
        )
        for n in ("0002", "0003")
    ]
    time.sleep(0.3)
    go.touch()
    outcomes = [json.loads(_finish(r)[1]) for r in racers]
    assert sorted(o["won"] for o in outcomes) == [False, True], outcomes
    loser = next(o for o in outcomes if not o["won"])
    assert loser["why"] == "StalePromotion"
    assert read_manifest(root)["version"] == "v0002"


def test_a_stale_promotion_request_is_refused(root):
    """Formed against v0001, submitted after v0002 was published: refused, not applied."""
    source = _source_warehouse(root)
    _publish_v1(root, source)
    for n in ("0002", "0003"):
        cand = root / VERSIONS / f"cand-{n}.duckdb"
        _snapshot(source, cand)
        _stand_in_build(cand, f"run-{n}", rows=20, validated=True)
    publish(
        root,
        root / VERSIONS / "cand-0002.duckdb",
        expected_previous="v0001",
        expected_run_id="run-0002",
    )
    with pytest.raises(StalePromotion):
        publish(
            root,
            root / VERSIONS / "cand-0003.duckdb",
            expected_previous="v0001",
            expected_run_id="run-0003",
        )
    assert read_manifest(root)["file"] == "cand-0002.duckdb"


def test_rollback_to_a_retained_version_is_a_manifest_change(root):
    source = _source_warehouse(root)
    _publish_v1(root, source)
    good = root / VERSIONS / "cand-0002.duckdb"
    _snapshot(source, good)
    _stand_in_build(good, "run-0002", rows=20, validated=True)
    publish(root, good, expected_previous="v0001", expected_run_id="run-0002")
    started = time.time()
    manifest = rollback(root, "cand-0001.duckdb", expected_previous="v0002")
    assert time.time() - started < 5
    assert manifest["file"] == "cand-0001.duckdb" and manifest["version"] == "v0003"
    path, _ = resolve(root)
    con = duckdb.connect(str(path), read_only=True)
    assert (
        con.execute("select run_id from proof_build_record").fetchone()[0] == "run-0001"
    )
    con.close()


def test_retention_spares_recent_and_protected_versions_and_open_readers_survive(root):
    source = _source_warehouse(root)
    _publish_v1(root, source)
    for n in ("0002", "0003"):
        cand = root / VERSIONS / f"cand-{n}.duckdb"
        _snapshot(source, cand)
        _stand_in_build(cand, f"run-{n}", rows=20, validated=True)
        publish(
            root,
            cand,
            expected_previous=f"v{int(n) - 1:04d}",
            expected_run_id=f"run-{n}",
        )
    # a reader holding v1 open, exactly as a mid-render connection would
    held = duckdb.connect(str(root / VERSIONS / "cand-0001.duckdb"), read_only=True)
    assert sweep(root, keep=1, grace_seconds=3600) == [], (
        "inside the grace window: nothing"
    )
    removed = sweep(root, keep=1, grace_seconds=0)
    assert removed == ["cand-0001.duckdb"], "published and previous are protected"
    assert (
        held.execute("select count(*) from scenario_build.fact").fetchone()[0] == 10
    ), "an open connection survives unlink (POSIX); a new open would not"
    held.close()
    with pytest.raises(duckdb.Error):
        duckdb.connect(str(root / VERSIONS / "cand-0001.duckdb"), read_only=True)
