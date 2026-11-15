"""Self-test of the tasks: each task is started in a fresh episode, once with the positive script (must pass the
oracle) and once doing nothing for 5 s (must fail it).

    python -m bench.env.selftest --tasks all|<app>|<id,id,...> --mode positive|noop|both --display :130 --out <dir>

Writes <out>/selftest.jsonl (one line per episode: task, mode, ok, detail, seconds, started, state_files changes,
plus `expected` and `pass` = ok == expected) and <out>/<task>/<mode>/final.png (last screenshot before the app
was closed).  The exit code is 0 only when every episode behaved as expected.
Displays: pass one of :130-:139; run several processes with different --display to parallelise.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import shutil
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.env import registry  # noqa: E402
from bench.env.episode import start_episode  # noqa: E402

NOOP_SECONDS = 5.0


def snapshot(home: Path, patterns) -> dict[str, str]:
    """{relative path: sha1 | 'dir'} of every file matching the state_files globs."""
    snap: dict[str, str] = {}
    for pat in patterns:
        for p in sorted(glob.glob(str(home / pat), recursive=True)):
            path = Path(p)
            files = [path] if path.is_file() else [q for q in sorted(path.rglob("*")) if q.is_file()]
            for q in files:
                try:
                    data = q.read_bytes()
                except OSError:
                    continue
                snap[str(q.relative_to(home))] = hashlib.sha1(data).hexdigest()[:12] + f":{len(data)}"
    return snap


def diff(before: dict, after: dict) -> dict:
    return {"added": sorted(set(after) - set(before)), "removed": sorted(set(before) - set(after)),
            "modified": sorted(k for k in set(before) & set(after) if before[k] != after[k])}


def pick(spec: str) -> list[str]:
    if spec == "all":
        return [t["id"] for t in sorted(registry.TASKS, key=lambda t: (t["app"], t["difficulty"], t["id"]))]
    out = []
    for part in spec.split(","):
        part = part.strip()
        if part in registry.APPS:
            out += [t["id"] for t in registry.TASKS if t["app"] == part]
        else:
            registry.get_task(part)
            out.append(part)
    return out


def run_episode(task_id: str, mode: str, display: str, out: Path) -> dict:
    task = registry.get_task(task_id)
    app = task["app"]
    cfg = registry.APPS[app]
    work = out / task_id / mode
    row = {"task": task_id, "app": app, "mode": mode, "difficulty": task["difficulty"], "ok": None, "detail": "",
           "seconds": None, "started": datetime.now().isoformat(timespec="seconds"), "state_files": {},
           "expected": mode == "positive", "error": ""}
    t0 = time.monotonic()
    ep = None
    try:
        ep = start_episode(app, display, work / "ep", task_id=task_id)
        row["startup_s"] = round(ep.startup_seconds, 1)
        before = snapshot(ep.home, cfg["state_files"])
        try:
            if mode == "positive":
                registry.positive(task_id, ep)
                time.sleep(1.0)
            else:
                time.sleep(NOOP_SECONDS)
        except Exception as exc:  # noqa: BLE001
            row["error"] = f"{mode} script: {type(exc).__name__}: {exc}"
            (work / "traceback.txt").parent.mkdir(parents=True, exist_ok=True)
            (work / "traceback.txt").write_text(traceback.format_exc())
        try:
            ep.save_screenshot(work / "final.png")
        except Exception as exc:  # noqa: BLE001
            row["error"] += f" screenshot: {exc}"
        ep.close_app(timeout=10)
        row["exited"] = not ep.alive()
        row["state_files"] = diff(before, snapshot(ep.home, cfg["state_files"]))
        ok, detail = registry.oracle(task_id, ep.home)
        row["ok"], row["detail"] = ok, detail
    except Exception as exc:  # noqa: BLE001
        row["ok"] = False
        row["error"] = (row["error"] + f" episode: {type(exc).__name__}: {exc}").strip()
        row["detail"] = row["detail"] or "episode failed before the oracle ran"
        work.mkdir(parents=True, exist_ok=True)
        (work / "traceback.txt").write_text(traceback.format_exc())
    finally:
        if ep is not None:
            ep.stop()
        row["seconds"] = round(time.monotonic() - t0, 1)
    row["pass"] = bool(row["ok"]) == row["expected"] and not row["error"]   # a noop that died at start is not a pass
    return row


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tasks", default="all")
    ap.add_argument("--mode", choices=["positive", "noop", "both"], default="both")
    ap.add_argument("--display", default=":130")
    ap.add_argument("--out", required=True)
    ap.add_argument("--keep", action="store_true", help="keep the sandbox of every episode (default: delete ok ones)")
    args = ap.parse_args(argv)
    if not any(args.display == f":{n}" for n in range(130, 140)):
        print("display must be one of :130-:139", file=sys.stderr)
        return 2
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    modes = ["positive", "noop"] if args.mode == "both" else [args.mode]
    jsonl = out / "selftest.jsonl"
    bad = total = 0
    with jsonl.open("a", encoding="utf-8") as fh:
        for tid in pick(args.tasks):
            for mode in modes:
                row = run_episode(tid, mode, args.display, out)
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
                total += 1
                bad += 0 if row["pass"] else 1
                print(f"{'PASS' if row['pass'] else 'FAIL'} {tid:34s} {mode:8s} ok={row['ok']} {row['seconds']}s "
                      f"{row['detail'][:110]} {row['error'][:160]}", flush=True)
                ep_dir = out / tid / mode / "ep"
                if not args.keep and row["pass"] and ep_dir.exists():
                    shutil.rmtree(ep_dir, ignore_errors=True)
    print(f"{total - bad}/{total} episodes behaved as expected -> {jsonl}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
