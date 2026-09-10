"""The serving snapshot: a published version relocated and still verifiable.

One dbt build for the module (a build is slow), promoted into a publication root, then
exported. The cases are the contract in ``serving.py``: a valid relocation reads; a
tampered file, a wrong pin, a partial download and a missing file are refused, each by
name; an unrelated copied build is still refused because its record names another origin;
and the existing path binding for candidates is untouched.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import zipfile
from pathlib import Path

import duckdb
import pytest
from conftest import HEADER, row

from energy_reconciliation import candidate as cand
from energy_reconciliation import publication, serving
from energy_reconciliation.ingest.loader import load_member
from energy_reconciliation.tariff import reads

SCRATCH_ROOT = Path("data/proof-scratch")
MEMBER = "Small LCL Data/LCL-June2015v2_0.csv"


def _warehouse(work: Path, name: str, *, value: str = " 1 ") -> Path:
    archive = work / f"{name}.zip"
    body = HEADER + b"".join(
        row(
            "MAC000001",
            "ToU",
            f"2013-01-01 {i // 2:02d}:{(i % 2) * 30:02d}:00.0000000",
            value,
        )
        for i in range(48)
    )
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(MEMBER, body)
    database = work / f"{name}.duckdb"
    assert load_member(archive, MEMBER, database).complete
    return database


def _writable(area: Path) -> None:
    for file in area.rglob("*"):
        if file.is_file():
            file.chmod(stat.S_IRUSR | stat.S_IWUSR)


@pytest.fixture(scope="module")
def published(tmp_path_factory):
    """A promoted publication and its export. Shared: one dbt build."""
    SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
    area = Path(str(tmp_path_factory.mktemp("serving", numbered=True)))
    source = _warehouse(area, "source")
    root = area / "pub"
    built = cand.build_candidate(source, root=root, schedule="demo")
    publication.publish(built.candidate, expected_previous=None, root=root)
    exported = area / "export"
    manifest = serving.export(root, exported)
    yield {"area": area, "root": root, "export": exported, "manifest": manifest}
    _writable(area)
    shutil.rmtree(area, ignore_errors=True)


# ----------------------------------------------------------------- relocation
def test_an_export_reads_in_place_and_after_being_moved(published):
    context = reads.serving(published["export"])
    assert context.role == reads.SERVING
    assert context.run_id == published["manifest"]["run_id"]
    assert context.version == "v0001"
    assert "serving snapshot" in context.label

    moved = published["area"] / "elsewhere" / "deep"
    shutil.copytree(published["export"], moved)
    relocated = reads.serving(moved)
    assert relocated.run_id == context.run_id
    assert relocated.database == moved / published["manifest"]["file"]
    assert relocated.identity.file_sha256 == context.identity.file_sha256


def test_the_manifest_records_the_origin_as_provenance_not_location(published):
    manifest = published["manifest"]
    origin = Path(manifest["build_origin_path"])
    assert origin.parent == (published["root"] / publication.VERSIONS).resolve()
    assert origin != (published["export"] / manifest["file"]).resolve()
    assert manifest["definition"] == serving.DEFINITION
    assert manifest["required_build"] == "complete"
    assert manifest["download"] is None, "an export pins no URL until `pin`"


def test_the_candidate_path_binding_is_unchanged(published):
    """A relocated copy read as a *candidate* is still refused: only the serving
    reader, with the manifest's origin, may accept it."""
    copy = published["export"] / published["manifest"]["file"]
    with pytest.raises(
        publication.PromotionRefused, match="does not authorise the copy"
    ):
        publication.build_record(copy)
    with pytest.raises(reads.ReadContextError, match="does not authorise the copy"):
        reads.candidate(copy)


# ------------------------------------------------------------------ refusals
def _copy_export(published, name: str) -> Path:
    target = published["area"] / name
    shutil.copytree(published["export"], target)
    _writable(target)
    return target


def test_a_wrong_pinned_digest_is_refused(published):
    with pytest.raises(reads.ReadContextError, match="deployment expects"):
        reads.serving(published["export"], expected_sha256="0" * 64)


def test_a_changed_byte_is_refused_by_the_pin_and_the_seal(published):
    where = _copy_export(published, "tampered")
    path = where / published["manifest"]["file"]
    with path.open("r+b") as handle:
        handle.seek(-1, os.SEEK_END)
        last = handle.read(1)
        handle.seek(-1, os.SEEK_END)
        handle.write(bytes([last[0] ^ 0x01]))
    with pytest.raises(reads.ReadContextError, match="differ from the sealed"):
        reads.serving(where)


def test_a_partial_file_is_refused_by_size_before_anything_else(published):
    where = _copy_export(published, "partial")
    path = where / published["manifest"]["file"]
    data = path.read_bytes()
    path.write_bytes(data[: len(data) // 2])
    with pytest.raises(reads.ReadContextError, match="partial file is not a version"):
        reads.serving(where)


def test_a_missing_file_is_an_explicit_absence(published):
    where = _copy_export(published, "missing")
    (where / published["manifest"]["file"]).unlink()
    with pytest.raises(reads.ReadContextError, match="not fetched"):
        reads.serving(where)


def test_a_manifest_naming_another_origin_is_refused(published):
    """The serving reader binds the record to the origin the manifest declares. A
    manifest edited to some other origin no longer matches the record inside the file."""
    where = _copy_export(published, "other-origin")
    manifest = json.loads((where / serving.MANIFEST_NAME).read_text())
    manifest["build_origin_path"] = "/somewhere/else/cand.duckdb"
    (where / serving.MANIFEST_NAME).write_text(json.dumps(manifest))
    with pytest.raises(reads.ReadContextError, match="does not authorise the copy"):
        reads.serving(where)


def test_a_manifest_naming_another_run_is_refused(published):
    where = _copy_export(published, "other-run")
    manifest = json.loads((where / serving.MANIFEST_NAME).read_text())
    manifest["run_id"] = "dbtcand-000000000000@20200101T000000000000"
    (where / serving.MANIFEST_NAME).write_text(json.dumps(manifest))
    with pytest.raises(reads.ReadContextError, match="names run"):
        reads.serving(where)


def test_export_refuses_a_root_with_nothing_published(tmp_path):
    with pytest.raises(publication.Unavailable):
        serving.export(tmp_path / "empty-root", tmp_path / "out")


# --------------------------------------------------------------------- fetch
def _pin_for(published, into: Path, *, file_source: Path | None = None) -> Path:
    """A pin whose download URLs point at local files (``file://``)."""
    manifest = dict(published["manifest"])
    src = published["export"]
    manifest["download"] = {
        "file_url": (file_source or (src / manifest["file"])).resolve().as_uri(),
        "seal_url": (src / manifest["seal_file"]).resolve().as_uri(),
    }
    into.parent.mkdir(parents=True, exist_ok=True)
    into.write_text(json.dumps(manifest))
    return into


def test_fetch_verifies_and_is_idempotent(published, tmp_path):
    pin = _pin_for(published, tmp_path / "serving" / "snapshot.json")
    directory = tmp_path / "data" / "serving"
    assert serving.fetch(pin, directory) == directory
    context = reads.serving(directory)
    assert context.run_id == published["manifest"]["run_id"]
    before = (directory / published["manifest"]["file"]).stat().st_mtime_ns
    serving.fetch(pin, directory)  # present and verified: not downloaded again
    assert (directory / published["manifest"]["file"]).stat().st_mtime_ns == before


def test_a_truncated_download_leaves_no_file(published, tmp_path):
    src = published["export"] / published["manifest"]["file"]
    truncated = tmp_path / "truncated.duckdb"
    truncated.write_bytes(src.read_bytes()[:1000])
    pin = _pin_for(published, tmp_path / "pin.json", file_source=truncated)
    directory = tmp_path / "data" / "serving"
    with pytest.raises(serving.ServingError, match="partial download discarded"):
        serving.fetch(pin, directory)
    assert not (directory / published["manifest"]["file"]).exists()
    assert not list(directory.glob("*.part"))
    with pytest.raises(reads.ReadContextError):
        reads.serving(directory)


def test_a_download_with_the_wrong_bytes_is_removed(published, tmp_path):
    src = published["export"] / published["manifest"]["file"]
    wrong = tmp_path / "wrong.duckdb"
    data = bytearray(src.read_bytes())
    data[-1] ^= 0x01
    wrong.write_bytes(bytes(data))
    pin = _pin_for(published, tmp_path / "pin.json", file_source=wrong)
    directory = tmp_path / "data" / "serving"
    with pytest.raises(serving.ServingError, match="file removed"):
        serving.fetch(pin, directory)
    assert not (directory / published["manifest"]["file"]).exists()


def test_a_pin_without_urls_cannot_fetch(published, tmp_path):
    pin = tmp_path / "pin.json"
    pin.write_text(json.dumps(published["manifest"]))
    with pytest.raises(serving.ServingError, match="no download URLs"):
        serving.fetch(pin, tmp_path / "d")


# --------------------------------------------------------------- the dashboard
def test_the_selection_resolves_a_configured_snapshot(published, monkeypatch):
    from energy_reconciliation.explorer import selection as sel

    sel.clear_caches()
    monkeypatch.setenv(serving.SERVING_ENV, str(published["export"]))
    monkeypatch.delenv(serving.SERVING_ERROR_ENV, raising=False)
    chosen = sel.published()
    assert chosen.ready and chosen.context.role == reads.SERVING
    assert chosen.mode == sel.PUBLISHED_MODE

    monkeypatch.setenv(serving.SERVING_ERROR_ENV, "ServingError: simulated")
    sel.clear_caches()
    failed = sel.published()
    assert not failed.ready and "download failed" in failed.unavailable


def test_the_row_count_read_through_the_snapshot_is_the_builds(published):
    context = reads.serving(published["export"])
    con = duckdb.connect(str(context.database), read_only=True)
    try:
        charged = con.execute(
            f"SELECT COUNT(*) FROM {context.relations.fact_scenario} WHERE run_id = ?",
            [context.run_id],
        ).fetchone()[0]
    finally:
        con.close()
    assert charged == 48, "every reading is ToU on the demo day and charged"
