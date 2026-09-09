#!/usr/bin/env bash
# Run the ACTUAL dbt child under GDB, stopping at SIGSEGV, and classify the inferior's
# outcome from GDB's own report -- never from GDB's exit code.
#
#   bash tools/dbt-segv-gdb.sh                      # 20 attempts / 15 min, demo warehouse
#   ATTEMPTS=5 EXTRA_ENV="PYTHONMALLOC=debug" bash tools/dbt-segv-gdb.sh
#   LABEL=real ATTEMPTS=1 SOURCE=data/warehouse/energy.duckdb bash tools/dbt-segv-gdb.sh
#   VALIDATE=1 bash tools/dbt-segv-gdb.sh           # classification self-test only
#
# Fidelity notes (differences from `uv run run-dbt`, stated rather than hidden):
#   - The inferior is `.venv/bin/python3 -c <wrapper>` calling dbt.cli.main:cli, exactly
#     what tools/dbt-segv-trace.sh runs; same interpreter, argv, cwd (repo root) and env.
#   - GDB normally disables ASLR for its inferior; this harness turns that back on
#     (`set disable-randomization off`) so memory layout matches an ordinary run.
#   - GDB intercepts SIGSEGV before the process's own handler. After dumping native state
#     the harness `continue`s once, so faulthandler still writes its Python frames to the
#     private file; the re-raised signal stops GDB a second time and the inferior is killed.
#   - No Python-level GDB helpers (python-gdb.py) ship with this interpreter build, so
#     `py-bt` is unavailable; Python frames come from faulthandler's file instead.
#   - Timing under a debugger differs. A crash-free run here is not evidence of a fix.
#   - This harness is diagnostic only. It records nothing in any dbt_build_run table and
#     sits entirely outside the run-dbt / build-candidate attestation path.
#
# Outcome classes: completed | failed:<code> | signalled:<SIG> | timeout | unknown
set -u
cd "$(dirname "$0")/.." || exit 2
DIR="${DIR:-data/proof-scratch/segv-gdb}"      # git-ignored
ATTEMPTS="${ATTEMPTS:-20}"; BUDGET="${BUDGET:-900}"; PER_ATTEMPT="${PER_ATTEMPT:-300}"
EXTRA_ENV="${EXTRA_ENV:-}"; LABEL="${LABEL:-gdb}"
SOURCE="${SOURCE:-data/warehouse/demo.duckdb}"   # any loaded warehouse; never written to
PY="$PWD/.venv/bin/python3"; PROJECT="$PWD/dbt"
mkdir -p "$DIR"

GDB_SCRIPT="$DIR/stop-at-segv.gdb"
cat > "$GDB_SCRIPT" <<'GDB'
set pagination off
set confirm off
set disable-randomization off
set print thread-events off
handle SIGSEGV stop print nopass
handle SIGBUS stop print nopass
handle SIGABRT stop print nopass
run
echo \n===== STOP: info program =====\n
info program
echo \n===== inferior identity =====\n
info inferiors
info proc
echo \n===== faulting thread: registers =====\n
info registers
echo \n===== faulting thread: instructions around $pc =====\n
x/12i $pc-24
info symbol $pc
echo \n===== faulting thread: backtrace with locals =====\n
bt full 20
echo \n===== all threads: backtrace =====\n
thread apply all bt 30
echo \n===== shared libraries =====\n
info sharedlibrary
echo \n===== continue once so faulthandler writes its Python frames =====\n
handle SIGSEGV stop print pass
continue
echo \n===== second stop =====\n
info program
kill
GDB

classify() {  # $1 = gdb transcript, $2 = shell rc of `timeout gdb ...`
  local t="$1" rc="$2"
  if [ "$rc" -eq 124 ] || [ "$rc" -eq 137 ]; then echo "timeout"; return; fi
  if grep -q "Program received signal SIG[A-Z]*" "$t"; then
    echo "signalled:$(grep -o 'Program received signal SIG[A-Z]*' "$t" | head -1 | awk '{print $4}')"; return; fi
  if grep -q "exited normally" "$t"; then echo "completed"; return; fi
  if grep -qE "exited with code [0-7]+" "$t"; then
    echo "failed:$(( 8#$(grep -oE 'exited with code [0-7]+' "$t" | head -1 | awk '{print $4}') ))"; return; fi
  echo "unknown"
}

if [ "${VALIDATE:-0}" = "1" ]; then
  echo "== classification self-test on tiny disposable processes =="
  for case in "ok::import sys; sys.exit(0)" "nonzero::import sys; sys.exit(3)" \
              "segv::import os, signal; os.kill(os.getpid(), signal.SIGSEGV)" \
              "realsegv::import ctypes; ctypes.string_at(0)"; do
    name="${case%%::*}"; code="${case#*::}"; t="$DIR/validate-$name.gdb.txt"
    PYTHONFAULTHANDLER=1 timeout -k 5 60 gdb -q -batch -x "$GDB_SCRIPT" --args "$PY" -c "$code" > "$t" 2>&1
    rc=$?
    printf "  %-9s gdb-rc=%-3s classified=%s\n" "$name" "$rc" "$(classify "$t" "$rc")"
  done
  exit 0
fi

START=$SECONDS; declare -A n=([completed]=0 [failed]=0 [signalled]=0 [timeout]=0 [unknown]=0)
echo "budget: $ATTEMPTS attempts or ${BUDGET}s · per-attempt ${PER_ATTEMPT}s · label=$LABEL · extra env: ${EXTRA_ENV:-none}"
for i in $(seq 1 "$ATTEMPTS"); do
  [ $((SECONDS-START)) -ge "$BUDGET" ] && { echo "CHECKPOINT: time budget reached at attempt $i"; break; }
  db="$DIR/$LABEL-$i.duckdb"; tgt="$DIR/$LABEL-$i-target"
  fh="$DIR/$LABEL-$i.faulthandler.txt"; t="$DIR/$LABEL-$i.gdb.txt"
  cp "$SOURCE" "$db"
  RUN_ID="dbtcand-gdb@$(date +%Y%m%dT%H%M%S%N)"
  t0=$SECONDS
  env $EXTRA_ENV PYTHONFAULTHANDLER=1 ENERGY_RECONCILIATION_DB="$PWD/$db" \
    timeout -k 10 "$PER_ATTEMPT" gdb -q -batch -x "$GDB_SCRIPT" --args "$PY" -c '
import sys, faulthandler
fh = open(sys.argv[1], "w")
faulthandler.enable(file=fh, all_threads=True)
sys.argv = ["dbt"] + sys.argv[2:]
from dbt.cli.main import cli
sys.exit(cli())
' "$PWD/$fh" build --target-path "$PWD/$tgt" --project-dir "$PROJECT" --profiles-dir "$PROJECT" \
    --vars "{\"schedule\": \"demo\", \"workbook\": \"\", \"tariff_group\": \"ToU\", \"run_id\": \"$RUN_ID\"}" \
    > "$t" 2>&1
  rc=$?
  outcome="$(classify "$t" "$rc")"; kind="${outcome%%:*}"; n[$kind]=$(( ${n[$kind]:-0} + 1 ))
  if [ "$kind" = "completed" ]; then rm -rf "$db" "$tgt" "$fh" "$t"
  else echo "  attempt $i: $outcome  (${SECONDS}s-${t0}s=$((SECONDS-t0))s) -- kept $t"; rm -rf "$db" "$tgt"; fi
  [ "$kind" = "signalled" ] && { echo "STOP: first useful crash capture -- inspect $t and $fh"; break; }
done
echo "RESULT label=$LABEL completed=${n[completed]} failed=${n[failed]} signalled=${n[signalled]} timeout=${n[timeout]} unknown=${n[unknown]} elapsed=$((SECONDS-START))s"
