"""The dashboard reading a published version: one file, one identity, no quiet fallback.

Driven through Streamlit's own harness (``AppTest``), headless, against a **disposable**
publication root named by ``ENERGY_RECONCILIATION_PUBLICATION_ROOT``. Nothing here touches
``data/published``.

The fixture is built to expose the failure this integration exists to prevent: the source
warehouse's Python tariff scenario is deliberately doctored before the snapshot, so the
copied ``main`` tables inside the published file disagree with the dbt tables the seal
certifies. Any read that lands in ``main`` shows the marker and fails its test.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import zipfile
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import pytest
from conftest import HEADER, MEMBER, row

from energy_reconciliation import candidate as cand
from energy_reconciliation import publication as pub
from energy_reconciliation.explorer import selection as sel
from energy_reconciliation.ingest.loader import load_member
from energy_reconciliation.tariff import analytics as ta
from energy_reconciliation.tariff import schedule as sch
from energy_reconciliation.tariff.models import build_scenario

pytest.importorskip("dbt.cli.main", reason="dbt is not installed")
pytest.importorskip("streamlit.testing.v1", reason="Streamlit test harness unavailable")
from streamlit.testing.v1 import AppTest

APP = (
    Path(__file__).resolve().parent.parent / "src/energy_reconciliation/explorer/app.py"
)
SCRATCH_ROOT = Path(__file__).resolve().parent.parent / "data" / "proof-scratch"

#: Written into the copied Python fact before the snapshot. A charge no correct build can
#: produce, so a figure derived from it proves a read reached ``main``.
MARKER_CHARGE = Decimal("999.0000000000000000")


def _warehouse(directory: Path, name: str = "source.duckdb") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / (name + ".zip")
    body = HEADER + b"".join(
        [
            row(
                "MAC000001",
                "ToU",
                f"2013-01-01 {i // 2:02d}:{(i % 2) * 30:02d}:00.0000000",
                " 1 ",
            )
            for i in range(48)
        ]
        + [
            row(
                "MAC000002",
                "Std",
                f"2013-01-01 {i // 2:02d}:{(i % 2) * 30:02d}:00.0000000",
                " 2 ",
            )
            for i in range(9)
        ]
    )
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(MEMBER, body)
    database = directory / name
    assert load_member(archive, MEMBER, database).complete
    return database


@pytest.fixture(scope="module")
def published(tmp_path_factory):
    """A doctored source, a candidate built from it, promoted in a disposable root."""
    SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
    area = Path(str(tmp_path_factory.mktemp("publication-app")))
    source = _warehouse(area / "warehouse")
    python_run = build_scenario(source, sch.demo_schedule()).run_id

    import duckdb

    con = duckdb.connect(str(source))
    try:
        con.execute(
            "UPDATE main.fact_interval_charge_scenario SET energy_charge_gbp = ?",
            [MARKER_CHARGE],
        )
        con.execute("DELETE FROM main.fact_interval_charge_exclusion WHERE rowid < 3")
    finally:
        con.close()

    root = area / "published"
    built = cand.build_candidate(source, root=root, schedule="demo")
    manifest = pub.publish(built.candidate, expected_previous=None, root=root)
    yield {
        "area": area,
        "source": source,
        "root": root,
        "built": built,
        "manifest": manifest,
        "python_run": python_run,
    }
    for file in area.rglob("*"):
        if file.is_file():
            file.chmod(stat.S_IRUSR | stat.S_IWUSR)
    shutil.rmtree(area, ignore_errors=True)


@contextmanager
def _environment(root: Path, warehouse_dir: Path):
    """Publication root and working directory for the whole block, then restored.

    The app reads both at import time of each rerun, so a test that reruns must stay
    inside this block: restoring between runs is what made the second run see no
    publication at all.
    """
    previous_root = os.environ.get(sel.ROOT_ENV)
    previous_cwd = Path.cwd()
    os.environ[sel.ROOT_ENV] = str(root)
    os.chdir(warehouse_dir)
    try:
        yield
    finally:
        os.chdir(previous_cwd)
        if previous_root is None:
            os.environ.pop(sel.ROOT_ENV, None)
        else:
            os.environ[sel.ROOT_ENV] = previous_root


def _fresh(mode: str | None = None):
    at = AppTest.from_file(str(APP), default_timeout=300)
    at.run()
    if mode is not None:
        at.radio(key="source-mode").set_value(mode).run()
    return at


def _site(area: Path, source: Path) -> Path:
    """A working directory whose data/warehouse holds one selectable file."""
    site = area / "site"
    (site / "data" / "warehouse").mkdir(parents=True, exist_ok=True)
    target = site / "data" / "warehouse" / source.name
    if not target.exists():
        shutil.copy(source, target)
    return site


def _text(at) -> str:
    parts = [e.value for e in at.markdown] + [e.value for e in at.caption]
    parts += [e.value for e in at.warning] + [e.value for e in at.error]
    parts += [e.value for e in at.success] + [e.value for e in at.info]
    return "\n".join(parts)


# ------------------------------------------------------------------ unavailable
def test_no_publication_is_an_explicit_unavailable_state(published, tmp_path):
    with _environment(
        tmp_path / "empty-root", _site(published["area"], published["source"])
    ):
        at = _fresh(sel.PUBLISHED_MODE)
    assert not at.exception, [e.value for e in at.exception]
    # An absence is an ordinary state, not a failure: neutral wording, no error styling.
    assert not at.error, [e.value for e in at.error]
    infos = [i.value for i in at.info]
    assert any("No published version yet" in i for i in infos), infos
    body = _text(at)
    assert "Nothing local is shown in its place" in body
    assert "How to publish a version" in [e.label for e in at.expander], (
        "the setup commands are available, but not in the reader's way"
    )
    # nothing from the local warehouse leaked in under the word "published"
    assert not at.tabs, "the page stops before rendering any tab"
    assert not at.metric


def test_a_broken_publication_shows_no_stale_or_legacy_results(published):
    """The seal names a different run from the build record: refused, nothing shown.

    Tampered **in place** and restored, because a copy of a publication root fails a
    different check first -- see
    ``test_a_publication_directory_moved_to_another_path_is_refused``.
    """
    root = published["root"]
    seal_path = next((root / pub.VERSIONS).glob("*.validated.json"))
    original = seal_path.read_bytes()
    seal = json.loads(original)
    seal["run_id"] = "dbtcand-0000deadbeef@20260101T000000000000"
    try:
        seal_path.write_text(json.dumps(seal))
        with _environment(root, _site(published["area"], published["source"])):
            at = _fresh(sel.PUBLISHED_MODE)
    finally:
        seal_path.write_bytes(original)
    assert not at.exception, [e.value for e in at.exception]
    # A publication that exists and fails validation IS an error, and stays styled as one.
    errors = [e.value for e in at.error]
    assert any("could not be read" in e for e in errors), errors
    assert any("the seal names" in e for e in errors), errors
    assert not any("No published version yet" in i.value for i in at.info)
    assert not at.metric, "no figures at all, stale or otherwise"


def test_a_publication_directory_moved_to_another_path_is_refused(published, tmp_path):
    """A known limitation, pinned rather than discovered later.

    The build attempt records the absolute path it was written in, so a publication root
    copied or moved elsewhere is refused: the record no longer describes that file. The
    refusal is explicit and names the recorded path, and no local warehouse is shown in
    its place -- but restoring a publication to a new location means rebuilding, not
    copying.
    """
    root = tmp_path / "moved"
    shutil.copytree(published["root"], root)
    with _environment(root, _site(published["area"], published["source"])):
        at = _fresh(sel.PUBLISHED_MODE)
    assert not at.exception, [e.value for e in at.exception]
    errors = [e.value for e in at.error]
    assert any("could not be read" in e for e in errors), errors
    assert any("not this file" in e for e in errors), errors
    assert not at.metric


# ------------------------------------------------------------------ the happy path
def test_the_published_version_renders_with_its_own_identity(published):
    with _environment(published["root"], _site(published["area"], published["source"])):
        at = _fresh(sel.PUBLISHED_MODE)
    assert not at.exception, [e.value for e in at.exception]
    assert not at.error
    body = _text(at)

    assert f"Published {published['manifest']['version']}" in [
        s.value for s in at.success
    ]
    assert "sealed dbt build" in body
    assert (
        "Source of these figures: dbt build (`scenario_build`), sealed and promoted."
        in body
    )
    # identity is the build's, never the Python run copied into the same file
    assert published["built"].seal.run_id in body
    assert published["python_run"] not in body
    assert "required dbt nodes passed" in body
    assert "Built tables digest" in body
    assert "canonical-rows-1" in body
    # and what a dbt build does not record is named rather than filled in
    assert "does not record" in body
    assert "scenario fingerprint" in body


def test_the_tariff_figures_are_the_dbt_ones_not_the_copied_python_tables(published):
    """The doctored copy would be unmissable: every charge in main is 999."""
    with _environment(published["root"], _site(published["area"], published["source"])):
        at = _fresh(sel.PUBLISHED_MODE)
    body = _text(at)
    # The whole-run total on screen is the dbt build's, computed from its own fact --
    # checked by value rather than by scanning for "999", which can also occur inside a
    # digest and made this test order-dependent.
    expected = ta.total_charge_exact(
        published["built"].candidate,
        published["built"].seal.run_id,
        relations=ta.DBT_RELATIONS,
    )
    doctored = ta.total_charge_exact(
        published["built"].candidate,
        published["python_run"],
        relations=ta.WAREHOUSE_RELATIONS,
    )
    assert Decimal(doctored) == MARKER_CHARGE * 48, (
        "the copied table really is doctored"
    )
    assert f"`£{expected}`" in body
    assert str(MARKER_CHARGE) not in body
    assert f"`£{doctored}`" not in body
    # the exclusion rows deleted from main are present in the dbt fact
    assert "| Excluded, each with a reason | 9 |" in body
    assert "Counted from the built tables" in body, (
        "the derived ladder says it is derived"
    )


def test_every_tab_describes_the_same_selected_file(published):
    with _environment(published["root"], _site(published["area"], published["source"])):
        at = _fresh(sel.PUBLISHED_MODE)
    name = published["manifest"]["file"]
    body = _text(at)
    assert body.count(name) >= 2, "the version file is named, and consistently"
    assert published["source"].name not in body, (
        "the local warehouse the candidate was built from is not what is being read"
    )


def test_the_forecast_tab_is_assessed_against_the_resolved_publication(published):
    """No report exists for this dataset, so the tab says so rather than showing one."""
    with _environment(published["root"], _site(published["area"], published["source"])):
        at = _fresh(sel.PUBLISHED_MODE)
    body = _text(at)
    assert "No forecast experiment has been run for this database yet" in body


# ------------------------------------------------------------------ mode separation
def test_switching_modes_does_not_mix_the_two_sources(published):
    site = _site(published["area"], published["source"])
    with _environment(published["root"], site):
        at = _fresh()  # warehouse mode, the default
        warehouse_body = _text(at)
        assert "not** a published version" in warehouse_body
        assert published["built"].seal.run_id not in warehouse_body
        assert "Python scenario builder" in warehouse_body
        # the doctored Python figures ARE what a warehouse selection shows
        assert str(MARKER_CHARGE) in warehouse_body

        at.radio(key="source-mode").set_value(sel.PUBLISHED_MODE).run()
        published_body = _text(at)
        assert published["built"].seal.run_id in published_body
        assert "dbt build (`scenario_build`)" in published_body
        assert str(MARKER_CHARGE) not in published_body, (
            "switching mode did not carry the warehouse figures across"
        )

        at.radio(key="source-mode").set_value(sel.WAREHOUSE_MODE).run()
        back = _text(at)
        assert published["built"].seal.run_id not in back
        assert "Python scenario builder" in back
        assert str(MARKER_CHARGE) in back


# ------------------------------------------------------------------ the cache
def test_a_validated_version_is_revalidated_once_and_then_reused(published):
    """The key is the file and the digest the manifest records, never the name."""
    sel.clear_caches()
    first = sel.published(published["root"])
    second = sel.published(published["root"])
    assert first.context is second.context, "the same sealed bytes are not re-proved"
    assert second.context.identity.file_sha256 == published["manifest"]["sha256"]


def test_a_promotion_invalidates_the_cached_version(published):
    """A new manifest names a different file and digest, so the next resolve misses."""
    sel.clear_caches()
    before = sel.published(published["root"])
    other = cand.build_candidate(
        published["source"], root=published["root"], schedule="demo"
    )
    pub.publish(other.candidate, expected_previous="v0001", root=published["root"])
    try:
        after = sel.published(published["root"])
        assert after.context is not before.context
        assert after.context.version == "v0002"
        assert after.database == other.candidate
    finally:
        pub.publish(
            published["built"].candidate,
            expected_previous="v0002",
            root=published["root"],
        )
        sel.clear_caches()


def test_a_warehouse_selection_is_never_cached(published):
    """A mutable file has no content identity, so nothing about it is remembered."""
    sel.clear_caches()
    first = sel.warehouse(published["source"])
    second = sel.warehouse(published["source"])
    assert first is not second and first.context is None
    assert not sel._VALIDATED, "no warehouse entry was stored"


def test_the_applicability_cache_is_keyed_by_the_report_digest_too(published):
    """A regenerated report is assessed again rather than answered from the old verdict."""
    sel.clear_caches()
    selected = sel.published(published["root"])
    report = {"database": "x", "identity": {"dataset_sha256": "a" * 64}, "config": {}}
    first = sel.forecast_applicability(selected, {"fore": report})
    again = sel.forecast_applicability(selected, {"fore": report})
    assert first["fore"] is again["fore"], "same report, same verdict, not recomputed"
    changed = {**report, "identity": {"dataset_sha256": "b" * 64}}
    other = sel.forecast_applicability(selected, {"fore": changed})
    assert other["fore"] is not first["fore"]
    sel.clear_caches()


# ------------------------------------------------------------------ promotion
def test_a_promotion_is_seen_by_the_next_rerun_and_not_by_a_held_context(published):
    """Resolve-once is what makes a render coherent; the next render sees the new one."""
    from energy_reconciliation.tariff import reads

    root = published["root"]
    sel.clear_caches()
    held = reads.published(root)
    was = held.version  # not hard-coded: other tests in this module also promote

    second = cand.build_candidate(published["source"], root=root, schedule="demo")
    pub.publish(second.candidate, expected_previous=was, root=root)
    now = pub.read_manifest(root)["version"]

    # the context obtained before the promotion still reads the version it resolved
    assert held.version == was
    assert held.database == published["built"].candidate
    assert held.run_id == published["built"].seal.run_id

    with _environment(root, _site(published["area"], published["source"])):
        at = _fresh(sel.PUBLISHED_MODE)
    body = _text(at)
    assert f"Published {now}" in [s.value for s in at.success]
    assert second.seal.run_id in body
    assert published["built"].seal.run_id not in body

    # put the fixture back so module order cannot matter
    pub.publish(published["built"].candidate, expected_previous=now, root=root)
    sel.clear_caches()
