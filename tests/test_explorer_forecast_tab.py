"""The forecast tab's applicability guard, driven through Streamlit's own test harness.

Headless: ``AppTest`` runs ``app.py`` in-process against a temporary working directory
holding ``data/warehouse/<fixture>.duckdb`` and ``data/forecasts/<report>.json`` -- the
same relative paths the app uses -- and exposes what it rendered. Nothing here opens a
browser; what a browser shows was not observed by these tests.

Three states are pinned: a report that describes the selected dataset is shown with a
verification note; the same report against different data under the **same file name** is
withheld with an explanation (the case the old file-name check accepted); and an identical
dataset under **another file name** is shown (the case the old check refused).
"""

from __future__ import annotations

import json
import os
import shutil
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pytest
from conftest import HEADER, MEMBER, row

from energy_reconciliation.forecast.evaluate import ExperimentConfig, run_experiment
from energy_reconciliation.forecast.prior_eligibility import (
    PriorConfig,
    run_prior_eligibility,
)
from energy_reconciliation.ingest.loader import load_member

pytest.importorskip("streamlit.testing.v1", reason="Streamlit test harness unavailable")
from streamlit.testing.v1 import AppTest

APP = (
    Path(__file__).resolve().parent.parent / "src/energy_reconciliation/explorer/app.py"
)
START = date(2013, 1, 1)


def _rows(days: int = 200) -> list[bytes]:
    return [
        row(
            "H1",
            "Std",
            f"{START + timedelta(days=i)} {j // 2:02d}:{(j % 2) * 30:02d}:00.0000000",
            " 0.25 ",
        )
        for i in range(days)
        for j in range(48)
    ]


def _site(root: Path, rows: list[bytes], name: str) -> Path:
    """A working directory shaped like the repository's: data/warehouse and data/forecasts."""
    (root / "data" / "warehouse").mkdir(parents=True, exist_ok=True)
    (root / "data" / "forecasts").mkdir(parents=True, exist_ok=True)
    archive = root / f"{name}.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(MEMBER, HEADER + b"".join(rows))
    database = root / "data" / "warehouse" / name
    assert load_member(archive, MEMBER, database).complete
    return database


@pytest.fixture(scope="module")
def recorded(tmp_path_factory):
    """A warehouse and the FORE-001 report run against it, once for the module."""
    area = Path(str(tmp_path_factory.mktemp("forecast-tab")))
    database = _site(area / "origin", _rows(), "fixture.duckdb")
    report = json.loads(
        json.dumps(run_experiment(database, ExperimentConfig()), default=str)
    )
    prior = run_prior_eligibility(database, PriorConfig())
    prior.pop("_cases", None)
    prior = json.loads(json.dumps(prior, default=str))
    return {"area": area, "database": database, "report": report, "prior": prior}


def _place_reports(root: Path, recorded: dict) -> None:
    (root / "data" / "forecasts").mkdir(parents=True, exist_ok=True)
    (root / "data" / "forecasts" / "fore-001-test.json").write_text(
        json.dumps(recorded["report"])
    )
    (root / "data" / "forecasts" / "i-08-test.json").write_text(
        json.dumps(recorded["prior"])
    )
    (root / "data" / "forecasts" / "i-08-test.json").write_text(
        json.dumps(recorded["prior"])
    )


def _run_app_in(root: Path) -> AppTest:
    previous = Path.cwd()
    os.chdir(root)
    try:
        at = AppTest.from_file(str(APP), default_timeout=180)
        at.run()
    finally:
        os.chdir(previous)
    assert not at.exception, [e.value for e in at.exception]
    return at


def _captions(at: AppTest) -> list[str]:
    return [c.value for c in at.caption]


def _warnings(at: AppTest) -> list[str]:
    return [w.value for w in at.warning]


def test_an_applicable_report_is_shown_with_its_verification_note(recorded):
    root = recorded["area"] / "origin"
    _place_reports(root, recorded)
    at = _run_app_in(root)
    notes = [
        c
        for c in _captions(at)
        if c.startswith("**Applies to this dataset**") and "fore-001" in c
    ]
    assert len(notes) == 1, _captions(at)
    assert "recorded against and read from `fixture.duckdb`" in notes[0]
    assert "fore-001-cohort-series-1" in notes[0]
    assert "Households evaluated" in [m.label for m in at.metric]
    assert not any("does not describe" in w for w in _warnings(at))
    # the I-08 report is assessed under its own definition, from the same scan
    prior_notes = [c for c in _captions(at) if "i-08-usable-days-1" in c]
    assert len(prior_notes) == 1 and prior_notes[0].startswith(
        "**Applies to this dataset**"
    )


def test_different_data_under_the_same_file_name_is_withheld(recorded):
    """The case the old file-name comparison would have accepted."""
    root = recorded["area"] / "impostor"
    rows = _rows()[:-48] + [
        row(
            "H1",
            "Std",
            f"{START + timedelta(days=199)} {j // 2:02d}:{(j % 2) * 30:02d}:00.0000000",
            " 9.0 ",
        )
        for j in range(48)
    ]
    database = _site(root, rows, "fixture.duckdb")
    assert database.name == Path(recorded["report"]["database"]).name
    _place_reports(root, recorded)
    at = _run_app_in(root)
    warnings = [w for w in _warnings(at) if "does not describe `fixture.duckdb`" in w]
    assert len(warnings) == 1, _warnings(at)
    assert "the same file name" in warnings[0]
    assert "computed from other data" in warnings[0]
    assert "run-forecast-experiment" in warnings[0]
    assert "Households evaluated" not in [m.label for m in at.metric], (
        "the report body is withheld, not shown with a footnote"
    )
    assert not any(c.startswith("**Applies to this dataset**") for c in _captions(at))
    # with the FORE-001 body withheld, the I-08 expander inside it is not reached either
    assert not any("i-08-usable-days-1" in c for c in _captions(at))


def test_an_identical_dataset_under_another_name_is_shown(recorded):
    """The case the old file-name comparison refused."""
    root = recorded["area"] / "renamed"
    (root / "data" / "warehouse").mkdir(parents=True)
    (root / "data" / "forecasts").mkdir(parents=True)
    copy = root / "data" / "warehouse" / "cand-20260908T000000000000.duckdb"
    shutil.copy(recorded["database"], copy)
    _place_reports(root, recorded)
    at = _run_app_in(root)
    notes = [
        c
        for c in _captions(at)
        if c.startswith("**Applies to this dataset**") and "fore-001" in c
    ]
    assert len(notes) == 1, (_captions(at), _warnings(at))
    assert "recorded against `fixture.duckdb`" in notes[0]
    assert "now read from `cand-20260908T000000000000.duckdb`" in notes[0]
    assert "Households evaluated" in [m.label for m in at.metric]


def test_a_context_only_change_is_withheld_with_the_differing_figures_named(recorded):
    """One extra household with a single unusable day: scores unchanged, page withheld."""
    root = recorded["area"] / "context"
    rows = _rows() + [
        row("H9", "Std", f"{START} {j // 2:02d}:{(j % 2) * 30:02d}:00.0000000", " 1.0 ")
        for j in range(47)
    ]
    _site(root, rows, "fixture.duckdb")
    _place_reports(root, recorded)
    at = _run_app_in(root)
    warnings = [w for w in _warnings(at) if "does not describe" in w]
    assert len(warnings) == 1, _warnings(at)
    assert "would be unchanged" in warnings[0]
    assert "`feasibility.households`" in warnings[0]
    assert "Households evaluated" not in [m.label for m in at.metric]


def test_the_report_body_never_reads_the_recorded_path_as_the_selected_dataset(
    recorded,
):
    """Provenance is labelled as provenance; the dataset line names the selected file."""
    root = recorded["area"] / "renamed"
    at = _run_app_in(root)
    dataset_lines = [m.value for m in at.markdown if m.value.startswith("**Dataset**")]
    assert dataset_lines and "`cand-20260908T000000000000.duckdb`" in dataset_lines[0]
    identity = [m.value for m in at.markdown if "Recorded against" in m.value]
    assert identity and "path at generation time, kept as provenance" in identity[0]


def test_an_i08_report_that_does_not_describe_the_dataset_is_withheld_alone(recorded):
    """Only the I-08 report is stale: FORE-001 is shown, the I-08 expander warns."""
    root = recorded["area"] / "stale-prior"
    (root / "data" / "warehouse").mkdir(parents=True)
    shutil.copy(recorded["database"], root / "data" / "warehouse" / "fixture.duckdb")
    _place_reports(root, recorded)
    stale = json.loads(json.dumps(recorded["prior"]))
    stale["identity"]["dataset_sha256"] = "0" * 64
    (root / "data" / "forecasts" / "i-08-test.json").write_text(json.dumps(stale))
    at = _run_app_in(root)
    assert "Households evaluated" in [m.label for m in at.metric]
    warnings = [w for w in _warnings(at) if "does not describe" in w]
    assert len(warnings) == 1 and "run-prior-eligibility" in warnings[0]
    assert not any("i-08-usable-days-1" in c for c in _captions(at))
