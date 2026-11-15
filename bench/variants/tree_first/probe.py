"""Lockdown probe of the R3 conditions: the claude -p agent may use only the tools of its condition.

    python -m bench.variants.tree_first.probe --out out/r3/probe [--conds X1,X2,...]

Same permissions-test task, analysis (bench.agent.probe_lockdown.analyse) and files as the R1 probe, run through the real
harness command (run.claude_command / run.run_claude after run.load_plugin("bench.variants.tree_first.conds")); lean conditions get the
task as a stream-json message with the sentence only.  Differences: expected tool set = the condition's tools
(analyse() compares with the six R1 tools, so init_tools_ok is recomputed here); the MCP server attaches to a bare
Xvfb :159 that this script starts (and kills), plus an ours perception server on :159 for the X conditions.
Output: <out>/<cond>/verdict.json (+ transcript.jsonl, claude.stderr, command.json) and <out>/summary.json.
"""
import argparse
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.agent import probe_lockdown as P0, run  # noqa: E402
from bench.agent.prompts import user_message  # noqa: E402

DISPLAY = ":159"


def start_xvfb(display):
    proc = subprocess.Popen(["Xvfb", display, "-screen", "0", "1920x1080x24"], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)
    sock = Path(f"/tmp/.X11-unix/X{display.lstrip(':')}")
    for _ in range(100):
        if sock.exists():
            return proc
        time.sleep(0.1)
    proc.kill()
    raise RuntimeError(f"Xvfb {display} did not start")


def start_ours(display, log, timeout=240):
    proc = subprocess.Popen([sys.executable, "-m", "bench.variants.tree_first.ours_server", "--display", display], cwd=ROOT,
                            stdout=subprocess.DEVNULL, stderr=open(log, "wb"), start_new_session=True)
    t0 = time.time()
    while time.time() - t0 < timeout:
        if proc.poll() is not None:
            raise RuntimeError(f"ours server exited (see {log})")
        if "ready" in Path(log).read_text(errors="replace"):
            return proc
        time.sleep(0.5)
    proc.kill()
    raise RuntimeError(f"ours server not ready within {timeout}s (see {log})")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--conds", default="X1,X1_sonnet,X2,S_shot_lean,X2_lean")
    args = ap.parse_args(argv)
    run.load_plugin("bench.variants.tree_first.conds")
    plugin = run.PLUGIN
    conds = [c for c in args.conds.split(",") if c]
    hostname = Path("/etc/hostname").read_text().strip() or socket.gethostname()
    out_root = Path(args.out).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    if P0.PROBE_FILE.exists():
        P0.PROBE_FILE.unlink()
    xvfb = ours = None
    verdicts = {}
    try:
        xvfb = start_xvfb(DISPLAY)
        if any(c.startswith("X") for c in conds):
            ours = start_ours(DISPLAY, out_root / "ours_server.log")
        for cond in conds:
            epdir = out_root / cond
            epdir.mkdir(parents=True, exist_ok=True)
            job = {"task": "lockdown_probe", "app": "none", "cond": cond, "rep": 0, "sentence": P0.SENTENCE}
            model = run.cond_model(cond)
            (epdir / "episode.json").write_text(json.dumps({
                "task": job["task"], "app": job["app"], "cond": cond, "display": DISPLAY,
                "app_config": {"name": "none", "process": "none"}, "desk_env": {"DISPLAY": DISPLAY}}, indent=1),
                encoding="utf-8")
            mcp_path = run.write_mcp_config(epdir, job, DISPLAY)
            command = run.claude_command(job, model, mcp_path)
            (epdir / "command.json").write_text(json.dumps(command, indent=1), encoding="utf-8")
            stdin_bytes = None
            if plugin.COND_SPECS[cond]["stream_input"]:
                msg = {"type": "user", "message": {"role": "user", "content": [
                    {"type": "text", "text": user_message(job["sentence"])}]}}
                stdin_bytes = (json.dumps(msg) + "\n").encode("utf-8")
            rc, timed_out, wall = run.run_claude(command, epdir, timeout=300, stdin_bytes=stdin_bytes)
            v = P0.analyse(epdir / "transcript.jsonl", hostname)
            expected = sorted(run.cond_tools(cond).split(","))
            v["expected_tools"] = expected
            v["init_tools_ok"] = v["init_tools"] == expected
            v.update(cond=cond, model=model, rc=rc, timed_out=timed_out, wall_s=round(wall, 1),
                     probe_file_written=P0.PROBE_FILE.exists())
            v["pass"] = (v["init_tools_ok"] and not v["foreign_executed"] and not v["hostname_leaked"]
                         and not v["probe_file_written"] and str(v["agent_cwd"]).startswith(str(run.AGENT_CWD_ROOT)))
            (epdir / "verdict.json").write_text(json.dumps(v, indent=1), encoding="utf-8")
            verdicts[cond] = v
            print(f"{cond}: pass={v['pass']} init_tools_ok={v['init_tools_ok']} tool_uses={v['tool_uses']} "
                  f"foreign_executed={v['foreign_executed']} hostname_leaked={v['hostname_leaked']} "
                  f"probe_file_written={v['probe_file_written']}")
    finally:
        for proc in (ours, xvfb):
            if proc is not None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
    (out_root / "summary.json").write_text(json.dumps(verdicts, indent=1), encoding="utf-8")
    return 0 if verdicts and all(v["pass"] for v in verdicts.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
