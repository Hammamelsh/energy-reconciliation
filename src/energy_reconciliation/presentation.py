"""The presentation bundle: the smallest public summary of a validated publication.

What it is for
--------------

The React front door shows the finished findings -- the pooled comparison, every household's
outcome and coverage, the band summaries, the accounting ladder, the data-quality and
forecast summaries -- without shipping the 210 MB version file or any row-level reading. This
module produces that summary **from a validated read context only** (a publication or a
serving snapshot that passed every gate), so a figure on the page can be traced to the sealed
build it came from.

The contract (``presentation-bundle-2``)
----------------------------------------

Version 2 adds one section, ``terrain``: a summary of the year-of-half-hours terrain
(:mod:`energy_reconciliation.terrain`, contract ``energy-terrain-1``) and the name of the
file that carries its cells. That file is written beside the bundle and pinned by the
manifest under ``terrain`` (digest, size, definition), so the browser verifies it the same
way before drawing a cell. Nothing else changed between versions 1 and 2: every earlier key
is produced by the same code from the same relations.

- **Exact values are strings with units.** Money is the unrounded decimal the fact stores,
  energy likewise; each carries ``unit``. A ``display`` value rounded once here (money to
  2 dp, energy to 3 dp, percentages to 1 dp, half up, in ``Decimal``) sits beside it, so the
  browser never performs the tariff arithmetic or the rounding in binary floating point.
- **Deterministic bytes.** The bundle carries no export timestamp; the same publication,
  profile and report produce byte-identical output. ``manifest.json`` pins the bundle's
  sha256, size and the source publication's identity, and :func:`load_bundle` refuses a
  bundle whose bytes, definition or source do not match.
- **No row-level data.** Per household: counts, dates (not timestamps), exact totals and band
  shares. No reading, no per-reading timestamp, no machine path, no credential. The tests
  scan for all of those.
- **Only what applies.** The forecast summary is embedded only when the report's dataset
  digest matches the publication's rows (``forecast.applicability``); otherwise the section
  says it was omitted and why. Nothing is copied from a report about other data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Final

from . import publication
from . import terrain as tr
from .forecast import applicability
from .forecast.dataset import daily_records
from .quality import zero_days as zd
from .tariff import analytics as ta
from .tariff import flat_comparison as fc
from .tariff import reads
from .tariff.models import ASSUMPTION_TEXT

DEFINITION: Final[str] = "presentation-bundle-2"
BUNDLE_NAME: Final[str] = "bundle.json"
MANIFEST_NAME: Final[str] = "manifest.json"
TERRAIN_NAME: Final[str] = tr.TERRAIN_NAME

ATTRIBUTION: Final[dict[str, str]] = {
    "dataset": "SmartMeter Energy Consumption Data in London Households",
    "publisher": "UK Power Networks, via the London Datastore",
    "dataset_url": (
        "https://data.london.gov.uk/dataset/"
        "smartmeter-energy-consumption-data-in-london-households-vqm0d"
    ),
    "licence": "Creative Commons Attribution 4.0 International (CC BY 4.0)",
    "licence_url": "https://creativecommons.org/licenses/by/4.0/",
    "accessed": "2026-09-06",
    "notice": (
        "Contains data from SmartMeter Energy Consumption Data in London Households, "
        "published by UK Power Networks via the London Datastore under CC BY 4.0."
    ),
}

LIMITATIONS: Final[tuple[str, ...]] = (
    "A historical scenario for 2013, not a bill: no standing charge, levy or tax is modelled.",
    (
        "The flat price's effective period is not documented; assumption A2 applies it to "
        "the whole year."
    ),
    (
        "Consumption is held fixed. Households on a dynamic tariff may have used "
        "electricity differently on a flat one, so the difference is not a saving anyone "
        "made."
    ),
    "27 households from one source file of 168: not a sample of the trial, not London.",
    (
        "Whether a reading's timestamp and a schedule label denote the same half hour (A1) "
        "is assumed, not established; the timezone and interval convention are unknown."
    ),
    (
        "No behavioural response is measured, and no clock time is shown to be cheaper: "
        "the schedule changed daily."
    ),
    "Coverage varies by household; figures are never scaled to a full year.",
)


class BundleError(RuntimeError):
    """The bundle cannot be produced or trusted. Never a fallback."""


# --------------------------------------------------------------------- values
def _money(value: Decimal | str) -> dict[str, Any]:
    d = Decimal(str(value))
    return {"exact": str(d), "unit": "GBP", "display": float(ta.round_money(d))}


def _energy(value: Decimal | str) -> dict[str, Any]:
    d = Decimal(str(value))
    return {"exact": str(d), "unit": "kWh", "display": float(ta.round_energy(d))}


def _pct(value: Decimal | str | None, denominator: str) -> dict[str, Any]:
    if value is None:
        return {
            "exact": None,
            "unit": "percent",
            "denominator": denominator,
            "display": None,
        }
    d = Decimal(str(value))
    return {
        "exact": str(d),
        "unit": "percent",
        "denominator": denominator,
        "display": float(d.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)),
    }


def _pence_per_kwh(charge: Decimal | str, kwh: Decimal | str) -> dict[str, Any]:
    """The flat price at which this consumption would cost the same as it did under the
    dynamic schedule: charge / kWh, in pence, exact. None when nothing was consumed."""
    c, k = Decimal(str(charge)), Decimal(str(kwh))
    if k == 0:
        return {"exact": None, "unit": "pence per kWh", "display": None}
    d = c / k * 100
    return {
        "exact": str(d),
        "unit": "pence per kWh",
        "display": float(d.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)),
    }


def _hour_band_ribbons(context: reads.ReadContext) -> dict[str, Any]:
    """Aggregates only: the schedule's slots by hour and band, and the sample's charged kWh
    by hour and band. No household appears; the hour is the source label's hour as written."""
    sched = ta.schedule_band_distribution(context.database, relations=context.relations)
    slots: dict[str, list[int]] = {}
    for r in sched.to_dict(orient="records"):
        slots.setdefault(r["band_label"], [0] * 24)[int(r["source_hour"])] += int(
            r["slots"]
        )
    sample = ta.household_band_distribution(
        context.database, context.run_id, relations=context.relations
    )
    kwh: dict[str, list[dict[str, Any]]] = {}
    for r in sample.to_dict(orient="records"):
        kwh.setdefault(r["band_label"], [None] * 24)[int(r["source_hour"])] = {
            "charged_readings": int(r["readings"]),
            "kwh": _energy(str(r["kwh"])),
        }
    return {
        "hour_meaning": (
            "the hour of the timestamp label as written in the source; no timezone applied"
        ),
        "schedule_slots_by_band_and_hour": {b: v for b, v in sorted(slots.items())},
        "charged_kwh_by_band_and_hour": {b: v for b, v in sorted(kwh.items())},
        "caveat": (
            "Consumption and an expensive band falling in the same hours is a coincidence "
            "of timing in this data, not evidence of a response to price."
        ),
    }


def _share(value: Any) -> float:
    """A share in [0, 1] from the analytics frame, shown to one decimal of a percent."""
    return float(
        (Decimal(str(value)) * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    )


def _bands(frame) -> list[dict[str, Any]]:
    out = []
    for r in frame.to_dict(orient="records"):
        out.append(
            {
                "band": r["band_label"],
                "price_pence_per_kwh": str(Decimal(str(r["price_pence_per_kwh"]))),
                "charged_readings": int(r["readings"]),
                "kwh": _energy(r["kwh_exact"]),
                "charge": _money(r["charge_gbp_exact"]),
                "consumption_share_pct": _share(r["consumption_share"]),
                "charge_share_pct": _share(r["charge_share"]),
            }
        )
    return out


# ------------------------------------------------------------------- sections
def _source(context: reads.ReadContext) -> dict[str, Any]:
    i = context.identity
    if i is None:
        raise BundleError(
            "a presentation bundle needs a validated dbt build (a publication)"
        )
    con = ta._con(context.database)
    try:
        groups = dict(
            con.execute(
                f"SELECT tariff_group, COUNT(DISTINCT household_id) FROM "
                f"{context.relations.readings} GROUP BY 1 ORDER BY 1"
            ).fetchall()
        )
        members = [
            m
            for (m,) in con.execute(
                f"SELECT member_name FROM {context.relations.load_registry} "
                "WHERE status = 'published' ORDER BY 1"
            ).fetchall()
        ]
        rows = con.execute(
            f"SELECT COUNT(*) FROM {context.relations.readings}"
        ).fetchone()[0]
        span = con.execute(
            "SELECT CAST(MIN(observed_at_naive) AS DATE), CAST(MAX(observed_at_naive) AS DATE) "
            f"FROM {context.relations.readings}"
        ).fetchone()
    finally:
        con.close()
    return {
        "publication": {
            "role": context.role,
            "version": context.version,
            "version_file": context.version_file,
            "promoted_at_utc": context.promoted_at_utc,
            "run_id": context.run_id,
            "file_sha256": i.file_sha256,
            "built_output_sha256": i.built_output_sha256,
            "output_digest_version": i.output_digest_version,
            "required_build": i.required_build,
            "required_nodes_total": i.required_nodes_total,
            "dbt_core_version": i.dbt_core_version,
            "dbt_duckdb_version": i.dbt_duckdb_version,
            "tariff_group": i.tariff_group,
            "schedule_variant": i.schedule_variant,
            "schedule_source": i.schedule_source,
            "schedule_sha256": i.schedule_sha256,
            "price_catalogue_version": i.price_catalogue_version,
            "calculation_code_sha256": i.calculation_code_sha256,
            "runtime_fingerprint": i.runtime_fingerprint,
            "route": context.relations.label,
        },
        "warehouse": {
            "source_files": [m.split("/")[-1] for m in members],
            "source_files_in_dataset": 168,
            "readings_loaded": int(rows),
            "households": int(sum(groups.values())),
            "households_by_group": {k: int(v) for k, v in groups.items()},
            "first_date": str(span[0]),
            "last_date": str(span[1]),
        },
        "attribution": dict(ATTRIBUTION),
    }


def _comparison(context: reads.ReadContext) -> dict[str, Any]:
    result = fc.compare(context.database, context.run_id, relations=context.relations)
    if isinstance(result, fc.Unavailable):
        raise BundleError(
            f"flat-price comparison unavailable ({result.kind}): {result.reason}"
        )
    t = result.totals
    households = []
    for r in result.households:
        bands = ta.band_summary(
            context.database,
            context.run_id,
            household=r["household_id"],
            relations=context.relations,
        )
        households.append(
            {
                "household_id": r["household_id"],
                "charged_readings": r["charged_readings"],
                "schedule_slots": r["schedule_slots_in_period"],
                "coverage": _pct(
                    None
                    if r["coverage_share"] is None
                    else Decimal(r["coverage_share"]) * 100,
                    "schedule_slots",
                ),
                "first_charged_date": r["first_charged_date"],
                "last_charged_date": r["last_charged_date"],
                "kwh": _energy(r["kwh_exact"]),
                "dynamic_charge": _money(r["dynamic_charge_gbp_exact"]),
                "flat_charge": _money(r["flat_charge_gbp_exact"]),
                "flat_minus_dynamic": _money(r["difference_exact"]),
                "pct_of_flat": _pct(r["pct_of_flat_exact"], "flat_charge"),
                "breakeven_flat_price": _pence_per_kwh(
                    r["dynamic_charge_gbp_exact"], r["kwh_exact"]
                ),
                "outcome_under_dynamic": r["outcome_under_dynamic"],
                "bands": _bands(bands),
            }
        )
    p = result.price
    v = result.variation
    return {
        "definition": result.definition,
        "sign_convention": "flat_minus_dynamic > 0 means the dynamic scenario is lower",
        "households": t.households,
        "charged_readings": t.readings,
        "schedule_slots": result.schedule_slots_in_period,
        "kwh": _energy(t.kwh),
        "dynamic_charge": _money(t.dynamic),
        "flat_charge": _money(t.flat),
        "flat_minus_dynamic": _money(t.difference),
        "pct_of_flat": _pct(t.pct_of_flat, "flat_charge"),
        "breakeven_flat_price": _pence_per_kwh(t.dynamic, t.kwh),
        "breakeven_meaning": (
            "the flat price at which this recorded consumption would have cost exactly what "
            "it did under the dynamic schedule; above it the dynamic scenario is lower"
        ),
        "outcomes_under_dynamic": dict(result.outcomes),
        "variation": {
            "largest_household": v.get("largest_household"),
            "largest_difference": _money(v["largest_difference_exact"]),
            "largest_share_of_pooled_pct": _pct(
                v.get("largest_share_of_pooled_pct"), "flat_minus_dynamic"
            ),
            "median_household_difference": _money(
                v["median_household_difference_exact"]
            ),
        }
        if v
        else {},
        "flat_price": {
            "tariff_group": p.tariff_group,
            "band": p.band_label,
            "pence_per_kwh": str(p.price_pence_per_kwh),
            "gbp_per_kwh": str(p.price_gbp_per_kwh),
            "catalogue_version": p.catalogue_version,
            "evidence_label": p.evidence_label,
            "validity": p.validity,
        },
        "assumption_ids": list(result.assumption_ids),
        "per_household": households,
    }


def _prices(context: reads.ReadContext) -> list[dict[str, Any]]:
    """The price dimension as stored: exact decimals, dates as text, UNKNOWN where NULL."""
    con = ta._con(context.database)
    try:
        rows = con.execute(
            "SELECT tariff_group, band_label, price_pence_per_kwh, price_gbp_per_kwh, "
            "CAST(effective_from AS VARCHAR), CAST(effective_until AS VARCHAR), "
            f"evidence_label FROM {context.relations.dim_price} "
            "ORDER BY tariff_group, band_label"
        ).fetchall()
    finally:
        con.close()
    return [
        {
            "tariff_group": g,
            "band": b,
            "pence_per_kwh": str(Decimal(str(pence))),
            "gbp_per_kwh": str(Decimal(str(gbp))),
            "valid_from": vf if vf is not None else "UNKNOWN",
            "valid_until_exclusive": vu if vu is not None else "UNKNOWN",
            "evidence_label": ev,
        }
        for g, b, pence, gbp, vf, vu, ev in rows
    ]


def _accounting(context: reads.ReadContext) -> dict[str, Any]:
    a = context.accounting()
    return {
        "raw_rows": a.raw_rows,
        "rows_collapsed_by_policy": a.rows_collapsed_by_policy,
        "distinct_readings": a.distinct_readings,
        "charged_readings": a.included_readings,
        "excluded_readings": a.excluded_readings,
        "excluded_by_reason": {k: int(v) for k, v in sorted(a.by_reason.items())},
        "reconciles": bool(a.reconciles),
        "counted_not_recorded": bool(a.derived),
    }


def _data_quality(
    context: reads.ReadContext, *, with_zero_days: bool
) -> dict[str, Any]:
    con = ta._con(context.database)
    r = context.relations.readings
    try:
        null_tokens = con.execute(
            f"SELECT COUNT(*) FROM {r} WHERE value_category = 'null_token'"
        ).fetchone()[0]
        off_grid = con.execute(
            f"SELECT COUNT(*) FROM {r} WHERE NOT on_half_hour_grid"
        ).fetchone()[0]
        zeros = con.execute(
            f"SELECT COUNT(*) FROM {r} WHERE consumption_kwh = 0"
        ).fetchone()[0]
        dup = con.execute(
            "SELECT COALESCE(SUM(extra_rows), 0) FROM main.v_exact_duplicates"
        ).fetchone()[0]
        conflicts = con.execute(
            "SELECT COUNT(*) FROM main.v_conflicting_keys"
        ).fetchone()[0]
    finally:
        con.close()
    out: dict[str, Any] = {
        "scope": "every reading loaded into this publication",
        "readings_loaded": None,  # filled from source.warehouse by the caller
        "exact_duplicate_extra_rows": int(dup),
        "conflicting_keys": int(conflicts),
        "null_tokens": int(null_tokens),
        "off_grid_rows": int(off_grid),
        "zero_readings": int(zeros),
        "policy": {
            "duplicates": "identical rows are collapsed to one and the number collapsed is shown",
            "conflicts": "rows that disagree at the same timestamp withhold that day's total",
            "missing": "a Null is recorded as missing; nothing is filled with zero",
        },
    }
    if with_zero_days:
        report = zd.summarise(daily_records(context.database))
        out["whole_zero_days"] = {
            "definition": report["definition"],
            "usable_days": report["usable_days"],
            "zero_days": report["zero_days"],
            "households_with_zero_days": report["households_with_zero_days"],
            "households": report["households"],
            "runs": report["runs"],
            "runs_28_days_or_more": report["runs_by_length"]["28+"],
            "runs_bounded_by_nonzero_usable_days": report[
                "runs_bounded_by_nonzero_usable_days"
            ],
            "longest_run_days": report["longest_run"]["days"]
            if report["longest_run"]
            else 0,
            "cause": "not established from readings; not inferred",
        }
    return out


def _find(obj: Any, *names: str) -> Any:
    """The first value under any of ``names`` anywhere in a nested dict, or None."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in names and not isinstance(v, (dict, list)):
                return v
        for v in obj.values():
            found = _find(v, *names)
            if found is not None:
                return found
    return None


def _without_id_prefix(assumption_id: str, text: str) -> str:
    """Drop a leading ``"A1 -- "``-style id so the page can label the assumption once."""
    if not text.startswith(assumption_id):
        return text
    rest = text[len(assumption_id) :].lstrip()
    for separator in ("--", "—", ".", ":"):
        if rest.startswith(separator):
            body = rest[len(separator) :].lstrip()
            return body[:1].upper() + body[1:]
    return text


def _profile_summary(profile: dict[str, Any] | None) -> dict[str, Any] | None:
    if profile is None:
        return None
    return {
        "source_file": str(profile.get("source", {}).get("member_name", "")).split("/")[
            -1
        ],
        "records": _find(profile.get("counts", {}), "data_records_excluding_header"),
        "malformed_records": _find(profile.get("counts", {}), "malformed_records"),
        "records_with_issues": _find(profile.get("counts", {}), "records_with_issues"),
        "households": _find(profile.get("households", {}), "distinct_in_member"),
        "off_grid_rows": _find(profile.get("timestamps", {}), "off_grid"),
        "exact_duplicate_extra_rows": _find(
            profile.get("duplicates", {}),
            "exact_duplicate_extra_rows",
            "exact_duplicate_rows",
            "extra_rows",
        ),
        "conflicting_keys": _find(
            profile.get("duplicates", {}), "conflicting_collisions", "conflicting_keys"
        ),
        "null_tokens": _find(
            profile.get("consumption", {}), "null_token", "null_tokens"
        ),
        "zero_values": _find(profile.get("consumption", {}), "zeros", "zero_values"),
    }


def _forecast(
    context: reads.ReadContext, report: dict[str, Any] | None
) -> dict[str, Any]:
    if report is None:
        return {"status": "omitted", "reason": "no forecast report was supplied"}
    verdict = applicability.assess(report, context)
    if not verdict.applicable:
        return {
            "status": "omitted",
            "reason": f"the report does not describe this publication's data: {verdict.reason}",
        }
    holdout = report["evaluation"]["holdout"]
    models = {m["name"]: m["description"] for m in report.get("models", [])}
    return {
        "status": "applicable",
        "applicability": verdict.reason,
        "kind": report.get("kind"),
        "target": report.get("target"),
        "cohort": {
            "households": report["selection"]["selected_households"],
            "eligible_households": report["selection"]["eligible_households"],
            "kind": report["selection"]["kind"],
            "min_run_days": report["config"]["min_run_days"],
            "holdout_days": report["config"]["holdout_days"],
            "horizon_days": report["config"]["horizon"],
        },
        "holdout": {
            "scored_predictions_per_model": holdout["by_model"][
                next(iter(holdout["by_model"]))
            ]["count"],
            "models": [
                {
                    "name": name,
                    "description": models.get(name, ""),
                    "mae_kwh": {
                        "exact": str(Decimal(str(m["mae_kwh_exact"]))),
                        "unit": "kWh per day",
                        "display": float(m["mae_kwh"]),
                    },
                    "median_ae_kwh_display": float(m["median_ae_kwh"]),
                }
                for name, m in sorted(
                    holdout["by_model"].items(),
                    key=lambda kv: Decimal(str(kv[1]["mae_kwh_exact"])),
                )
            ],
        },
        "identity": {
            "dataset_sha256": report["identity"]["dataset_sha256"],
            "forecast_code_sha256": report["identity"]["forecast_code_sha256"],
        },
    }


# ---------------------------------------------------------------------- bundle
def build_payload(
    context: reads.ReadContext,
    *,
    profile: dict[str, Any] | None = None,
    forecast_report: dict[str, Any] | None = None,
    with_zero_days: bool = True,
    terrain: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Everything the public page shows, from one validated context. No timestamps of ours.

    ``terrain`` is the payload :func:`terrain.build_terrain` produced from the **same**
    context; when omitted it is built here. Only its summary enters the bundle; the cells
    are written to their own file by :func:`write_bundle`.
    """
    source = _source(context)
    schedule = ta.schedule_bounds(context.database, relations=context.relations)
    quality = _data_quality(context, with_zero_days=with_zero_days)
    quality["readings_loaded"] = source["warehouse"]["readings_loaded"]
    if terrain is None:
        terrain = tr.build_terrain(context)
    if terrain["source"]["run_id"] != context.run_id:
        raise BundleError(
            f"the terrain describes run {terrain['source']['run_id']}, not this "
            f"context's {context.run_id}"
        )
    return {
        "definition": DEFINITION,
        "title": "The same electricity, priced two ways",
        "source": source,
        "assumptions": {
            "A1": _without_id_prefix("A1", ASSUMPTION_TEXT),
            "A2": _without_id_prefix("A2", fc.A2_TEXT),
        },
        "schedule": {
            "first_date": str(schedule[0]) if schedule else None,
            "last_date": str(schedule[1]) if schedule else None,
            "source": context.identity.schedule_source,
            "slots": context.identity.schedule_rows,
        },
        "prices": _prices(context),
        "bands": _bands(
            ta.band_summary(
                context.database, context.run_id, relations=context.relations
            )
        ),
        "comparison": _comparison(context),
        "hour_bands": _hour_band_ribbons(context),
        "accounting": _accounting(context),
        "data_quality": quality,
        "source_file_profile": _profile_summary(profile),
        "forecast": _forecast(context, forecast_report),
        "limitations": list(LIMITATIONS),
        "terrain": tr.summary(terrain),
    }


def canonical_bytes(payload: dict[str, Any]) -> bytes:
    """Sorted keys, minimal separators, UTF-8, one trailing newline. Byte-stable."""
    return (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def write_bundle(
    payload: dict[str, Any], directory: Path, terrain: dict[str, Any]
) -> dict[str, Any]:
    """Write the bundle, the terrain file and the manifest that pins both.

    The terrain must be the payload whose summary the bundle carries: same definition,
    same run. A bundle that names a terrain file the manifest does not pin would leave the
    browser nothing to verify, so the pair is written together or not at all.
    """
    if terrain.get("definition") != payload["terrain"]["definition"]:
        raise BundleError("the terrain file and the bundle's terrain summary differ")
    if terrain["source"]["run_id"] != payload["source"]["publication"]["run_id"]:
        raise BundleError("the terrain file and the bundle name different runs")
    directory.mkdir(parents=True, exist_ok=True)
    body = canonical_bytes(payload)
    digest = hashlib.sha256(body).hexdigest()
    terrain_body = canonical_bytes(terrain)
    terrain_digest = hashlib.sha256(terrain_body).hexdigest()
    (directory / BUNDLE_NAME).write_bytes(body)
    (directory / TERRAIN_NAME).write_bytes(terrain_body)
    manifest = {
        "definition": DEFINITION,
        "bundle": BUNDLE_NAME,
        "content_digest": digest,
        "size_bytes": len(body),
        "source": {
            "version": payload["source"]["publication"]["version"],
            "run_id": payload["source"]["publication"]["run_id"],
            "file_sha256": payload["source"]["publication"]["file_sha256"],
        },
        "terrain": {
            "file": TERRAIN_NAME,
            "definition": terrain["definition"],
            "content_digest": terrain_digest,
            "size_bytes": len(terrain_body),
        },
    }
    (directory / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=1, sort_keys=True) + "\n"
    )
    return manifest


def load_terrain(directory: Path) -> dict[str, Any]:
    """The terrain file, or a refusal naming what does not match the manifest."""
    manifest_path = directory / MANIFEST_NAME
    if not manifest_path.is_file():
        raise BundleError(f"no manifest under {directory}")
    manifest = json.loads(manifest_path.read_text())
    pin = manifest.get("terrain")
    if not isinstance(pin, dict):
        raise BundleError("the manifest pins no terrain file")
    if pin.get("definition") != tr.DEFINITION:
        raise BundleError(
            f"terrain definition {pin.get('definition')!r} is not {tr.DEFINITION!r}"
        )
    path = directory / str(pin.get("file"))
    if not path.is_file():
        raise BundleError(f"the manifest names {pin.get('file')} but it is missing")
    body = path.read_bytes()
    if len(body) != pin.get("size_bytes"):
        raise BundleError("terrain size differs from the manifest")
    digest = hashlib.sha256(body).hexdigest()
    if digest != pin.get("content_digest"):
        raise BundleError(
            f"{path.name} digests {digest[:12]}…, manifest pins "
            f"{str(pin.get('content_digest'))[:12]}…; the terrain changed after it was "
            "written"
        )
    try:
        payload = json.loads(body)
    except ValueError as error:
        raise BundleError(f"{path.name} is not JSON: {error}") from error
    if not isinstance(payload, dict) or payload.get("definition") != tr.DEFINITION:
        raise BundleError("terrain definition does not match")
    if payload["source"]["run_id"] != manifest["source"]["run_id"]:
        raise BundleError("the terrain and its manifest name different runs")
    if not payload.get("reconciliation", {}).get("all_hold"):
        raise BundleError("the terrain does not record a reconciliation that holds")
    return payload


def load_bundle(
    directory: Path, *, expected_run_id: str | None = None
) -> dict[str, Any]:
    """The bundle, or a refusal naming what does not match."""
    manifest_path, bundle_path = directory / MANIFEST_NAME, directory / BUNDLE_NAME
    if not manifest_path.is_file() or not bundle_path.is_file():
        raise BundleError(f"no bundle under {directory}")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("definition") != DEFINITION:
        raise BundleError(
            f"manifest definition {manifest.get('definition')!r} is not {DEFINITION!r}"
        )
    body = bundle_path.read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    if digest != manifest.get("content_digest"):
        raise BundleError(
            f"{BUNDLE_NAME} digests {digest[:12]}…, manifest pins "
            f"{str(manifest.get('content_digest'))[:12]}…; the bundle changed after it was written"
        )
    if len(body) != manifest.get("size_bytes"):
        raise BundleError("bundle size differs from the manifest")
    payload = json.loads(body)
    if payload.get("definition") != DEFINITION:
        raise BundleError("bundle definition does not match")
    run_id = payload["source"]["publication"]["run_id"]
    if run_id != manifest["source"]["run_id"]:
        raise BundleError("the bundle and its manifest name different runs")
    if expected_run_id is not None and run_id != expected_run_id:
        raise BundleError(
            f"the bundle describes run {run_id}, not the expected {expected_run_id}: stale"
        )
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="export-presentation",
        description=(
            "Write the public presentation bundle from a validated publication or serving "
            "snapshot: exact totals, every household's outcome and coverage, band summaries, "
            "accounting, data-quality and forecast summaries, assumptions, attribution and "
            "identity. No row-level data."
        ),
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--root", type=Path, help="a publication root")
    src.add_argument("--serving-dir", type=Path, help="a serving snapshot directory")
    parser.add_argument(
        "--profile", type=Path, help="the tracked source-file profile JSON"
    )
    parser.add_argument("--forecast-report", type=Path, help="a FORE-001 report JSON")
    parser.add_argument(
        "--no-zero-days", action="store_true", help="skip the ANL-004 summary"
    )
    parser.add_argument("--into", type=Path, default=Path("web/public/data"))
    args = parser.parse_args(argv)
    try:
        context = (
            reads.published(args.root) if args.root else reads.serving(args.serving_dir)
        )
        profile = json.loads(args.profile.read_text()) if args.profile else None
        report = (
            json.loads(args.forecast_report.read_text())
            if args.forecast_report
            else None
        )
        terrain = tr.build_terrain(context)
        payload = build_payload(
            context,
            profile=profile,
            forecast_report=report,
            with_zero_days=not args.no_zero_days,
            terrain=terrain,
        )
        manifest = write_bundle(payload, args.into, terrain)
    except (
        BundleError,
        tr.TerrainError,
        reads.ReadContextError,
        publication.PublicationError,
        OSError,
    ) as error:
        print(f"export-presentation: {error}", file=sys.stderr)
        return 1
    print(
        f"wrote {args.into / BUNDLE_NAME}: {manifest['size_bytes']:,} bytes, sha256 "
        f"{manifest['content_digest'][:12]}… from {context.label}; forecast "
        f"{payload['forecast']['status']}; {TERRAIN_NAME}: "
        f"{manifest['terrain']['size_bytes']:,} bytes, sha256 "
        f"{manifest['terrain']['content_digest'][:12]}…, "
        f"{terrain['grid']['cells']:,} cells, reconciled"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
