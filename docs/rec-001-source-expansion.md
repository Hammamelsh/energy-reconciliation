# REC-001 — Reproducing a result, and explaining what more source changed

**Date:** 2026-09-08. **Status:** measured; residual exactly zero. **Nothing here is a
bill, a saving, or a change in behaviour** — it is additional loaded coverage.

This answers the project's question for one kind of change: *what did we calculate at the
time, what would we calculate now, and can we explain every difference?*

## 1. The accepted baseline, identified by content

Not by filename. `4b3ee235d7ac@20260908T133513.json` is the accepted baseline because its
`run_id` **and** `scenario_fingerprint` match the live published run, its
`calculation_code_sha256` matches the current code, its price catalogue version and
assumption id match, and it is the only baseline carrying a charged-row digest. The four
earlier baselines are kept, unmodified, as the record of the two fingerprint defects the
replay found (ANL-002 §9.3).

**What the charged-row digest covers, exactly:** `household_id`, `source_timestamp_text`,
`band_label`, `consumption_kwh`, `energy_charge_gbp`, ordered by household, label, band.

**What it does not cover:** the fact table carries **no** `member_name` and no
`source_record_no`, so the digest proves the charged *output* is identical row for row. It
does **not** prove each charged row came from the same source member or record — that
lineage lives in `readings`, and is verified separately by the member content digests
checked before replay. Lineage equality is claimed only to that extent.

## 2. Reproduction

```bash
uv run replay-baseline --baseline data/baselines/4b3ee235d7ac@20260908T133513.json \
  --database data/warehouse/rec001-baseline-4b3ee235d7ac.duckdb
```

The target did not exist beforehand (checked), and replay refuses an existing database.
Result: **17 of 17 fields matched, 0 differ**, including the exact total, every per-band
charge, all 27 per-household charges, the scenario fingerprint and the charged-row digest.

## 3. The comparison warehouse

Built separately, never by loading into the reproduced baseline: members 4, 5, 135 — the
same bytes, verified by content digest — then **member 136**. Every identity field is
equal to the baseline's: calculation code, policy, model code, runtime, price catalogue
version, assumption, schedule digest, ingestion pipeline. The comparison refuses to run
if any of them differs, because the difference would no longer be attributable to source.

## 4. Grains

| Grain | Definition |
|---|---|
| Raw row | one line of a source member, as loaded |
| Distinct reading | one (household, source timestamp label, value signature); exact duplicates and equivalent representations collapse into it |
| Charged output | one (household, source timestamp label) with band, kWh and charge; at most one per key, since a disputed label is excluded entirely |

## 5. Measured result

| | Baseline | Comparison | Change |
|---|---:|---:|---:|
| Loaded members | 3 | 4 | +1 |
| Households recorded | 83 | 113 | +30 new |
| Households charged | 27 | 57 | +30 |
| Raw rows | 3,000,000 | 4,000,000 | +1,000,000 |
| Distinct readings | 2,997,962 | 3,997,276 | +999,314 |
| Charged readings | 456,096 | 963,663 | +507,567 |
| Charged kWh | 85,467.133 | 173,195.214 | +87,728.081 |
| Scenario charge | £11,675.43 | £23,820.50 | +£12,145.07 |

**Where the million added rows went**, at the distinct-reading grain:
`1,000,000 = 686 + 0 + 0 + 997,989 + 1,325` and `3,997,276 = 2,997,962 + 999,314`. Both
identities hold.

Two of those categories are easy to confuse, so they are counted separately:

| Category | Count | What it means |
|---|---:|---|
| Repeats **within** the added member | 686 | Two rows inside member 136 itself carry one household, label and value. They collapse to one distinct reading before anything else happens. Measured: **every one is at exactly `00:00:00`**, and **0** are conflicting — the same monthly-midnight duplication REP-001 §12 found elsewhere in the archive. |
| **Overlap with the baseline**, exact duplicate | 0 | A row in member 136 identical to one already loaded. |
| **Overlap with the baseline**, equivalent representation | 0 | A row in member 136 writing an already-loaded value a different way (`0.5` / `0.50`). |

Both overlap counts are zero **by construction, and it is worth saying why**: member 136
shares **no** (household, source timestamp label) key with the baseline at all. Its
households are new, except `MAC000298`, whose member-136 rows begin after its last
member-135 reading. So this expansion exercised the within-member path and left the
cross-member overlap path unexercised on real data — that path is covered by the
synthetic cases instead (`tests/test_rec001_comparison.py`), which is exactly the split
those tests exist for.

**Reconciliation, exact `Decimal`:**

| | GBP |
|---|---:|
| Baseline charge | `11675.4339216532500000` |
| + added, existing households (0 rows) | `0` |
| + added, new households (507,567 rows) | `12145.0654911822600000` |
| − removed (0 rows) | `0` |
| ± changed (0 rows) | `0` |
| = comparison charge | `23820.4994128355100000` |
| **residual** | **`0E-16` — exactly zero** |

## 6. Two findings

**Every added charge came from a household not previously loaded.** All 507,567 added
charged readings belong to the 30 new households in member 136; no existing household
gained a single charged reading. Member 136 is entirely `ToU`, like 135.

**A cross-file household gained observations and no charge.** `MAC000298` straddles the
135/136 boundary — REP-001 established that households span members, and here it is in
the tariff output. Its 1,326 rows in member 136 run **2014-01-31 10:00 to 2014-02-28**,
giving 1,325 new distinct readings, **all excluded as `outside_schedule_period`** because
the dToU schedule covers 2013 only. More coverage, no charge. A further 490,422 new
readings for the new households are excluded for the same reason;
`507,567 + 490,422 = 997,989` accounts for every new reading in a new household.

**No conflicts, no removals, no eligibility changes.** 0 new conflicting labels, 0
resolved, 0 households recorded under more than one tariff group. That is a measurement
of this member, not a property of the archive: the comparison reports removals as
first-class, and a synthetic case proves it explains a decrease.

## 7. What this is not

Additional loaded coverage. **Not** a higher bill, a saving, a change in anyone's
consumption, or a change in behaviour by the pipeline. The charge rose because 30 more
households are now loaded, each priced under the same assumption **A1**, which remains
unestablished. Nothing here brings a historical cost closer.

## 8. Validation

Thirteen synthetic cases with expectations hand-derived in each docstring
(`tests/test_rec001_comparison.py`), including the case an "additions only" model gets
wrong: an added member carrying a **conflicting** observation withholds a charge the
baseline had, and the household's net change is **negative** despite gaining a reading.
Also covered: an overlapping exact duplicate that moves nothing, an equivalent
representation that is not a change, a member of pure duplicates, and three guards that
refuse a comparison whose warehouses differ in more than source.

## 9. Limits

- **A1 unresolved.** Everything above is a scenario.
- **4 members of 168**; 113 households are a bounded, non-representative subset.
- The charged-row digest establishes output equality, **not** source-row lineage (§1).
- The comparison assumes the baseline members' bytes are unchanged and verifies it; it
  does not detect a source file that changed *and* was reloaded identically by chance.
