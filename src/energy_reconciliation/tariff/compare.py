"""REC-001 -- explain the effect of additional source coverage on a scenario.

The project's question is *what did we calculate at the time, what would we calculate
now, and can we explain every difference?* This module answers it for one kind of
change -- **more source loaded, nothing else changed** -- by comparing two warehouses
built with identical code, runtime, prices, schedule and assumption, and attributing
every difference in the charged output to a category with evidence.

Grains, stated once:

- **Raw row** -- one line of a source member, as loaded.
- **Distinct reading** -- the policy unit: one (household, source timestamp label, value
  signature). Exact duplicates and equivalent representations collapse into it.
- **Charged output** -- one (household, source timestamp label) with a band, kWh and
  charge. There is at most one per key: a disputed label is excluded entirely.

The reconciliation identity, in exact ``Decimal``:

    baseline charge + added (existing households) + added (new households)
                    - removed + changed = comparison charge

Any residual is reported as a residual. It is never rounded away.

Adding a member does **not** only add: a newly loaded row can disagree with an already
charged reading, and under the conflict policy the earlier charge is then **withheld**.
Removals are therefore first-class here, each carrying the reason recorded in the
comparison warehouse's exclusion table and the source rows on both sides of the dispute.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from ..policy import CONFLICTING_LABELS, DISTINCT_READINGS, TEXT_KEY

BASE, COMP = "base", "comp"

#: Identity fields that must be equal for the comparison to be about *source* alone.
IDENTITY_FIELDS = (
    "calculation_code_sha256",
    "policy_sha256",
    "model_code_sha256",
    "runtime_fingerprint",
    "price_catalogue_version",
    "assumption_ids",
    "scope_tariff_group",
    "schedule_sha256",
    "ingestion_pipeline_fingerprint",
)


class ComparisonError(RuntimeError):
    """The two warehouses differ in something other than loaded source."""


def _on(schema: str, sql: str) -> str:
    """Point one of the shared policy queries at an attached warehouse."""
    return sql.replace("FROM readings", f"FROM {schema}.readings")


@dataclass
class HouseholdDelta:
    household_id: str
    status: str  # "existing" | "new"
    added_charged: int = 0
    added_charge: Decimal = Decimal(0)
    removed_charged: int = 0
    removed_charge: Decimal = Decimal(0)
    changed_charged: int = 0
    changed_delta: Decimal = Decimal(0)
    source_members_added: dict[str, int] = field(default_factory=dict)
    removed_detail: list[dict[str, Any]] = field(default_factory=list)

    @property
    def net(self) -> Decimal:
        return self.added_charge - self.removed_charge + self.changed_delta


def _dec(value) -> Decimal:
    return Decimal(str(value)) if value is not None else Decimal(0)


def _run(con, schema: str) -> dict[str, Any]:
    cur = con.execute(
        f"SELECT * FROM {schema}.scenario_run WHERE status = 'published' "
        "ORDER BY run_at_utc DESC LIMIT 1"
    )
    row = cur.fetchone()
    if row is None:
        raise ComparisonError(f"{schema}: no published scenario run")
    return dict(zip([d[0] for d in cur.description], row, strict=True))


def _members(con, schema: str) -> list[dict[str, Any]]:
    cur = con.execute(
        f"SELECT member_name, member_content_sha256, records_published "
        f"FROM {schema}.load_registry WHERE status = 'published' ORDER BY member_name"
    )
    return [
        dict(zip([d[0] for d in cur.description], r, strict=True))
        for r in cur.fetchall()
    ]


def compare_scenarios(baseline_db: Path, comparison_db: Path) -> dict[str, Any]:
    """Attach both warehouses read-only and explain the difference between them."""
    con = duckdb.connect()
    try:
        con.execute(f"ATTACH '{baseline_db}' AS {BASE} (READ_ONLY)")
        con.execute(f"ATTACH '{comparison_db}' AS {COMP} (READ_ONLY)")
        return _compare(con, baseline_db, comparison_db)
    finally:
        con.close()


def _compare(con, baseline_db: Path, comparison_db: Path) -> dict[str, Any]:
    run_b, run_c = _run(con, BASE), _run(con, COMP)
    identity = {}
    for f in IDENTITY_FIELDS:
        identity[f] = {
            "baseline": run_b[f],
            "comparison": run_c[f],
            "same": run_b[f] == run_c[f],
        }
    unequal = [f for f, v in identity.items() if not v["same"]]
    if unequal:
        raise ComparisonError(
            "the warehouses differ in more than loaded source: " + ", ".join(unequal)
        )

    members_b = {m["member_name"]: m for m in _members(con, BASE)}
    members_c = {m["member_name"]: m for m in _members(con, COMP)}
    if not set(members_b) <= set(members_c):
        raise ComparisonError("the comparison warehouse lacks a baseline member")
    for name, m in members_b.items():
        if members_c[name]["member_content_sha256"] != m["member_content_sha256"]:
            raise ComparisonError(f"{name}: content differs between the warehouses")
    added_members = sorted(set(members_c) - set(members_b))
    if not added_members:
        raise ComparisonError("no member was added; nothing to explain")
    in_added = "member_name IN (" + ",".join("?" * len(added_members)) + ")"

    # ------------------------------------------------------------ households
    hh_b = {
        r[0]
        for r in con.execute(
            f"SELECT DISTINCT household_id FROM {BASE}.readings"
        ).fetchall()
    }
    hh_c = {
        r[0]
        for r in con.execute(
            f"SELECT DISTINCT household_id FROM {COMP}.readings"
        ).fetchall()
    }
    new_households = sorted(hh_c - hh_b)
    lost_households = sorted(hh_b - hh_c)

    # -------------------------------------------------------------- raw rows
    rows_b = con.execute(f"SELECT COUNT(*) FROM {BASE}.readings").fetchone()[0]
    rows_c = con.execute(f"SELECT COUNT(*) FROM {COMP}.readings").fetchone()[0]
    rows_added = con.execute(
        f"SELECT COUNT(*) FROM {COMP}.readings WHERE {in_added}", added_members
    ).fetchone()[0]

    # ------------------------------------------------ distinct readings (policy grain)
    con.execute(f"CREATE TEMP TABLE d_b AS {_on(BASE, DISTINCT_READINGS)}")
    con.execute(f"CREATE TEMP TABLE d_c AS {_on(COMP, DISTINCT_READINGS)}")
    con.execute(
        f"CREATE TEMP TABLE d_added AS {_on(COMP, DISTINCT_READINGS)} WHERE {in_added}",
        added_members,
    )
    distinct_b = con.execute("SELECT COUNT(*) FROM d_b").fetchone()[0]
    distinct_c = con.execute("SELECT COUNT(*) FROM d_c").fetchone()[0]
    distinct_in_added = con.execute("SELECT COUNT(*) FROM d_added").fetchone()[0]
    within_added_repeats = rows_added - distinct_in_added
    # readings the added members carry that the baseline already had, by policy grain
    already = con.execute(
        "SELECT COUNT(*) FROM d_added a WHERE EXISTS (SELECT 1 FROM d_b b "
        "WHERE b.household_id = a.household_id AND b.source_timestamp_text = a.source_timestamp_text "
        "AND b.value_signature = a.value_signature)"
    ).fetchone()[0]
    # of those, how many are byte-identical to a baseline row (exact) vs equivalent text
    exact_of_baseline = con.execute(
        f"SELECT COUNT(*) FROM (SELECT DISTINCT {TEXT_KEY} FROM {COMP}.readings WHERE {in_added}) a "
        f"WHERE EXISTS (SELECT 1 FROM {BASE}.readings b WHERE b.household_id = a.household_id "
        f"AND b.tariff_group = a.tariff_group AND b.source_timestamp_text = a.source_timestamp_text "
        f"AND b.consumption_raw_text = a.consumption_raw_text)",
        added_members,
    ).fetchone()[0]
    equivalent_of_baseline = already - exact_of_baseline
    new_distinct = distinct_in_added - already
    new_distinct_existing = con.execute(
        f"SELECT COUNT(*) FROM d_added a WHERE NOT EXISTS (SELECT 1 FROM d_b b WHERE "
        f"b.household_id = a.household_id AND b.source_timestamp_text = a.source_timestamp_text "
        f"AND b.value_signature = a.value_signature) AND a.household_id IN "
        f"(SELECT DISTINCT household_id FROM {BASE}.readings)"
    ).fetchone()[0]
    new_distinct_new_households = new_distinct - new_distinct_existing

    # A new reading that produced no charge is as much a difference to explain as one
    # that did. Every new distinct reading is either charged or carries an exclusion
    # reason in the comparison warehouse, split by whether its household is new.
    con.execute(
        "CREATE TEMP TABLE d_new AS SELECT a.* FROM d_added a WHERE NOT EXISTS ("
        "SELECT 1 FROM d_b b WHERE b.household_id = a.household_id "
        "AND b.source_timestamp_text = a.source_timestamp_text "
        "AND b.value_signature = a.value_signature)"
    )
    not_charged = [
        {
            "household_status": status,
            "exclusion_reason": reason,
            "readings": int(count),
            "first_source_date": str(first),
            "last_source_date": str(last),
        }
        for status, reason, count, first, last in con.execute(
            f"""
            SELECT CASE WHEN n.household_id IS NULL THEN 'existing' ELSE 'new' END,
                   x.exclusion_reason, COUNT(*), MIN(x.source_date), MAX(x.source_date)
            FROM d_new a
            JOIN {COMP}.fact_interval_charge_exclusion x
              ON x.household_id = a.household_id
             AND x.source_timestamp_text = a.source_timestamp_text
            LEFT JOIN (SELECT DISTINCT household_id FROM {COMP}.readings
                       WHERE household_id NOT IN (SELECT DISTINCT household_id FROM {BASE}.readings)) n
              ON n.household_id = a.household_id
            GROUP BY 1, 2 ORDER BY 3 DESC
            """
        ).fetchall()
    ]

    # ---------------------------------------------------------- disagreements
    con.execute(f"CREATE TEMP TABLE c_b AS {_on(BASE, CONFLICTING_LABELS)}")
    con.execute(f"CREATE TEMP TABLE c_c AS {_on(COMP, CONFLICTING_LABELS)}")
    new_conflicts = con.execute(
        "SELECT household_id, source_timestamp_text FROM c_c EXCEPT "
        "SELECT household_id, source_timestamp_text FROM c_b"
    ).fetchall()
    resolved_conflicts = con.execute(
        "SELECT COUNT(*) FROM (SELECT household_id, source_timestamp_text FROM c_b EXCEPT "
        "SELECT household_id, source_timestamp_text FROM c_c)"
    ).fetchone()[0]
    multi_group_c = con.execute(
        f"SELECT household_id FROM {COMP}.readings GROUP BY 1 "
        "HAVING COUNT(DISTINCT tariff_group) > 1 ORDER BY 1"
    ).fetchall()
    multi_group_b = {
        r[0]
        for r in con.execute(
            f"SELECT household_id FROM {BASE}.readings GROUP BY 1 "
            "HAVING COUNT(DISTINCT tariff_group) > 1"
        ).fetchall()
    }
    eligibility_changes = [r[0] for r in multi_group_c if r[0] not in multi_group_b]

    # ----------------------------------------------------------- charged output
    fact = (
        "SELECT household_id, source_timestamp_text, band_label, consumption_kwh, "
        "energy_charge_gbp FROM {s}.fact_interval_charge_scenario"
    )
    con.execute(f"CREATE TEMP TABLE f_b AS {fact.format(s=BASE)}")
    con.execute(f"CREATE TEMP TABLE f_c AS {fact.format(s=COMP)}")
    total_b = _dec(con.execute("SELECT SUM(energy_charge_gbp) FROM f_b").fetchone()[0])
    total_c = _dec(con.execute("SELECT SUM(energy_charge_gbp) FROM f_c").fetchone()[0])
    assert str(total_b) == str(run_b["total_energy_charge_gbp_exact"])
    assert str(total_c) == str(run_c["total_energy_charge_gbp_exact"])

    added_rows = con.execute(
        "SELECT c.household_id, c.source_timestamp_text, c.energy_charge_gbp "
        "FROM f_c c LEFT JOIN f_b b USING (household_id, source_timestamp_text) "
        "WHERE b.household_id IS NULL"
    ).fetchall()
    removed_rows = con.execute(
        "SELECT b.household_id, b.source_timestamp_text, b.energy_charge_gbp "
        "FROM f_b b LEFT JOIN f_c c USING (household_id, source_timestamp_text) "
        "WHERE c.household_id IS NULL"
    ).fetchall()
    changed_rows = con.execute(
        "SELECT b.household_id, b.source_timestamp_text, b.energy_charge_gbp, "
        "c.energy_charge_gbp, b.band_label, c.band_label, b.consumption_kwh, c.consumption_kwh "
        "FROM f_b b JOIN f_c c USING (household_id, source_timestamp_text) "
        "WHERE b.energy_charge_gbp <> c.energy_charge_gbp OR b.band_label <> c.band_label "
        "OR b.consumption_kwh <> c.consumption_kwh"
    ).fetchall()

    deltas: dict[str, HouseholdDelta] = {}

    def hh(h: str) -> HouseholdDelta:
        if h not in deltas:
            deltas[h] = HouseholdDelta(h, "new" if h in new_households else "existing")
        return deltas[h]

    added_existing = added_new = Decimal(0)
    for h, _label, charge in added_rows:
        d = hh(h)
        d.added_charged += 1
        d.added_charge += _dec(charge)
        if d.status == "new":
            added_new += _dec(charge)
        else:
            added_existing += _dec(charge)
    removed_total = Decimal(0)
    for h, label, charge in removed_rows:
        d = hh(h)
        d.removed_charged += 1
        d.removed_charge += _dec(charge)
        removed_total += _dec(charge)
        reasons = [
            r[0]
            for r in con.execute(
                f"SELECT DISTINCT exclusion_reason FROM {COMP}.fact_interval_charge_exclusion "
                "WHERE household_id = ? AND source_timestamp_text = ?",
                [h, label],
            ).fetchall()
        ]
        sources = con.execute(
            f"SELECT member_name, source_record_no, consumption_raw_text, value_category "
            f"FROM {COMP}.readings WHERE household_id = ? AND source_timestamp_text = ? "
            "ORDER BY member_name, source_record_no",
            [h, label],
        ).fetchall()
        d.removed_detail.append(
            {
                "source_timestamp_text": label,
                "baseline_charge_gbp": str(_dec(charge)),
                "reason_in_comparison": reasons or ["NOT FOUND IN EXCLUSIONS"],
                "source_rows": [
                    {"member": m, "record_no": n, "raw_text": t, "value_category": v}
                    for m, n, t, v in sources
                ],
            }
        )
    changed_total = Decimal(0)
    for h, _label, cb, cc, *_rest in changed_rows:
        d = hh(h)
        d.changed_charged += 1
        d.changed_delta += _dec(cc) - _dec(cb)
        changed_total += _dec(cc) - _dec(cb)

    # where the added charged rows came from, per household, by member
    for h, d in deltas.items():
        if d.added_charged:
            for m, n in con.execute(
                f"SELECT r.member_name, COUNT(DISTINCT r.source_timestamp_text) "
                f"FROM {COMP}.readings r JOIN f_c c USING (household_id, source_timestamp_text) "
                f"LEFT JOIN f_b b USING (household_id, source_timestamp_text) "
                f"WHERE r.household_id = ? AND b.household_id IS NULL GROUP BY 1 ORDER BY 1",
                [h],
            ).fetchall():
                d.source_members_added[m] = int(n)

    explained = added_existing + added_new - removed_total + changed_total
    residual = total_c - (total_b + explained)

    def ladder(schema: str) -> dict[str, Any]:
        r = _run(con, schema)
        reasons = dict(
            con.execute(
                f"SELECT exclusion_reason, COUNT(*) FROM {schema}.fact_interval_charge_exclusion "
                "GROUP BY 1 ORDER BY 1"
            ).fetchall()
        )
        return {
            "raw_rows": int(r["raw_rows"]),
            "distinct_readings": int(r["distinct_readings"]),
            "charged": int(r["included_readings"]),
            "excluded": int(r["excluded_readings"]),
            "excluded_by_reason": {k: int(v) for k, v in reasons.items()},
            "charged_kwh_exact": str(
                _dec(
                    con.execute(
                        f"SELECT SUM(consumption_kwh) FROM {schema}.fact_interval_charge_scenario"
                    ).fetchone()[0]
                )
            ),
            "charge_gbp_exact": str(_dec(r["total_energy_charge_gbp_exact"])),
            "charged_households": int(
                con.execute(
                    f"SELECT COUNT(DISTINCT household_id) FROM {schema}.fact_interval_charge_scenario"
                ).fetchone()[0]
            ),
        }

    affected = sorted(deltas.values(), key=lambda d: (-abs(d.net), d.household_id))
    return {
        "generated_at_utc": datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" "),
        "kind": "source expansion: additional loaded coverage, identical code, runtime, prices, schedule and assumption",
        "assumption": run_c["assumption_ids"],
        "assumption_text": run_c["assumption_text"],
        "baseline_db": str(baseline_db),
        "comparison_db": str(comparison_db),
        "baseline_run_id": run_b["run_id"],
        "comparison_run_id": run_c["run_id"],
        "identity": identity,
        "members": {
            "baseline": sorted(members_b),
            "added": added_members,
            "added_detail": [members_c[m] for m in added_members],
        },
        "households": {
            "baseline": len(hh_b),
            "comparison": len(hh_c),
            "new": new_households,
            "lost": lost_households,
        },
        "raw_rows": {
            "baseline": int(rows_b),
            "comparison": int(rows_c),
            "added": int(rows_added),
        },
        "distinct_readings": {
            "baseline": int(distinct_b),
            "comparison": int(distinct_c),
            "added_member_rows": int(rows_added),
            "repeats_within_added_members": int(within_added_repeats),
            "already_in_baseline_exact_duplicate": int(exact_of_baseline),
            "already_in_baseline_equivalent_representation": int(
                equivalent_of_baseline
            ),
            "new_for_existing_households": int(new_distinct_existing),
            "new_for_new_households": int(new_distinct_new_households),
            "identity_holds": int(rows_added)
            == int(within_added_repeats) + int(already) + int(new_distinct)
            and int(distinct_c) == int(distinct_b) + int(new_distinct),
        },
        "new_readings_not_charged": not_charged,
        "disagreements": {
            "new_conflicting_labels": [
                {"household_id": h, "source_timestamp_text": t}
                for h, t in sorted(new_conflicts)
            ],
            "resolved_conflicting_labels": int(resolved_conflicts),
            "households_now_under_more_than_one_tariff_group": eligibility_changes,
        },
        "ladder": {"baseline": ladder(BASE), "comparison": ladder(COMP)},
        "charged_output": {
            "added_existing_households": {
                "rows": sum(
                    d.added_charged for d in deltas.values() if d.status == "existing"
                ),
                "charge_gbp_exact": str(added_existing),
            },
            "added_new_households": {
                "rows": sum(
                    d.added_charged for d in deltas.values() if d.status == "new"
                ),
                "charge_gbp_exact": str(added_new),
            },
            "removed": {
                "rows": len(removed_rows),
                "charge_gbp_exact": str(removed_total),
            },
            "changed": {
                "rows": len(changed_rows),
                "delta_gbp_exact": str(changed_total),
            },
        },
        "reconciliation": {
            "baseline_charge_gbp_exact": str(total_b),
            "plus_added_existing_households": str(added_existing),
            "plus_added_new_households": str(added_new),
            "minus_removed": str(removed_total),
            "plus_changed": str(changed_total),
            "explained_adjustment": str(explained),
            "comparison_charge_gbp_exact": str(total_c),
            "residual_gbp_exact": str(residual),
            "residual_is_zero": residual == 0,
        },
        "affected_households": [
            {
                "household_id": d.household_id,
                "status": d.status,
                "added_charged": d.added_charged,
                "added_charge_gbp_exact": str(d.added_charge),
                "removed_charged": d.removed_charged,
                "removed_charge_gbp_exact": str(d.removed_charge),
                "changed_charged": d.changed_charged,
                "changed_delta_gbp_exact": str(d.changed_delta),
                "net_gbp_exact": str(d.net),
                "source_members_of_added_rows": d.source_members_added,
                "removed_detail": d.removed_detail,
            }
            for d in affected
        ],
    }


def summarise(report: dict[str, Any]) -> str:
    """A short markdown summary; the JSON carries the detail and every source reference."""
    r, co = report["reconciliation"], report["charged_output"]
    b, c = report["ladder"]["baseline"], report["ladder"]["comparison"]
    d, disagree = report["distinct_readings"], report["disagreements"]

    def money(value: str) -> str:
        return f"£{Decimal(value):,.2f}"

    baseline_members = " + ".join(
        m.split("/")[-1] for m in report["members"]["baseline"]
    )
    added = ", ".join(m.split("/")[-1] for m in report["members"]["added"])
    lines = [
        f"# Source expansion: {baseline_members} → plus {added}",
        "",
        f"Scenario under assumption **{report['assumption']}** — not a bill. {report['kind']}.",
        "",
        "| | Baseline | Comparison | Change |",
        "|---|---:|---:|---:|",
        f"| Loaded members | {len(report['members']['baseline'])} | {len(report['members']['baseline']) + len(report['members']['added'])} | +{len(report['members']['added'])} |",
        f"| Households recorded | {report['households']['baseline']:,} | {report['households']['comparison']:,} | +{len(report['households']['new']):,} new |",
        f"| Households charged | {b['charged_households']:,} | {c['charged_households']:,} | {c['charged_households'] - b['charged_households']:+,} |",
        f"| Raw rows | {b['raw_rows']:,} | {c['raw_rows']:,} | {c['raw_rows'] - b['raw_rows']:+,} |",
        f"| Distinct readings | {b['distinct_readings']:,} | {c['distinct_readings']:,} | {c['distinct_readings'] - b['distinct_readings']:+,} |",
        f"| Charged readings | {b['charged']:,} | {c['charged']:,} | {c['charged'] - b['charged']:+,} |",
        f"| Charged kWh | {Decimal(b['charged_kwh_exact']):,.3f} | {Decimal(c['charged_kwh_exact']):,.3f} | {Decimal(c['charged_kwh_exact']) - Decimal(b['charged_kwh_exact']):+,.3f} |",
        f"| Scenario charge | {money(b['charge_gbp_exact'])} | {money(c['charge_gbp_exact'])} | {Decimal(c['charge_gbp_exact']) - Decimal(b['charge_gbp_exact']):+,.2f} |",
        "",
        "## Where the added rows went",
        "",
        (
            f"- {d['added_member_rows']:,} rows in the added member(s): "
            f"{d['new_for_existing_households']:,} new readings for existing households, "
            f"{d['new_for_new_households']:,} for newly encountered households, "
            f"{d['already_in_baseline_exact_duplicate']:,} exact duplicates of baseline "
            f"rows, {d['already_in_baseline_equivalent_representation']:,} equivalent "
            f"representations, {d['repeats_within_added_members']:,} repeats within the "
            f"added member(s). Identity holds: {d['identity_holds']}."
        ),
        *[
            (
                f"- {r['readings']:,} new reading(s) for **{r['household_status']}** "
                f"household(s) produced no charge: `{r['exclusion_reason']}`, "
                f"{r['first_source_date']} to {r['last_source_date']}."
            )
            for r in report["new_readings_not_charged"]
        ],
        (
            f"- New conflicting labels: {len(disagree['new_conflicting_labels']):,}; "
            f"resolved: {disagree['resolved_conflicting_labels']:,}; households now "
            "under more than one tariff group: "
            f"{len(disagree['households_now_under_more_than_one_tariff_group']):,}."
        ),
        "",
        "## Reconciliation (exact Decimal)",
        "",
        "| | GBP (exact) |",
        "|---|---:|",
        f"| Baseline charge | {r['baseline_charge_gbp_exact']} |",
        f"| + added, existing households ({co['added_existing_households']['rows']:,} rows) | {r['plus_added_existing_households']} |",
        f"| + added, new households ({co['added_new_households']['rows']:,} rows) | {r['plus_added_new_households']} |",
        f"| − removed ({co['removed']['rows']:,} rows) | {r['minus_removed']} |",
        f"| ± changed ({co['changed']['rows']:,} rows) | {r['plus_changed']} |",
        f"| = comparison charge | {r['comparison_charge_gbp_exact']} |",
        f"| **residual** | **{r['residual_gbp_exact']}** ({'exactly zero' if r['residual_is_zero'] else 'NOT ZERO — unexplained'}) |",
        "",
        "## Affected households (largest net change first)",
        "",
        "| Household | Status | Added rows | Removed rows | Net £ (exact) | Added rows came from |",
        "|---|---|---:|---:|---:|---|",
    ]
    for h in report["affected_households"][:40]:
        src = ", ".join(
            f"{m.split('/')[-1]}: {n:,}"
            for m, n in h["source_members_of_added_rows"].items()
        )
        lines.append(
            f"| {h['household_id']} | {h['status']} | {h['added_charged']:,} | {h['removed_charged']:,} | "
            f"{h['net_gbp_exact']} | {src} |"
        )
    if len(report["affected_households"]) > 40:
        lines.append(
            f"| … {len(report['affected_households']) - 40} more in the JSON | | | | | |"
        )
    lines += [
        "",
        (
            "Additional loaded coverage is what changed. Nothing here is a changed "
            "behaviour, a higher bill or a saving."
        ),
    ]
    return "\n".join(lines) + "\n"


def write_report(report: dict[str, Any], directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"{report['baseline_run_id'][:12]}-vs-{report['comparison_run_id'][:12]}"
    json_path = directory / f"{stem}.json"
    md_path = directory / f"{stem}.md"
    json_path.write_text(json.dumps(report, indent=2, default=str) + "\n")
    md_path.write_text(summarise(report))
    return json_path, md_path
