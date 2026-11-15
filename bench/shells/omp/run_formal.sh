#!/usr/bin/env bash
# R5 driver: one lane per reader model, each lane = `python -m bench.shells.omp.run` repeated until a pass has nothing
# left to run.  Resumable: rerunning skips finished episodes.  From the repository root:
#
#   PY=python OUT=out/r5 bash bench/shells/omp/run_formal.sh glm:150 deepseek:151 longcat:152 haiku:153
#
# Lane spec: <model>:<display number>[+<display number>...]  (several displays = several workers for that model).
#
# Environment:
#   PY             Python interpreter with the bench dependencies (default: python)
#   OUT            output root; lane <model> writes to $OUT/<model>/$BENCH_OMP_OUT_SUB (default: out/r5)
#   BENCH_OMP_OUT_SUB  output subdirectory per model (default: formal)
#   BENCH_OMP_FIRST    only the first N tasks of the stratified order (default 24; use 48 for all tasks)
#   FREEZE_SHA     optional git commit; the runner refuses to start when the frozen env / apps / task files differ
#   PAUSE_FILE     optional path: while it exists no new episode starts (create / remove it yourself)
#
# 1. makes sure the shared ours perception server answers (starts it on the first lane's display if not);
# 2. one lane per model, repeated until a pass has nothing left to run (error rows are rerun) or <model>/<sub>/STOP exists
#    (run.py writes STOP itself: a provider quota error after 3 attempts, local time >= $BENCH_NIGHT_HHMM if set, or a date from which
#    the calendar tasks are no longer valid);
# 3. when a lane is finished: regrade with oracle v1.1.
set -u
PY=${PY:-python}
SUB=${BENCH_OMP_OUT_SUB:-formal}
W=${OUT:-out/r5}
LOG=$W/formal.log
mkdir -p "$W/servers"
log() { echo "$(date '+%F %T') $*" >> "$LOG"; }

first_display=":${1##*:}"; first_display=${first_display%%+*}

ensure_server() {
  if "$PY" -c "from bench.variants.tree_first import ours_client; ours_client.ping('$first_display')" 2>/dev/null; then return 0; fi
  log "ours server not answering: starting it"
  setsid nohup "$PY" -m bench.variants.tree_first.ours_server --display "$first_display" >> "$W/servers/ours.log" 2>&1 < /dev/null &
  for _ in $(seq 1 60); do
    sleep 5
    "$PY" -c "from bench.variants.tree_first import ours_client; ours_client.ping('$first_display')" 2>/dev/null && { log "ours server up"; return 0; }
  done
  log "ours server failed to start"; return 1
}

lane() {  # model display
  local m=$1 d=$2 out=$W/$1/$SUB pass=0
  local extra=()
  [ -n "${FREEZE_SHA:-}" ] && extra+=(--freeze-sha "$FREEZE_SHA")
  [ -n "${PAUSE_FILE:-}" ] && extra+=(--pause-file "$PAUSE_FILE")
  mkdir -p "$out"
  while true; do
    [ -e "$out/STOP" ] && { log "$m: STOP present ($(head -n 1 "$out/STOP")): lane exits"; return 0; }
    ensure_server || return 1
    pass=$((pass + 1))
    "$PY" -m bench.shells.omp.run --model "$m" --out "$out" --displays ":${d//+/,:}" \
        --first "${BENCH_OMP_FIRST:-24}" "${extra[@]}" >> "$W/$m/formal.log" 2>&1
    [ -e "$out/STOP" ] && continue
    if tail -n 400 "$W/$m/formal.log" | grep "episodes to run" | tail -n 1 | grep -q "^0 episodes to run"; then break; fi
    [ "$pass" -ge 4 ] && { log "$m: still errors after $pass passes; lane exits"; break; }
  done
  "$PY" -m bench.agent.regrade "$out" --oracles v1_1 --tag v1_1 >> "$W/$m/formal.log" 2>&1
  log "$m: lane finished, regraded"
}

log "driver start HEAD=$(git rev-parse --short HEAD 2>/dev/null || echo unknown) lanes: $*"
ensure_server || exit 1
pids=()
for spec in "$@"; do
  mkdir -p "$W/${spec%%:*}"
  lane "${spec%%:*}" "${spec##*:}" & pids+=($!)
done
wait "${pids[@]}"
log "driver finished"
