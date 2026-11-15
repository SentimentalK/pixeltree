"""Summary of one run directory: `python -m bench.agent.summarize <out>` writes <out>/summary.md.

Success rate of a condition = mean over tasks of (mean of `ok` over the reps of that task); the 95 % CI is a
percentile bootstrap over TASKS (2000 resamples, seed 0).  Groups (app / tier / difficulty) use the same
task-level mean, without CI.  When a (task, cond, rep) occurs more than once in episodes.jsonl (a re-run after an
`error`), the last row counts.  Tier comes from the episode row, else from bench/tasks_v1.json (empty if neither has it).
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.agent.prompts import CONDS  # noqa: E402

TASKS_JSON = ROOT / "bench" / "tasks_v1.json"
N_BOOT = 2000


def bootstrap_ci(values, n_boot=N_BOOT, seed=0, level=0.95):
    """(mean, lo, hi): percentile bootstrap CI of the mean of `values`."""
    values = np.asarray(list(values), dtype=float)
    if values.size == 0:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    means = values[rng.integers(0, values.size, size=(n_boot, values.size))].mean(axis=1)
    alpha = (1.0 - level) / 2.0
    return float(values.mean()), float(np.quantile(means, alpha)), float(np.quantile(means, 1.0 - alpha))


def rows_path(out):
    """<out>/episodes.jsonl for a run directory; `out` itself for a rows file (e.g. a regrade's episodes_v1_1.jsonl)."""
    out = Path(out)
    return out if out.suffix == ".jsonl" else out / "episodes.jsonl"


def load_rows(out):
    """Episode rows of <out>/episodes.jsonl (or of the rows file `out`), the last one per (task, cond, rep)."""
    path = rows_path(out)
    latest = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        latest[(row.get("task"), row.get("cond"), row.get("rep"))] = row
    return list(latest.values())


def load_tiers(path=TASKS_JSON):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    items = data.get("tasks", []) if isinstance(data, dict) else data
    return {t["id"]: t.get("tier") for t in items if isinstance(t, dict) and "id" in t}


def _mean(values):
    values = [v for v in values if v is not None]
    return float(np.mean(values)) if values else None


def task_means(rows):
    """{task: mean ok over its reps}."""
    by_task = defaultdict(list)
    for r in rows:
        by_task[r["task"]].append(1.0 if r.get("ok") else 0.0)
    return {t: float(np.mean(v)) for t, v in by_task.items()}


def _f(value, digits=2, pct=False):
    if value is None or (isinstance(value, float) and value != value):
        return "-"
    return f"{value * 100:.0f}%" if pct else f"{value:.{digits}f}"


def _table(header, body):
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in body]
    return "\n".join(lines)


def summarize(out):
    rows = load_rows(out)
    tiers = load_tiers()
    for r in rows:
        r["_tier"] = r.get("tier") or tiers.get(r["task"]) or ""
    conds = [c for c in CONDS if any(r["cond"] == c for r in rows)] + \
            sorted({r["cond"] for r in rows} - set(CONDS))
    by_cond = {c: [r for r in rows if r["cond"] == c] for c in conds}
    md = [f"# R1 summary: {Path(out).resolve().name}", "",
          f"{len(rows)} episodes, {len({r['task'] for r in rows})} tasks, conditions: {', '.join(conds)}. "
          "Success = oracle passed; rate = mean over tasks of the per-task mean over reps; "
          f"CI = 95 % percentile bootstrap over tasks ({N_BOOT} resamples, seed 0).", ""]

    body = []
    for c in conds:
        rs = by_cond[c]
        mean, lo, hi = bootstrap_ci(list(task_means(rs).values()))
        body.append([c, len(task_means(rs)), len(rs), f"{_f(mean, pct=True)} [{_f(lo, pct=True)}, {_f(hi, pct=True)}]",
                     _f(_mean([r.get("steps") for r in rs]), 1), _f(_mean([r.get("mean_obs_s") for r in rs]), 2),
                     _f(_mean([r.get("mean_model_s") for r in rs]), 2)])
    md += ["## Success rate per condition", "",
           _table(["cond", "tasks", "episodes", "success (95% CI)", "mean steps", "mean_obs_s", "mean_model_s"], body), ""]

    body = []
    for c in conds:
        rs = by_cond[c]
        body.append([c] + [_f(_mean([r.get(k) for r in rs]), 0) for k in
                           ("input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens")]
                    + [_f(_mean([r.get("cost_usd") for r in rs]), 4), _f(_mean([r.get("wall_s") for r in rs]), 0)])
    md += ["## Tokens and cost per episode (cost_usd = API-equivalent price)", "",
           _table(["cond", "input", "output", "cache read", "cache creation", "cost_usd", "wall_s"], body), ""]

    reasons = sorted({r.get("stop_reason") for r in rows}, key=str)
    body = [[c] + [sum(1 for r in by_cond[c] if r.get("stop_reason") == s) for s in reasons] for c in conds]
    md += ["## Stop reasons (episodes)", "", _table(["cond"] + [str(s) for s in reasons], body), ""]

    for title, key in (("app", "app"), ("tier", "_tier"), ("difficulty", "difficulty")):
        values = sorted({r.get(key) for r in rows if r.get(key) not in (None, "")}, key=str)
        if not values:
            md += [f"## By {title}", "", "(no data)", ""]
            continue
        body = []
        for v in values:
            cells = [v]
            for c in conds:
                tm = task_means([r for r in by_cond[c] if r.get(key) == v])
                cells.append(f"{_f(_mean(list(tm.values())), pct=True)} (n={len(tm)})" if tm else "-")
            body.append(cells)
        md += [f"## By {title} (task-level success, n = tasks)", "", _table([title] + conds, body), ""]

    body = []
    for c in conds:
        rs = by_cond[c]
        mean, _, _ = bootstrap_ci(list(task_means(rs).values()))
        costs = [r.get("cost_usd") for r in rs if r.get("cost_usd") is not None]
        wins = sum(1 for r in rs if r.get("ok"))
        per_ep = float(np.mean(costs)) if costs else None
        per_win = float(np.sum(costs)) / wins if costs and wins else None
        body.append([c, _f(mean, pct=True), _f(per_ep, 4), _f(per_win, 4), wins, len(rs)])
    md += ["## Success rate x cost per episode", "",
           _table(["cond", "success", "cost_usd / episode", "cost_usd / successful episode", "successes", "episodes"],
                  body), ""]
    text = "\n".join(md)
    path = rows_path(out)
    name = "summary.md" if path.name == "episodes.jsonl" else f"summary_{path.stem}.md"
    (path.parent / name).write_text(text + "\n", encoding="utf-8")
    return text


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", help="run directory containing episodes.jsonl, or a rows file (*.jsonl)")
    args = ap.parse_args(argv)
    print(summarize(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
