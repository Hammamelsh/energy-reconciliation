"""The tariff tab shows the ANL-005 comparison for the selection on screen, and an
unavailable comparison leaves the dynamic-tariff figures untouched.

Driven headless through Streamlit's test harness on the committed demo archive with the
invented one-day schedule: DEMO0002 has 1.000 kWh Low and 1.125 kWh High, so its dynamic
charge is 0.7959 and its flat-price charge is 2.125 x 0.14228 = 0.302345.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

import duckdb
import pytest
from demo_fixture import DEMO_MEMBER, write

from energy_reconciliation.ingest.loader import load_member
from energy_reconciliation.tariff import schedule as sch
from energy_reconciliation.tariff.models import build_scenario

pytest.importorskip("streamlit.testing.v1", reason="Streamlit test harness unavailable")
from streamlit.testing.v1 import AppTest

APP = (
    Path(__file__).resolve().parent.parent / "src/energy_reconciliation/explorer/app.py"
)


@pytest.fixture
def site(tmp_path):
    area = tmp_path / "site"
    warehouse = area / "data" / "warehouse"
    warehouse.mkdir(parents=True)
    archive = write(tmp_path / "demo-lcl-sample.zip")
    db = warehouse / "demo.duckdb"
    assert load_member(archive, DEMO_MEMBER, db).complete
    build_scenario(db, sch.demo_schedule())
    return area


@contextmanager
def _in(site: Path):
    previous = Path.cwd()
    os.chdir(site)
    try:
        yield
    finally:
        os.chdir(previous)


def _sample_view(site: Path) -> AppTest:
    at = AppTest.from_file(str(APP), default_timeout=300)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    at.segmented_control(key="scenario-view").set_value("Loaded ToU sample").run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def _metrics(at: AppTest) -> dict[str, str]:
    return {m.label: m.value for m in at.metric}


def test_the_comparison_renders_for_the_loaded_sample(site):
    with _in(site):
        at = _sample_view(site)
        metrics = _metrics(at)
        assert metrics["Scenario energy charge"] == "£0.80"
        assert metrics["Dynamic energy charge"] == "£0.80"
        assert metrics["Flat-price energy charge"] == "£0.30"
        assert metrics["Flat minus dynamic"] == "-£0.49", "dynamic higher for the demo"
        assert metrics["As % of flat-price charge"] == "-163.2%"
        text = "\n".join(m.value for m in at.markdown)
        assert "0 household(s) are lower, 1 higher and 0 equal" in text
        captions = "\n".join(c.value for c in at.caption)
        assert "Positive means the dynamic scenario is lower" in captions
        assert "not a bill, a saving" in captions
        assert any("A2" in e.label for e in at.expander) or any(
            "provenance" in e.label for e in at.expander
        )


def test_an_unavailable_comparison_leaves_the_dynamic_figures_intact(site):
    with _in(site):
        con = duckdb.connect(str(site / "data/warehouse/demo.duckdb"))
        try:
            con.execute("DELETE FROM main.dim_tariff_price WHERE tariff_group = 'Std'")
        finally:
            con.close()
        at = _sample_view(site)
        metrics = _metrics(at)
        assert metrics["Scenario energy charge"] == "£0.80", (
            "dynamic figures unaffected"
        )
        assert "Flat-price energy charge" not in metrics
        notices = [
            i.value for i in at.info if "Flat-price comparison not available" in i.value
        ]
        assert len(notices) == 1 and "no_price" in notices[0]
