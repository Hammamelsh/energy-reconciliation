"""The presentation bundle: reconciles with the validated relations, is deterministic,
refuses stale or corrupted bundles, and carries no row-level data.

One dbt build for the module, promoted into a publication root; every test reads the
bundle built from that context. The committed bundle under ``web/public/data`` is checked
by the same content rules so a regenerated bundle cannot quietly start shipping something
it must not.
"""

from __future__ import annotations

import json
import re
import shutil
import stat
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest
from conftest import HEADER, row

from energy_reconciliation import candidate as cand
from energy_reconciliation import presentation as pres
from energy_reconciliation import publication
from energy_reconciliation.ingest.loader import load_member
from energy_reconciliation.tariff import analytics as ta
from energy_reconciliation.tariff import flat_comparison as fc
from energy_reconciliation.tariff import reads

SCRATCH_ROOT = Path("data/proof-scratch")
MEMBER = "Small LCL Data/LCL-June2015v2_0.csv"
REPO = Path(__file__).resolve().parent.parent

#: Every key a per-household entry may carry. Anything else is a leak until reviewed.
HOUSEHOLD_KEYS = {
    "household_id",
    "charged_readings",
    "schedule_slots",
    "coverage",
    "first_charged_date",
    "last_charged_date",
    "kwh",
    "dynamic_charge",
    "flat_charge",
    "flat_minus_dynamic",
    "pct_of_flat",
    "breakeven_flat_price",
    "outcome_under_dynamic",
    "bands",
}
TIME_OF_DAY = re.compile(r"\d{2}:\d{2}:\d{2}")
DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _warehouse(work: Path) -> Path:
    archive = work / "source.zip"
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
            row("MAC000002", "ToU", "2013-01-01 00:30:00.0000000", " 3 "),  # Low only
            row("MAC000003", "ToU", "2013-01-01 01:00:00.0000000", " 2 "),  # High only
            row("MAC000009", "Std", "2013-01-01 00:30:00.0000000", " 7 "),  # excluded
            row("MAC000009", "Std", "2013-01-01 00:30:00.0000000", " 7 "),  # duplicate
        ]
    )
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(MEMBER, body)
    database = work / "source.duckdb"
    assert load_member(archive, MEMBER, database).complete
    return database


def _writable(area: Path) -> None:
    for file in area.rglob("*"):
        if file.is_file():
            file.chmod(stat.S_IRUSR | stat.S_IWUSR)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
    area = Path(str(tmp_path_factory.mktemp("presentation", numbered=True)))
    source = _warehouse(area)
    root = area / "pub"
    candidate = cand.build_candidate(source, root=root, schedule="demo")
    publication.publish(candidate.candidate, expected_previous=None, root=root)
    context = reads.published(root)
    payload = pres.build_payload(context)
    out = area / "bundle"
    manifest = pres.write_bundle(payload, out)
    yield {
        "area": area,
        "context": context,
        "payload": payload,
        "dir": out,
        "manifest": manifest,
    }
    _writable(area)
    shutil.rmtree(area, ignore_errors=True)


# ------------------------------------------------------------ reconciliation
def test_totals_and_households_reconcile_with_the_validated_relations(built):
    ctx, payload = built["context"], built["payload"]
    direct = fc.compare(ctx.database, ctx.run_id, relations=ctx.relations)
    assert isinstance(direct, fc.FlatComparison)
    c = payload["comparison"]
    assert c["dynamic_charge"]["exact"] == str(direct.totals.dynamic)
    assert c["flat_charge"]["exact"] == str(direct.totals.flat)
    assert c["flat_minus_dynamic"]["exact"] == str(direct.totals.difference)
    assert c["kwh"]["exact"] == str(direct.totals.kwh)
    assert c["charged_readings"] == direct.totals.readings
    assert c["outcomes_under_dynamic"] == direct.outcomes
    assert c["dynamic_charge"]["unit"] == "GBP" and c["kwh"]["unit"] == "kWh"
    by_id = {h["household_id"]: h for h in c["per_household"]}
    assert set(by_id) == {r["household_id"] for r in direct.households}
    for r in direct.households:
        h = by_id[r["household_id"]]
        assert h["dynamic_charge"]["exact"] == r["dynamic_charge_gbp_exact"]
        assert h["flat_charge"]["exact"] == r["flat_charge_gbp_exact"]
        assert h["flat_minus_dynamic"]["exact"] == r["difference_exact"]
        assert h["outcome_under_dynamic"] == r["outcome_under_dynamic"]
        assert h["charged_readings"] == r["charged_readings"]
    # the dynamic total is the scenario total the tariff tab shows
    assert c["dynamic_charge"]["exact"] == ta.total_charge_exact(
        ctx.database, ctx.run_id, relations=ctx.relations
    )


def test_bands_accounting_and_prices_reconcile(built):
    ctx, payload = built["context"], built["payload"]
    bands = ta.band_summary(ctx.database, ctx.run_id, relations=ctx.relations)
    got = {b["band"]: b for b in payload["bands"]}
    for r in bands.to_dict(orient="records"):
        assert got[r["band_label"]]["charge"]["exact"] == r["charge_gbp_exact"]
        assert got[r["band_label"]]["kwh"]["exact"] == r["kwh_exact"]
        assert got[r["band_label"]]["charged_readings"] == int(r["readings"])
    ladder = ctx.accounting()
    a = payload["accounting"]
    assert (
        a["raw_rows"],
        a["distinct_readings"],
        a["charged_readings"],
        a["excluded_readings"],
    ) == (
        ladder.raw_rows,
        ladder.distinct_readings,
        ladder.included_readings,
        ladder.excluded_readings,
    )
    assert a["reconciles"] is True and a["counted_not_recorded"] is True
    assert a["raw_rows"] == 52 and a["rows_collapsed_by_policy"] == 1
    prices = {(p["tariff_group"], p["band"]): p for p in payload["prices"]}
    assert Decimal(prices[("Std", "flat")]["pence_per_kwh"]) == Decimal("14.228")
    assert prices[("Std", "flat")]["valid_from"] == "UNKNOWN"
    assert prices[("ToU", "High")]["valid_from"] == "2013-01-01"
    assert prices[("ToU", "High")]["valid_until_exclusive"] == "2014-01-01"


def test_display_values_are_rounded_once_in_decimal_not_recomputed(built):
    c = built["payload"]["comparison"]
    for key in ("dynamic_charge", "flat_charge", "flat_minus_dynamic"):
        exact = Decimal(c[key]["exact"])
        assert Decimal(str(c[key]["display"])) == ta.round_money(exact)
    assert Decimal(str(c["kwh"]["display"])) == ta.round_energy(
        Decimal(c["kwh"]["exact"])
    )
    pct = c["pct_of_flat"]
    assert pct["denominator"] == "flat_charge"
    assert Decimal(str(pct["display"])) == Decimal(pct["exact"]).quantize(
        Decimal("0.1")
    )


def test_breakeven_prices_are_exact_ratios(built):
    c = built["payload"]["comparison"]
    pooled = Decimal(c["dynamic_charge"]["exact"]) / Decimal(c["kwh"]["exact"]) * 100
    assert Decimal(c["breakeven_flat_price"]["exact"]) == pooled
    for h in c["per_household"]:
        expected = (
            Decimal(h["dynamic_charge"]["exact"]) / Decimal(h["kwh"]["exact"]) * 100
        )
        assert Decimal(h["breakeven_flat_price"]["exact"]) == expected
        # the break-even price and the flat price agree with the outcome: above it, lower
        flat = Decimal(c["flat_price"]["pence_per_kwh"])
        expected_outcome = (
            "lower" if expected < flat else "higher" if expected > flat else "equal"
        )
        assert h["outcome_under_dynamic"] == expected_outcome
    # the demo fixture: Low-only household breaks even at 3.99p, High-only at 67.20p
    by_id = {h["household_id"]: h for h in c["per_household"]}
    assert Decimal(by_id["MAC000002"]["breakeven_flat_price"]["exact"]) == Decimal(
        "3.99"
    )
    assert Decimal(by_id["MAC000003"]["breakeven_flat_price"]["exact"]) == Decimal(
        "67.20"
    )


# --------------------------------------------------------------- determinism
def test_generation_is_byte_deterministic(built):
    ctx = built["context"]
    again = pres.build_payload(ctx)
    assert pres.canonical_bytes(again) == pres.canonical_bytes(built["payload"])
    other = built["area"] / "bundle-again"
    manifest = pres.write_bundle(again, other)
    assert manifest["content_digest"] == built["manifest"]["content_digest"]
    assert (other / pres.BUNDLE_NAME).read_bytes() == (
        built["dir"] / pres.BUNDLE_NAME
    ).read_bytes()


def test_the_bundle_carries_no_timestamp_of_its_own(built):
    text = (built["dir"] / pres.BUNDLE_NAME).read_text()
    assert "generated" not in text and "exported_at" not in text


# ------------------------------------------------------------------ refusals
def _copy(built, name: str) -> Path:
    target = built["area"] / name
    shutil.copytree(built["dir"], target)
    return target


def test_a_corrupted_bundle_is_refused(built):
    where = _copy(built, "corrupt")
    path = where / pres.BUNDLE_NAME
    path.write_bytes(path.read_bytes().replace(b'"display":', b'"display" :', 1))
    with pytest.raises(pres.BundleError, match="changed after it was written"):
        pres.load_bundle(where)


def test_a_stale_bundle_is_refused_by_run_id(built):
    with pytest.raises(pres.BundleError, match="stale"):
        pres.load_bundle(
            built["dir"], expected_run_id="dbtcand-000000000000@20200101T000000000000"
        )
    assert pres.load_bundle(built["dir"], expected_run_id=built["context"].run_id)


def test_a_manifest_with_another_definition_or_run_is_refused(built):
    where = _copy(built, "other-def")
    m = json.loads((where / pres.MANIFEST_NAME).read_text())
    m["definition"] = "presentation-bundle-0"
    (where / pres.MANIFEST_NAME).write_text(json.dumps(m))
    with pytest.raises(pres.BundleError, match="definition"):
        pres.load_bundle(where)
    where2 = _copy(built, "other-run")
    m = json.loads((where2 / pres.MANIFEST_NAME).read_text())
    m["source"]["run_id"] = "dbtcand-ffffffffffff@20200101T000000000000"
    (where2 / pres.MANIFEST_NAME).write_text(json.dumps(m))
    with pytest.raises(pres.BundleError, match="different runs"):
        pres.load_bundle(where2)


def test_a_missing_bundle_is_an_explicit_absence(tmp_path):
    with pytest.raises(pres.BundleError, match="no bundle"):
        pres.load_bundle(tmp_path)


def test_a_forecast_report_about_other_data_is_omitted_not_copied(built):
    ctx = built["context"]
    unknown = pres.build_payload(
        ctx, forecast_report={"kind": "something-else"}, with_zero_days=False
    )
    assert unknown["forecast"]["status"] == "omitted"
    none = pres.build_payload(ctx, forecast_report=None, with_zero_days=False)
    assert none["forecast"] == {
        "status": "omitted",
        "reason": "no forecast report was supplied",
    }


# ------------------------------------------------------------ content rules
def _walk(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk(v, f"{path}[{i}]")
    else:
        yield path, obj


def _assert_content_rules(payload: dict) -> None:
    for path, value in _walk(payload):
        if isinstance(value, str):
            assert "/home/" not in value and "hammam" not in value.lower(), path
            assert not re.search(
                r"(?i)(password|secret|token=|bearer |api[_-]?key)", value
            ), path
            if TIME_OF_DAY.search(value):
                assert path.endswith(".promoted_at_utc"), (
                    f"a time of day outside the build record: {path}"
                )
        assert "timestamp" not in path.lower() or path.endswith("hour_meaning"), path
    for h in payload["comparison"]["per_household"]:
        assert set(h) == HOUSEHOLD_KEYS, set(h) ^ HOUSEHOLD_KEYS
        assert DATE_ONLY.match(h["first_charged_date"]) and DATE_ONLY.match(
            h["last_charged_date"]
        )
        for band in h["bands"]:
            assert set(band) <= {
                "band",
                "price_pence_per_kwh",
                "charged_readings",
                "kwh",
                "charge",
                "consumption_share_pct",
                "charge_share_pct",
            }
    assert "readings" not in payload or not isinstance(payload.get("readings"), list)
    assert "per_reading" not in json.dumps(payload)


def test_the_bundle_contains_no_row_level_data_paths_or_credentials(built):
    _assert_content_rules(built["payload"])
    text = (built["dir"] / pres.BUNDLE_NAME).read_text()
    # the source rows carried 48 timestamps for one household; none may appear
    assert not re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{7}", text)
    assert "NaN" not in text and "Infinity" not in text, "not JSON a browser can parse"


def test_the_committed_public_bundle_obeys_the_same_rules_and_its_manifest():
    where = REPO / "web" / "public" / "data"
    if not (where / pres.BUNDLE_NAME).exists():
        pytest.skip("no committed bundle yet")
    payload = pres.load_bundle(where)
    _assert_content_rules(payload)
    assert payload["comparison"]["households"] == len(
        payload["comparison"]["per_household"]
    )
    assert payload["source"]["publication"]["required_build"] == "complete"
    assert payload["source"]["attribution"]["licence_url"].startswith(
        "https://creativecommons.org/"
    )
    size = (where / pres.BUNDLE_NAME).stat().st_size
    assert size < 400_000, f"the public bundle is {size:,} bytes; it should stay small"
