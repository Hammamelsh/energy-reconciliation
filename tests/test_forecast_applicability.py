"""Does a forecast report describe the selected dataset? Content, never the file name.

The defect (I-19): the forecast tab compared ``Path(report["database"]).name`` with the
open file's name. A published version or a renamed copy with byte-identical readings was
refused; a different warehouse reusing the name would have been accepted. These tests pin
the replacement: each report kind is recomputed under its **own** recorded digest
definition, and every displayed figure the digest does not cover is recomputed separately.
"""

from __future__ import annotations

import json
import random
import shutil
import zipfile
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest
from conftest import HEADER, MEMBER, row

from energy_reconciliation.forecast import applicability as ap
from energy_reconciliation.forecast import dataset as ds
from energy_reconciliation.forecast.evaluate import ExperimentConfig, run_experiment
from energy_reconciliation.forecast.prior_eligibility import (
    PriorConfig,
    run_prior_eligibility,
)
from energy_reconciliation.ingest.loader import load_member

START = date(2013, 1, 1)
REAL_WAREHOUSE = Path("data/warehouse/energy.duckdb")
REAL_REPORTS = Path("data/forecasts")


def _day(household: str, day: date, intervals: int = 48, value=" 0.5 ", group="Std"):
    return [
        row(
            household, group, f"{day} {i // 2:02d}:{(i % 2) * 30:02d}:00.0000000", value
        )
        for i in range(intervals)
    ]


def _rows(days: int = 200, second_household: bool = True) -> list[bytes]:
    """Two households: H1 flat, H2 rising. Long enough for FORE-001's default run rule."""
    out: list[bytes] = []
    for i in range(days):
        out += _day("H1", START + timedelta(days=i), value=" 0.25 ")
        if second_household:
            out += _day(
                "H2", START + timedelta(days=i), value=f" {0.1 + i / 1000:.3f} "
            )
    return out


def _warehouse(directory: Path, rows: list[bytes], name: str = "fc.duckdb") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / (name + ".zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(MEMBER, HEADER + b"".join(rows))
    database = directory / name
    assert load_member(archive, MEMBER, database).complete
    return database


@pytest.fixture(scope="module")
def experiments(tmp_path_factory):
    """One warehouse, one FORE-001 report and one I-08 report, shared across the module."""
    area = Path(str(tmp_path_factory.mktemp("applicability")))
    database = _warehouse(area / "a", _rows())
    fore = run_experiment(database, ExperimentConfig())
    prior = run_prior_eligibility(database, PriorConfig())
    prior.pop("_cases", None)
    fore = json.loads(json.dumps(fore, default=str))
    prior = json.loads(json.dumps(prior, default=str))
    return {"area": area, "database": database, "fore": fore, "prior": prior}


# ------------------------------------------------------------- identical content
def test_the_recorded_dataset_is_applicable_for_both_kinds(experiments):
    fits = ap.assess_reports(
        {"fore": experiments["fore"], "prior": experiments["prior"]},
        experiments["database"],
    )
    for fit in fits.values():
        assert fit.applicable, fit.reason
        assert fit.core_matches and not fit.differing
        assert not fit.renamed
    assert fits["fore"].kind == ap.FORE_001 and fits["prior"].kind == ap.I08
    assert fits["fore"].definition == ds.FORE_001_DIGEST
    assert fits["prior"].definition == ds.I08_DIGEST


def test_a_renamed_identical_database_is_accepted(experiments):
    renamed = experiments["area"] / "elsewhere" / "cand-20260908T000000.duckdb"
    renamed.parent.mkdir()
    shutil.copy(experiments["database"], renamed)
    fits = ap.assess_reports(
        {"fore": experiments["fore"], "prior": experiments["prior"]}, renamed
    )
    for fit in fits.values():
        assert fit.applicable, fit.reason
        assert fit.renamed, "the name differs, and that is provenance, not a mismatch"
        assert Path(fit.recorded_database).name == experiments["database"].name
        assert fit.selected_database == str(renamed)


def test_reordering_source_rows_does_not_cause_a_mismatch(experiments):
    """Same readings loaded in a different physical order digest the same."""
    rows = _rows()
    random.Random(7).shuffle(rows)
    shuffled = _warehouse(experiments["area"] / "shuffled", rows)
    fits = ap.assess_reports(
        {"fore": experiments["fore"], "prior": experiments["prior"]}, shuffled
    )
    assert all(fit.applicable for fit in fits.values()), [
        f.reason for f in fits.values()
    ]


def test_a_read_context_is_used_as_is_and_never_re_resolved(experiments):
    """Anything with a ``database`` attribute is accepted; nothing else is consulted."""

    class Context:
        database = experiments["database"]
        role = "published"

    fit = ap.assess(experiments["fore"], Context())
    assert fit.applicable and fit.selected_database == str(experiments["database"])


# ------------------------------------------------------------- different content
def test_different_data_under_the_same_file_name_is_refused(experiments):
    other = _warehouse(
        experiments["area"] / "b",
        _rows(days=200)[:-48]
        + _day("H2", START + timedelta(days=199), value=" 9.999 "),
    )
    assert other.name == experiments["database"].name
    fits = ap.assess_reports(
        {"fore": experiments["fore"], "prior": experiments["prior"]}, other
    )
    for fit in fits.values():
        assert fit.outcome == ap.MISMATCHED, fit.reason
        assert not fit.core_matches
        assert "computed from other data" in fit.reason
        assert not fit.renamed, "same name, and the name settled nothing"


def test_one_changed_usable_target_value_is_detected(experiments):
    changed = experiments["area"] / "one-value" / experiments["database"].name
    changed.parent.mkdir()
    shutil.copy(experiments["database"], changed)
    con = duckdb.connect(str(changed))
    con.execute(
        "UPDATE readings SET consumption_kwh = consumption_kwh + 0.001 WHERE "
        "household_id = 'H2' AND source_timestamp_text LIKE '2013-03-15 12:00%'"
    )
    con.close()
    fits = ap.assess_reports(
        {"fore": experiments["fore"], "prior": experiments["prior"]}, changed
    )
    for fit in fits.values():
        core = [c for c in fit.checks if c.core]
        assert fit.outcome == ap.MISMATCHED and not core[0].matches, fit.reason


def test_a_change_outside_the_digest_is_reported_as_a_context_mismatch(experiments):
    """A household with only unusable days: no usable total, so both digests are unchanged
    -- and the households-considered / feasibility counts the page shows are wrong."""
    rows = _rows() + _day("H3", START, intervals=47, value=" 1.0 ")
    extra = _warehouse(experiments["area"] / "extra", rows)
    fits = ap.assess_reports(
        {"fore": experiments["fore"], "prior": experiments["prior"]}, extra
    )
    for fit in fits.values():
        assert fit.outcome == ap.MISMATCHED, fit.reason
        assert fit.core_matches, "the scores themselves would not change"
        assert "would be unchanged" in fit.reason
    fore_fields = {c.field for c in fits["fore"].differing}
    assert {"feasibility.households", "feasibility.household_days"} <= fore_fields
    assert "identity.dataset_sha256" not in fore_fields
    prior_fields = {c.field for c in fits["prior"].differing}
    assert "universe.households" in prior_fields
    assert "target_availability.unavailable_by_reason" in prior_fields, (
        "the absent-versus-not-usable split moved: H3's unusable day is 'not usable' "
        "where the recorded report had nothing"
    )


def test_a_membership_change_that_alters_the_cohort_is_a_core_mismatch(experiments):
    """A new eligible household with a smaller id displaces the cohort's first member."""
    rows = _rows() + [
        r
        for i in range(200)
        for r in _day("H0", START + timedelta(days=i), value=" 0.75 ", group="ToU")
    ]
    grown = _warehouse(experiments["area"] / "grown", rows)
    fit = ap.assess(experiments["fore"], grown)
    assert fit.outcome == ap.MISMATCHED and not fit.core_matches
    prior_fit = ap.assess(experiments["prior"], grown)
    assert prior_fit.outcome == ap.MISMATCHED and not prior_fit.core_matches


# -------------------------------------------------------------- legacy / missing
def test_a_report_without_a_definition_is_read_under_the_documented_rule(experiments):
    legacy = json.loads(json.dumps(experiments["fore"]))
    del legacy["identity"]["dataset_digest_definition"]
    fit = ap.assess(legacy, experiments["database"])
    assert fit.applicable and fit.definition == ds.FORE_001_DIGEST


def test_an_unknown_digest_definition_is_unverifiable_not_evaluated(experiments):
    other = json.loads(json.dumps(experiments["prior"]))
    other["identity"]["dataset_digest_definition"] = "i-08-usable-days-9"
    fit = ap.assess(other, experiments["database"])
    assert fit.outcome == ap.UNVERIFIABLE
    assert "i-08-usable-days-9" in fit.reason and not fit.applicable
    assert fit.checks == (), "nothing was compared under a guessed definition"


def test_missing_identity_or_config_is_unverifiable(experiments):
    no_identity = json.loads(json.dumps(experiments["fore"]))
    del no_identity["identity"]["dataset_sha256"]
    assert ap.assess(no_identity, experiments["database"]).outcome == ap.UNVERIFIABLE

    no_config = json.loads(json.dumps(experiments["fore"]))
    del no_config["config"]["household_limit"]
    assert ap.assess(no_config, experiments["database"]).outcome == ap.UNVERIFIABLE

    bad_prior = json.loads(json.dumps(experiments["prior"]))
    bad_prior["config"]["unknown_knob"] = 3
    assert ap.assess(bad_prior, experiments["database"]).outcome == ap.UNVERIFIABLE


def test_a_missing_recorded_context_field_is_unverifiable_not_a_match(experiments):
    partial = json.loads(json.dumps(experiments["fore"]))
    del partial["selection"]["cohort_members"]
    fit = ap.assess(partial, experiments["database"])
    assert fit.outcome == ap.UNVERIFIABLE
    assert "selection.cohort_members" in fit.reason
    assert fit.core_matches, "the digest did match; the missing claim is what stops it"


def test_an_unknown_report_kind_is_unverifiable(experiments):
    fit = ap.assess({"database": "x.duckdb", "hello": 1}, experiments["database"])
    assert fit.outcome == ap.UNVERIFIABLE and fit.kind == "unknown"


def test_nothing_is_scanned_when_there_is_no_report(experiments, monkeypatch):
    def boom(*_args, **_kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("daily_records must not run with no report to assess")

    monkeypatch.setattr(ds, "daily_records", boom)
    assert ap.assess_reports(
        {"fore": None, "prior": None}, experiments["database"]
    ) == {
        "fore": None,
        "prior": None,
    }


# --------------------------------------------------------------- the real reports
@pytest.mark.skipif(
    not REAL_WAREHOUSE.exists() or not any(REAL_REPORTS.glob("fore-001-*.json")),
    reason="the real warehouse and reports are local, not part of the repository",
)
def test_the_committed_real_reports_apply_to_energy_and_to_an_identical_copy(tmp_path):
    """Both real reports, unchanged, recompute against the warehouse they were run on --
    and against a byte-for-byte copy at a candidate-style path, which the old file-name
    check refused."""
    fore = json.loads(max(REAL_REPORTS.glob("fore-001-*.json")).read_text())
    prior = json.loads(max(REAL_REPORTS.glob("i-08-*.json")).read_text())
    assert "dataset_digest_definition" not in fore["identity"], (
        "the real report predates the field: it is read under the compatibility rule"
    )
    fits = ap.assess_reports({"fore": fore, "prior": prior}, REAL_WAREHOUSE)
    assert fits["fore"].applicable, fits["fore"].reason
    assert fits["prior"].applicable, fits["prior"].reason

    scratch = Path("data/proof-scratch") / "applicability" / "versions"
    scratch.mkdir(parents=True, exist_ok=True)
    copy = scratch / "cand-20260908T000000000000.duckdb"
    try:
        shutil.copy(REAL_WAREHOUSE, copy)
        fits = ap.assess_reports({"fore": fore, "prior": prior}, copy)
        assert fits["fore"].applicable and fits["fore"].renamed
        assert fits["prior"].applicable and fits["prior"].renamed
    finally:
        shutil.rmtree(scratch.parent, ignore_errors=True)
