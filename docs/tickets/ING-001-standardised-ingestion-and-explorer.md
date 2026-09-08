# ING-001 — Standardised ingestion and household data-quality explorer

| Field | Value |
|---|---|
| Ticket | ING-001 |
| Milestone | M2 (partial) — first visible product slice |
| Depends on | REP-001 findings in `docs/source-data-profile.md` |
| Out of scope | Billing, tariff joins, forecasting, AI features, cloud |

## Purpose

Turn the verified source understanding into something a person can look at: load records into a
local database with a stable schema, and browse one household's data quality.

## Sources

- `data/demo/demo-lcl-sample.zip` — the committed synthetic fixture.
- Members **4** and **5** of `Partitioned LCL Data.zip`. They are chosen because REP-001 §13.4
  established that household `MAC000166` appears in **both**, so cross-file handling is exercised
  by real data rather than only by a fixture.

**These two members are 2 of 168. They do not contain every household's complete history**, and
nothing in the output may imply otherwise.

## Rerun policy — decided

**Content-addressed replace, per member.**

On load, the member's decompressed content SHA-256 is compared with the last successful load of
that archive+member:

| Situation | Action |
|---|---|
| Never loaded | Insert; register the load. |
| Loaded before, content identical | **Skip entirely.** No rows touched, no new load id. |
| Loaded before, content differs | Delete that member's rows and insert the new read, in one transaction. |

Rationale. Skipping on an identical digest makes an unchanged rerun a provable no-op, which is
what M2's "rerunning identical inputs does not duplicate published output" asks for, and it is
cheap. Replacing on a changed digest means a corrected source file supersedes the old load rather
than accumulating beside it. Refusing without a flag was rejected: it makes reruns non-idempotent
by default, which becomes an obstacle once Airflow re-executes tasks (M5).

Scope of the replace is one archive+member. Loading member 5 never disturbs member 4.

## Failure policy

A load runs inside a single transaction and the registry row is written in that same transaction.
If anything raises, the transaction rolls back: the previously published dataset and its registry
entry survive untouched. A partially written load is never visible and never marked published.

## Decimal handling

Consumption is stored as `DECIMAL(28,10)` — up to 10 decimal places, with 18 integer digits of
headroom. The highest precision REP-001 observed is 7 decimal places (`6.5279999`), so a
`DECIMAL(18,7)` column would have had no headroom at all: one member carrying an eighth digit
would start rejecting real readings. *(Corrected 2026-09-08: this section said `DECIMAL(18,7)`;
the shipped schema in `ingest/warehouse.py` has always been `DECIMAL(28,10)`.)*

**Values are never silently rounded.** A value whose scale exceeds 10 decimal places, or whose
magnitude exceeds the precision, is **not** stored as a reading; it is written to
`rejected_records` with reason `excessive_precision` or `value_overflow`, keeping the source text.
Rounding a meter reading to fit a column is a silent data change and is prohibited here.

## What must stay distinguishable

| Case | Where it lives |
|---|---|
| Finite reading | `readings`, `value_category = 'finite_numeric'`, `consumption_kwh` set |
| `Null` token | `readings`, `value_category = 'null_token'`, `consumption_kwh` NULL |
| Empty / unexpected token / non-finite | `readings`, own `value_category`, `consumption_kwh` NULL |
| Wrong field count, invalid timestamp, precision/overflow | `rejected_records` with a reason |
| Exact duplicate rows | kept in `readings`; identified by view |
| Conflicting candidate keys | kept in `readings`; identified by view |

Duplicates and conflicts are **not** removed at load. The source is recorded as it is; resolution
is a later, separate decision (REP-001 §12).

## Timestamps

`source_timestamp_text` holds the exact source characters. `observed_at_naive` is the parsed value
with **no timezone attached**. Every row carries `timezone_status = 'unresolved'` and
`interval_anchor_status = 'unresolved'`, so no consumer can mistake the parsed value for an instant.

## Review outcomes (2026-09-08)

Seven defects were found and fixed after the first implementation.

| Defect | Fix |
|---|---|
| The skip decision compared only source content, so changing the transformation left rows built by old logic in place | A pipeline fingerprint over the ingest and profiling sources plus the decimal shape now takes part in the decision. Unchanged source **and** unchanged pipeline skips; either changing rebuilds. |
| `load_id` was derived from content and pipeline, so reverting a code change collided with the retained superseded row | A load id now identifies a load *event* and carries the moment as well as the digests. |
| Replacing a member deleted its registry row, leaving no trace an earlier load existed | The earlier row is marked `superseded` with a timestamp. Its readings are still replaced; recovering them means re-loading the earlier file. |
| Totals deduplicated on member name, the duplicate views did not | One shared definition, `v_distinct_readings`, keyed on household, source timestamp text, tariff group and raw consumption text. Totals, chart and counters all use it. |
| The chart drew a straight line across absent timestamps, implying continuity never observed | A single blank row is inserted at each gap to break the line. It is a visual break only; no interval count is implied. |
| Gaps and repeated timestamps were reported in one list, so a 0-second repeat appeared as a "discontinuity" | Reported separately. A repeat is not a hole and a hole is not a repetition. |
| Decimal scale was 7, exactly the highest precision observed, leaving no headroom | `DECIMAL(28,10)`. Values still beyond that are rejected with their source text, never rounded. |

**Atomicity is per member, not per run.** Each member loads in its own transaction. A
two-member command that fails on the second leaves the first published and registered.
That is deliberate — one bad member should not discard a good one — but it means a
multi-member command is not all-or-nothing.

## Explorer review outcomes (2026-09-08, second pass)

An independent review of the rendered explorer against the code found six further defects.

| Defect | Fix |
|---|---|
| The Data quality counters covered the whole household while Overview and Source records covered the selected period — one page, two silent scopes | Every query takes the same `start`/`end`. The whole-history figures survive only in an expander that says so. |
| The explorer's dedup key omitted the raw consumption text while `v_exact_duplicates` keys on it, so `' 0.5 '` and `' 0.50 '` collapsed in totals but not in the counter | One key (`household, tariff, source timestamp text, raw consumption text`) in both places, with a test that the two texts do **not** collapse. |
| The half-hour detail chart drew straight across absent half-hours; the earlier "line breaks" only existed in a series the UI never displayed | Break insertion is a shared helper applied to the detail chart, with a test asserting where the break lands. |
| "Fewer readings than a full day" compared each day with 48 — a completeness verdict the clock semantics cannot support | Removed. Days carry counts, duplicates collapsed, missing values, observed gaps and a boundary-day flag. Days inside the recorded span with no rows appear as "no readings recorded". |
| "No concerns" status; duplicate removal invisible when no repeats survived deduplication | `review_status()` says at most "No detected conflicts or internal gaps", always with the caveat that boundary coverage and clock semantics are unresolved, and always names how many identical readings were collapsed. |
| Repeated naive timestamps described as "the same instant" | Reworded: the same source timestamp *text* on readings that differ; whether a clock change or a source duplication caused it is unknown. |
| The date widget carried no household key, so switching to a household whose span excluded the stored date could raise | Period controls are keyed by household and reset to a preset anchored to that household's last recorded date. |

**Issues requiring review** is defined as missing values + observed gaps + conflicting
timestamps within the selected period. Repeated identical readings are deliberately not
issues: the duplicate policy collapses them and the count collapsed is shown separately.

## Analytical resolution policy (2026-09-08, third pass)

Traced from the rendered demo: the conflict day showed "total withheld" beside a 3.5 kWh
bar. The bar summed **both** disputed values at 03:30. Fixed, with the policy below.

**At one household + source timestamp label, three kinds of repetition are kept apart:**

| Kind | Definition | Treatment |
|---|---|---|
| Exact duplicate rows | Identical raw text | Collapsed everywhere; count reported as *duplicates removed* |
| Equivalent representations | Different raw texts, one numeric value (`' 0.5 '`, `' 0.50 '`) | Both rows kept as evidence; the value enters a total **once**; not a conflict |
| Conflict | More than one numeric value, or a number beside a non-numeric token | Day total and period total **withheld** (NULL, not zero); readings that exist still counted as *available* |

**Totals** sum each distinct (label, value) of finite readings once, grid or off-grid,
as Decimal in the database. A withheld day carries no number anywhere downstream: the
chart draws a labelled baseline marker for it, never a bar. In half-hour detail,
conflicting observations are plotted as flagged points with member and record number,
and the line is broken at the disputed label rather than passing through it.

**Steps** are computed between consecutive *distinct grid* timestamp labels inside the
selection, across midnight. Each gap is one event attributed to the date of the reading
after it, so daily gap counts sum to the period count. Off-grid observations are counted
separately and never form part of the step sequence. A step across the selection edge is
not counted; nothing outside the selection is read for context, so no neighbouring
record can enter a total. A gap is an observed step, not a confirmed missing interval
or a meter failure.

## Closing policies (2026-09-08, fourth pass)

**`Null` beside a number at one timestamp is an unresolved disagreement.** The affected
day and period totals are withheld; both rows are preserved with provenance. This is
**our analytical policy, not a publisher rule** — the source documentation says nothing
about it, and nothing here infers that the meter produced either row.

**Off-grid observations are excluded from half-hour analytical totals.** The period
total, daily totals and the detail line use grid readings only. Off-grid rows remain
counted (`off_grid_observations`, per-day `off_grid_rows`), listed with member and record
number, and plotted as separate flagged points. Rationale: the step policy already treats
the half-hour grid as the analytical series; every off-grid row seen in the real member 0
carried `Null`; and summing an off-grid value into a "kWh per half hour" total attributes
energy to a slot that does not exist on the grid. The profiler's descriptive statistics
over source values are a different instrument and are unchanged by this.

**"Items for review"** = missing values + gaps + conflicting timestamps + off-grid
observations in the period — a sum across four categories, not a count of unique records;
one row can appear under more than one heading. Off-grid is included so an excluded reading
can never vanish from view.

**All-unavailable chart state.** When no selected date has a publishable total, the daily
view is a status strip with no kWh axis: "withheld — conflicting readings",
"no observations" and "no half-hour-grid readings" are distinct statuses, none of them zero.
Mixed selections keep bars for valid days.

## Acceptance criteria

1. Loading the same unchanged member twice does not change any row count.
2. A load that fails partway leaves the previous published dataset and registry entry intact.
3. Every source record is either in `readings` or in `rejected_records`; the two reconcile to the
   records read.
4. A household present in members 4 and 5 shows records from both, labelled by member.
5. `Null` values, exact duplicates and conflicting candidate keys are each separately countable.
6. The explorer withholds any consumption total for a household affected by an unresolved conflict.
7. The explorer states which members are loaded and that coverage may be partial.
