"""R5 analysis: model x condition table, paired condition differences, Haiku (OMP) vs Haiku (R1, claude -p).

    cd experiments/phase6 && python -m bench.shells.omp.analyze \
        --run glm=out/r5/glm/formal/episodes_v1_1.jsonl --run deepseek=... --run longcat=... --run haiku=... \
        --ref-r1 out/r1/final/episodes_v1_1.jsonl --out out/r5/analysis

Row rules (per model): the last attempt of each (task, cond, rep) counts.  Rows whose error is a quota / rate-limit
error are left out of every denominator (`quota`); other error rows (harness) are left out too and listed (`error`);
`invalid` rows (any non-bench tool call) are counted and named but are not in the success denominator.  Success rate =
ok / valid.  With all 48 tasks valid in a condition: 95 % interval by bootstrap over tasks (2,000 resamples,
random.Random(0)); paired differences between two conditions use the tasks valid in both (interval only when that is
48).  Fewer tasks: counts and paired win / loss / tie only.  Tokens, steps, wall: means over valid rows, to be compared
only within one model.
"""
import argparse
import json
import random
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.shells.omp import omp  # noqa: E402

N_TASKS = 48
BOOT = 2000
PAIRS = [("T_ours", "S_shot"), ("H_ours", "S_shot"), ("H_ours", "T_ours"), ("T_ours", "T_atspi")]
HAIKU125 = "claude-haiku-5-5"


def load_rows(path):
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def post_limit_fix(r):
    """A timeout row whose agent had already hit the 20-call limit (step_limit.json written) is a step_limit row:
    before 2026-11-13 17:20 the runner did not end omp after the limit and GLM kept calling done until the cap."""
    if r.get("stop_reason") == "timeout" and r.get("dir") and (Path(r["dir"]) / "step_limit.json").exists():
        return dict(r, stop_reason="step_limit", post_limit_loop=True)
    return r


def last_attempts(rows):
    """The last row of every (task, cond, rep), in file order."""
    last = {}
    for r in rows:
        last[(r["task"], r["cond"], r.get("rep", 0))] = r
    return list(last.values())


def is_quota_row(r):
    if r.get("stop_reason") != "error":
        return False
    return omp.is_quota_error(" ".join([" ".join(r.get("omp_errors") or []), str(r.get("oracle_detail") or "")]))


def classify(r):
    """'quota' | 'error' | 'invalid' | 'valid'."""
    if r.get("stop_reason") == "error":
        return "quota" if is_quota_row(r) else "error"
    return "invalid" if r.get("invalid") else "valid"


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def boot_ci(values, n=BOOT, seed=0):
    """95 % percentile interval of the mean of `values` (one value per task) under resampling of tasks."""
    rng = random.Random(seed)
    k = len(values)
    means = sorted(sum(values[rng.randrange(k)] for _ in range(k)) / k for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n) - 1]


def summarize(rows, conds):
    """Per-condition counts and means for one model; rows = all rows of its run (every attempt)."""
    rows = [post_limit_fix(r) for r in last_attempts(rows)]
    per = {}
    by_task = defaultdict(dict)
    for cond in conds:
        rs = [r for r in rows if r["cond"] == cond]
        kinds = Counter(classify(r) for r in rs)
        valid = [r for r in rs if classify(r) == "valid"]
        for r in valid:
            by_task[cond][r["task"]] = 1.0 if r["ok"] else 0.0
        ok = sum(bool(r["ok"]) for r in valid)
        inv = [r for r in rs if classify(r) == "invalid"]
        names = Counter(c["name"] for r in inv for c in (r.get("foreign_calls") or []))
        c = {"ok": ok, "valid": len(valid), "rate": ok / len(valid) if valid else None,
             "invalid": len(inv), "invalid_ok": sum(bool(r["ok"]) for r in inv), "invalid_calls": dict(names),
             "quota": kinds["quota"], "error": kinds["error"],
             "error_tasks": [r["task"] for r in rs if classify(r) == "error"],
             "steps": mean([r.get("steps") for r in valid]),
             "model_calls": mean([r.get("n_model_calls") for r in valid]),
             "input_tokens": mean([r.get("input_tokens") for r in valid]),
             "cache_read_tokens": mean([r.get("cache_read_tokens") for r in valid]),
             "output_tokens": mean([r.get("output_tokens") for r in valid]),
             "reasoning_tokens": mean([r.get("reasoning_tokens") for r in valid]),
             "cost_usd": mean([r.get("cost_usd") for r in valid]),
             "wall_mean": mean([r.get("wall_s") for r in valid]),
             "wall_median": statistics.median([r["wall_s"] for r in valid if r.get("wall_s") is not None])
             if any(r.get("wall_s") is not None for r in valid) else None,
             "stop": dict(Counter(r["stop_reason"] for r in valid)),
             "timeout": sum(1 for r in valid if r["stop_reason"] == "timeout"),
             "post_limit_loops": sum(1 for r in rs if r.get("post_limit_loop")), "ci": None}
        if len(by_task[cond]) == N_TASKS:
            c["ci"] = boot_ci([by_task[cond][t] for t in sorted(by_task[cond])])
        per[cond] = c
    pairs = {}
    for a, b in PAIRS:
        if a not in conds or b not in conds:
            continue
        common = sorted(set(by_task[a]) & set(by_task[b]))
        w = sum(1 for t in common if by_task[a][t] > by_task[b][t])
        l = sum(1 for t in common if by_task[a][t] < by_task[b][t])
        diffs = [by_task[a][t] - by_task[b][t] for t in common]
        pairs[f"{a} - {b}"] = {"n": len(common), "win": w, "loss": l, "tie": len(common) - w - l,
                               "diff": mean(diffs), "ci": boot_ci(diffs) if len(common) == N_TASKS else None}
    return {"per_cond": per, "pairs": pairs, "by_task": {c: dict(v) for c, v in by_task.items()}}


def ref_r1_by_task(ref_rows, conds):
    """Haiku R1 per condition: task -> mean success over its reps."""
    acc = defaultdict(lambda: defaultdict(list))
    for r in ref_rows:
        if r.get("model") == HAIKU125 and r["cond"] in conds:
            acc[r["cond"]][r["task"]].append(1.0 if r["ok"] else 0.0)
    return {c: {t: sum(v) / len(v) for t, v in d.items()} for c, d in acc.items()}


def shell_effect(haiku_res, ref_rows):
    """Haiku OMP minus Haiku R1 (mean of 3 reps) per condition, paired over the tasks valid in the OMP run."""
    conds = list(haiku_res["by_task"])
    ref = ref_r1_by_task(ref_rows, conds)
    out = {}
    for cond in conds:
        mine = haiku_res["by_task"][cond]
        common = sorted(set(mine) & set(ref.get(cond, {})))
        diffs = [mine[t] - ref[cond][t] for t in common]
        out[cond] = {"n": len(common), "omp": mean([mine[t] for t in common]),
                     "p125": mean([ref[cond][t] for t in common]),
                     "p125_all48": mean(list(ref.get(cond, {}).values())),
                     "diff": mean(diffs), "ci": boot_ci(diffs) if len(common) == N_TASKS else None}
    return out


def pct(x, nd=0):
    return "–" if x is None else f"{100 * x:.{nd}f}"


def fmt(x, nd=0):
    return "–" if x is None else f"{x:,.{nd}f}"


def render(results, shell):
    L = ["# R5 main table (OMP shell, provider opencode-go, 48 tasks x 1 rep, oracle v1.1)", "",
         "valid = graded rows without a non-bench tool call; quota / harness-error rows are not in any denominator.",
         "Tokens, steps and wall are means over valid rows; compare them only within one model.", "",
         "| model | cond | ok / valid | rate (95 % CI) | timeout | invalid (ok) [calls] | quota err | other err | steps | model "
         "calls | input / cache-read / output (reasoning) tokens | cost $ | wall mean / median s |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for key, res in results.items():
        for cond, c in res["per_cond"].items():
            ci = f" ({pct(c['ci'][0])}–{pct(c['ci'][1])})" if c["ci"] else ""
            calls = ", ".join(f"{k}×{v}" for k, v in c["invalid_calls"].items())
            L.append(f"| {key} | {cond} | {c['ok']} / {c['valid']} | {pct(c['rate'])} %{ci} | {c['timeout']} | {c['invalid']} "
                     f"({c['invalid_ok']}) {('[' + calls + ']') if calls else ''} | {c['quota']} | {c['error']} | "
                     f"{fmt(c['steps'], 1)} | {fmt(c['model_calls'], 1)} | {fmt(c['input_tokens'])} / "
                     f"{fmt(c['cache_read_tokens'])} / {fmt(c['output_tokens'])} ({fmt(c['reasoning_tokens'])}) | "
                     f"{fmt(c['cost_usd'], 4)} | {fmt(c['wall_mean'])} / {fmt(c['wall_median'])} |")
    L += ["", "## Paired differences (tasks valid in both conditions)", "",
          "| model | pair | tasks | win / loss / tie | mean diff (pts) | 95 % CI (pts) |", "|---|---|---|---|---|---|"]
    for key, res in results.items():
        for name, p in res["pairs"].items():
            ci = f"{pct(p['ci'][0])} to {pct(p['ci'][1])}" if p["ci"] else "– (< 48 tasks)"
            L.append(f"| {key} | {name} | {p['n']} | {p['win']} / {p['loss']} / {p['tie']} | {pct(p['diff'])} | {ci} |")
    if shell:
        L += ["", "## Shell effect: Haiku through OMP minus Haiku R1 (claude -p, mean of 3 reps), same tasks", "",
              "| cond | tasks | OMP | R1 same tasks | R1 all 48 | diff (pts) | 95 % CI (pts) |",
              "|---|---|---|---|---|---|---|"]
        for cond, s in shell.items():
            ci = f"{pct(s['ci'][0])} to {pct(s['ci'][1])}" if s["ci"] else "– (< 48 tasks)"
            L.append(f"| {cond} | {s['n']} | {pct(s['omp'])} % | {pct(s['p125'])} % | {pct(s['p125_all48'])} % | "
                     f"{pct(s['diff'])} | {ci} |")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="append", default=[],
                    help="<model key>=<episodes jsonl>[+<episodes jsonl>...]; rows of later files replace rows of "
                         "earlier ones for the same (task, cond, rep) (reruns)")
    ap.add_argument("--ref-r1", default="")
    ap.add_argument("--tasks", default="", help="file with one task id per line: analyse only these tasks")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    keep = {t.strip() for t in Path(args.tasks).read_text().splitlines() if t.strip()} if args.tasks else set()
    results = {}
    for item in args.run:
        key, paths = item.split("=", 1)
        rows = [r for p in paths.split("+") if Path(p).exists() for r in load_rows(p)]
        if keep:
            rows = [r for r in rows if r["task"] in keep]
        if rows:
            results[key] = summarize(rows, omp.MODELS[key]["conds"])
    shell = shell_effect(results["haiku"], load_rows(args.ref_r1)) if "haiku" in results and args.ref_r1 else {}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "omp_analysis.json").write_text(json.dumps({"results": results, "shell": shell}, indent=1),
                                           encoding="utf-8")
    md = render(results, shell)
    (out / "omp_analysis.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
