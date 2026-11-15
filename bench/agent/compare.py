"""Paired condition differences for the main exam (R1).

For each pair of conditions (A, B) it takes the tasks both ran, the per-task success rate of each (mean over reps),
and reports mean(A - B) with a 95 % percentile bootstrap CI that resamples TASKS (2,000 resamples, seed 0) -- the same
resampling unit as summarize.py, but paired, so task difficulty cancels out. Optional --app and --tier filters.

  python -m bench.agent.compare out/r1/formal [--pairs T_ours:T_atspi,S_shot:T_ours]
      (out = a run directory or a rows file *.jsonl, e.g. a regrade's episodes_v1_1.jsonl or a concatenation of runs)
      [--tier poor] [--save out/r1/formal/compare.md]
"""
import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

from .summarize import load_rows, load_tiers

N_BOOT = 2000
DEFAULT_PAIRS = ("T_ours:T_atspi", "T_ours:T_omni", "T_ours:S_shot", "S_shot_strong:T_ours", "T_atspi:S_shot",
                 "S_shot_strong:S_shot", "H_ours:S_shot", "H_atspi:S_shot", "H_ours:H_atspi", "H_ours:T_ours",
                 "H_atspi:T_atspi")


def per_task(rows):
    acc = defaultdict(lambda: defaultdict(list))
    for r in rows:
        acc[r["cond"]][r["task"]].append(1.0 if r["ok"] else 0.0)
    return {c: {t: sum(v) / len(v) for t, v in ts.items()} for c, ts in acc.items()}


def paired(a, b, n_boot=N_BOOT, seed=0):
    tasks = sorted(set(a) & set(b))
    if not tasks:
        return None
    d = [a[t] - b[t] for t in tasks]
    rng = random.Random(seed)
    boots = sorted(sum(rng.choice(d) for _ in d) / len(d) for _ in range(n_boot))
    return {"n_tasks": len(tasks), "mean": sum(d) / len(d), "lo": boots[int(0.025 * n_boot)],
            "hi": boots[int(0.975 * n_boot) - 1]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--pairs", default=",".join(DEFAULT_PAIRS))
    ap.add_argument("--tier", default=None, help="good | poor (from tasks_v1.json)")
    ap.add_argument("--app", default=None)
    ap.add_argument("--save", default=None, help="write a markdown table here")
    args = ap.parse_args(argv)
    rows = [r for r in load_rows(args.out) if r.get("stop_reason") != "error"]
    tiers = load_tiers()
    if args.tier:
        rows = [r for r in rows if tiers.get(r["task"]) == args.tier]
    if args.app:
        rows = [r for r in rows if r["app"] == args.app]
    pt = per_task(rows)
    lines = [f"Paired differences (A - B) in success rate, scope tier={args.tier or 'all'} app={args.app or 'all'}; "
             f"95 % percentile bootstrap over tasks ({N_BOOT}, seed 0).", "",
             "| A - B | tasks | mean (pts) | 95 % CI (pts) |", "|---|---|---|---|"]
    for pair in args.pairs.split(","):
        a, b = pair.split(":")
        res = paired(pt.get(a, {}), pt.get(b, {}))
        if res is None:
            lines.append(f"| {a} - {b} | 0 | - | - |")
            continue
        lines.append(f"| {a} - {b} | {res['n_tasks']} | {100 * res['mean']:+.1f} | "
                     f"[{100 * res['lo']:+.1f}, {100 * res['hi']:+.1f}] |")
    text = "\n".join(lines)
    print(text)
    if args.save:
        Path(args.save).write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
