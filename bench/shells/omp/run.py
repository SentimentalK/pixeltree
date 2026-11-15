"""R5 runner: one reader model through OMP (`omp`, provider opencode-go) on the R1 test bench.

    python -m bench.shells.omp.run --model glm --out out/r5/glm/formal --displays :150 [--freeze-sha <sha>]

Models and conditions: `omp.MODELS` (glm / deepseek / haiku: S_shot, T_ours, H_ours; longcat: T_ours, T_atspi).
System prompt = `bench.agent.prompts.system_prompt(cond)`, plus the coordinate sentence for S_shot / H_ours (`shared.COORD_NOTE`), set on
every provider request by the R5 hook.  Tools = the bench MCP server (six tools, 20-call limit, step archive), T_ours /
H_ours trees from the resident ours service (bench.shells.omp.shared.load_service), tool calls of one message executed in
request order (bench.shells.omp.mcp_server; OMP sends them concurrently).  Order = `shared.schedule` (stratified by app,
random.Random(0), conditions of a task adjacent and rotating).  One worker per --displays entry.  Resumable
(finished (task, cond, rep) are skipped; error rows are rerun).

Stops between episodes (writes <out>/STOP): an OpenCode Go quota / rate-limit error that survives 3 attempts of the
same episode (60 s, 180 s) -> `quota_omp: <text>`; local time >= $BENCH_NIGHT_HHMM (optional) -> `night`.  While --pause-file exists
no new episode starts (run_formal.sh writes it while the provider's short-window usage is high).  From 2026-11-15 on the
gnome-calendar tasks are skipped (their oracle assumes 2026-11-08..14); the others continue.
After the run: `python -m bench.agent.regrade <out> --oracles v1_1 --tag v1_1`, then `python -m bench.shells.omp.analyze`.
"""
import argparse
import json
import multiprocessing
import os
import shutil
import signal
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.agent import run as r1run  # noqa: E402
from bench.agent.prompts import system_prompt, user_message  # noqa: E402
from bench.shells.omp.shared import COORD_NOTE, harness_error, schedule, server_env, write_stop  # noqa: E402
from bench.shells.omp import omp  # noqa: E402

EPISODE_TIMEOUT_S = 10 * 60      # 10 minutes per episode (R1 had 15); a timeout is a failure
AGENT_CWD_ROOT = r1run.AGENT_CWD_ROOT          # /tmp/pixeltree_agent
POST_FINISH_GRACE_S = 20         # after step_limit.json / done.json appears, omp is ended (see run_omp)
QUOTA_ATTEMPTS = 3
QUOTA_BACKOFF_S = (60, 180)
NIGHT_HHMM = int(os.environ["BENCH_NIGHT_HHMM"]) if os.environ.get("BENCH_NIGHT_HHMM") else None  # optional nightly stop, e.g. 2340
CALENDAR_APP = "gnome-calendar"
CALENDAR_LAST_DATE = 20261114


def cond_system_prompt(cond):
    """The R1 system prompt of `cond`, plus COORD_NOTE for S_shot / H_ours."""
    return system_prompt(cond) + (" " + COORD_NOTE if cond in omp.IMAGE_CONDS else "")


def prepare_cwd(job, display, epdir, tag):
    """Fresh neutral cwd /tmp/pixeltree_agent/omp_<tag>__<episode>/ holding only .mcp.json."""
    cwd = AGENT_CWD_ROOT / f"omp_{tag}__{Path(epdir).name}"
    if cwd.exists():
        shutil.rmtree(cwd)
    cwd.mkdir(parents=True)
    omp.write_workspace(cwd, [sys.executable, "-m", "bench.shells.omp.mcp_server"], server_env(job, display, epdir))
    return cwd


def run_omp(cmd, cwd, epdir, env, timeout=EPISODE_TIMEOUT_S):
    """Run omp in `cwd`, stdout -> transcript.jsonl. Returns (returncode, timed_out, wall_s)."""
    t0 = time.monotonic()
    with open(Path(epdir) / "transcript.jsonl", "wb") as out, open(Path(epdir) / "omp.stderr", "wb") as err:
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                start_new_session=True)
        timed_out = finished_at = False
        while True:
            try:
                proc.wait(timeout=2)
                break
            except subprocess.TimeoutExpired:
                pass
            if time.monotonic() - t0 > timeout:
                timed_out = True
                break
            # R1 semantics: nothing after the 20th call or after done is executed; some models (GLM) keep calling
            # done after "step limit reached" for minutes (OMP's loop guard is off), so end the episode here.
            if not finished_at and any((Path(epdir) / f).exists() for f in ("step_limit.json", "done.json")):
                finished_at = time.monotonic()
            if finished_at and time.monotonic() - finished_at > POST_FINISH_GRACE_S:
                break
        for sig in (signal.SIGTERM, signal.SIGKILL):   # also reaps the MCP server child
            try:
                os.killpg(proc.pid, sig)
            except ProcessLookupError:
                break
            try:
                proc.wait(timeout=5)
                break
            except subprocess.TimeoutExpired:
                continue
    return proc.returncode, timed_out, time.monotonic() - t0


def error_text(scan, epdir):
    stderr = Path(epdir, "omp.stderr")
    tail = stderr.read_text(errors="replace")[-2000:] if stderr.exists() else ""
    return " | ".join([*scan["errors"], tail]).strip(" |")


def run_episode(job, display, out, envmod, model_key, attempt=1):
    """One episode; returns the row (never raises)."""
    spec = omp.MODELS[model_key]
    out = Path(out)
    epdir = out / "ep" / f"{job['task']}__{job['cond']}__r{job['rep']}"
    shutil.rmtree(epdir, ignore_errors=True)
    epdir.mkdir(parents=True)
    row = {"task": job["task"], "app": job["app"], "difficulty": job["difficulty"], "cond": job["cond"],
           "model": spec["id"], "rep": job["rep"], "ok": False, "oracle_detail": "", "stop_reason": "error",
           "answer": "", "steps": 0, "input_tokens": None, "output_tokens": None, "cache_read_tokens": None,
           "cache_creation_tokens": None, "cost_usd": None, "wall_s": None, "mean_obs_s": None,
           "mean_model_s": None, "t_start": datetime.now().isoformat(timespec="seconds"),
           "tier": job.get("tier"), "dir": str(epdir), "attempt": attempt, "thinking": spec["thinking"]}
    ep = None
    try:
        ep = envmod.start_episode(job["app"], display, epdir / "sbx", task_id=job["task"])
        from bench.env.actions import desktop_env_subset

        config = getattr(ep, "config", None) or {}
        (epdir / "episode.json").write_text(json.dumps({
            "task": job["task"], "app": job["app"], "cond": job["cond"], "display": display,
            "app_config": {"name": job["app"], "process": config.get("process") or job["app"]},
            "desk_env": desktop_env_subset(ep.desk.env)}, indent=1), encoding="utf-8")
        cwd = prepare_cwd(job, display, epdir, model_key)
        sp = cond_system_prompt(job["cond"])
        cmd = omp.command(user_message(job["sentence"]), spec["id"], spec["thinking"])
        (epdir / "command.json").write_text(json.dumps({"cmd": cmd, "cwd": str(cwd), "system_prompt": sp},
                                                       indent=1), encoding="utf-8")
        rc, timed_out, wall = run_omp(cmd, cwd, epdir, omp.omp_env(sp, epdir / "requests.jsonl"))
        row["wall_s"] = round(wall, 1)
        ep.close_app()
        ok, detail = envmod.oracle(job["task"], ep.home)
        row["ok"], row["oracle_detail"] = bool(ok), str(detail)
        scan = omp.scan_stream(epdir / "transcript.jsonl")
        req_ok, req_reason = omp.requests_ok(omp.read_requests(epdir / "requests.jsonl"), sp)
        scan["requests_ok"], scan["requests_reason"] = req_ok, req_reason
        (epdir / "scan.json").write_text(json.dumps(scan, ensure_ascii=False, indent=1), encoding="utf-8")
        fake = {"result": scan["final_text"], "is_error": bool(scan["errors"]) or not scan["has_end"]}
        row["ended_by_runner"] = rc is not None and rc < 0 and not timed_out
        row["stop_reason"], row["answer"] = r1run.stop_reason_of(epdir, timed_out, rc, fake)
        u = scan["usage"]
        row.update(input_tokens=u["input_tokens"], output_tokens=u["output_tokens"],
                   cache_read_tokens=u["cache_read_tokens"], cache_creation_tokens=u["cache_write_tokens"],
                   reasoning_tokens=u["reasoning_tokens"], cost_usd=u["cost_usd"],
                   n_model_calls=scan["n_model_calls"], n_p125_calls=scan["n_p125_calls"],
                   tool_counts=scan["tool_counts"], foreign_calls=scan["foreign_calls"], invalid=omp.invalid(scan),
                   omp_errors=[e[:300] for e in scan["errors"]][:5], omp_rc=rc)
        row["steps"], row["mean_obs_s"], row["mean_model_s"] = r1run.step_stats(epdir)
        reasons = [r for r in (harness_error(epdir), None if req_ok else f"R5 hook check: {req_reason}") if r]
        if scan["n_p125_calls"] == 0 and row["stop_reason"] != "timeout":
            reasons.append("no bench tool call at all")
        if reasons:
            row["stop_reason"] = "error"
            row["oracle_detail"] += " | " + "; ".join(reasons)
        if row["stop_reason"] == "error":
            row["oracle_detail"] += f" | omp rc={rc} {error_text(scan, epdir)[-400:]}"
    except BaseException as exc:  # noqa: BLE001
        row["stop_reason"] = "error"
        row["oracle_detail"] = f"runner error: {type(exc).__name__}: {exc}"[:500]
        (epdir / "runner_error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        if isinstance(exc, KeyboardInterrupt):
            raise
    finally:
        if ep is not None:
            try:
                ep.stop()
            except Exception:  # noqa: BLE001
                (epdir / "runner_error.txt").open("a").write("stop failed:\n" + traceback.format_exc())
    (epdir / "result.json").write_text(json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")
    return row


def quota_text(row):
    """The quota / rate-limit message of an error row ('' when it is not one)."""
    if row.get("stop_reason") != "error":
        return ""
    text = " ".join([" ".join(row.get("omp_errors") or []), str(row.get("oracle_detail") or "")])
    return text.strip() if omp.is_quota_error(text) else ""


def stop_reason_now(out):
    if (Path(out) / "STOP").exists():
        return "STOP file present: " + (Path(out) / "STOP").read_text(errors="replace").strip()
    if NIGHT_HHMM is not None and int(datetime.now().strftime("%H%M")) >= NIGHT_HHMM:
        return "night"
    return ""


def first_tasks(jobs, n):
    """The first `n` distinct tasks of `jobs` in run order."""
    out = []
    for j in jobs:
        if j["task"] not in out:
            out.append(j["task"])
    return set(out[:n])


def skip_job(job, today=None):
    """True for a gnome-calendar task after 2026-11-14 (its oracle assumes the 11-08..14 week)."""
    today = today if today is not None else int(datetime.now().strftime("%Y%m%d"))
    return job["app"] == CALENDAR_APP and today > CALENDAR_LAST_DATE


def wait_while_paused(pause_file, out, label):
    """Block while `pause_file` exists (the driver's OpenCode Go 5-hour-window pause); '' or a stop reason."""
    logged = False
    while pause_file and Path(pause_file).exists():
        reason = stop_reason_now(out)
        if reason:
            return reason
        if not logged:
            print(f"[{label}] paused: {Path(pause_file).read_text(errors='replace').strip()}", file=sys.stderr,
                  flush=True)
            logged = True
        time.sleep(30)
    return ""


def worker(display, jobs, out, model_key, max_episodes=0, pause_file=""):
    """Run `jobs` (an iterable; a queue reader ends at None) one after the other on `display`."""
    envmod = r1run.load_env()
    n = 0
    for job in jobs:
        reason = wait_while_paused(pause_file, out, f"{model_key} {display}") or stop_reason_now(out)
        if reason:
            if reason == "night":
                write_stop(out, reason)
            print(f"[{model_key} {display}] stop before {job['task']} {job['cond']}: {reason}", file=sys.stderr,
                  flush=True)
            return
        if skip_job(job):
            print(f"[{model_key} {display}] skip {job['task']} {job['cond']}: calendar task after 11-14",
                  file=sys.stderr, flush=True)
            continue
        for attempt in range(1, QUOTA_ATTEMPTS + 1):
            row = run_episode(job, display, out, envmod, model_key, attempt)
            r1run.append_row(out, row)
            print(f"[{model_key} {display}] {row['task']} {row['cond']} r{row['rep']}: ok={row['ok']} "
                  f"{row['stop_reason']} steps={row['steps']} calls={row.get('n_model_calls')} "
                  f"in={row['input_tokens']} out={row['output_tokens']} invalid={row.get('invalid')} "
                  f"wall={row['wall_s']}s", file=sys.stderr, flush=True)
            qt = quota_text(row)
            if not qt:
                break
            if attempt == QUOTA_ATTEMPTS:
                write_stop(out, f"quota_omp: {qt[:1000]}")
                print(f"[{model_key} {display}] quota_omp STOP after {attempt} attempts: {qt[:300]}",
                      file=sys.stderr, flush=True)
                return
            time.sleep(QUOTA_BACKOFF_S[attempt - 1])
        n += 1
        if max_episodes and n >= max_episodes:
            return


def _queue_iter(queue):
    while True:
        job = queue.get()
        if job is None:
            return
        yield job


def _worker_main(display, queue, out, model_key, pause_file):
    worker(display, _queue_iter(queue), out, model_key, pause_file=pause_file)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True, choices=sorted(omp.MODELS))
    ap.add_argument("--out", required=True)
    ap.add_argument("--tasks", default="all", help="all | <id,id,...> (the order is still the stratified one)")
    ap.add_argument("--only", default="", help="file with one <task>__<cond> per line: run only these episodes")
    ap.add_argument("--first", type=int, default=0,
                    help="only the first N tasks of the stratified order (e.g. 24 first, the rest after reviewing them)")
    ap.add_argument("--conds", default="", help="default: the model's conditions (omp.MODELS)")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--displays", default=":150", help="one worker per display, all taking jobs from one queue")
    ap.add_argument("--freeze-sha", default="")
    ap.add_argument("--pause-file", default="", help="no new episode starts while this file exists")
    ap.add_argument("--max-episodes", type=int, default=0, help="single worker only: stop after this many episodes")
    args = ap.parse_args(argv)

    if shutil.which(omp.OMP) is None:
        raise SystemExit("omp not found on PATH")
    if args.freeze_sha:
        r1run.check_frozen(args.freeze_sha)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    conds = tuple(c for c in args.conds.split(",") if c) or omp.MODELS[args.model]["conds"]
    jobs = schedule(r1run.load_env().TASKS, conds, args.reps)
    if args.tasks != "all":
        wanted = set(args.tasks.split(","))
        jobs = [j for j in jobs if j["task"] in wanted]
    if args.first:
        jobs = [j for j in jobs if j["task"] in first_tasks(jobs, args.first)]
    if args.only:
        keep = {line.strip() for line in Path(args.only).read_text().splitlines() if line.strip()}
        jobs = [j for j in jobs if f"{j['task']}__{j['cond']}" in keep]
    done = r1run.done_keys(r1run.read_rows(out / "episodes.jsonl"))
    jobs = [j for j in jobs if (j["task"], j["cond"], j["rep"]) not in done]
    displays = [d for d in args.displays.split(",") if d]
    print(f"{len(jobs)} episodes to run ({len(done)} already complete), model {args.model} "
          f"({omp.MODELS[args.model]['id']}, thinking {omp.MODELS[args.model]['thinking']}), displays {displays}",
          file=sys.stderr, flush=True)
    if len(displays) == 1:
        worker(displays[0], jobs, out, args.model, args.max_episodes, args.pause_file)
        return 0
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    for job in jobs:
        queue.put(job)
    for _ in displays:
        queue.put(None)
    procs = [ctx.Process(target=_worker_main, args=(d, queue, str(out), args.model, args.pause_file)) for d in displays]
    for p in procs:
        p.start()
    for p in procs:
        p.join()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
