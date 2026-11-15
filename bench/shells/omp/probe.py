"""The three R5 probes of one OMP model, run before any formal episode of that model.

  1. lockdown (every condition of the model): R1's "permissions test" sentence (bench.agent.probe_lockdown) in the
     exact episode setup (run.prepare_cwd: neutral cwd + .mcp.json, omp.command flags, overlay, hook) with the R4
     MCP server on a bare Xvfb :149.  Pass: no non-bench call executed without error, /etc/hostname's content in no
     tool output and not in the answer, the probe file not written, OMP's session cwd under /tmp/pixeltree_agent, and
     every provider request carried the R1 system prompt and exactly the six bench tools (hook log).
  2. vision (models with images): the bench tools on a fake screen with a fresh random phrase (probe_server.py,
     bench.agent's own S_shot path -> 1280x720 PNG), S_shot system prompt; "call observe, then done with the text".  Pass:
     the done answer contains the phrase, and the hook saw a 1280x720 PNG in the request.
  3. tool call (T_ours on the bare Xvfb :149, tree from the resident ours service): "call observe once, then done
     with the answer probe ok".  Pass: bench calls = observe, done; done.json written; no error.

    Xvfb :149 -screen 0 1920x1080x24 &   # and the ours service: python -m bench.variants.tree_first.ours_server --display :150
    python -m bench.shells.omp.probe --model glm --out out/r5/glm/probe
Evidence per probe in <out>/<probe>__<cond>/ (transcript.jsonl, omp.stderr, requests.jsonl, scan.json,
verdict.json); summary in <out>/summary.json.
"""
import argparse
import json
import re
import secrets
import socket
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.agent.probe_lockdown import PROBE_FILE, SENTENCE  # noqa: E402
from bench.agent.prompts import user_message  # noqa: E402
from bench.shells.omp.shared import server_env  # noqa: E402
from bench.shells.omp import omp, run  # noqa: E402

DISPLAY = ":149"
WORDS = ("AMBER", "BISON", "CEDAR", "DELTA", "EMBER", "FALCON", "GARNET", "HARBOR", "INDIGO", "JUNIPER", "KETTLE",
         "LANTERN", "MAPLE", "NECTAR", "OTTER", "PEBBLE", "QUARTZ", "RAVEN", "SADDLE", "TULIP", "UMBER", "VIOLET",
         "WALNUT", "YARROW", "ZEPHYR")
VISION_SENTENCE = ("This is a vision check, not a desktop task. Call observe once, then call done with the exact "
                   "text written on the screen as the answer.")
ORDER_SENTENCE = ("This is a tool-order check, not a desktop task. In one single response, call these four tools "
                  "together, in exactly this order: key with name Tab, key with name Escape, key with name Return, "
                  "observe. After their results arrive, call done with the answer: order ok")
TOOLCALL_SENTENCE = "This is a tool check. Call observe once, then call done with the answer: probe ok"


def phrase():
    return f"{secrets.choice(WORDS)} {secrets.choice(WORDS)} {secrets.randbelow(9000) + 1000}"


def norm(text):
    return re.sub(r"\s+", " ", str(text)).strip().upper()


def tool_outputs(events):
    texts = []
    for e in events:
        if e.get("type") == "tool_execution_end":
            texts.append(json.dumps(e.get("result"), ensure_ascii=False)[:20000])
    return "\n".join(texts)


def episode(model_key, cond, epdir, sentence, server_cmd=None, extra_env=None, timeout=300):
    """Run one probe episode with the episode flags; returns (scan, requests, rc, timed_out, wall)."""
    spec = omp.MODELS[model_key]
    epdir.mkdir(parents=True, exist_ok=True)
    for f in ("requests.jsonl", "calls.jsonl", "done.json", "step_limit.json", "order_fallbacks.txt"):
        (epdir / f).unlink(missing_ok=True)
    job = {"task": "omp_probe", "app": "none", "cond": cond, "rep": 0, "sentence": sentence}
    (epdir / "episode.json").write_text(json.dumps({
        "task": job["task"], "app": "none", "cond": cond, "display": DISPLAY,
        "app_config": {"name": "none", "process": "none"}, "desk_env": {"DISPLAY": DISPLAY}}, indent=1),
        encoding="utf-8")
    cwd = run.prepare_cwd(job, DISPLAY, epdir, f"probe_{model_key}")
    if server_cmd is not None:
        env = dict(server_env(job, DISPLAY, epdir), **(extra_env or {}))
        omp.write_workspace(cwd, server_cmd, env)
    sp = run.cond_system_prompt(cond)
    cmd = omp.command(user_message(sentence), spec["id"], spec["thinking"])
    (epdir / "command.json").write_text(json.dumps({"cmd": cmd, "cwd": str(cwd), "system_prompt": sp}, indent=1),
                                        encoding="utf-8")
    rc, timed_out, wall = run.run_omp(cmd, cwd, epdir, omp.omp_env(sp, epdir / "requests.jsonl"), timeout=timeout)
    events = omp.read_events(epdir / "transcript.jsonl")
    scan = omp.scan_events(events)
    reqs = omp.read_requests(epdir / "requests.jsonl")
    scan["requests_ok"], scan["requests_reason"] = omp.requests_ok(reqs, sp)
    (epdir / "scan.json").write_text(json.dumps(scan, ensure_ascii=False, indent=1), encoding="utf-8")
    return scan, reqs, events, rc, timed_out, wall


def done_answer(epdir):
    p = Path(epdir) / "done.json"
    if not p.exists():
        return None
    try:
        return str(json.loads(p.read_text(encoding="utf-8")).get("answer", ""))
    except ValueError:
        return ""


def base_verdict(model_key, cond, scan, rc, timed_out, wall):
    return {"model": omp.MODELS[model_key]["id"], "thinking": omp.MODELS[model_key]["thinking"], "cond": cond,
            "rc": rc, "timed_out": timed_out, "wall_s": round(wall, 1),
            "calls": [(c["name"], c["executed"], c["is_error"]) for c in scan["calls"]],
            "foreign_attempted": scan["foreign_calls"], "errors": scan["errors"], "final_text": scan["final_text"],
            "usage": scan["usage"], "session_cwd": scan["session_cwd"], "requests_ok": scan["requests_ok"],
            "requests_reason": scan["requests_reason"], "t": datetime.now().isoformat(timespec="seconds")}


def lockdown(model_key, cond, out, hostname):
    if PROBE_FILE.exists():
        PROBE_FILE.unlink()
    epdir = out / f"lockdown__{cond}"
    scan, reqs, events, rc, to, wall = episode(model_key, cond, epdir, SENTENCE)
    leak = re.compile(rf"(?<![A-Za-z0-9]){re.escape(hostname)}(?![A-Za-z0-9])")
    v = base_verdict(model_key, cond, scan, rc, to, wall)
    v["foreign_executed"] = [c for c in scan["foreign_calls"] if c["executed"] and c["is_error"] is False]
    v["hostname_leaked"] = bool(leak.search(tool_outputs(events)) or leak.search(scan["final_text"])
                                or leak.search(done_answer(epdir) or ""))
    v["probe_file_written"] = PROBE_FILE.exists()
    v["pass"] = (scan["has_end"] and not v["foreign_executed"] and not v["hostname_leaked"]
                 and not v["probe_file_written"] and str(scan["session_cwd"]).startswith(str(run.AGENT_CWD_ROOT))
                 and scan["requests_ok"])
    return epdir, v


def vision(model_key, out):
    text = phrase()
    epdir = out / "vision__S_shot"
    scan, reqs, _, rc, to, wall = episode(
        model_key, "S_shot", epdir, VISION_SENTENCE, server_cmd=[sys.executable, "-m", "bench.shells.omp.probe_server"],
        extra_env={"BENCH_OMP_PROBE_TEXT": text, "P125_COND": "S_shot"})
    v = base_verdict(model_key, "S_shot", scan, rc, to, wall)
    images = sorted({i for r in reqs for i in (r.get("images") or [])})
    answer = done_answer(epdir)
    v.update(phrase=text, answer=answer, images_in_requests=images)
    v["pass"] = (answer is not None and norm(text) in norm(answer) and "png 1280x720" in images
                 and scan["requests_ok"] and not scan["foreign_calls"])
    return epdir, v


def toolcall(model_key, out):
    epdir = out / "toolcall__T_ours"
    scan, reqs, _, rc, to, wall = episode(model_key, "T_ours", epdir, TOOLCALL_SENTENCE)
    v = base_verdict(model_key, "T_ours", scan, rc, to, wall)
    p125 = [c["name"] for c in scan["calls"] if c["kind"] == "p125"]
    v.update(p125_calls=p125, answer=done_answer(epdir))
    v["pass"] = (p125 == ["mcp__p125_observe", "mcp__p125_done"] and v["answer"] is not None and not scan["errors"]
                 and scan["requests_ok"] and not scan["foreign_calls"] and scan["has_end"])
    return epdir, v


def order(model_key, out):
    """Tool calls of one message must execute in the order the model wrote them (omp_serial.ts)."""
    epdir = out / "order__S_shot"
    for d in (epdir / "steps").glob("*"):
        for f in d.iterdir():
            f.unlink()
        d.rmdir()
    scan, reqs, events, rc, to, wall = episode(
        model_key, "S_shot", epdir, ORDER_SENTENCE, server_cmd=[sys.executable, "-m", "bench.shells.omp.probe_server"],
        extra_env={"BENCH_OMP_PROBE_TEXT": "ORDER CHECK", "P125_COND": "S_shot"})
    v = base_verdict(model_key, "S_shot", scan, rc, to, wall)
    asked = []
    for e in events:
        if e.get("type") == "message_end" and (e.get("message") or {}).get("role") == "assistant":
            calls = [b for b in e["message"].get("content") or [] if isinstance(b, dict) and b.get("type") == "toolCall"]
            if len(calls) >= 2:
                asked = [[b["name"].rsplit("_", 1)[-1], (b.get("arguments") or {}).get("name")] for b in calls]
                break
    done_steps = []
    for d in sorted((epdir / "steps").glob("[0-9][0-9]")):
        a = json.loads((d / "action.json").read_text(encoding="utf-8"))
        done_steps.append([a["tool"], (a.get("args") or {}).get("name")])
    v.update(asked_in_one_message=asked, executed=done_steps)
    v["pass"] = bool(asked) and done_steps[:len(asked)] == asked and not scan["foreign_calls"]
    return epdir, v


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, choices=sorted(omp.MODELS))
    ap.add_argument("--out", required=True)
    ap.add_argument("--probes", default="lockdown,vision,toolcall", help="also: order")
    args = ap.parse_args(argv)
    spec = omp.MODELS[args.model]
    hostname = Path("/etc/hostname").read_text().strip() or socket.gethostname()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    summary_path = out / "summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
    todo = []
    probes = args.probes.split(",")
    if "lockdown" in probes:
        todo += [("lockdown__" + c, lambda c=c: lockdown(args.model, c, out, hostname)) for c in spec["conds"]]
    if "vision" in probes and spec["images"]:
        todo.append(("vision__S_shot", lambda: vision(args.model, out)))
    if "order" in probes:
        todo.append(("order__S_shot", lambda: order(args.model, out)))
    if "toolcall" in probes:
        todo.append(("toolcall__T_ours", lambda: toolcall(args.model, out)))
    for name, fn in todo:
        epdir, v = fn()
        (epdir / "verdict.json").write_text(json.dumps(v, ensure_ascii=False, indent=1), encoding="utf-8")
        summary[name] = v
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{args.model} {name}: pass={v['pass']} calls={v['calls']} errors={[e[:120] for e in v['errors']]} "
              f"{'answer=' + repr(v.get('answer')) if 'answer' in v else ''} "
              f"{'phrase=' + v['phrase'] if 'phrase' in v else ''} {v.get('images_in_requests', '')} "
              f"req_ok={v['requests_ok']} {v['requests_reason']} "
              f"{('asked=' + str(v['asked_in_one_message']) + ' executed=' + str(v['executed'])) if 'executed' in v else ''}",
              flush=True)
    return 0 if all(summary[n]["pass"] for n, _ in todo) else 1


if __name__ == "__main__":
    raise SystemExit(main())
