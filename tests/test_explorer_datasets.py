"""Which warehouse a picker offers, what it calls each one, and what it refuses to guess.

Three near-identical *Low Carbon London sample (member 135, member 4, member 5)* entries
were being offered as if they were alternatives. Two of them are artefacts of one past
investigation (REC-001) and one is the working warehouse. This module pins the labels, the
rule that assigns them, and the behaviour when a hidden file is the one selected.

The rule under test is deliberately narrow: a role comes from **explicit configuration**
(the default-database constant, the runbook's file names) or **corroborating metadata**
(a captured baseline with that id, household ids beginning ``DEMO``). Never from how many
source members a file happens to contain -- the anti-inference cases below are the point.
"""

from __future__ import annotations

import os
import zipfile
from contextlib import contextmanager
from pathlib import Path

import pytest
from conftest import HEADER, row

from energy_reconciliation.explorer import datasets as ds
from energy_reconciliation.ingest.loader import load_member

pytest.importorskip("streamlit.testing.v1", reason="Streamlit test harness unavailable")
from streamlit.testing.v1 import AppTest

APP = (
    Path(__file__).resolve().parent.parent / "src/energy_reconciliation/explorer/app.py"
)


def _rows(household: str, member_label: str, days: int = 1) -> list[bytes]:
    return [
        row(
            household,
            "Std",
            f"2013-01-0{day + 1} {i // 2:02d}:{(i % 2) * 30:02d}:00.0000000",
            " 0.5 ",
        )
        for day in range(days)
        for i in range(4)
    ]


def _warehouse(directory: Path, name: str, households: list[str], members: int = 1):
    """A warehouse with the given households, loaded from ``members`` source files."""
    directory.mkdir(parents=True, exist_ok=True)
    database = directory / name
    for index in range(members):
        member = f"Small LCL Data/LCL-June2015v2_{index}.csv"
        archive = directory / f"{name}-{index}.zip"
        body = HEADER + b"".join(
            r for h in households for r in _rows(f"{h}{index}", member)
        )
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr(member, body)
        assert load_member(archive, member, database).complete
    return database


# ------------------------------------------------------------------ the rule
def test_the_default_database_is_the_main_sample(tmp_path):
    path = _warehouse(tmp_path, "energy.duckdb", ["MAC000001"])
    assert ds.role_of(path, all_demo=False, default=path) == ds.MAIN
    entry = ds.catalogue([path], default=path)[0]
    assert entry.label == "Main sample" and not entry.is_comparison


def test_demo_data_is_recognised_from_its_household_ids(tmp_path):
    path = _warehouse(tmp_path, "demo.duckdb", ["DEMO0001", "DEMO0002"])
    entry = ds.catalogue([path], default=None)[0]
    assert entry.role == ds.DEMO
    assert entry.label == "Synthetic demo — invented data"
    assert not entry.is_comparison
    assert "invented" in entry.note


def test_a_replayed_baseline_needs_a_baseline_record_to_earn_the_role(tmp_path):
    """The name alone is not evidence; a captured baseline with that id is."""
    baselines = tmp_path / "baselines"
    baselines.mkdir()
    path = _warehouse(tmp_path, "rec001-baseline-4b3ee235d7ac.duckdb", ["MAC000001"])

    unproven = ds.role_of(path, all_demo=False, baselines_dir=baselines)
    assert unproven == ds.UNCLASSIFIED, "no such baseline exists, so no role is claimed"

    (baselines / "4b3ee235d7ac@20260908T133513.json").write_text("{}")
    proven = ds.role_of(path, all_demo=False, baselines_dir=baselines)
    assert proven == ds.REC001_BASELINE
    entry = ds.catalogue([path], baselines_dir=baselines)[0]
    assert entry.label == "REC-001 replayed baseline" and entry.is_comparison


def test_the_expanded_sample_is_named_by_the_runbook_convention(tmp_path):
    path = _warehouse(tmp_path, "rec001-comparison-plus136.duckdb", ["MAC000001"])
    entry = ds.catalogue([path], default=None)[0]
    assert entry.role == ds.REC001_COMPARISON
    assert entry.label == "REC-001 expanded sample" and entry.is_comparison


@pytest.mark.parametrize("members", [3, 4])
def test_the_number_of_source_files_never_decides_a_role(tmp_path, members):
    """The anti-inference case: three members is not a baseline, four is not a comparison."""
    path = _warehouse(
        tmp_path / f"m{members}", "someones-warehouse.duckdb", ["MAC000001"], members
    )
    entry = ds.catalogue([path], default=None)[0]
    assert len(entry.members) == members
    assert entry.role == ds.UNCLASSIFIED
    assert entry.label == "someones-warehouse", "labelled by its file name, truthfully"
    assert not entry.is_comparison, "a file we do not understand is never hidden"


def test_the_detail_keeps_the_file_name_members_and_household_count(tmp_path):
    path = _warehouse(tmp_path, "energy.duckdb", ["MAC000001", "MAC000002"], members=2)
    entry = ds.catalogue([path], default=path)[0]
    assert "`energy.duckdb`" in entry.detail
    assert "2 source files" in entry.detail
    assert "4 households" in entry.detail  # two ids per member file


def test_ordinary_choices_come_first_and_comparisons_last(tmp_path):
    baselines = tmp_path / "b"
    baselines.mkdir()
    (baselines / "abc123@x.json").write_text("{}")
    main = _warehouse(tmp_path / "a", "energy.duckdb", ["MAC000001"])
    demo = _warehouse(tmp_path / "a", "demo.duckdb", ["DEMO0001"])
    base = _warehouse(tmp_path / "a", "rec001-baseline-abc123.duckdb", ["MAC000001"])
    comp = _warehouse(tmp_path / "a", "rec001-comparison-plus136.duckdb", ["MAC000001"])
    order = [
        e.role
        for e in ds.catalogue(
            [comp, base, demo, main], default=main, baselines_dir=baselines
        )
    ]
    assert order == [ds.MAIN, ds.DEMO, ds.REC001_BASELINE, ds.REC001_COMPARISON]


def test_a_repeated_label_is_settled_by_the_file_name(tmp_path):
    first = _warehouse(tmp_path / "a", "rec001-comparison-one.duckdb", ["MAC000001"])
    second = _warehouse(tmp_path / "a", "rec001-comparison-two.duckdb", ["MAC000001"])
    entries = ds.catalogue([first, second], default=None)
    labels = ds.display_labels(entries)
    assert labels[first] == "REC-001 expanded sample — rec001-comparison-one.duckdb"
    assert labels[second] == "REC-001 expanded sample — rec001-comparison-two.duckdb"
    # and a label that does not repeat stays concise
    only = ds.catalogue([first], default=None)
    assert ds.display_labels(only)[first] == "REC-001 expanded sample"


# ------------------------------------------------------------------ the picker
@pytest.fixture(scope="module")
def site(tmp_path_factory):
    """A working directory holding all four kinds of warehouse, and a baseline record."""
    area = Path(str(tmp_path_factory.mktemp("selector")))
    warehouse = area / "data" / "warehouse"
    _warehouse(warehouse, "energy.duckdb", ["MAC000001"])
    _warehouse(warehouse, "demo.duckdb", ["DEMO0001"])
    _warehouse(warehouse, "rec001-baseline-4b3ee235d7ac.duckdb", ["MAC000001"])
    _warehouse(warehouse, "rec001-comparison-plus136.duckdb", ["MAC000001"])
    for stray in warehouse.glob("*.zip"):
        stray.unlink()
    baselines = area / "data" / "baselines"
    baselines.mkdir(parents=True)
    (baselines / "4b3ee235d7ac@20260908T133513.json").write_text("{}")
    return area


@contextmanager
def _in(site: Path):
    previous = Path.cwd()
    os.chdir(site)
    try:
        yield
    finally:
        os.chdir(previous)


def _app():
    at = AppTest.from_file(str(APP), default_timeout=300)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_the_picker_offers_only_the_two_ordinary_choices(site):
    with _in(site):
        at = _app()
        assert at.radio(key="warehouse-file").options == [
            "Main sample",
            "Synthetic demo — invented data",
        ]
        assert at.checkbox(key="show-comparison-warehouses").value is False


def test_the_comparison_control_reveals_the_rec001_files_with_role_labels(site):
    with _in(site):
        at = _app()
        at.checkbox(key="show-comparison-warehouses").set_value(True).run()
        assert at.radio(key="warehouse-file").options == [
            "Main sample",
            "Synthetic demo — invented data",
            "REC-001 replayed baseline",
            "REC-001 expanded sample",
        ]


def test_the_selection_is_held_by_path_not_by_label(site):
    with _in(site):
        at = _app()
        at.checkbox(key="show-comparison-warehouses").set_value(True).run()
        comparison = Path("data/warehouse/rec001-comparison-plus136.duckdb")
        at.radio(key="warehouse-file").set_value(comparison).run()
        assert at.radio(key="warehouse-file").value == comparison
        assert at.session_state["warehouse-file"] == comparison, (
            "a path is what is stored, so a renamed label cannot move what is read"
        )
        detail = "\n".join(c.value for c in at.caption)
        assert "rec001-comparison-plus136.duckdb" in detail
        assert "REC-001 expanded sample" in detail


def test_hiding_a_selected_comparison_falls_back_and_says_so(site):
    with _in(site):
        at = _app()
        at.checkbox(key="show-comparison-warehouses").set_value(True).run()
        at.radio(key="warehouse-file").set_value(
            Path("data/warehouse/rec001-comparison-plus136.duckdb")
        ).run()
        at.checkbox(key="show-comparison-warehouses").set_value(False).run()

        assert at.radio(key="warehouse-file").value == Path(
            "data/warehouse/energy.duckdb"
        ), "the sidebar and the data shown agree on one file"
        notices = [
            i.value
            for i in at.info
            if "comparison warehouse" in i.value and "hidden" in i.value
        ]
        assert len(notices) == 1, [i.value for i in at.info]
        assert "rec001-comparison-plus136.duckdb" in notices[0]
        assert "Main sample" in notices[0]
        shown = "\n".join(c.value for c in at.caption)
        assert "energy.duckdb" in shown
        assert "rec001-comparison-plus136.duckdb" not in shown


def test_published_mode_hides_the_warehouse_controls_entirely(site):
    with _in(site):
        at = _app()
        at.radio(key="source-mode").set_value("Published version").run()
        assert not [r for r in at.radio if r.key == "warehouse-file"]
        assert not at.checkbox, "a control with no effect is worse than no control"
