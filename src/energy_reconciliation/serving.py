"""A serving snapshot: a published version carried to another machine, still verifiable.

The problem
-----------

A sealed version is bound to the place it was built: its attempt record names the
absolute path the build wrote, and :func:`publication.build_record` refuses a file whose
path differs, because a snapshot of a built warehouse inherits a history that does not
authorise the copy. That protection is right for candidates. It also means a published
file cannot simply be copied to a hosting machine and read as *published*.

The contract (``serving-snapshot-1``)
-------------------------------------

An **export** is made only from a publication that validates in place -- manifest, seal,
attempt record and path binding all agreeing. It copies the version file and its seal
byte for byte and writes ``serving.json``, which pins the whole-file sha256, size, run id,
version, and the **build origin path** exactly as the record names it. That path is
provenance: it says where the file was built, and is deliberately distinct from where it
is served.

A **serving read** (:func:`tariff.reads.serving`) verifies the file's bytes against the
pinned sha256 *and* against the seal, and then applies every attempt-record gate with one
substitution: the record must name the origin the manifest declares, not the current
location. An unrelated copied candidate still fails, because its record names some other
path than the one this manifest was exported from. The built-tables digest is **not**
recomputed on a serving read: the whole-file hash certifies every byte, including those
tables, and the digest was checked at origin when the file was sealed and again when it
was exported. Recomputing it needs ~900 MB for three million rows (measured), which is the
difference between fitting on a small host and not.

Delivery
--------

The committed pin (``serving/snapshot.json``) is the exported manifest plus download
URLs. :func:`fetch` downloads the file and seal to a ``.part`` name, verifies size and
sha256, and renames atomically; a partial or mismatched download leaves no usable file.
Nothing here builds anything: a page request can only read.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import duckdb

from . import publication

DEFINITION: Final[str] = "serving-snapshot-1"
MANIFEST_NAME: Final[str] = "serving.json"
#: The committed pin a deployment reads: the exported manifest plus download URLs.
DEFAULT_PIN: Final[Path] = Path("serving/snapshot.json")
#: Where a deployment keeps the fetched snapshot. Git-ignored.
DEFAULT_DIRECTORY: Final[Path] = Path("data/serving")
#: Environment variable the dashboard reads to find a serving snapshot directory.
SERVING_ENV: Final[str] = "ENERGY_RECONCILIATION_SERVING_SNAPSHOT"
#: Set by the entrypoint when a fetch failed, so the page can say why.
SERVING_ERROR_ENV: Final[str] = "ENERGY_RECONCILIATION_SERVING_ERROR"


class ServingError(RuntimeError):
    """The snapshot cannot be exported, fetched or trusted. Never a fallback."""


def _origin_path(version_file: Path) -> str:
    """The absolute path the latest attempt record names: where this file was built."""
    con = duckdb.connect(str(version_file), read_only=True)
    try:
        row = con.execute(
            f"SELECT database_path FROM {publication.BUILD_RUN_TABLE} "
            "ORDER BY started_at_utc DESC, run_id DESC LIMIT 1"
        ).fetchone()
    finally:
        con.close()
    if row is None:  # pragma: no cover - a validated context always has one
        raise ServingError(
            f"{version_file.name}: no attempt record to take an origin from"
        )
    return str(row[0])


def _copy_atomically(source: Path, target: Path) -> None:
    part = target.with_name(target.name + ".part")
    shutil.copyfile(source, part)
    os.replace(part, target)


def export(root: Path, into: Path) -> dict[str, Any]:
    """Validate the publication in place, then copy it with a pinned manifest."""
    from .tariff import reads  # function-local: reads imports publication

    context = reads.published(root)
    seal = publication.read_seal(context.database)
    origin = _origin_path(context.database)
    into.mkdir(parents=True, exist_ok=True)
    target = into / context.database.name
    seal_target = into / (context.database.name + publication.SEAL_SUFFIX)
    _copy_atomically(context.database, target)
    _copy_atomically(publication._seal_path(context.database), seal_target)
    copied = publication._sha256(target)
    if copied != seal.sha256:
        target.unlink(missing_ok=True)
        raise ServingError(
            f"the copy digests {copied[:12]}…, not the sealed {seal.sha256[:12]}…; "
            "nothing exported"
        )
    manifest = {
        "definition": DEFINITION,
        "file": target.name,
        "seal_file": seal_target.name,
        "sha256": seal.sha256,
        "size_bytes": target.stat().st_size,
        "run_id": context.run_id,
        "version": context.version,
        "promoted_at_utc": context.promoted_at_utc,
        "built_output_sha256": seal.built_output_sha256,
        "output_digest_version": seal.output_digest_version,
        "required_build": seal.required_build,
        "required_nodes_total": seal.required_nodes_total,
        "schedule_variant": seal.schedule_variant,
        "schedule_source": seal.schedule_source,
        "tariff_group": seal.tariff_group,
        "build_origin_path": origin,
        "exported_at_utc": datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" "),
        "download": None,
    }
    (into / MANIFEST_NAME).write_text(json.dumps(manifest, indent=1))
    return manifest


def load_manifest(where: Path) -> dict[str, Any]:
    """The manifest in a directory, or a manifest file itself."""
    path = where / MANIFEST_NAME if where.is_dir() else where
    if not path.is_file():
        raise ServingError(f"no serving manifest at {path}")
    manifest = json.loads(path.read_text())
    if manifest.get("definition") != DEFINITION:
        raise ServingError(
            f"{path}: definition {manifest.get('definition')!r} is not {DEFINITION!r}"
        )
    return manifest


def pin(
    manifest_path: Path, file_url: str, seal_url: str, into: Path = DEFAULT_PIN
) -> None:
    """Record where the exported files can be downloaded, in the committed pin."""
    manifest = load_manifest(manifest_path)
    manifest["download"] = {"file_url": file_url, "seal_url": seal_url}
    into.parent.mkdir(parents=True, exist_ok=True)
    into.write_text(json.dumps(manifest, indent=1))


def _download(url: str, target: Path, *, expected_size: int | None) -> None:
    part = target.with_name(target.name + ".part")
    with urllib.request.urlopen(url, timeout=60) as response, part.open("wb") as out:
        shutil.copyfileobj(response, out, length=1 << 20)
    if expected_size is not None and part.stat().st_size != expected_size:
        size = part.stat().st_size
        part.unlink(missing_ok=True)
        raise ServingError(
            f"{target.name}: downloaded {size:,} bytes, expected {expected_size:,}; "
            "partial download discarded"
        )
    os.replace(part, target)


def fetch(pin_path: Path = DEFAULT_PIN, directory: Path = DEFAULT_DIRECTORY) -> Path:
    """Make ``directory`` hold the pinned snapshot, verified. Idempotent.

    A file already present with the pinned sha256 is kept; anything else is replaced. A
    mismatch after download removes the file, so a bad download can never be read.
    """
    manifest = load_manifest(pin_path)
    download = manifest.get("download") or {}
    if not download.get("file_url") or not download.get("seal_url"):
        raise ServingError(f"{pin_path}: no download URLs pinned")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / manifest["file"]
    if not (target.is_file() and publication._sha256(target) == manifest["sha256"]):
        _download(download["file_url"], target, expected_size=manifest["size_bytes"])
        digest = publication._sha256(target)
        if digest != manifest["sha256"]:
            target.unlink(missing_ok=True)
            raise ServingError(
                f"{target.name}: downloaded bytes digest {digest[:12]}…, pinned "
                f"{manifest['sha256'][:12]}…; file removed"
            )
    seal_target = directory / manifest["seal_file"]
    _download(download["seal_url"], seal_target, expected_size=None)
    try:
        seal = json.loads(seal_target.read_text())
    except ValueError as error:
        seal_target.unlink(missing_ok=True)
        raise ServingError(f"{seal_target.name}: not a seal ({error})") from error
    if seal.get("sha256") != manifest["sha256"]:
        seal_target.unlink(missing_ok=True)
        raise ServingError(
            f"{seal_target.name}: the downloaded seal certifies "
            f"{str(seal.get('sha256'))[:12]}…, not the pinned file"
        )
    (directory / MANIFEST_NAME).write_text(json.dumps(manifest, indent=1))
    return directory


def ensure_fetched(
    pin_path: Path = DEFAULT_PIN, directory: Path = DEFAULT_DIRECTORY
) -> Path:
    """Fetch once per process; a failure is recorded in the environment, not hidden."""
    try:
        return fetch(pin_path, directory)
    except (ServingError, OSError, ValueError) as error:
        os.environ[SERVING_ERROR_ENV] = f"{type(error).__name__}: {error}"
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="serving-snapshot",
        description=(
            "Export a validated published version as a relocatable serving snapshot, pin "
            "its download location, or fetch and verify a pinned snapshot."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    ex = sub.add_parser(
        "export", help="copy the published version and write serving.json"
    )
    ex.add_argument("--root", type=Path, default=publication.DEFAULT_ROOT)
    ex.add_argument("--into", type=Path, required=True)
    pn = sub.add_parser("pin", help="record download URLs in the committed pin")
    pn.add_argument("--manifest", type=Path, required=True)
    pn.add_argument("--file-url", required=True)
    pn.add_argument("--seal-url", required=True)
    pn.add_argument("--into", type=Path, default=DEFAULT_PIN)
    ft = sub.add_parser("fetch", help="download and verify the pinned snapshot")
    ft.add_argument("--pin", type=Path, default=DEFAULT_PIN)
    ft.add_argument("--directory", type=Path, default=DEFAULT_DIRECTORY)
    vf = sub.add_parser("verify", help="validate a snapshot directory as the app would")
    vf.add_argument("--directory", type=Path, default=DEFAULT_DIRECTORY)
    args = parser.parse_args(argv)
    try:
        if args.command == "export":
            manifest = export(args.root, args.into)
            print(
                f"exported {manifest['version']} ({manifest['file']}, "
                f"{manifest['size_bytes']:,} bytes, sha256 {manifest['sha256'][:12]}…) "
                f"into {args.into}; origin {manifest['build_origin_path']}"
            )
        elif args.command == "pin":
            pin(args.manifest, args.file_url, args.seal_url, args.into)
            print(f"pinned download URLs into {args.into}")
        elif args.command == "fetch":
            where = fetch(args.pin, args.directory)
            print(f"snapshot verified in {where}")
        else:
            from .tariff import reads

            context = reads.serving(args.directory)
            print(f"valid: {context.label}")
    except (ServingError, publication.PublicationError, OSError) as error:
        print(f"serving-snapshot: {error}", file=sys.stderr)
        return 1
    except Exception as error:  # reads raises its own error type
        if type(error).__name__ == "ReadContextError":
            print(f"serving-snapshot: {error}", file=sys.stderr)
            return 1
        raise
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
