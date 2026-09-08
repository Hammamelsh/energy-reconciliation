"""Publication: immutable versioned warehouse files and an atomically replaced manifest.

The decision this implements is design D5 in ``docs/anl-003-dbt-design.md``, proved first
on disposable fixtures. The short form:

- A **version** is a whole-warehouse DuckDB file under ``<root>/versions/``. It is written
  once (snapshot + dbt build), **sealed** by :func:`finalise`, and never opened read-write
  again. Readers hold it read-only; a builder writes a *different* file. That is what
  keeps a build from ever locking the file a reader holds -- DuckDB locks the file, not
  the schema, so no arrangement inside one file could have given this.
- **Published** means one thing only: ``<root>/published.json`` names the file. The
  manifest is replaced by ``rename``, which is atomic on a POSIX filesystem, so a reader
  sees the old manifest or the new one and never a torn one.
- A reader calls :func:`resolve` **once per render** and threads the path it gets through
  every query. It does not consult the manifest again mid-render, so a promotion during a
  render is invisible to it and the next render sees the new version whole.

Two properties that are easy to conflate, kept apart on purpose:

- **Atomic visibility** comes from the rename. Tested, with separate processes.
- **Power-loss durability** comes from ``fsync`` of the temporary manifest and of the
  directory. Called, not tested -- nothing here pulls the power.

Filesystem assumptions, stated rather than implied: this relies on POSIX ``rename`` being
atomic within one filesystem and on ``O_EXCL`` being honoured. Both hold on the ext4
volume this repository lives on. ``/tmp`` on this machine is tmpfs, and NTFS, drvfs and
network shares were **not** tested. The lock's liveness check reads ``/proc``, so recovery
is Linux-specific and refuses to act where it cannot tell.

What this module does **not** do: build a candidate (that is ``run-dbt`` over a snapshot,
and the ``build-candidate`` command is a later slice), switch the dashboard (later slice),
or delete anything (retention is a documented policy and :func:`inventory` is a dry run;
automatic sweeping is deferred on purpose).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import duckdb

from .dbt_run import BUILD_RUN_TABLE, build_output_digest

#: Where publications live unless a caller says otherwise. Git-ignored under ``data/``.
DEFAULT_ROOT: Final[Path] = Path("data/published")

MANIFEST: Final[str] = "published.json"
MANIFEST_TMP: Final[str] = "published.json.tmp"
HISTORY: Final[str] = "history.jsonl"
PROMOTE_LOCK: Final[str] = "promote.lock"
VERSIONS: Final[str] = "versions"

#: Sidecar written by :func:`finalise` beside a candidate. Its presence, and the digest it
#: carries, is what "validated" means to :func:`publish`.
SEAL_SUFFIX: Final[str] = ".validated.json"

#: Test seam. A child process in the test suite sets this to ``os._exit`` to die between
#: writing the temporary manifest and renaming it -- the one boundary worth exercising
#: with a real process death. Never set in production code.
_BEFORE_RENAME: Callable[[], None] | None = None


class PublicationError(RuntimeError):
    """Base class; every refusal below is one of these."""


class Unavailable(PublicationError):
    """No published version. Deliberately an error, never an empty dataset."""


class StalePromotion(PublicationError):
    """The manifest no longer names the version the request expected to replace,
    or another promotion holds the lock."""


class PromotionRefused(PublicationError):
    """The candidate is not a sealed, validated file, or is not the one validated."""


class RecoveryRefused(PublicationError):
    """Recovery could not tell whether a lock is live, so it did nothing."""


# ------------------------------------------------------------------ helpers
def _utc_now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_dir(directory: Path) -> None:
    fd = os.open(str(directory), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _wal(path: Path) -> Path:
    return path.with_name(path.name + ".wal")


def _seal_path(candidate: Path) -> Path:
    return candidate.with_name(candidate.name + SEAL_SUFFIX)


def _process_start(pid: int) -> str | None:
    """The kernel's start time for ``pid``, or None when it cannot be read.

    A pid alone is not an identity: pids are reused. Recording the start time as well
    lets recovery distinguish "the promoter that took this lock is still running" from
    "a different process happens to have the same number".
    """
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    except (OSError, IndexError):
        return None
    return fields[19]  # field 22 overall; 20th after the command name


# ------------------------------------------------------------------ manifest
def read_manifest(root: Path = DEFAULT_ROOT) -> dict[str, Any] | None:
    path = root / MANIFEST
    return json.loads(path.read_text()) if path.is_file() else None


def resolve(root: Path = DEFAULT_ROOT) -> tuple[Path, dict[str, Any]]:
    """The published database and its manifest, from ONE read.

    Callers keep the returned path for the whole render. They do not call this again
    until the next render, and they do not re-read the manifest between queries.
    """
    manifest = read_manifest(root)
    if manifest is None:
        raise Unavailable(
            f"nothing is published under {root}. Build and promote a candidate first; "
            "this is an explicit absence, not an empty dataset."
        )
    path = root / VERSIONS / manifest["file"]
    if not path.is_file():
        raise Unavailable(
            f"{root / MANIFEST} names {manifest['file']} but that file is missing. The "
            "manifest was not changed; restore the file or roll back to a retained version."
        )
    return path, manifest


# ------------------------------------------------------------------ candidates
@dataclass(frozen=True, slots=True)
class Seal:
    """What :func:`finalise` attests about a candidate."""

    file: str
    sha256: str
    run_id: str
    built_at_utc: str
    dbt_core_version: str
    dbt_duckdb_version: str
    tariff_group: str
    schedule_variant: str
    built_output_sha256: str
    sealed_at_utc: str


def build_record(candidate: Path) -> dict[str, Any]:
    """The single successful ``run-dbt`` record inside a candidate, and proof it still
    describes the file, read-only.

    ``run-dbt`` records only successful builds, so a row's presence *is* the success. A
    candidate is one attempt: zero rows means it was never built or the build failed, and
    more than one means the file was reused, which the design forbids.

    **A record alone is not enough, and that was measured rather than assumed.** dbt fails
    per model, so a second attempt in the same file can replace some tables, skip others
    and leave the first attempt's record standing over contents it no longer describes --
    a duplicated schedule label does exactly that, and before this check `finalise`
    accepted the result. So the record carries a digest of the built tables, and it is
    recomputed here: the record must describe **this file, as it is now**.
    """
    if _wal(candidate).exists():
        raise PromotionRefused(
            f"{candidate.name} has a .wal sidecar: its writer did not close and "
            "checkpoint it, so part of its content may live only in the WAL. Refusing."
        )
    con = duckdb.connect(str(candidate), read_only=True)
    try:
        try:
            rows = con.execute(
                "SELECT run_id, CAST(built_at_utc AS VARCHAR), dbt_core_version, "
                "dbt_duckdb_version, tariff_group, schedule_variant, "
                f"built_output_sha256 FROM {BUILD_RUN_TABLE}"
            ).fetchall()
        except duckdb.Error as error:
            raise PromotionRefused(
                f"{candidate.name}: no successful build record ({BUILD_RUN_TABLE} "
                f"is absent). Either run-dbt was never run on it or the build failed. "
                f"Underlying: {error}"
            ) from error
    finally:
        con.close()
    if len(rows) != 1:
        raise PromotionRefused(
            f"{candidate.name}: {len(rows)} build records; a candidate is one attempt "
            "and must carry exactly one. A snapshot of a warehouse that was itself built "
            "inherits its history, which is why a candidate starts with the build schema "
            "cleared."
        )
    keys = (
        "run_id",
        "built_at_utc",
        "dbt_core_version",
        "dbt_duckdb_version",
        "tariff_group",
        "schedule_variant",
        "built_output_sha256",
    )
    record = dict(zip(keys, rows[0], strict=True))
    con = duckdb.connect(str(candidate), read_only=True)
    try:
        current = build_output_digest(con)
    finally:
        con.close()
    if record["built_output_sha256"] != current:
        raise PromotionRefused(
            f"{candidate.name}: the built tables digest {current[:12]}… but the build "
            f"record describes {str(record['built_output_sha256'])[:12]}…. Something "
            "changed them after that build -- most likely a later attempt that failed "
            "part way. This candidate cannot be sealed; build a fresh one."
        )
    return record


def finalise(candidate: Path) -> Seal:
    """Seal a built candidate: validate it, record its digest, make it read-only.

    This is the boundary between *writable during construction* and *immutable after*.
    The digest is taken over the closed file; the sidecar records it beside the run_id
    that produced the file; the file's mode drops the write bits, so a read-write open
    fails from here on. Sealing an already sealed file with unchanged bytes is a no-op.
    """
    if not candidate.is_file():
        raise PromotionRefused(f"{candidate} does not exist")
    record = build_record(candidate)
    digest = _sha256(candidate)
    seal_path = _seal_path(candidate)
    if seal_path.exists():
        existing = json.loads(seal_path.read_text())
        if existing.get("sha256") != digest:
            raise PromotionRefused(
                f"{candidate.name} was sealed with digest {existing.get('sha256', '')[:12]}… "
                f"but now has {digest[:12]}…: the file changed after sealing."
            )
        return Seal(**existing)
    seal = Seal(
        file=candidate.name,
        sha256=digest,
        sealed_at_utc=_utc_now(),
        **record,
    )
    with seal_path.open("w") as handle:
        json.dump(asdict(seal), handle, indent=1)
        handle.flush()
        os.fsync(handle.fileno())
    candidate.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    _fsync_dir(candidate.parent)
    return seal


def read_seal(candidate: Path) -> Seal:
    seal_path = _seal_path(candidate)
    if not seal_path.is_file():
        raise PromotionRefused(
            f"{candidate.name} is not sealed. Run finalise on it after a successful build."
        )
    return Seal(**json.loads(seal_path.read_text()))


# ------------------------------------------------------------------ promotion
def _acquire_lock(root: Path) -> Path:
    lock = root / PROMOTE_LOCK
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise StalePromotion(
            f"another promotion holds {lock}. If its process is dead, run recover."
        ) from error
    try:
        pid = os.getpid()
        os.write(
            fd,
            json.dumps(
                {"pid": pid, "started": _process_start(pid), "at": _utc_now()}
            ).encode(),
        )
    finally:
        os.close(fd)
    return lock


def publish(
    candidate: Path,
    *,
    expected_previous: str | None,
    root: Path = DEFAULT_ROOT,
) -> dict[str, Any]:
    """Make a sealed candidate the published version, if nothing moved underneath.

    Every step refuses rather than proceeds on doubt, and a refusal at any step leaves
    the manifest exactly as it was:

    1. ``O_EXCL`` lock — two promoters cannot both be inside this function.
    2. Compare-and-swap — the manifest must still name ``expected_previous``. A request
       formed against an older state is refused as stale rather than winning.
    3. Gate — the candidate must be sealed and its bytes must still match the seal's
       digest. Promotion uses the exact file that was validated, not whatever is at that
       path now.
    4. Write the temporary manifest, ``fsync`` it, ``rename`` it over the manifest,
       ``fsync`` the directory. The rename is the atomic visibility boundary.
    5. Append to ``history.jsonl`` — after the boundary, best effort, not part of it.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / VERSIONS).mkdir(exist_ok=True)
    lock = _acquire_lock(root)
    try:
        current = read_manifest(root)
        current_version = current["version"] if current else None
        if current_version != expected_previous:
            raise StalePromotion(
                f"the manifest names {current_version!r} but this request expected "
                f"{expected_previous!r}. Something was promoted since the request was "
                "formed; re-inspect and decide again."
            )
        if candidate.parent.resolve() != (root / VERSIONS).resolve():
            raise PromotionRefused(
                f"{candidate} is not under {root / VERSIONS}; only versions there are "
                "publishable."
            )
        seal = read_seal(candidate)
        digest = _sha256(candidate)
        if digest != seal.sha256:
            raise PromotionRefused(
                f"{candidate.name}: bytes {digest[:12]}… differ from the sealed "
                f"{seal.sha256[:12]}…. The file changed after validation; refusing."
            )
        if _wal(candidate).exists():
            raise PromotionRefused(f"{candidate.name} has a .wal sidecar; refusing.")

        sequence = (current["sequence"] + 1) if current else 1
        manifest = {
            "version": f"v{sequence:04d}",
            "sequence": sequence,
            "file": candidate.name,
            "sha256": seal.sha256,
            "run_id": seal.run_id,
            "built_at_utc": seal.built_at_utc,
            "dbt_core_version": seal.dbt_core_version,
            "dbt_duckdb_version": seal.dbt_duckdb_version,
            "tariff_group": seal.tariff_group,
            "schedule_variant": seal.schedule_variant,
            "previous": current_version,
            "previous_file": current["file"] if current else None,
            "promoted_at_utc": _utc_now(),
        }
        tmp = root / MANIFEST_TMP
        with tmp.open("w") as handle:
            json.dump(manifest, handle, indent=1)
            handle.flush()
            os.fsync(handle.fileno())
        if (
            _BEFORE_RENAME is not None
        ):  # test seam: die between durability and visibility
            _BEFORE_RENAME()
        os.replace(tmp, root / MANIFEST)
        _fsync_dir(root)
        with (root / HISTORY).open("a") as handle:
            handle.write(json.dumps(manifest) + "\n")
        return manifest
    finally:
        lock.unlink(missing_ok=True)


def rollback(
    to_file: str, *, expected_previous: str, root: Path = DEFAULT_ROOT
) -> dict[str, Any]:
    """Point the manifest at a retained version. Seconds, no rebuild.

    Goes through :func:`publish`, so it carries the same lock, compare-and-swap and
    digest check: a retained file that has been altered is refused like any other.
    """
    return publish(
        root / VERSIONS / to_file, expected_previous=expected_previous, root=root
    )


# ------------------------------------------------------------------ recovery
def recover(root: Path = DEFAULT_ROOT) -> list[str]:
    """After an interruption: remove an orphan temporary manifest and a dead lock.

    Narrow on purpose. It never edits ``published.json`` — either the rename happened or
    it did not, and there is no third state to repair. It never touches a candidate or a
    version: a partial build is evidence, and its owner may still be running. And it
    removes a lock only when it can show the process that took it is gone; when it
    cannot tell, it raises rather than guesses.
    """
    actions: list[str] = []
    tmp = root / MANIFEST_TMP
    if tmp.exists():
        tmp.unlink()
        actions.append(f"removed orphan {MANIFEST_TMP}")
    lock = root / PROMOTE_LOCK
    if lock.exists():
        try:
            owner = json.loads(lock.read_text() or "{}")
        except json.JSONDecodeError:
            owner = {}
        pid = owner.get("pid")
        if not isinstance(pid, int):
            raise RecoveryRefused(
                f"{lock} does not name its owner; not removing it. Inspect it by hand."
            )
        if not Path("/proc").is_dir():
            raise RecoveryRefused(
                f"cannot tell whether pid {pid} is alive on this platform; not removing "
                f"{lock}."
            )
        live_start = _process_start(pid)
        if live_start is not None and live_start == owner.get("started"):
            raise RecoveryRefused(
                f"{lock} belongs to pid {pid}, which is still running. Not removed."
            )
        lock.unlink()
        actions.append(f"removed lock left by dead pid {pid}")
    return actions


# ------------------------------------------------------------------ inventory
@dataclass(frozen=True, slots=True)
class VersionFile:
    file: str
    role: (
        str  # published | previous | retained | sealed-unpublished | unsealed | broken
    )
    bytes: int
    sealed: bool
    has_wal: bool
    run_id: str | None
    writable: bool


def inventory(root: Path = DEFAULT_ROOT) -> list[VersionFile]:
    """Every version file and what it is. Read-only: a dry run for retention.

    Retention policy, documented rather than automated in this slice: keep the newest N
    versions; never delete the published or the immediately previous one; never delete
    anything younger than a grace window, because a render opens a fresh connection per
    query to the path it resolved at its start. Deleting is deferred until that policy
    has a command of its own with a dry run and an explicit confirmation.
    """
    manifest = read_manifest(root)
    published = manifest["file"] if manifest else None
    previous = manifest.get("previous_file") if manifest else None
    history_files: set[str] = set()
    history = root / HISTORY
    if history.is_file():
        for line in history.read_text().splitlines():
            if line.strip():
                history_files.add(json.loads(line)["file"])
    out: list[VersionFile] = []
    versions = root / VERSIONS
    if not versions.is_dir():
        return out
    for path in sorted(versions.glob("*.duckdb")):
        sealed = _seal_path(path).is_file()
        run_id = None
        if sealed:
            try:
                run_id = read_seal(path).run_id
            except (PromotionRefused, TypeError, KeyError, json.JSONDecodeError):
                run_id = None
        if path.name == published:
            role = "published"
        elif path.name == previous:
            role = "previous"
        elif path.name in history_files:
            role = "retained"
        elif sealed:
            role = "sealed-unpublished"
        elif _wal(path).exists():
            role = "broken"
        else:
            role = "unsealed"
        out.append(
            VersionFile(
                file=path.name,
                role=role,
                bytes=path.stat().st_size,
                sealed=sealed,
                has_wal=_wal(path).exists(),
                run_id=run_id,
                writable=bool(path.stat().st_mode & stat.S_IWUSR),
            )
        )
    return out


# ------------------------------------------------------------------ CLI
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="publication",
        description=(
            "Inspect, seal, promote and roll back published warehouse versions. "
            "Nothing here builds a candidate or deletes a file."
        ),
    )
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="what is published, from one manifest read")
    sub.add_parser("inventory", help="every version file and its role (read-only)")
    seal = sub.add_parser("finalise", help="validate and seal a built candidate")
    seal.add_argument("candidate", type=Path)
    promote = sub.add_parser("promote", help="publish a sealed candidate")
    promote.add_argument("candidate", type=Path)
    promote.add_argument(
        "--expect-published",
        required=True,
        help="the version you saw in status; 'none' when nothing is published yet",
    )
    back = sub.add_parser("rollback", help="publish a retained version again")
    back.add_argument("file", help="a file name under versions/")
    back.add_argument("--expect-published", required=True)
    sub.add_parser(
        "recover",
        help="remove an orphan temporary manifest and a dead lock; never edits the manifest",
    )
    args = parser.parse_args(argv)
    root: Path = args.root

    try:
        if args.command == "status":
            try:
                path, manifest = resolve(root)
            except Unavailable as error:
                print(f"UNAVAILABLE: {error}")
                return 1
            print(
                f"published {manifest['version']} -> {path.name} · run {manifest['run_id']} "
                f"· dbt-core {manifest['dbt_core_version']} · previous "
                f"{manifest['previous'] or 'none'} · promoted {manifest['promoted_at_utc']}"
            )
            return 0
        if args.command == "inventory":
            rows = inventory(root)
            if not rows:
                print(f"no version files under {root / VERSIONS}")
                return 0
            for r in rows:
                print(
                    f"{r.role:18s} {r.file:40s} {r.bytes:>12,} B  sealed={r.sealed!s:5s} "
                    f"writable={r.writable!s:5s} wal={r.has_wal!s:5s} run={r.run_id or '-'}"
                )
            print(
                "\nretention is not automated: nothing above will be deleted by this tool."
            )
            return 0
        if args.command == "finalise":
            seal = finalise(args.candidate)
            print(
                f"sealed {seal.file} · run {seal.run_id} · sha256 {seal.sha256[:16]}…"
            )
            return 0
        if args.command == "promote":
            expected = (
                None if args.expect_published == "none" else args.expect_published
            )
            manifest = publish(args.candidate, expected_previous=expected, root=root)
            print(
                f"published {manifest['version']} -> {manifest['file']} "
                f"(previous {manifest['previous'] or 'none'})"
            )
            return 0
        if args.command == "rollback":
            manifest = rollback(
                args.file, expected_previous=args.expect_published, root=root
            )
            print(
                f"published {manifest['version']} -> {manifest['file']} "
                f"(rolled back from {manifest['previous']})"
            )
            return 0
        if args.command == "recover":
            actions = recover(root)
            print("\n".join(actions) if actions else "nothing to recover")
            return 0
    except PublicationError as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 2
    return 2  # pragma: no cover - argparse enforces the choices


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
