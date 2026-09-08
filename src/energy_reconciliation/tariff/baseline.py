"""Capture a scenario result so a later result can be *explained*, not just compared.

Why this exists
---------------

A warehouse is mutable. Loading another member changes it, and after that the figures
it produces are figures for a different input set. A fingerprint recorded inside that
warehouse detects the change but cannot reconstruct what came before: the rows it
described are gone.

A baseline is the durable record. It names the **exact input members** by archive and
by decompressed content digest, the calculation identity that transformed them, the
runtime that evaluated the arithmetic, and enough of the result to say *where* a later
run differs and by how much -- per band, per household and per exclusion reason.

Replay rebuilds from that record into a **fresh** database. Nothing is reused from the
warehouse the baseline came from, so a replay that reproduces the figures has actually
re-derived them. A replay is only ever reported as successful when it has been run and
its output compared field by field.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from ..ingest.loader import load_member, member_content_digest
from ..ingest.warehouse import connect
from ..profiling.reader import DEFAULT_ARCHIVE, member_identity
from . import identity
from . import prices as pr
from .models import ASSUMPTION_ID, build_scenario
from .schedule import DEFAULT_WORKBOOK, demo_schedule, read_workbook

BASELINE_DIR: Final[Path] = Path("data/baselines")
FORMAT_VERSION: Final[str] = "1"


class BaselineError(RuntimeError):
    """The baseline cannot be captured or replayed as recorded."""


@dataclass(frozen=True, slots=True)
class Difference:
    field: str
    baseline: str
    replay: str

    @property
    def matches(self) -> bool:
        return self.baseline == self.replay


def fact_row_digest(con, run_id: str) -> str:
    """SHA-256 over every charged row, in a fixed order.

    Aggregates can agree while rows differ -- a reading moved between two households, or
    two rows in one band changed by equal and opposite amounts. This digest is what turns
    "the totals match" into "every row matches". Computed in Python from a streamed
    cursor so the ordering and the rendering of every value are ours, not the engine's.
    """
    digest = hashlib.sha256()
    cur = con.execute(
        "SELECT household_id, source_timestamp_text, band_label, "
        "CAST(consumption_kwh AS VARCHAR), CAST(energy_charge_gbp AS VARCHAR) "
        "FROM fact_interval_charge_scenario WHERE run_id = ? "
        "ORDER BY household_id, source_timestamp_text, band_label",
        [run_id],
    )
    while chunk := cur.fetchmany(50_000):
        for r in chunk:
            digest.update("|".join(r).encode())
            digest.update(b"\n")
    return digest.hexdigest()


def _rows(con, sql: str, params: list | None = None) -> list[dict[str, Any]]:
    cur = con.execute(sql, params or [])
    names = [d[0] for d in cur.description]
    return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]


def capture(database: Path, directory: Path = BASELINE_DIR) -> Path:
    """Write an immutable baseline for the currently published scenario run."""
    con = connect(database, read_only=True)
    try:
        run = con.execute(
            "SELECT * FROM scenario_run WHERE status = 'published' "
            "ORDER BY run_at_utc DESC LIMIT 1"
        ).fetchone()
        if run is None:
            raise BaselineError(f"{database}: no published scenario run to capture")
        columns = [d[0] for d in con.description]
        run_row = dict(zip(columns, run, strict=True))
        run_id = run_row["run_id"]

        loads = _rows(
            con,
            "SELECT load_id, archive_name, archive_sha256, member_name, "
            "member_content_sha256, CAST(loaded_at_utc AS VARCHAR) AS loaded_at_utc, "
            "records_read, records_published, records_rejected, pipeline_fingerprint "
            "FROM load_registry WHERE status = 'published' ORDER BY member_name",
        )
        if not loads:
            raise BaselineError(f"{database}: no published loads to record")

        per_band = _rows(
            con,
            "SELECT band_label, COUNT(*) AS readings, "
            "CAST(SUM(consumption_kwh) AS VARCHAR) AS kwh_exact, "
            "CAST(SUM(energy_charge_gbp) AS VARCHAR) AS charge_exact "
            "FROM fact_interval_charge_scenario WHERE run_id = ? GROUP BY 1 ORDER BY 1",
            [run_id],
        )
        per_household = _rows(
            con,
            "SELECT household_id, COUNT(*) AS readings, "
            "CAST(MIN(source_date) AS VARCHAR) AS first_date, "
            "CAST(MAX(source_date) AS VARCHAR) AS last_date, "
            "CAST(SUM(consumption_kwh) AS VARCHAR) AS kwh_exact, "
            "CAST(SUM(energy_charge_gbp) AS VARCHAR) AS charge_exact "
            "FROM fact_interval_charge_scenario WHERE run_id = ? GROUP BY 1 ORDER BY 1",
            [run_id],
        )
        per_reason = _rows(
            con,
            "SELECT exclusion_reason, COUNT(*) AS readings "
            "FROM fact_interval_charge_exclusion WHERE run_id = ? GROUP BY 1 ORDER BY 1",
            [run_id],
        )
        row_digest = fact_row_digest(con, run_id)
    finally:
        con.close()

    captured = datetime.now(UTC).replace(tzinfo=None)
    baseline = {
        "format_version": FORMAT_VERSION,
        "baseline_id": f"{run_row['scenario_fingerprint'][:12]}"
        f"@{captured.strftime('%Y%m%dT%H%M%S')}",
        "captured_at_utc": captured.isoformat(sep=" "),
        "captured_from_database": str(database),
        "note": (
            "Immutable record of one scenario result. The database it came from is "
            "mutable and may already differ. Replay rebuilds into a fresh database "
            "from the inputs named here."
        ),
        "inputs": {
            "members": loads,
            "member_count": len(loads),
            "schedule": {
                "source": run_row["schedule_source"],
                "sha256": run_row["schedule_sha256"],
                "rows": run_row["schedule_rows"],
                "first_label": str(run_row["schedule_first_label"]),
                "last_label": str(run_row["schedule_last_label"]),
            },
        },
        "calculation": {
            "price_catalogue_version": run_row["price_catalogue_version"],
            "calculation_code_sha256": run_row["calculation_code_sha256"],
            "policy_sha256": run_row["policy_sha256"],
            "model_code_sha256": run_row["model_code_sha256"],
            "ingestion_pipeline_fingerprint": run_row["ingestion_pipeline_fingerprint"],
            "assumption_ids": run_row["assumption_ids"],
            "scope_tariff_group": run_row["scope_tariff_group"],
            "covered_files": identity.file_digests(),
        },
        "runtime": json.loads(run_row["runtime_detail"]),
        "output": {
            "run_id": run_id,
            "scenario_fingerprint": run_row["scenario_fingerprint"],
            "raw_rows": run_row["raw_rows"],
            "rows_collapsed_by_policy": run_row["rows_collapsed_by_policy"],
            "distinct_readings": run_row["distinct_readings"],
            "included_readings": run_row["included_readings"],
            "excluded_readings": run_row["excluded_readings"],
            "total_energy_charge_gbp_exact": run_row["total_energy_charge_gbp_exact"],
            "per_band": per_band,
            "per_household": per_household,
            "per_exclusion_reason": per_reason,
            "fact_row_digest": row_digest,
            "fact_row_digest_note": (
                "SHA-256 over every charged row (household, label, band, kWh, charge) "
                "in a fixed order: row-level lineage, not only aggregates."
            ),
        },
    }
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{baseline['baseline_id']}.json"
    if path.exists():
        raise BaselineError(f"{path} already exists; a baseline is never overwritten")
    path.write_text(json.dumps(baseline, indent=2, sort_keys=False) + "\n")
    return path


def reproduce_command(baseline: dict, database: Path) -> str:
    """The command that rebuilds this result from the baseline's own input set."""
    return f"uv run replay-baseline --baseline {baseline['baseline_id']}.json --database {database}"


def replay(
    baseline_path: Path,
    database: Path,
    archive: Path = DEFAULT_ARCHIVE,
    workbook: Path = DEFAULT_WORKBOOK,
) -> tuple[list[Difference], dict]:
    """Rebuild the baseline's result in a fresh database and compare, field by field.

    Every recorded member is re-ingested from the archive and its **decompressed
    content digest is checked against the baseline** before anything is built: a member
    whose bytes have changed is not the input the baseline describes, and replaying it
    would produce a different result that looked like the same one.
    """
    baseline = json.loads(baseline_path.read_text())
    if baseline.get("format_version") != FORMAT_VERSION:
        raise BaselineError(
            f"{baseline_path}: format version {baseline.get('format_version')!r}, "
            f"expected {FORMAT_VERSION!r}"
        )
    if database.exists():
        raise BaselineError(
            f"{database} already exists. Replay must build a fresh database: "
            "reusing one proves nothing about rebuilding from the recorded inputs."
        )

    members = baseline["inputs"]["members"]
    for member in members:
        actual = member_content_digest(archive, member["member_name"])
        if actual != member["member_content_sha256"]:
            raise BaselineError(
                f"{member['member_name']}: content digest {actual[:12]}… does not "
                f"match the baseline's {member['member_content_sha256'][:12]}…"
            )
        found = member_identity(archive, member["member_name"]).archive_sha256
        if found != member["archive_sha256"]:
            raise BaselineError(
                f"{archive}: archive digest {found[:12]}… does not match the "
                f"baseline's {member['archive_sha256'][:12]}…"
            )
        load_member(archive, member["member_name"], database)

    schedule_source = baseline["inputs"]["schedule"]["source"]
    schedule = (
        demo_schedule()
        if schedule_source != "Tariffs.xlsx"
        else read_workbook(workbook)
    )
    if schedule.source_sha256 != baseline["inputs"]["schedule"]["sha256"]:
        raise BaselineError(
            f"schedule digest {schedule.source_sha256[:12]}… does not match the "
            f"baseline's {baseline['inputs']['schedule']['sha256'][:12]}…"
        )
    result = build_scenario(
        database,
        schedule,
        tariff_group=baseline["calculation"]["scope_tariff_group"],
    )
    return compare(baseline, database, result), baseline


def compare(baseline: dict, database: Path, result) -> list[Difference]:
    """Field-by-field comparison of a replay against the baseline it came from."""
    out = baseline["output"]
    differences = [
        Difference(
            "distinct_readings",
            str(out["distinct_readings"]),
            str(result.distinct_readings),
        ),
        Difference(
            "included_readings",
            str(out["included_readings"]),
            str(result.included_readings),
        ),
        Difference(
            "excluded_readings",
            str(out["excluded_readings"]),
            str(result.excluded_readings),
        ),
        Difference("raw_rows", str(out["raw_rows"]), str(result.raw_rows)),
        Difference(
            "rows_collapsed_by_policy",
            str(out["rows_collapsed_by_policy"]),
            str(result.rows_collapsed_by_policy),
        ),
        Difference(
            "total_energy_charge_gbp_exact",
            str(out["total_energy_charge_gbp_exact"]),
            str(result.total_energy_charge_gbp_exact),
        ),
        Difference(
            "scenario_fingerprint",
            out["scenario_fingerprint"],
            result.scenario_fingerprint,
        ),
    ]
    con = connect(database, read_only=True)
    try:
        if "fact_row_digest" in out:
            # Older baselines predate the digest; they are compared on aggregates only,
            # and say so rather than pretend a comparison that did not happen.
            differences.append(
                Difference(
                    "fact_row_digest (every charged row)",
                    out["fact_row_digest"],
                    fact_row_digest(con, result.run_id),
                )
            )
        bands = {
            r["band_label"]: r
            for r in _rows(
                con,
                "SELECT band_label, COUNT(*) AS readings, "
                "CAST(SUM(consumption_kwh) AS VARCHAR) AS kwh_exact, "
                "CAST(SUM(energy_charge_gbp) AS VARCHAR) AS charge_exact "
                "FROM fact_interval_charge_scenario GROUP BY 1",
            )
        }
        households = {
            r["household_id"]: r
            for r in _rows(
                con,
                "SELECT household_id, COUNT(*) AS readings, "
                "CAST(SUM(energy_charge_gbp) AS VARCHAR) AS charge_exact "
                "FROM fact_interval_charge_scenario GROUP BY 1",
            )
        }
        reasons = {
            r["exclusion_reason"]: r["readings"]
            for r in _rows(
                con,
                "SELECT exclusion_reason, COUNT(*) AS readings "
                "FROM fact_interval_charge_exclusion GROUP BY 1",
            )
        }
    finally:
        con.close()

    for band in out["per_band"]:
        got = bands.get(band["band_label"], {})
        differences.append(
            Difference(
                f"band[{band['band_label']}].charge_exact",
                band["charge_exact"],
                str(got.get("charge_exact")),
            )
        )
        differences.append(
            Difference(
                f"band[{band['band_label']}].readings",
                str(band["readings"]),
                str(got.get("readings")),
            )
        )
    for reason in out["per_exclusion_reason"]:
        differences.append(
            Difference(
                f"excluded[{reason['exclusion_reason']}]",
                str(reason["readings"]),
                str(reasons.get(reason["exclusion_reason"])),
            )
        )
    mismatched_households = [
        h["household_id"]
        for h in out["per_household"]
        if households.get(h["household_id"], {}).get("charge_exact")
        != h["charge_exact"]
    ]
    differences.append(
        Difference(
            f"per_household charges ({len(out['per_household'])} households)",
            "all match",
            "all match"
            if not mismatched_households
            else f"{len(mismatched_households)} differ: {mismatched_households[:5]}",
        )
    )
    return differences


def describe_environment_drift(baseline: dict) -> list[Difference]:
    """Recorded environment against the one replaying it. Reported, not enforced."""
    now = identity.runtime_identity()
    return [
        Difference(f"runtime.{key}", str(value), str(now.get(key)))
        for key, value in sorted(baseline["runtime"].items())
    ] + [
        Difference(
            "price_catalogue_version",
            baseline["calculation"]["price_catalogue_version"],
            pr.PRICE_CATALOGUE_VERSION,
        ),
        Difference(
            "assumption_ids", baseline["calculation"]["assumption_ids"], ASSUMPTION_ID
        ),
        Difference(
            "calculation_code_sha256",
            baseline["calculation"]["calculation_code_sha256"],
            identity.calculation_digest(),
        ),
    ]
