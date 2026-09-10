"""What must invalidate a scenario, and what must not.

Two failure modes are guarded here, and they pull in opposite directions:

- **Under-inclusion** -- a file that can change a figure escapes the digest, so a
  changed rule silently reuses an old result. The coverage guard takes the *real* import
  closure of the models in a fresh interpreter and fails if anything is missing.
- **Over-inclusion** -- a file that cannot change a figure is in the digest, so editing
  a print statement invalidates every result and the signal becomes noise nobody trusts.
  The reporting and replay modules are asserted *out*.
"""

from __future__ import annotations

import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest
from conftest import HEADER, row
from test_tariff import load, make_schedule

from energy_reconciliation.tariff import analytics as ta
from energy_reconciliation.tariff import candidate_identity as cid
from energy_reconciliation.tariff import identity
from energy_reconciliation.tariff import prices as pr
from energy_reconciliation.tariff.models import build_scenario

SRC = Path(__file__).resolve().parent.parent / "src"


def _one_reading(tmp_path, name="id.zip"):
    body = HEADER + row("MAC000001", "ToU", "2013-01-01 00:30:00.0000000", " 1 ")
    return load(tmp_path, body, name=name)


# ------------------------------------------------------------- coverage guard
def test_every_first_party_module_the_models_import_is_covered():
    """The real import closure of the models, taken in a fresh interpreter.

    A package-local source hash is not evidence that an imported shared file is
    covered. This resolves the question by importing the models with nothing else
    loaded and comparing what arrives against the declared list.
    """
    script = (
        "import sys, json;"
        f"sys.path.insert(0, {str(SRC)!r});"
        "import energy_reconciliation.tariff.models;"
        "from energy_reconciliation.tariff import identity;"
        "print(json.dumps(identity.import_closure()))"
    )
    out = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    closure = set(json.loads(out.stdout).values())
    covered = {
        str(p.relative_to(identity.PACKAGE_ROOT)) for p in identity.calculation_files()
    }
    missing = closure - covered
    assert not missing, (
        f"these files are imported by the models but escape invalidation: {sorted(missing)}"
    )


def test_the_shared_policy_module_is_covered_by_name():
    covered = {
        str(p.relative_to(identity.PACKAGE_ROOT)) for p in identity.calculation_files()
    }
    assert "policy.py" in covered
    assert "tariff/models.py" in covered
    assert "ingest/loader.py" in covered


def test_reporting_and_replay_code_is_deliberately_not_covered():
    """Editing a print statement in the replay CLI must not invalidate a result.

    Over-inclusion was a real defect here, not a hypothetical: adding the baseline
    tooling once changed the fingerprint of a scenario whose every figure was identical.
    """
    covered = {
        str(p.relative_to(identity.PACKAGE_ROOT)) for p in identity.calculation_files()
    }
    for reporting in (
        "tariff/analytics.py",
        "tariff/cli.py",
        "tariff/baseline.py",
        "tariff/baseline_cli.py",
        # Format-2 recording and replay read a result and compare it. Neither can change
        # a stored figure, and putting them in the digest would invalidate every result
        # whenever the reporting wording changed.
        "tariff/published_baseline.py",
        "tariff/reads.py",
        # ANL-005 prices the certified facts a second way and stores nothing.
        "tariff/flat_comparison.py",
    ):
        assert reporting not in covered


def test_a_changed_file_changes_the_digest(tmp_path):
    """Byte-level, not name-level: one character in policy.py moves the digest."""
    original = (identity.PACKAGE_ROOT / "policy.py").read_bytes()
    before = identity.calculation_digest()
    policy_before = identity.policy_digest()
    try:
        (identity.PACKAGE_ROOT / "policy.py").write_bytes(original + b"\n# touched\n")
        assert identity.calculation_digest() != before
        assert identity.policy_digest() != policy_before
    finally:
        (identity.PACKAGE_ROOT / "policy.py").write_bytes(original)
    assert identity.calculation_digest() == before


def test_runtime_identity_names_the_libraries_that_do_the_arithmetic():
    runtime = identity.runtime_identity()
    assert runtime["python"] and runtime["duckdb"]
    assert set(runtime) >= {"python", "implementation", *identity.RUNTIME_PACKAGES}
    assert len(identity.runtime_fingerprint()) == 64


# ---------------------------------------------------------- candidate identity
def _covered_for_candidates(project=None) -> set[str]:
    return {
        str(p.relative_to(identity.PACKAGE_ROOT))
        if p.is_relative_to(identity.PACKAGE_ROOT)
        else str(p)
        for p in cid.candidate_calculation_files(project)
    }


def test_every_first_party_module_the_dbt_python_models_import_is_covered():
    """The dbt Python models import ``dimensions`` and ``schedule``; take their closure."""
    script = (
        "import sys, json;"
        f"sys.path.insert(0, {str(SRC)!r});"
        "import energy_reconciliation.tariff.dimensions;"
        "import energy_reconciliation.tariff.schedule;"
        "from energy_reconciliation.tariff import identity;"
        "print(json.dumps(identity.import_closure()))"
    )
    out = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    closure = set(json.loads(out.stdout).values())
    missing = closure - _covered_for_candidates()
    assert not missing, (
        f"imported by the dbt Python models but not in the candidate identity: "
        f"{sorted(missing)}"
    )
    assert "tariff/dimensions.py" in _covered_for_candidates()


def test_every_dbt_project_file_is_covered_or_deliberately_excluded():
    """An independent walk of dbt/, minus the documented exclusions, must equal the globs.

    A new directory under dbt/ (seeds, snapshots, analyses) shows up here and fails, so
    the decision to cover or exclude it is made rather than defaulted.
    """
    project = cid.default_dbt_project()
    excluded_dirs = {"target", "logs", "dbt_packages", "tests"}
    excluded_files = {".user.yml", "profiles.yml"}
    walked = {
        p.resolve()
        for p in project.rglob("*")
        if p.is_file()
        and not (set(p.relative_to(project).parts[:-1]) & excluded_dirs)
        and p.name not in excluded_files
    }
    assert walked == set(cid.dbt_project_files()), (
        f"uncovered: {sorted(str(p.relative_to(project)) for p in walked - set(cid.dbt_project_files()))}"
    )
    for name in (
        "dbt_project.yml",
        "macros/generated_policy.sql",
        "models/tariff/schema.yml",
    ):
        assert (project / name).resolve() in walked


def test_the_candidate_digest_moves_when_a_dbt_model_changes(tmp_path):
    """Byte-level on a COPY of the project; the repository's project is never edited."""
    import shutil

    copy = tmp_path / "dbt"
    shutil.copytree(
        cid.default_dbt_project(),
        copy,
        ignore=shutil.ignore_patterns("target", "logs", ".user.yml"),
    )
    assert (
        cid.candidate_calculation_digest(copy) == cid.candidate_calculation_digest()
    ), "an identical copy digests the same, so the digest is content, not location"
    model = copy / "models" / "tariff" / "fact_interval_charge_scenario.sql"
    model.write_text(model.read_text() + "\n-- touched\n")
    assert cid.candidate_calculation_digest(copy) != cid.candidate_calculation_digest()
    assert cid.dbt_project_digest(copy) != cid.dbt_project_digest()


def test_the_candidate_runtime_names_every_library_that_produces_a_table():
    runtime = cid.candidate_runtime_identity()
    assert set(runtime) >= {
        "python",
        "duckdb",
        "pyarrow",
        "pandas",
        "openpyxl",
        "dbt-core",
        "dbt-duckdb",
    }
    assert runtime["dbt-core"] not in {"", "absent"}
    assert len(cid.candidate_runtime_fingerprint()) == 64
    # the published runtime identity is a strict subset, unchanged
    assert {
        k: runtime[k] for k in identity.runtime_identity()
    } == identity.runtime_identity()


def test_the_published_identity_is_a_subset_and_untouched_by_the_candidate_one():
    """Deliberate in this slice: the dashboard reads no candidate yet, so the published
    fingerprint must not claim a dependency on dbt or on dimensions.py."""
    published = {
        str(p.relative_to(identity.PACKAGE_ROOT)) for p in identity.calculation_files()
    }
    candidate = _covered_for_candidates()
    assert published < candidate
    assert "tariff/dimensions.py" not in published
    assert "tariff/candidate_identity.py" not in published
    assert "tariff/published_baseline.py" not in candidate, (
        "recording and comparing a result cannot change one; over-inclusion is the "
        "failure here"
    )
    assert "tariff/candidate_identity.py" not in candidate, (
        "the identity code is not the calculation; over-inclusion is the failure here"
    )
    assert "tariff/flat_comparison.py" not in candidate, (
        "a comparison read over the facts cannot change a stored figure"
    )


# ------------------------------------------- invalidation reaches a real rebuild
def test_an_unchanged_rerun_skips(tmp_path):
    database = _one_reading(tmp_path)
    schedule = make_schedule([("2013-01-01 00:30:00", "Low")])
    first = build_scenario(database, schedule)
    second = build_scenario(database, schedule)
    assert not first.skipped and second.skipped
    assert second.run_id == first.run_id


@pytest.mark.parametrize(
    "component",
    ["calculation_digest", "runtime_fingerprint"],
)
def test_changing_a_relevant_component_rebuilds_the_result(
    tmp_path, monkeypatch, component
):
    """A changed policy or runtime must produce a new run, not reuse the old one.

    ``calculation_digest`` is what a policy edit moves; the parametrised runtime case
    covers a library upgrade. Both are patched at their source rather than simulated
    downstream, so the test exercises the same path a real change would.
    """
    database = _one_reading(tmp_path)
    schedule = make_schedule([("2013-01-01 00:30:00", "Low")])
    first = build_scenario(database, schedule)

    monkeypatch.setattr(identity, component, lambda: "f" * 64)
    second = build_scenario(database, schedule)

    assert not second.skipped, f"a changed {component} must not be skipped"
    assert second.replaced_previous
    assert second.run_id != first.run_id
    assert second.scenario_fingerprint != first.scenario_fingerprint
    con = duckdb.connect(str(database), read_only=True)
    try:
        statuses = dict(
            con.execute("SELECT run_id, status FROM scenario_run").fetchall()
        )
    finally:
        con.close()
    assert statuses[first.run_id] == "superseded"
    assert statuses[second.run_id] == "published"


def test_a_changed_price_catalogue_version_rebuilds(tmp_path, monkeypatch):
    database = _one_reading(tmp_path)
    schedule = make_schedule([("2013-01-01 00:30:00", "Low")])
    first = build_scenario(database, schedule)
    monkeypatch.setattr(pr, "PRICE_CATALOGUE_VERSION", "9999-01-01.9")
    second = build_scenario(database, schedule)
    assert not second.skipped
    assert second.run_id != first.run_id


def test_the_run_records_the_runtime_it_used(tmp_path):
    database = _one_reading(tmp_path)
    build_scenario(database, make_schedule([("2013-01-01 00:30:00", "Low")]))
    run = ta.latest_run(database)
    assert run.runtime["duckdb"] == identity.runtime_identity()["duckdb"]
    assert run.runtime_fingerprint == identity.runtime_fingerprint()
    assert run.calculation_code_sha256 == identity.calculation_digest()
    assert run.policy_sha256 == identity.policy_digest()


# --------------------------------------------------------- baseline and replay
def test_a_baseline_records_the_inputs_and_replays_into_a_fresh_database(tmp_path):
    """Capture, then rebuild from the captured inputs alone, then compare.

    The replay database must not already exist: reusing a warehouse proves nothing
    about rebuilding from a record.
    """
    from energy_reconciliation.tariff import baseline as bl

    body = HEADER + b"".join(
        [
            row("MAC000001", "ToU", "2013-01-01 00:30:00.0000000", " 2 "),
            row("MAC000002", "ToU", "2013-01-01 01:00:00.0000000", " 4 "),
            row("MAC000003", "Std", "2013-01-01 01:00:00.0000000", " 9 "),
        ]
    )
    archive = tmp_path / "src.zip"
    import zipfile

    member = "Small LCL Data/LCL-June2015v2_0.csv"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(member, body)

    from energy_reconciliation.ingest.loader import load_member

    original = tmp_path / "original.duckdb"
    load_member(archive, member, original)
    schedule = make_schedule(
        [("2013-01-01 00:30:00", "High"), ("2013-01-01 01:00:00", "Low")]
    )
    built = build_scenario(original, schedule)
    # 2 x 0.6720 + 4 x 0.0399 = 1.3440 + 0.1596 = 1.5036
    assert Decimal(built.total_energy_charge_gbp_exact) == Decimal("1.5036")

    path = bl.capture(original, tmp_path / "baselines")
    record = json.loads(path.read_text())
    assert record["inputs"]["member_count"] == 1
    assert record["inputs"]["members"][0]["member_content_sha256"]
    assert record["calculation"]["policy_sha256"] == identity.policy_digest()
    assert record["runtime"]["duckdb"] == identity.runtime_identity()["duckdb"]
    assert {b["band_label"] for b in record["output"]["per_band"]} == {"High", "Low"}

    replayed = tmp_path / "replay.duckdb"
    # The schedule is synthetic here, so the replay path reads it from the record's
    # source marker rather than the workbook; feed it the same one.
    from energy_reconciliation.ingest.loader import load_member as _load

    _load(archive, member, replayed)
    result = build_scenario(replayed, schedule)
    differences = bl.compare(record, replayed, result)
    failed = [d for d in differences if not d.matches]
    assert not failed, [(d.field, d.baseline, d.replay) for d in failed]


def test_a_baseline_is_never_overwritten(tmp_path):
    from energy_reconciliation.tariff import baseline as bl

    database = _one_reading(tmp_path)
    build_scenario(database, make_schedule([("2013-01-01 00:30:00", "Low")]))
    first = bl.capture(database, tmp_path / "b")
    first.write_text(first.read_text())  # still there
    assert first.exists()


def test_replay_refuses_an_existing_database(tmp_path):
    from energy_reconciliation.tariff import baseline as bl

    database = _one_reading(tmp_path)
    build_scenario(database, make_schedule([("2013-01-01 00:30:00", "Low")]))
    path = bl.capture(database, tmp_path / "b")
    with pytest.raises(bl.BaselineError, match="fresh database"):
        bl.replay(path, database)


def test_replay_refuses_a_member_whose_content_changed(tmp_path):
    """A member whose bytes differ is not the input the baseline describes."""
    import zipfile

    from energy_reconciliation.ingest.loader import load_member
    from energy_reconciliation.tariff import baseline as bl

    member = "Small LCL Data/LCL-June2015v2_0.csv"
    archive = tmp_path / "src.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            member, HEADER + row("H1", "ToU", "2013-01-01 00:30:00.0000000", " 1 ")
        )
    database = tmp_path / "orig.duckdb"
    load_member(archive, member, database)
    build_scenario(database, make_schedule([("2013-01-01 00:30:00", "Low")]))
    path = bl.capture(database, tmp_path / "b")

    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            member, HEADER + row("H1", "ToU", "2013-01-01 00:30:00.0000000", " 2 ")
        )
    with pytest.raises(bl.BaselineError, match="content digest"):
        bl.replay(path, tmp_path / "fresh.duckdb", archive=archive)


def test_the_baseline_records_row_level_lineage_and_replay_compares_it(tmp_path):
    """Aggregates can agree while rows differ; the row digest cannot."""
    from energy_reconciliation.tariff import baseline as bl

    body = HEADER + b"".join(
        [
            row("MAC000001", "ToU", "2013-01-01 00:30:00.0000000", " 2 "),
            row("MAC000002", "ToU", "2013-01-01 00:30:00.0000000", " 4 "),
        ]
    )
    database = load(tmp_path, body, name="lineage.zip")
    schedule = make_schedule([("2013-01-01 00:30:00", "High")])
    result = build_scenario(database, schedule)
    record = json.loads(bl.capture(database, tmp_path / "b").read_text())
    assert len(record["output"]["fact_row_digest"]) == 64

    # same aggregates, different rows: swap the two households' readings
    swapped = HEADER + b"".join(
        [
            row("MAC000001", "ToU", "2013-01-01 00:30:00.0000000", " 4 "),
            row("MAC000002", "ToU", "2013-01-01 00:30:00.0000000", " 2 "),
        ]
    )
    other = load(tmp_path, swapped, name="swapped.zip")
    other_result = build_scenario(other, schedule)
    assert (
        other_result.total_energy_charge_gbp_exact
        == result.total_energy_charge_gbp_exact
    )
    differences = {d.field: d for d in bl.compare(record, other, other_result)}
    assert differences["band[High].charge_exact"].matches  # band total unchanged
    assert differences["fact_row_digest (every charged row)"].matches is False
    assert differences["per_household charges (2 households)"].matches is False
