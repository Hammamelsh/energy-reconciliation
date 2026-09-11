"""The terrain (``energy-terrain-1``): reconciles with the comparison and the band summary,
keeps empty cells apart from recorded zeros, rounds once in Decimal, is deterministic,
is pinned by the manifest, carries nothing household-level, and refuses what does not
match.

Two synthetic publications: one whose single demo day is fully covered, one with two
charged readings (one of them zero) and 46 empty cells.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import stat
import zipfile
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest
from conftest import HEADER, row

from energy_reconciliation import candidate as cand
from energy_reconciliation import presentation as pres
from energy_reconciliation import publication
from energy_reconciliation import terrain as tr
from energy_reconciliation.ingest.loader import load_member
from energy_reconciliation.tariff import analytics as ta
from energy_reconciliation.tariff import flat_comparison as fc
from energy_reconciliation.tariff import reads

MEMBER = "Small LCL Data/LCL-June2015v2_0.csv"
REPO = Path(__file__).resolve().parent.parent

FULL_DAY = [
    row(
        "MAC000001",
        "ToU",
        f"2013-01-01 {i // 2:02d}:{(i % 2) * 30:02d}:00.0000000",
        " 1 ",
    )
    for i in range(48)
] + [
    row("MAC000002", "ToU", "2013-01-01 00:30:00.0000000", " 3 "),
    row("MAC000003", "ToU", "2013-01-01 01:00:00.0000000", " 2 "),
    row("MAC000009", "Std", "2013-01-01 00:30:00.0000000", " 7 "),
]
SPARSE_DAY = [
    row("MAC000002", "ToU", "2013-01-01 00:30:00.0000000", " 0 "),  # a recorded zero
    row("MAC000003", "ToU", "2013-01-01 01:00:00.0000000", " 2 "),
    row("MAC000009", "Std", "2013-01-01 01:00:00.0000000", " 7 "),  # excluded
]


def _publish(area: Path, rows: list[bytes]) -> reads.ReadContext:
    archive = area / "source.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(MEMBER, HEADER + b"".join(rows))
    database = area / "source.duckdb"
    assert load_member(archive, MEMBER, database).complete
    root = area / "pub"
    built = cand.build_candidate(database, root=root, schedule="demo")
    publication.publish(built.candidate, expected_previous=None, root=root)
    return reads.published(root)


def _writable(area: Path) -> None:
    for file in area.rglob("*"):
        if file.is_file():
            file.chmod(stat.S_IRUSR | stat.S_IWUSR)


@pytest.fixture(scope="module")
def full(tmp_path_factory):
    Path("data/proof-scratch").mkdir(parents=True, exist_ok=True)
    area = Path(str(tmp_path_factory.mktemp("terrain-full", numbered=True)))
    context = _publish(area, FULL_DAY)
    yield {"area": area, "context": context, "terrain": tr.build_terrain(context)}
    _writable(area)
    shutil.rmtree(area, ignore_errors=True)


@pytest.fixture(scope="module")
def sparse(tmp_path_factory):
    Path("data/proof-scratch").mkdir(parents=True, exist_ok=True)
    area = Path(str(tmp_path_factory.mktemp("terrain-sparse", numbered=True)))
    context = _publish(area, SPARSE_DAY)
    yield {"area": area, "context": context, "terrain": tr.build_terrain(context)}
    _writable(area)
    shutil.rmtree(area, ignore_errors=True)


def _exact_cells(
    ctx: reads.ReadContext,
) -> dict[int, tuple[int, int, Decimal, Decimal]]:
    """Independent evidence: the cell sums read straight from the fact table."""
    con = duckdb.connect(str(ctx.database), read_only=True)
    try:
        rows = con.execute(
            "SELECT CAST(EXTRACT(hour FROM observed_at_naive) AS INTEGER) * 2 "
            "+ CAST(EXTRACT(minute FROM observed_at_naive) AS INTEGER) // 30, "
            "COUNT(*), COUNT(DISTINCT household_id), SUM(consumption_kwh), "
            f"SUM(energy_charge_gbp) FROM {ctx.relations.fact_scenario} "
            "WHERE run_id = ? GROUP BY 1",
            [ctx.run_id],
        ).fetchall()
    finally:
        con.close()
    return {
        int(s): (int(n), int(h), Decimal(str(k)), Decimal(str(g)))
        for s, n, h, k, g in rows
    }


# ------------------------------------------------------------ reconciliation
def test_grid_totals_and_bands_reconcile_with_the_validated_relations(full):
    ctx, t = full["context"], full["terrain"]
    assert t["definition"] == "energy-terrain-1"
    assert t["grid"] == {
        **t["grid"],
        "dates": 1,
        "slots": 48,
        "cells": 48,
        "first_date": "2013-01-01",
        "last_date": "2013-01-01",
    }
    assert t["grid"]["date_labels"] == ["2013-01-01"]
    assert t["grid"]["slot_labels"][:3] == ["00:00", "00:30", "01:00"]
    assert len(t["cells"]["band"]) == 48 and set(t["cells"]["band"]) <= set("LNH")
    assert t["reconciliation"]["all_hold"] is True
    assert all(t["reconciliation"]["checks"].values())
    direct = fc.compare(ctx.database, ctx.run_id, relations=ctx.relations)
    assert isinstance(direct, fc.FlatComparison)
    assert t["totals"]["charged_readings"] == direct.totals.readings == 50
    assert t["totals"]["households"] == direct.totals.households == 3
    assert Decimal(t["totals"]["kwh"]["exact"]) == direct.totals.kwh
    assert Decimal(t["totals"]["charge"]["exact"]) == direct.totals.dynamic
    bands = {
        r["band_label"]: r
        for r in ta.band_summary(
            ctx.database, ctx.run_id, relations=ctx.relations
        ).to_dict(orient="records")
    }
    for b in t["by_band"]:
        ref = bands.get(b["band"])
        if ref is None:
            assert b["charged_readings"] == 0
            continue
        assert b["charged_readings"] == int(ref["readings"])
        assert b["kwh"]["exact"] == ref["kwh_exact"]
        assert b["charge"]["exact"] == ref["charge_gbp_exact"]
        assert Decimal(b["price_pence_per_kwh"]) == Decimal(
            str(ref["price_pence_per_kwh"])
        )
    assert sum(b["cells"] for b in t["by_band"]) == 48
    (month,) = t["by_month"]
    assert month["month"] == "2013-01" and month["cells"] == 48
    assert month["charged_readings"] == 50
    assert Decimal(month["charge"]["exact"]) == direct.totals.dynamic
    assert sum(
        Decimal(month["bands"][b]["charge"]["exact"]) for b in ("Low", "Normal", "High")
    ) == Decimal(month["charge"]["exact"])


def test_every_cell_is_the_exact_sum_rounded_once(full):
    ctx, t = full["context"], full["terrain"]
    exact = _exact_cells(ctx)
    c = t["cells"]
    assert len(exact) == 48 == t["coverage"]["cells_with_readings"]
    for s, (n, h, kwh, charge) in exact.items():
        assert c["readings"][s] == n and c["households"][s] == h
        assert Decimal(str(c["kwh"][s])) == ta.round_energy(kwh)
        assert Decimal(str(c["charge"][s])) == ta.round_money(charge)
    # the 00:30 cell pools two households: 1 + 3 kWh
    assert c["kwh"][1] == 4.0 and c["households"][1] == 2
    assert t["coverage"]["households_per_cell_max"] == 2
    assert t["coverage"]["households_per_cell_min"] == 1
    assert t["totals"]["kwh"]["exact"] == str(sum(v[2] for v in exact.values()))


def test_peaks_and_scale_come_from_the_exact_maxima(full):
    t = full["terrain"]
    c = t["cells"]
    assert t["scale"]["zero_based"] is True and t["scale"]["kwh"]["min"] == 0
    assert t["scale"]["kwh"]["max"] == max(v for v in c["kwh"] if v is not None)
    assert t["scale"]["charge"]["max"] == max(v for v in c["charge"] if v is not None)
    pk = t["peaks"]["kwh"]
    assert (
        pk["date"] == "2013-01-01" and pk["slot"] == 1 and pk["slot_label"] == "00:30"
    )
    assert pk["kwh"]["display"] == 4.0 and pk["households"] == 2
    pc = t["peaks"]["charge"]
    assert pc["slot"] == c["charge"].index(t["scale"]["charge"]["max"])
    assert pc["band"] in ("Low", "Normal", "High")


# ------------------------------------------------------- empty versus zero
def test_empty_cells_are_null_and_a_recorded_zero_is_zero(sparse):
    ctx, t = sparse["context"], sparse["terrain"]
    c = t["cells"]
    assert t["coverage"]["cells_with_readings"] == 2
    assert t["coverage"]["cells_without_readings"] == 46
    assert c["kwh"].count(None) == 46 and c["charge"].count(None) == 46
    assert c["readings"].count(0) == 46 and c["households"].count(0) == 46
    # 00:30 holds one reading of exactly 0: a cell, not a gap
    assert c["readings"][1] == 1 and c["kwh"][1] == 0.0 and c["charge"][1] == 0.0
    assert c["kwh"][2] == 2.0 and c["readings"][2] == 1
    assert len(c["band"]) == 48, "the schedule still gives every empty cell a band"
    assert t["totals"]["charged_readings"] == 2
    direct = fc.compare(ctx.database, ctx.run_id, relations=ctx.relations)
    assert Decimal(t["totals"]["charge"]["exact"]) == direct.totals.dynamic
    (month,) = t["by_month"]
    assert month["cells_with_readings"] == 2 and month["households_min"] == 1
    assert t["reconciliation"]["all_hold"] is True


# ------------------------------------------------- determinism and pinning
def test_generation_is_byte_deterministic(full):
    again = tr.build_terrain(full["context"])
    assert pres.canonical_bytes(again) == pres.canonical_bytes(full["terrain"])


def _written(built, name: str) -> Path:
    ctx, t = built["context"], built["terrain"]
    payload = pres.build_payload(ctx, terrain=t, with_zero_days=False)
    out = built["area"] / name
    pres.write_bundle(payload, out, t)
    return out


def test_the_bundle_summarises_the_terrain_and_the_manifest_pins_its_file(full):
    ctx, t = full["context"], full["terrain"]
    payload = pres.build_payload(ctx, terrain=t, with_zero_days=False)
    assert payload["definition"] == "presentation-bundle-2"
    s = payload["terrain"]
    assert s["file"] == "terrain.json" and s["definition"] == "energy-terrain-1"
    assert s["totals"] == t["totals"] and s["grid"]["cells"] == 48
    assert "cells" not in s or not isinstance(s.get("cells"), dict), (
        "no arrays in the bundle"
    )
    out = _written(full, "written")
    manifest = json.loads((out / pres.MANIFEST_NAME).read_text())
    body = (out / pres.TERRAIN_NAME).read_bytes()
    assert manifest["terrain"] == {
        "file": "terrain.json",
        "definition": "energy-terrain-1",
        "content_digest": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }
    assert pres.load_bundle(out)["terrain"]["file"] == "terrain.json"
    assert pres.load_terrain(out)["totals"] == t["totals"]
    # the same context must produce the same bundle bytes whether or not the terrain is
    # passed in: building it inside build_payload is not a second path
    assert pres.canonical_bytes(
        pres.build_payload(ctx, with_zero_days=False)
    ) == pres.canonical_bytes(payload)


def test_a_terrain_from_another_run_or_definition_is_refused_at_write(full):
    ctx, t = full["context"], full["terrain"]
    payload = pres.build_payload(ctx, terrain=t, with_zero_days=False)
    other = json.loads(json.dumps(t))
    other["source"]["run_id"] = "dbtcand-000000000000@20200101T000000000000"
    with pytest.raises(pres.BundleError, match="different runs"):
        pres.write_bundle(payload, full["area"] / "wrong-run", other)
    with pytest.raises(pres.BundleError, match="not this context"):
        pres.build_payload(ctx, terrain=other, with_zero_days=False)
    foreign = json.loads(json.dumps(t))
    foreign["definition"] = "energy-terrain-0"
    with pytest.raises(pres.BundleError, match="differ"):
        pres.write_bundle(payload, full["area"] / "wrong-def", foreign)


def _copy(built, name: str) -> Path:
    src = built["area"] / "written"
    if not src.exists():
        _written(built, "written")
    target = built["area"] / name
    shutil.copytree(src, target)
    return target


def test_a_missing_terrain_file_is_an_explicit_absence(full):
    where = _copy(full, "missing")
    (where / pres.TERRAIN_NAME).unlink()
    with pytest.raises(pres.BundleError, match="missing"):
        pres.load_terrain(where)
    assert pres.load_bundle(where), "the bundle itself still verifies"


def test_a_manifest_without_a_terrain_pin_is_refused(full):
    where = _copy(full, "unpinned")
    m = json.loads((where / pres.MANIFEST_NAME).read_text())
    del m["terrain"]
    (where / pres.MANIFEST_NAME).write_text(json.dumps(m))
    with pytest.raises(pres.BundleError, match="pins no terrain"):
        pres.load_terrain(where)


def test_a_changed_byte_is_refused(full):
    where = _copy(full, "corrupt")
    path = where / pres.TERRAIN_NAME
    body = path.read_bytes()
    assert b'"zero_based":true' in body
    # same length, one byte different: the size check passes and the digest refuses
    path.write_bytes(body.replace(b'"zero_based":true', b'"zero_based":trUe', 1))
    with pytest.raises(pres.BundleError, match="changed after it was written"):
        pres.load_terrain(where)
    # a shorter file is refused by size before any hash is computed
    path.write_bytes(body[:-1])
    with pytest.raises(pres.BundleError, match="size differs"):
        pres.load_terrain(where)


def test_malformed_terrain_json_is_refused_not_parsed_leniently(full):
    where = _copy(full, "malformed")
    path = where / pres.TERRAIN_NAME
    path.write_bytes(b"{not json")
    m = json.loads((where / pres.MANIFEST_NAME).read_text())
    m["terrain"]["size_bytes"] = 9
    m["terrain"]["content_digest"] = hashlib.sha256(b"{not json").hexdigest()
    (where / pres.MANIFEST_NAME).write_text(json.dumps(m))
    with pytest.raises(pres.BundleError, match="not JSON"):
        pres.load_terrain(where)


def test_another_definition_or_run_in_the_manifest_is_refused(full):
    where = _copy(full, "other-def")
    m = json.loads((where / pres.MANIFEST_NAME).read_text())
    m["terrain"]["definition"] = "energy-terrain-0"
    (where / pres.MANIFEST_NAME).write_text(json.dumps(m))
    with pytest.raises(pres.BundleError, match="definition"):
        pres.load_terrain(where)
    where2 = _copy(full, "other-run")
    m = json.loads((where2 / pres.MANIFEST_NAME).read_text())
    m["source"]["run_id"] = "dbtcand-ffffffffffff@20200101T000000000000"
    (where2 / pres.MANIFEST_NAME).write_text(json.dumps(m))
    with pytest.raises(pres.BundleError, match="different runs"):
        pres.load_terrain(where2)


# ------------------------------------------------------------------ refusals
def test_a_terrain_that_does_not_reconcile_is_never_returned(full, monkeypatch):
    ctx = full["context"]
    real = fc.compare(ctx.database, ctx.run_id, relations=ctx.relations)
    assert isinstance(real, fc.FlatComparison)
    wrong = fc.Totals(
        households=real.totals.households,
        readings=real.totals.readings + 1,
        kwh=real.totals.kwh,
        dynamic=real.totals.dynamic,
        flat=real.totals.flat,
    )
    monkeypatch.setattr(fc, "compare", lambda *a, **k: replace(real, totals=wrong))
    with pytest.raises(
        tr.TerrainError,
        match="does not reconcile with the comparison: charged_readings",
    ):
        tr.build_terrain(ctx)


def test_an_unavailable_comparison_is_a_refusal(full, monkeypatch):
    monkeypatch.setattr(
        fc, "compare", lambda *a, **k: fc.Unavailable("no-price", "no flat price row")
    )
    with pytest.raises(tr.TerrainError, match="unavailable"):
        tr.build_terrain(full["context"])


def test_a_band_disagreement_between_facts_and_schedule_is_a_refusal(full, monkeypatch):
    real = tr._schedule_cells

    def flipped(context):
        bands, off = real(context)
        key = next(iter(bands))
        bands[key] = "High" if bands[key] != "High" else "Low"
        return bands, off

    monkeypatch.setattr(tr, "_schedule_cells", flipped)
    with pytest.raises(tr.TerrainError, match="schedule says"):
        tr.build_terrain(full["context"])


# ------------------------------------------------------------ content rules
def _walk(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(obj, list):
        if obj and not isinstance(obj[0], (dict, list)):
            yield path, obj
            return
        for i, v in enumerate(obj):
            yield from _walk(v, f"{path}[{i}]")
    else:
        yield path, obj


def _assert_content_rules(t: dict) -> None:
    text = json.dumps(t)
    assert "MAC0" not in text, "no household id may appear"
    assert not re.search(r"\d{2}:\d{2}:\d{2}", text), "no time of day beyond labels"
    assert "/home/" not in text and "hammam" not in text.lower()
    assert "NaN" not in text and "Infinity" not in text
    for path, value in _walk(t):
        assert "timestamp" not in path.lower(), path
        if isinstance(value, list) and path.startswith(".cells"):
            assert len(value) == t["grid"]["cells"], path
    assert set(t["cells"]) == {
        "band",
        "band_codes",
        "readings",
        "households",
        "kwh",
        "charge",
    }
    for key in ("readings", "households", "kwh", "charge"):
        assert len(t["cells"][key]) == t["grid"]["cells"], key
    assert len(t["cells"]["band"]) == t["grid"]["cells"]


def test_the_terrain_carries_no_household_or_row_level_data(full, sparse):
    _assert_content_rules(full["terrain"])
    _assert_content_rules(sparse["terrain"])


def test_the_committed_terrain_verifies_and_reconciles_with_the_committed_bundle():
    where = REPO / "web" / "public" / "data"
    if not (where / pres.TERRAIN_NAME).exists():
        pytest.skip("no committed terrain yet")
    bundle = pres.load_bundle(where)
    t = pres.load_terrain(where)
    _assert_content_rules(t)
    c = bundle["comparison"]
    assert t["grid"]["cells"] == t["grid"]["dates"] * 48
    assert t["totals"]["charged_readings"] == c["charged_readings"]
    assert t["totals"]["households"] == c["households"]
    assert t["totals"]["kwh"]["exact"] == c["kwh"]["exact"]
    assert t["totals"]["charge"]["exact"] == c["dynamic_charge"]["exact"]
    assert bundle["terrain"]["totals"] == t["totals"]
    assert bundle["terrain"]["file"] == pres.TERRAIN_NAME
    by_band = {b["band"]: b for b in bundle["bands"]}
    for b in t["by_band"]:
        assert b["kwh"]["exact"] == by_band[b["band"]]["kwh"]["exact"]
        assert b["charge"]["exact"] == by_band[b["band"]]["charge"]["exact"]
    assert sum(m["charged_readings"] for m in t["by_month"]) == c["charged_readings"]
    assert sum(t["cells"]["readings"]) == c["charged_readings"]
    size = (where / pres.TERRAIN_NAME).stat().st_size
    assert size < 600_000, f"the terrain file is {size:,} bytes; it should stay small"
