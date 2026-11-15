"""Runner of the agent harness (main exam, R1): for every (task, condition, rep) start the app, run `claude -p`
against the MCP server, close the app, let the oracle judge, archive everything.

    python -m bench.agent.run --conds T_ours,T_atspi,S_shot --tasks pilot --pilot-ids a,b --reps 3 \
        --parallel 3 --displays :140,:141,:142 --out out/r1/run1 [--freeze-sha <sha>]

Output layout: <out>/episodes.jsonl (one row per episode, appended; the last row of an episode wins),
<out>/ep/<task>__<cond>__r<rep>/ (transcript.jsonl, claude.stderr, steps/NN/*, done.json, result.json ...).
Re-running the same command resumes: finished episodes are skipped, episodes that ended in "error" are retried.
Creating the file <out>/STOP makes every worker finish its current episode and start no new one.
"""
import argparse
import fcntl
import importlib
import importlib.util
import json
import multiprocessing
import os
import random
import shutil
import signal
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.agent.prompts import CONDS, model_for, system_prompt, user_message  # noqa: E402

CLAUDE = "claude"
TOOLS = ",".join(f"mcp__p125__{t}" for t in ("observe", "click", "type", "key", "scroll", "done"))
EPISODE_TIMEOUT_S = 15 * 60
FREEZE_PATHS = ["bench/apps", "bench/env/episode.py", "bench/env/oracle_kit.py", "bench/env/registry.py",
                "bench/tasks_v1.json"]
FIELDS = ["task", "app", "difficulty", "cond", "model", "rep", "ok", "oracle_detail", "stop_reason", "answer",
          "steps", "input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens", "cost_usd",
          "wall_s", "mean_obs_s", "mean_model_s", "t_start"]
EXTRA_FIELDS = ["tier", "dir"]   # not required for "complete"
PASS_ENV = ("VAX_OBSERVE_DEVICE", "VAX_OBSERVE_THREADS", "CUDA_VISIBLE_DEVICES")

# ---------------------------------------------------------------- plugin conditions (R3)
# A plugin module (--plugin <module>) adds conditions without touching the seven above. It provides COND_SPECS
# {cond: {system_prompt, model, tools (names without the mcp__p125__ prefix), mcp_module, stream_input}},
# initial_message(cond, job, ep, epdir, display) -> list of content blocks | None and harness_error(cond, epdir) -> str | None.
PLUGIN = None


def load_plugin(name):
    """Import the plugin module `name` (empty: no plugin)."""
    global PLUGIN
    if name:
        PLUGIN = importlib.import_module(name)
    return PLUGIN


def _spec(cond):
    return PLUGIN.COND_SPECS[cond] if PLUGIN is not None and cond in PLUGIN.COND_SPECS else None


def is_plugin_cond(cond):
    return cond not in CONDS and _spec(cond) is not None


def all_conds():
    return list(CONDS) + ([c for c in PLUGIN.COND_SPECS if c not in CONDS] if PLUGIN is not None else [])


def cond_system_prompt(cond):
    return system_prompt(cond) if cond in CONDS else _spec(cond)["system_prompt"]


def cond_model(cond):
    return model_for(cond) if cond in CONDS else _spec(cond)["model"]


def cond_tools(cond):
    if cond in CONDS:
        return TOOLS
    return ",".join(f"mcp__p125__{t}" for t in _spec(cond)["tools"])


def cond_mcp_module(cond):
    return "bench.agent.mcp_server" if cond in CONDS else _spec(cond)["mcp_module"]


# ---------------------------------------------------------------- environment layer
def load_env():
    """The env layer: bench.env.episode + registry."""
    from bench.env import episode, registry

    return SimpleNamespace(start_episode=episode.start_episode, TASKS=registry.TASKS, get_task=registry.get_task,
                           oracle=registry.oracle)


def select_tasks(envmod, spec, pilot_ids):
    ids = [t["id"] for t in envmod.TASKS]
    if spec == "all":
        chosen = ids
    elif spec == "pilot":
        if not pilot_ids:
            raise SystemExit("--tasks pilot needs --pilot-ids <id,...>")
        chosen = [s for s in pilot_ids.split(",") if s]
    else:
        chosen = [s for s in spec.split(",") if s]
    unknown = [t for t in chosen if t not in ids]
    if unknown:
        raise SystemExit(f"unknown task ids {unknown}; known: {ids}")
    return chosen


# ---------------------------------------------------------------- planning and resuming
def plan_jobs(envmod, task_ids, conds, reps, done):
    """Jobs in run order: tasks shuffled with seed 0; for each (task, rep) the conditions rotate (no cond always first)."""
    order = list(task_ids)
    random.Random(0).shuffle(order)
    jobs, pair = [], 0
    for tid in order:
        task = envmod.get_task(tid)
        for rep in range(reps):
            shift = pair % len(conds)
            pair += 1
            for cond in conds[shift:] + conds[:shift]:
                if (tid, cond, rep) in done:
                    continue
                jobs.append({"task": tid, "app": task["app"], "difficulty": task.get("difficulty"),
                             "tier": task.get("tier"), "sentence": task["sentence"], "cond": cond, "rep": rep})
    return jobs


def read_rows(path):
    rows = []
    if Path(path).exists():
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def done_keys(rows):
    """(task, cond, rep) whose LAST row is complete: every FIELDS key present and stop_reason != "error" (errors are
    retried; a later error row, e.g. from requeue_mcp_failures, re-opens an episode)."""
    last = {}
    for r in rows:
        last[(r.get("task"), r.get("cond"), r.get("rep"))] = r
    return {k for k, r in last.items() if all(f in r for f in FIELDS) and r.get("stop_reason") != "error"}


def requeue_mcp_failures(out):
    """Append an error row for every episode whose last row is not an error but whose agent session started without
    the bench MCP server (init status 'failed', no tools: e.g. the detector / OCR ran out of memory while loading).
    The agent could not act at all, so the episode is a harness error and is rerun; both rows stay in the file."""
    path = Path(out) / "episodes.jsonl"
    last = {}
    for r in read_rows(path):
        last[(r.get("task"), r.get("cond"), r.get("rep"))] = r
    n = 0
    for r in last.values():
        if r.get("stop_reason") == "error" or not r.get("dir") or r.get("cond") not in all_conds():
            continue
        transcript = Path(r["dir"]) / "transcript.jsonl"
        if transcript.exists() and not mcp_ok(transcript, r.get("cond")):
            fixed = dict(r, stop_reason="error", ok=False,
                         oracle_detail=f"{r.get('oracle_detail', '')} | requeued: bench MCP server not connected at init"
                                       f" (was {r.get('stop_reason')}, ok={r.get('ok')})")
            append_row(out, fixed)
            n += 1
    return n


def append_row(out, row):
    with open(Path(out) / "episodes.jsonl", "a", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        fh.flush()
        fcntl.flock(fh, fcntl.LOCK_UN)


def check_frozen(sha):
    """Refuse to run when the frozen env / apps / task files differ from commit `sha`."""
    res = subprocess.run(["git", "diff", "--quiet", sha, "--"] + FREEZE_PATHS, cwd=ROOT)
    if res.returncode != 0:
        raise SystemExit(f"--freeze-sha {sha}: frozen files differ from that commit "
                         f"(git diff {sha} -- {' '.join(FREEZE_PATHS)}); refusing to run")


# ---------------------------------------------------------------- one episode
def claude_env():
    env = {k: v for k, v in os.environ.items()
           if k not in ("DISPLAY", "WAYLAND_DISPLAY", "WAYLAND_SOCKET", "QT_QPA_PLATFORM_PLUGIN_PATH",
                        "QT_PLUGIN_PATH") }
    env["MCP_TIMEOUT"] = os.environ.get("MCP_TIMEOUT", "180000")   # the server loads models before it answers
    return env


def write_mcp_config(epdir, job, display):
    env = {"P125_COND": job["cond"], "P125_APP": job["app"], "P125_DISPLAY": display, "P125_EPDIR": str(epdir),
           "PYTHONPATH": str(ROOT)}
    env.update({k: os.environ[k] for k in PASS_ENV if k in os.environ})
    config = {"mcpServers": {"p125": {"command": sys.executable, "args": ["-m", cond_mcp_module(job["cond"])],
                                      "env": env}}}
    path = Path(epdir) / "mcp.json"
    path.write_text(json.dumps(config, indent=1), encoding="utf-8")
    return path


DENIED_TOOLS = ",".join(["Bash", "BashOutput", "KillShell", "Read", "Write", "Edit", "MultiEdit", "NotebookEdit",
                          "Glob", "Grep", "LS", "WebFetch", "WebSearch", "Agent", "Task", "Skill", "TodoWrite",
                          "ToolSearch", "Monitor", "SlashCommand"])
AGENT_CWD_ROOT = Path(os.environ.get("P125_AGENT_CWD_ROOT", "/tmp/pixeltree_agent"))


def claude_command(job, model, mcp_path):
    cond = job["cond"]
    spec = _spec(cond) if cond not in CONDS else None
    if spec is not None and spec.get("stream_input"):
        head = [CLAUDE, "-p", "--input-format", "stream-json", "--model", model]   # the task arrives on stdin
    else:
        head = [CLAUDE, "-p", user_message(job["sentence"]), "--model", model]
    return head + [
            "--system-prompt", cond_system_prompt(cond),
            "--mcp-config", str(mcp_path), "--strict-mcp-config",
            "--tools", "",                       # no built-in tools: only the MCP tools of the condition exist
            "--allowedTools", cond_tools(cond),
            "--disallowedTools", DENIED_TOOLS,     # belt and braces on top of --tools "" (see bench.agent.probe_lockdown)
            "--disable-slash-commands",            # no skills / slash commands either
            "--setting-sources", "", "--no-session-persistence",
            "--output-format", "stream-json", "--verbose"]


def init_event(transcript):
    """The stream-json init event of the claude session ({} when missing)."""
    try:
        with open(transcript, encoding="utf-8") as f:
            for line in f:
                event = json.loads(line)
                if event.get("type") == "system" and event.get("subtype") == "init":
                    return event
    except (OSError, ValueError):
        pass
    return {}


def init_cwd(transcript):
    """cwd of the claude session from the stream-json init event ('' when missing)."""
    return init_event(transcript).get("cwd", "")


def mcp_ok(transcript, cond=None):
    """True when the session started with the bench MCP server connected and exactly the tools of `cond` (six if None)."""
    init = init_event(transcript)
    status = {s.get("name"): s.get("status") for s in init.get("mcp_servers", [])}
    tools = TOOLS if cond is None else cond_tools(cond)
    return status.get("p125") == "connected" and sorted(init.get("tools", [])) == sorted(tools.split(","))


def run_claude(command, epdir, timeout=EPISODE_TIMEOUT_S, stdin_bytes=None):
    """Run claude in the episode directory, stdout -> transcript.jsonl. Returns (returncode, timed_out, wall_s).
    `stdin_bytes` (stream-json input) is written to claude's stdin, which is then closed; None: stdin is /dev/null."""
    t0 = time.monotonic()
    # claude must NOT run inside a project tree. There Claude Code injects the user's auto-memory for that project,
    # the git worktree path and git rules into the agent's context (seen in a pilot run: the agent refused gitg tasks
    # as "not the worktree I was asked to work in"). A fresh empty dir under
    # AGENT_CWD_ROOT (not a git repo, no CLAUDE.md, no memory) leaves only the generic environment block.
    cwd = AGENT_CWD_ROOT / Path(epdir).name
    if cwd.exists():
        shutil.rmtree(cwd)
    cwd.mkdir(parents=True)
    with open(Path(epdir) / "transcript.jsonl", "wb") as out, open(Path(epdir) / "claude.stderr", "wb") as err:
        proc = subprocess.Popen(command, cwd=cwd, env=claude_env(),
                                stdin=subprocess.DEVNULL if stdin_bytes is None else subprocess.PIPE, stdout=out,
                                stderr=err, start_new_session=True)
        if stdin_bytes is not None:
            try:
                proc.stdin.write(stdin_bytes)
                proc.stdin.close()
            except OSError:
                pass
        try:
            proc.wait(timeout=timeout)
            timed_out = False
        except subprocess.TimeoutExpired:
            timed_out = True
            for sig in (signal.SIGTERM, signal.SIGKILL):
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


def result_event(path):
    """The last `result` event of a stream-json transcript, or None."""
    last = None
    try:
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("type") == "result":
                last = event
    except OSError:
        pass
    return last


def step_stats(epdir):
    """(steps, mean_obs_s, mean_model_s) from steps/NN/action.json.

    mean_model_s = mean over consecutive calls of (t_start of the next call - t_end of the previous one): the time
    the model (plus claude and the MCP round trip) spent between two tool calls; the first call has no predecessor.
    """
    records = []
    for d in sorted((Path(epdir) / "steps").glob("[0-9][0-9]")):
        try:
            records.append(json.loads((d / "action.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    obs = [r["t_obs_s"] for r in records if r.get("t_obs_s") is not None]
    gaps = [b["t_start"] - a["t_end"] for a, b in zip(records, records[1:])
            if a.get("t_end") is not None and b.get("t_start") is not None]
    return (len(records), round(sum(obs) / len(obs), 4) if obs else None,
            round(sum(gaps) / len(gaps), 3) if gaps else None)


def stop_reason_of(epdir, timed_out, returncode, result):
    """(stop_reason, answer): timeout > done / fail_answer > step_limit > error > no_done (ended without done)."""
    epdir = Path(epdir)
    final = (result or {}).get("result") or ""
    if timed_out:
        return "timeout", final
    done = epdir / "done.json"
    if done.exists():
        try:
            answer = str(json.loads(done.read_text(encoding="utf-8")).get("answer", ""))
        except ValueError:
            answer = ""
        return ("fail_answer" if answer.lstrip().startswith("FAIL:") else "done"), answer
    if (epdir / "step_limit.json").exists():
        return "step_limit", final
    if result is None or result.get("is_error") or returncode != 0:
        return "error", final
    return "no_done", final


def run_episode(job, display, out, envmod):
    """One episode; returns the episodes.jsonl row (never raises)."""
    from bench.agent.transcript import parse_transcript, parse_usage

    out = Path(out)
    epdir = out / "ep" / f"{job['task']}__{job['cond']}__r{job['rep']}"
    shutil.rmtree(epdir, ignore_errors=True)
    epdir.mkdir(parents=True)
    model = cond_model(job["cond"])
    row = {"task": job["task"], "app": job["app"], "difficulty": job["difficulty"], "cond": job["cond"],
           "model": model, "rep": job["rep"], "ok": False, "oracle_detail": "", "stop_reason": "error",
           "answer": "", "steps": 0, "input_tokens": None, "output_tokens": None, "cache_read_tokens": None,
           "cache_creation_tokens": None, "cost_usd": None, "wall_s": None, "mean_obs_s": None,
           "mean_model_s": None, "t_start": datetime.now().isoformat(timespec="seconds"),
           "tier": job.get("tier"), "dir": str(epdir)}
    ep = None
    try:
        from bench.env.actions import desktop_env_subset

        ep = envmod.start_episode(job["app"], display, epdir / "sbx", task_id=job["task"])
        config = getattr(ep, "config", None) or {}
        (epdir / "episode.json").write_text(json.dumps({
            "task": job["task"], "app": job["app"], "cond": job["cond"], "display": display,
            "app_config": {"name": job["app"], "process": config.get("process") or job["app"]},
            "desk_env": desktop_env_subset(ep.desk.env)}, indent=1), encoding="utf-8")
        mcp_path = write_mcp_config(epdir, job, display)
        stdin_bytes = None
        if is_plugin_cond(job["cond"]):
            blocks = PLUGIN.initial_message(job["cond"], job, ep, epdir, display)
            if blocks is not None:
                stdin_bytes = (json.dumps({"type": "user", "message": {"role": "user", "content": blocks}})
                               + "\n").encode("utf-8")
        returncode, timed_out, wall = run_claude(claude_command(job, model, mcp_path), epdir,
                                                 stdin_bytes=stdin_bytes)
        row["wall_s"] = round(wall, 1)
        ep.close_app()
        ok, detail = envmod.oracle(job["task"], ep.home)
        row["ok"], row["oracle_detail"] = bool(ok), str(detail)
        result = result_event(epdir / "transcript.jsonl")
        row["stop_reason"], row["answer"] = stop_reason_of(epdir, timed_out, returncode, result)
        usage = parse_usage(epdir / "transcript.jsonl")
        _, cost, _, _ = parse_transcript(epdir / "transcript.jsonl")
        row.update(input_tokens=usage["input_tokens"], output_tokens=usage["output_tokens"],
                   cache_read_tokens=usage["cache_read_tokens"], cache_creation_tokens=usage["cache_write_tokens"],
                   cost_usd=cost)
        row["steps"], row["mean_obs_s"], row["mean_model_s"] = step_stats(epdir)
        row["agent_cwd"] = init_cwd(epdir / "transcript.jsonl")
        if not str(row["agent_cwd"]).startswith(str(AGENT_CWD_ROOT)):  # context-leak guard (see run_claude)
            row["stop_reason"] = "error"
            row["oracle_detail"] += f" | agent cwd {row['agent_cwd']!r} outside {AGENT_CWD_ROOT}"
        if not mcp_ok(epdir / "transcript.jsonl", job["cond"]):  # the agent had no tools at all: harness error, rerun
            row["stop_reason"] = "error"
            row["oracle_detail"] += " | bench MCP server not connected at init"
        if is_plugin_cond(job["cond"]):  # plugin-side harness failure (perception service down ...): rerun on resume
            reason = PLUGIN.harness_error(job["cond"], epdir)
            if reason:
                row["stop_reason"] = "error"
                row["oracle_detail"] += f" | {reason}"
        if row["stop_reason"] == "error":
            row["oracle_detail"] += f" | claude rc={returncode} {(epdir / 'claude.stderr').read_text(errors='replace')[-300:]}"
    except BaseException as exc:  # noqa: BLE001  (a failed episode is a row, not a crash)
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


# ---------------------------------------------------------------- workers
def worker_loop(display, jobs, out, envmod, log=True):
    """Run jobs one after the other on one display; `jobs` is an iterable (a queue reader ends at None)."""
    for job in jobs:
        if (Path(out) / "STOP").exists():
            print(f"[{display}] STOP file present: no new episode", file=sys.stderr)
            break
        row = run_episode(job, display, out, envmod)
        append_row(out, row)
        if log:
            print(f"[{display}] {row['task']} {row['cond']} r{row['rep']}: ok={row['ok']} {row['stop_reason']} "
                  f"steps={row['steps']} cost=${row['cost_usd']} wall={row['wall_s']}s", file=sys.stderr, flush=True)


def _queue_iter(queue):
    while True:
        job = queue.get()
        if job is None:
            return
        yield job


def worker_main(display, queue, out, plugin=""):
    load_plugin(plugin)   # spawn context: the child starts without the parent's PLUGIN
    worker_loop(display, _queue_iter(queue), out, load_env())


# ---------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--conds", default=",".join(CONDS))
    ap.add_argument("--tasks", default="all", help="all | pilot | <id,id,...>")
    ap.add_argument("--pilot-ids", default="", help="task ids used by --tasks pilot")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--parallel", type=int, default=3)
    ap.add_argument("--displays", default=":140,:141,:142,:143")
    ap.add_argument("--out", required=True)
    ap.add_argument("--freeze-sha", default="")
    ap.add_argument("--plugin", default="", help="module adding conditions (COND_SPECS), e.g. bench.variants.tree_first.conds")
    args = ap.parse_args(argv)

    load_plugin(args.plugin)
    conds = [c for c in args.conds.split(",") if c]
    bad = [c for c in conds if c not in all_conds()]
    if bad or not conds:
        raise SystemExit(f"unknown conditions {bad}; choose from {all_conds()}")
    if "T_omni" in conds and importlib.util.find_spec("bench.perception.omni") is None:
        raise SystemExit("condition T_omni needs bench/perception/omni.py, which does not exist in this checkout")
    displays = [d for d in args.displays.split(",") if d]
    if args.parallel < 1 or len(displays) < args.parallel:
        raise SystemExit(f"--parallel {args.parallel} needs at least that many --displays (got {displays})")
    if shutil.which(CLAUDE) is None:
        raise SystemExit("claude CLI not found on PATH")
    if args.freeze_sha:
        check_frozen(args.freeze_sha)

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    envmod = load_env()
    task_ids = select_tasks(envmod, args.tasks, args.pilot_ids)
    requeued = requeue_mcp_failures(out)
    if requeued:
        print(f"requeued {requeued} episodes whose bench MCP server failed at init", file=sys.stderr)
    done = done_keys(read_rows(out / "episodes.jsonl"))
    jobs = plan_jobs(envmod, task_ids, conds, args.reps, done)
    print(f"{len(jobs)} episodes to run ({len(done)} already complete), models: "
          f"{ {c: cond_model(c) for c in conds} }", file=sys.stderr)
    if not jobs:
        return 0

    if args.parallel == 1:
        worker_loop(displays[0], jobs, out, envmod)
        return 0
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    for job in jobs:
        queue.put(job)
    for _ in range(args.parallel):
        queue.put(None)
    procs = [ctx.Process(target=worker_main, args=(displays[i], queue, str(out), args.plugin))
             for i in range(args.parallel)]
    try:
        for p in procs:
            p.start()
        for p in procs:
            p.join()
    except KeyboardInterrupt:
        for p in procs:
            p.terminate()
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
