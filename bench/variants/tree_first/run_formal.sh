#!/usr/bin/env bash
# R3 driver (tree-first conditions X1, X1_sonnet, X2, S_shot_lean, X2_lean + the R1 S_shot control).
# Resumable: rerunning skips finished episodes.  From the repository root:
#
#   PY=python OUT=out/r3/formal bash bench/variants/tree_first/run_formal.sh
#
# Environment:
#   PY            Python interpreter with the bench dependencies (default: python)
#   OUT           output directory (default: out/r3/formal)
#   DISPLAYS      three Xvfb display numbers, comma separated (default :150,:151,:152; the first one also names the
#                 resident perception server)
#   FREEZE_SHA    optional git commit; the runner refuses to start when the frozen env / apps / task files differ from it
#   R1_ROWS       optional R1 rows file (episodes_v1_1.jsonl); the analysis then compares this batch's S_shot with it
#   NIGHT_HHMM    optional, e.g. 2340: write <OUT>/STOP when the local time passes it
#
# 1. makes sure the shared ours perception server answers (starts it if not);
# 2. pass 1: rep 0 of S_shot, X1, X2, S_shot_lean, X2_lean, X1_sonnet; pass 2: reps 1-2 of the five Haiku conditions;
#    bench.agent.run plan_jobs order = tasks shuffled (seed 0), per (task, rep) all conditions adjacent with a rotating start;
# 3. a watchdog loop next to the runner writes <OUT>/STOP (episodes in progress finish, no new one starts) when
#      - NIGHT_HHMM is set and the local time has passed it  -> reason "night"
#      - date >= 2026-11-15 (the calendar tasks assume the week 2026-11-08..14) -> reason "date"
# 4. when all rows exist: regrade with oracle v1.1 and run the analysis.
set -u
PY=${PY:-python}
OUT=${OUT:-out/r3/formal}
DISPLAYS=${DISPLAYS:-:150,:151,:152}
SERVER_DISPLAY=${DISPLAYS%%,*}
LOG=$OUT.log
mkdir -p "$OUT" "$OUT/servers"

log() { echo "$(date '+%F %T') $*" >> "$LOG"; }

ensure_server() {
  if "$PY" -c "from bench.variants.tree_first import ours_client; ours_client.ping('$SERVER_DISPLAY')" 2>/dev/null; then return 0; fi
  log "ours server not answering: starting it"
  setsid nohup "$PY" -m bench.variants.tree_first.ours_server --display "$SERVER_DISPLAY" >> "$OUT/servers/ours.log" 2>&1 < /dev/null &
  for _ in $(seq 1 60); do
    sleep 5
    "$PY" -c "from bench.variants.tree_first import ours_client; ours_client.ping('$SERVER_DISPLAY')" 2>/dev/null && { log "ours server up"; return 0; }
  done
  log "ours server failed to start"; return 1
}

stop_with() {  # reason; keeps an existing STOP (first reason wins)
  [ -e "$OUT/STOP" ] || { echo "$1 $(date '+%F %T')" > "$OUT/STOP"; log "STOP written: $1"; }
}

watchdog() {
  while true; do
    [ -n "${NIGHT_HHMM:-}" ] && [ "$(date +%H%M)" -ge "$NIGHT_HHMM" ] && stop_with "night"
    [ "$(date +%Y%m%d)" -ge 20261115 ] && stop_with "date"
    sleep 30
  done
}

run_batch() {  # conds reps
  local freeze=()
  [ -n "${FREEZE_SHA:-}" ] && freeze=(--freeze-sha "$FREEZE_SHA")
  "$PY" -m bench.agent.run --plugin bench.variants.tree_first.conds --conds "$1" --tasks all --reps "$2" --parallel 3 \
      --displays "$DISPLAYS" --out "$OUT" "${freeze[@]}" >> "$LOG" 2>&1
}

complete() {  # true when the runner has nothing left to do for both batches
  grep -q "^0 episodes to run" <(tail -n 400 "$LOG" | grep "episodes to run" | tail -n 2 | head -n 1) 2>/dev/null &&
  grep -q "^0 episodes to run" <(tail -n 400 "$LOG" | grep "episodes to run" | tail -n 1) 2>/dev/null
}

log "driver start HEAD=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
ensure_server || exit 1
watchdog & WD=$!
trap 'kill $WD 2>/dev/null' EXIT
while true; do
  [ -e "$OUT/STOP" ] && { log "STOP present ($(cat "$OUT/STOP")): driver exits"; exit 0; }
  ensure_server || exit 1
  # pass 1 = rep 0 of all six conditions (X1_sonnet interleaved with the Haiku ones, same task adjacent);
  # pass 2 = reps 1-2 of the five Haiku conditions (rep 0 rows are skipped as complete)
  run_batch S_shot,X1,X2,S_shot_lean,X2_lean,X1_sonnet 1
  [ -e "$OUT/STOP" ] && continue
  run_batch S_shot,X1,X2,S_shot_lean,X2_lean 3
  [ -e "$OUT/STOP" ] && continue
  if complete; then break; fi        # a pass that still had work (errors requeued): go round once more
done
log "all episodes done; regrade v1.1 + analysis"
"$PY" -m bench.agent.regrade "$OUT" --oracles v1_1 --tag v1_1 >> "$LOG" 2>&1
ref=()
[ -n "${R1_ROWS:-}" ] && ref=(--ref-r1 "$R1_ROWS")
"$PY" -m bench.variants.tree_first.analyze "$OUT/episodes_v1_1.jsonl" --out "$OUT/analysis" --sample-failures 15 \
    "${ref[@]}" >> "$LOG" 2>&1
log "driver finished"
