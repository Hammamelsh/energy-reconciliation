#!/usr/bin/env bash
# Bounded reproducer for the intermittent dbt SIGSEGV (open release blocker).
#
# WHAT IT DOES
#   Runs sequential `run-dbt build` attempts against a throwaway copy of the demo
#   warehouse, each into its own fresh target directory, with PYTHONFAULTHANDLER=1 so a
#   crash prints a Python traceback (or, as observed, prints the thread header with no
#   Python frames -- which is itself the finding). It does NOT stop at the first crash:
#   it counts them, so a rate can be compared between two conditions.
#
# WHY IT EXISTS
#   `dbt build` segfaults intermittently. Observed 2 crashes in 294 recorded invocations
#   in ordinary use, and 1 in 66 attempts under this harness. The lifecycle handles every
#   crash correctly -- the attempt is recorded `failed`, nothing is sealed -- but an
#   unattended build cannot yet be relied on. See docs/tickets/ANL-003-dbt-port.md.
#
# USAGE
#   bash tools/dbt-segv-repro.sh                          # 60 attempts, 10 min budget
#   ATTEMPTS=200 SECONDS_BUDGET=1800 bash tools/dbt-segv-repro.sh
#   PROJECT=/path/to/dbt-copy LABEL=threads1 bash tools/dbt-segv-repro.sh
#
#   Always state the budget and report BOTH numbers (attempts and crashes). A crash-free
#   run is evidence about a rate, never proof that the fault cannot happen.
#
#   NOTE: this machine's clock has been observed to jump, so the elapsed seconds printed
#   below are not dependable. The attempt count is.
set -u
cd "$(dirname "$0")/.." || exit 2
DIR="${DIR:-data/proof-scratch/segv-repro}"          # git-ignored
PROJECT="${PROJECT:-$PWD/dbt}"
ATTEMPTS="${ATTEMPTS:-60}"
SECONDS_BUDGET="${SECONDS_BUDGET:-600}"
LABEL="${LABEL:-baseline}"
SOURCE="${SOURCE:-data/warehouse/demo.duckdb}"

[ -f "$SOURCE" ] || { echo "no source warehouse at $SOURCE"; exit 2; }
mkdir -p "$DIR"
START=$(date +%s); ok=0; crashed=0; other=0
echo "budget: $ATTEMPTS attempts or ${SECONDS_BUDGET}s · project $PROJECT · label $LABEL"
for i in $(seq 1 "$ATTEMPTS"); do
  [ $(( $(date +%s)-START )) -ge "$SECONDS_BUDGET" ] && { echo "BUDGET: time limit reached at attempt $i"; break; }
  db="$DIR/$LABEL-$i.duckdb"; tgt="$DIR/$LABEL-$i-target"; log="$DIR/$LABEL-$i.stderr"
  cp "$SOURCE" "$db"
  PYTHONFAULTHANDLER=1 uv run run-dbt --database "$db" --project-dir "$PROJECT" \
      --schedule demo build --target-path "$PWD/$tgt" > "$log" 2>&1
  rc=$?
  if [ "$rc" -eq 0 ]; then
    ok=$((ok+1)); rm -rf "$db" "$tgt" "$log"
  elif [ "$rc" -eq 245 ]; then     # 256-11: killed by SIGSEGV
    crashed=$((crashed+1))
    echo "  CRASH attempt $i · last console line: $(sed 's/\x1b\[[0-9;]*m//g' "$log" | grep -E '^[0-9]{2}:[0-9]{2}:[0-9]{2}' | tail -1 | cut -c11-80)"
    echo "    stderr kept at $log ; see dbt/logs/dbt.log for the node it reached"
    rm -rf "$db" "$tgt"
  else
    other=$((other+1)); echo "  non-zero rc=$rc attempt $i (kept $log)"; rm -rf "$db" "$tgt"
  fi
done
echo "RESULT label=$LABEL attempts=$((ok+crashed+other)) ok=$ok crashed=$crashed other=$other (elapsed ~$(( $(date +%s)-START ))s, clock unreliable)"
