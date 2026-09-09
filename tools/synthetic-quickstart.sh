#!/usr/bin/env bash
# The documented synthetic demonstration, end to end, with its expected numbers checked.
#
#   bash tools/synthetic-quickstart.sh
#   DEMO_ROOT=/tmp/my-demo bash tools/synthetic-quickstart.sh
#
# Uses only the committed invented archive (data/demo/demo-lcl-sample.zip). It downloads
# nothing, needs neither the real dataset nor the publisher's workbook, and writes only
# inside DEMO_ROOT. It never touches data/published.
#
# Every figure asserted below is derivable by hand from the 12 rows of that archive; the
# comments say how. Exit 0 means the numbers matched, not merely that commands ran.
set -euo pipefail
cd "$(dirname "$0")/.."

DEMO_ROOT="${DEMO_ROOT:-data/proof-scratch/quickstart}"
ARCHIVE="data/demo/demo-lcl-sample.zip"

[ -f "$ARCHIVE" ] || { echo "missing $ARCHIVE (is this a full checkout?)" >&2; exit 2; }
if [ -e "$DEMO_ROOT" ]; then
  echo "refusing: $DEMO_ROOT already exists. Remove it first:" >&2
  echo "  chmod -R u+w '$DEMO_ROOT' && rm -rf '$DEMO_ROOT'" >&2
  exit 2
fi

WAREHOUSE="$DEMO_ROOT/warehouse/demo.duckdb"
PUBLISHED="$DEMO_ROOT/published"
say() { printf '\n=== %s ===\n' "$1"; }
fail() { echo "QUICKSTART FAILED: $1" >&2; exit 1; }
expect() {  # expect <description> <literal needle> <file>
  grep -qF -- "$2" "$3" || fail "$1 — expected to find: $2"
  printf '  ok  %s\n' "$1"
}
expect_re() {  # expect_re <description> <regex> <file> -- for column-aligned output
  grep -qE -- "$2" "$3" || fail "$1 — expected to match: $2"
  printf '  ok  %s\n' "$1"
}

say "1/6 ingest the invented archive"
uv run ingest-member --demo --database "$WAREHOUSE"

say "2/6 build a candidate with dbt (all models and all tests)"
uv run build-candidate --source "$WAREHOUSE" --root "$PUBLISHED" --schedule demo \
  | tee "$DEMO_ROOT/build.txt"
CANDIDATE="$(sed -n 's/^sealed //p' "$DEMO_ROOT/build.txt" | head -1)"
[ -n "$CANDIDATE" ] || fail "build-candidate did not report a sealed candidate"
expect "the build sealed only after every required node passed" \
       "5 models, 49 tests passed" "$DEMO_ROOT/build.txt"
expect "it did not publish anything by itself" \
       "READY FOR PROMOTION" "$DEMO_ROOT/build.txt"

say "3/6 promote inside the disposable root"
uv run publication --root "$PUBLISHED" promote "$CANDIDATE" --expect-published none

say "4/6 read it back through the validated read contract"
uv run publication --root "$PUBLISHED" read | tee "$DEMO_ROOT/read.txt"
# The archive holds 12 rows. One is an exact duplicate (03:00, 0.500 twice), so 11 are
# distinct. DEMO0001 is Std and the scenario is scoped to ToU, so its 9 distinct rows are
# excluded as ineligible_tariff_group; DEMO0002 is ToU with 2 rows, both charged.
expect "12 recorded rows collapse to 11 distinct"  "12 rows recorded → 11 distinct" "$DEMO_ROOT/read.txt"
expect "one row collapsed by policy"               "(1 collapsed by policy)"        "$DEMO_ROOT/read.txt"
expect "2 charged and 9 excluded, reconciling"     "2 charged + 9 excluded · reconciles True" "$DEMO_ROOT/read.txt"
expect_re "all 9 exclusions are the ineligible group" "excluded ineligible_tariff_group +9$" "$DEMO_ROOT/read.txt"
expect "every required dbt node passed"            "complete, 54 required dbt nodes passed" "$DEMO_ROOT/read.txt"
# 1.000 kWh in the Low band at 3.99 p/kWh = 0.0399; 1.125 kWh in the High band at
# 67.20 p/kWh = 0.756. Exact, unrounded, no float anywhere: 0.0399 + 0.756 = 0.7959.
expect "the Low band charge is exactly 1.000 x 3.99p"  "GBP 0.0399000000000000" "$DEMO_ROOT/read.txt"
expect "the High band charge is exactly 1.125 x 67.20p" "GBP 0.7560000000000000" "$DEMO_ROOT/read.txt"
expect "the total is exactly their sum"                 "GBP 0.7959000000000000" "$DEMO_ROOT/read.txt"

say "5/6 record a format-2 baseline of the published result"
uv run capture-published-baseline --root "$PUBLISHED" --directory "$DEMO_ROOT/baselines" \
  | tee "$DEMO_ROOT/capture.txt"
BASELINE="$(sed -n 's/^baseline : //p' "$DEMO_ROOT/capture.txt" | head -1)"
[ -n "$BASELINE" ] || fail "capture-published-baseline did not report a baseline path"

say "6/6 rebuild it from the archive alone, in a fresh destination, and compare"
# Re-ingests the recorded member from the archive and runs the supported build path
# again. Nothing is copied from the publication being checked.
uv run replay-published-baseline --baseline "$BASELINE" --into "$DEMO_ROOT/replay" \
  --archive "$ARCHIVE" | tee "$DEMO_ROOT/replay.txt"
expect "the rebuild reproduced every compared field" \
       "REBUILD REPRODUCED THE PUBLISHED RESULT EXACTLY." "$DEMO_ROOT/replay.txt"
expect "0 of the compared fields differed" "0 differ" "$DEMO_ROOT/replay.txt"

cat <<EOF

=== quickstart complete: every expected figure matched ===
published root : $PUBLISHED
candidate      : $CANDIDATE
baseline       : $BASELINE

View it in the dashboard (Ctrl-C to stop; then choose Source -> Published version):
  ENERGY_RECONCILIATION_PUBLICATION_ROOT="\$PWD/$PUBLISHED" \\
    PYTHONPATH=src uv run streamlit run src/energy_reconciliation/explorer/app.py

Remove everything this created:
  chmod -R u+w '$DEMO_ROOT' && rm -rf '$DEMO_ROOT'
EOF
