#!/usr/bin/env bash
# Trace the ACTUAL dbt child directly (companion to dbt-segv-repro.sh).
#
#   bash tools/dbt-segv-trace.sh                                  # 20 attempts
#   LABEL=B ATTEMPTS=40 EXTRA_ENV="PYTHONMALLOC=debug" bash tools/dbt-segv-trace.sh
#
# Why a wrapper and not `.venv/bin/dbt`: PYTHONFAULTHANDLER writes to stderr, where dbt's
# own output and the multiprocessing resource_tracker's warnings interleave with it -- the
# first attempt at this lost the frame list that way. Here faulthandler writes all-thread
# stacks to a private file instead. The wrapper runs the same interpreter and calls the
# same `dbt.cli.main:cli` the console script calls, with the same argv, cwd and env, so
# the traced process IS the dbt process.
#
# Original, with faulthandler writing all-thread Python stacks
# to a private file (so nothing can interleave with it). The wrapper IS the dbt process
# -- same interpreter, same argv, same cwd, same env -- so a SIGSEGV kills it and the
# shell sees the real signal status. No debugger wrapping, no status laundering.
set -u
cd "$(dirname "$0")/.." || exit 2
DIR="${DIR:-data/proof-scratch/segv-trace}"   # git-ignored
LABEL="${LABEL:-A}"; ATTEMPTS="${ATTEMPTS:-20}"; BUDGET="${BUDGET:-900}"
EXTRA_ENV="${EXTRA_ENV:-}"
PY="$PWD/.venv/bin/python3"
PROJECT="$PWD/dbt"
START=$SECONDS; ok=0; crashed=0; other=0
echo "budget: $ATTEMPTS attempts or ${BUDGET}s · label=$LABEL · extra env: ${EXTRA_ENV:-none}"
for i in $(seq 1 "$ATTEMPTS"); do
  [ $((SECONDS-START)) -ge "$BUDGET" ] && { echo "CHECKPOINT: time budget reached at attempt $i"; break; }
  db="$DIR/$LABEL-$i.duckdb"; tgt="$DIR/$LABEL-$i-target"
  fh="$DIR/$LABEL-$i.faulthandler.txt"; out="$DIR/$LABEL-$i.out"
  cp data/warehouse/demo.duckdb "$db"
  RUN_ID="dbtcand-trace@$(date +%Y%m%dT%H%M%S%N)"
  env $EXTRA_ENV PYTHONFAULTHANDLER=1 ENERGY_RECONCILIATION_DB="$PWD/$db" \
    "$PY" -c '
import sys, faulthandler
fh = open(sys.argv[1], "w")
faulthandler.enable(file=fh, all_threads=True)
sys.argv = ["dbt"] + sys.argv[2:]
from dbt.cli.main import cli
sys.exit(cli())
' "$PWD/$fh" build --target-path "$PWD/$tgt" --project-dir "$PROJECT" \
    --profiles-dir "$PROJECT" \
    --vars "{\"schedule\": \"demo\", \"workbook\": \"\", \"tariff_group\": \"ToU\", \"run_id\": \"$RUN_ID\"}" \
    > "$out" 2>&1
  rc=$?
  if [ "$rc" -eq 0 ]; then ok=$((ok+1)); rm -rf "$db" "$tgt" "$fh" "$out"
  elif [ "$rc" -ge 128 ]; then
    crashed=$((crashed+1)); sig=$((rc-128))
    echo "  CRASH attempt $i rc=$rc (signal $sig) -- faulthandler file: $fh"
    rm -rf "$db" "$tgt"
  else other=$((other+1)); echo "  non-zero rc=$rc attempt $i (kept $out)"; rm -rf "$db" "$tgt"; fi
done
echo "RESULT label=$LABEL attempts=$((ok+crashed+other)) ok=$ok crashed=$crashed other=$other elapsed=$((SECONDS-START))s"
