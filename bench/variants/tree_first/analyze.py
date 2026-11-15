"""R3 result analysis: success, cost / time, tool use, look / hover behaviour, tokens per step, cleared-name clicks.

    cd experiments/phase6
    python -m bench.variants.tree_first.analyze <rows.jsonl> --out <dir> [--ref-r1 <R1 rows.jsonl>] [--sample-failures N]

Rows: bench.agent.summarize.load_rows (last row per (task, cond, rep)).  Success rates / paired differences use the
rows whose stop_reason is not `error` (as bench.agent.compare); error rows are counted in the main table.  Intervals:
summarize.bootstrap_ci (2,000 resamples, seed 0, over tasks) and compare.paired (paired by task, bootstrap over tasks).
Per-episode details are read from the episode directory in the row (`dir`): steps/NN/{action.json, obs.txt, tree.json},
initial/tree.json (lean conditions), transcript.jsonl.  Writes <out>/r3_analysis.md, r3_analysis.json and, with
--sample-failures, <out>/failures_sample.json.
"""
import argparse
import json
import math
import random
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.agent import compare, summarize  # noqa: E402
from bench.analysis.obs_tokens import parse_transcript  # noqa: E402
from pixeltree import formats  # noqa: E402

COND_ORDER = ["S_shot", "S_shot_strong", "X1", "X1_sonnet", "X2", "S_shot_lean", "X2_lean", "T_ours", "T_atspi",
              "T_omni", "H_ours", "H_atspi"]
TOOL_ORDER = ["observe", "look", "hover", "click", "type", "key", "scroll", "done"]
CLEAR_CONDS = ("X1", "X1_sonnet", "X2", "X2_lean")
R2_TOK = {"F2": 594, "F3": 271}          # R2 conversions, tokens per observation step
GATE_PTS = -0.05
_NEW_TEXT = re.compile(r'^(?:\+ \d+ \S+|~ \d+) "((?:[^"\\]|\\.)*)"')


# ---------------------------------------------------------------- small helpers
def nan_to_none(o):
    if isinstance(o, float):
        return None if math.isnan(o) or math.isinf(o) else o
    if isinstance(o, dict):
        return {k: nan_to_none(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [nan_to_none(v) for v in o]
    return o


def mean(xs):
    xs = [x for x in xs if x is not None]
    return float(np.mean(xs)) if xs else float("nan")


def median(xs):
    xs = [x for x in xs if x is not None]
    return float(np.median(xs)) if xs else float("nan")


def f(v, nd=2):
    return "-" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:.{nd}f}"


def pct(v, nd=0):
    return "-" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{100 * v:.{nd}f}%"


def pts(v):
    return "-" if v is None else f"{100 * v:+.1f}"


def table(header, body):
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in body]
    return "\n".join(out)


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def episode_steps(row):
    """[{action, obs, dir}] of the steps of an episode, in order ([] when the directory is missing)."""
    base = Path(row.get("dir") or "") / "steps"
    out = []
    for d in sorted(base.glob("[0-9][0-9]")) if base.is_dir() else []:
        a = read_json(d / "action.json")
        if a is None:
            continue
        try:
            obs = (d / "obs.txt").read_text(encoding="utf-8")
        except OSError:
            obs = ""
        out.append({"action": a, "obs": obs, "dir": d})
    return out


# ---------------------------------------------------------------- a. main table
def paired_to(pt, cond, ref):
    if cond == ref or cond not in pt or ref not in pt:
        return None
    return compare.paired(pt[cond], pt[ref])


def main_table(rows, conds):
    ok_rows = [r for r in rows if r.get("stop_reason") != "error"]
    pt = compare.per_task(ok_rows)
    stats = {}
    for c in conds:
        rs = [r for r in rows if r["cond"] == c]
        good = [r for r in rs if r.get("stop_reason") != "error"]
        mean_, lo, hi = summarize.bootstrap_ci(list(pt.get(c, {}).values()))
        tools = Counter()
        for r in good:
            tools.update(s["action"].get("tool") for s in episode_steps(r))
        total = sum(tools.values())
        stats[c] = {
            "model": next((r.get("model") for r in rs), None), "episodes": len(rs), "scored": len(good),
            "success": mean_, "ci": [lo, hi], "paired_vs_S_shot": paired_to(pt, c, "S_shot"),
            "cost_mean": mean([r.get("cost_usd") for r in good]),
            "wall_mean": mean([r.get("wall_s") for r in good]), "wall_median": median([r.get("wall_s") for r in good]),
            "steps_mean": mean([r.get("steps") for r in good]),
            "tool_share": {t: (tools[t] / total if total else float("nan")) for t in TOOL_ORDER},
            "tool_calls": total,
            "mean_obs_s": mean([r.get("mean_obs_s") for r in good]),
            "n_error": sum(1 for r in rs if r.get("stop_reason") == "error"),
            "n_timeout": sum(1 for r in rs if r.get("stop_reason") == "timeout"),
            "n_step_limit": sum(1 for r in rs if r.get("stop_reason") == "step_limit"),
        }
    return stats


def gate(stats):
    x2, s = stats.get("X2"), stats.get("S_shot")
    if not x2 or not s:
        return {"verdict": "n/a", "reason": "X2 or S_shot missing"}
    d = x2["paired_vs_S_shot"]
    diff = d["mean"] if d else float("nan")
    ok_acc = bool(d) and diff >= GATE_PTS
    cost_lt = x2["cost_mean"] < s["cost_mean"]
    wall_lt = x2["wall_mean"] < s["wall_mean"]
    return {"verdict": "PASS" if ok_acc and (cost_lt or wall_lt) else "FAIL", "diff_pts": diff,
            "diff_ok": ok_acc, "x2_cost": x2["cost_mean"], "s_cost": s["cost_mean"], "cost_lower": cost_lt,
            "x2_wall": x2["wall_mean"], "s_wall": s["wall_mean"], "wall_lower": wall_lt}


# ---------------------------------------------------------------- c. look / hover
def has_new_text(obs):
    """A change text with a new or renamed element that carries a non-empty name."""
    for line in obs.splitlines():
        m = _NEW_TEXT.match(line)
        if m and m.group(1).strip():
            return True
    return False


def look_hover(rows, cond):
    rs = [r for r in rows if r["cond"] == cond and r.get("stop_reason") != "error"]
    looks, looks_ok, hovers, hover_new = [], [], 0, 0
    for r in rs:
        steps = episode_steps(r)
        n_look = sum(1 for s in steps if s["action"].get("tool") == "look")
        looks.append(n_look)
        if r.get("ok"):
            looks_ok.append(n_look)
        for s in steps:
            if s["action"].get("tool") == "hover" and s["action"].get("ok", True):
                hovers += 1
                hover_new += has_new_text(s["obs"])
    buckets = ["0", "1", "2", "3", "4+"]
    dist = {b: sum(1 for n in looks if (str(n) if n < 4 else "4+") == b) for b in buckets}
    return {"episodes": len(rs), "look_dist": dist,
            "look_share": {b: (dist[b] / len(rs) if rs else float("nan")) for b in buckets},
            "zero_look_all": (dist["0"] / len(rs)) if rs else float("nan"),
            "zero_look_success": (sum(1 for n in looks_ok if n == 0) / len(looks_ok)) if looks_ok else float("nan"),
            "n_success": len(looks_ok), "hovers": hovers, "hover_new_text": hover_new,
            "hover_new_text_share": (hover_new / hovers) if hovers else float("nan")}


# ---------------------------------------------------------------- d. tokens per step
def ols_through_origin(y, X, names):
    y = np.asarray(y, dtype=float)
    X = np.asarray(X, dtype=float)
    used = [i for i in range(X.shape[1]) if X[:, i].std() > 0 or X[:, i].any()]
    coef = {n: float("nan") for n in names}
    if len(y) < len(used) or not used:
        return coef, float("nan"), float("nan")
    beta, *_ = np.linalg.lstsq(X[:, used], y, rcond=None)
    for i, b in zip(used, beta):
        coef[names[i]] = float(b)
    res = float(((y - X[:, used] @ beta) ** 2).sum())
    r2_unc = 1 - res / float((y ** 2).sum()) if (y ** 2).sum() > 0 else float("nan")
    tot = float(((y - y.mean()) ** 2).sum())
    return coef, r2_unc, (1 - res / tot if tot > 0 else float("nan"))


def episode_deltas(row):
    """(contexts, rows) of one episode: per API call k < last, (delta ctx, obs chars, images, assistant chars);
    None when the transcript's tool calls do not line up with the step directories."""
    tp = Path(row.get("dir") or "") / "transcript.jsonl"
    if not tp.exists():
        return None
    try:
        calls, _ = parse_transcript(tp)
    except (OSError, ValueError, KeyError):
        return None
    steps = episode_steps(row)
    if sum(len(c["tools"]) for c in calls) != len(steps):
        return None
    out, i = [], 0
    per_call = []
    for c in calls:
        mine = steps[i:i + len(c["tools"])]
        i += len(c["tools"])
        per_call.append((sum(len(s["obs"]) for s in mine), sum(1 for s in mine if (s["dir"] / "shot.png").exists()),
                         c["A"]))
    for k in range(len(calls) - 1):
        out.append((calls[k + 1]["ctx"] - calls[k]["ctx"],) + per_call[k])
    return [c["ctx"] for c in calls], out


def token_analysis(rows, cond):
    rs = [r for r in rows if r["cond"] == cond and r.get("stop_reason") != "error"]
    ctx_first, deltas, fit_rows, skipped = [], [], [], 0
    for r in rs:
        res = episode_deltas(r)
        if res is None:
            skipped += 1
            continue
        ctxs, ep_rows = res
        if ctxs:
            ctx_first.append(ctxs[0])
        deltas += [d[0] for d in ep_rows]
        fit_rows += ep_rows
    out = {"episodes": len(rs), "skipped": skipped, "ctx_first_mean": mean(ctx_first),
           "delta_mean": mean(deltas), "delta_median": median(deltas), "n_deltas": len(deltas)}
    if len(fit_rows) >= 3:
        y = [d[0] for d in fit_rows]
        X = [[d[1], d[2], d[3]] for d in fit_rows]
        coef, r2, r2c = ols_through_origin(y, X, ["a", "b", "c"])
        mo, mi = mean([d[1] for d in fit_rows]), mean([d[2] for d in fit_rows])
        out.update(a=coef["a"], b=coef["b"], c=coef["c"], r2=r2, r2_centered=r2c, mean_obs_chars=mo,
                   mean_images=mi, fit_obs_tokens=(coef["a"] * mo if not math.isnan(coef["a"]) else 0.0)
                   + (coef["b"] * mi if not math.isnan(coef["b"]) else 0.0))
    return out


# ---------------------------------------------------------------- e. clicks into boxes whose name was cleared
def last_tree_before(row, steps, k):
    """tree.json dict of the latest observation with a tree before step index k (initial/tree.json for the first)."""
    for j in range(k - 1, -1, -1):
        t = steps[j]["dir"] / "tree.json"
        if t.exists():
            return read_json(t)
    return read_json(Path(row["dir"]) / "initial" / "tree.json")


def smallest_containing(elements, xy):
    best = None
    x, y = xy
    for e in elements:
        bx, by, bw, bh = e["box"]
        if bx <= x < bx + bw and by <= y < by + bh:
            if best is None or bw * bh < best["box"][2] * best["box"][3]:
                best = e
    return best


def cleared_clicks(rows):
    out = {}
    for cond in CLEAR_CONDS:
        rs = [r for r in rows if r["cond"] == cond and r.get("stop_reason") != "error"]
        if not rs:
            continue
        counts = {"success": Counter(), "fail": Counter()}
        names = Counter()
        for r in rs:
            grp = "success" if r.get("ok") else "fail"
            steps = episode_steps(r)
            for k, s in enumerate(steps):
                a = s["action"]
                if a.get("tool") != "click" or not a.get("ok", True) or not a.get("screen_xy"):
                    continue
                counts[grp]["clicks"] += 1
                tree = last_tree_before(r, steps, k)
                if not tree:
                    counts[grp]["no_tree"] += 1
                    continue
                hit = smallest_containing(tree["elements"], a["screen_xy"])
                if hit is None:
                    counts[grp]["no_box"] += 1
                    continue
                cleaned = {e["id"]: e for e in formats.clean(tree)}
                kept = cleaned.get(hit["id"])
                if hit.get("name") and kept is not None and not kept.get("name"):
                    counts[grp]["name_cleared"] += 1
                    names[formats.one_line(hit["name"])] += 1
        out[cond] = {g: dict(c) for g, c in counts.items()}
        out[cond]["top_names"] = names.most_common(10)
    return out


# ---------------------------------------------------------------- g. failures sample
def failures_sample(rows, n):
    bad = sorted((r for r in rows if r["cond"] in ("X1", "X2") and not r.get("ok")),
                 key=lambda r: (r["cond"], r["task"], r["rep"]))
    chosen = random.Random(0).sample(bad, min(n, len(bad)))
    return [{"cond": r["cond"], "task": r["task"], "rep": r["rep"], "dir": r.get("dir"),
             "stop_reason": r.get("stop_reason"), "answer": r.get("answer")} for r in chosen]


# ---------------------------------------------------------------- report
def analyse(rows, ref_rows=None, n_failures=0):
    present = {r["cond"] for r in rows}
    conds = [c for c in COND_ORDER if c in present] + sorted(present - set(COND_ORDER))
    res = {"conds": conds}
    res["main"] = main_table(rows, conds)
    res["gate"] = gate(res["main"])
    res["look_hover"] = {c: look_hover(rows, c) for c in ("X2", "X2_lean") if c in present}
    res["tokens"] = {c: token_analysis(rows, c) for c in conds}
    res["w1_tokens_per_step"] = R2_TOK
    res["cleared_clicks"] = cleared_clicks(rows)
    if ref_rows is not None:
        a = compare.per_task([r for r in rows if r.get("stop_reason") != "error"]).get("S_shot", {})
        b = compare.per_task([r for r in ref_rows if r.get("stop_reason") != "error"]).get("S_shot", {})
        res["ref_r1_S_shot"] = compare.paired(a, b)
    if n_failures:
        res["failures_sample"] = failures_sample(rows, n_failures)
    return res


def render(res, src):
    md = [f"# R3 analysis: {src}", "",
          "Success = oracle passed, mean over tasks of the per-task mean over reps; episodes with stop_reason `error` "
          "(harness failures) are left out of rates, cost and time, and counted in the last column group. CI = 95 % "
          "bootstrap over tasks (2,000, seed 0); paired difference = condition - S_shot of this batch, paired by task.", ""]
    body = []
    for c in res["conds"]:
        m = res["main"][c]
        d = m["paired_vs_S_shot"]
        paired = "-" if c == "S_shot" or not d else f"{pts(d['mean'])} [{pts(d['lo'])}, {pts(d['hi'])}] (n={d['n_tasks']})"
        body.append([c, m["model"], m["episodes"], f"{pct(m['success'])} [{pct(m['ci'][0])}, {pct(m['ci'][1])}]", paired,
                     f(m["cost_mean"], 4), f(m["wall_mean"], 1), f(m["wall_median"], 1), f(m["steps_mean"], 1),
                     " / ".join(pct(m["tool_share"][t]) for t in TOOL_ORDER), f(m["mean_obs_s"], 2),
                     f"{m['n_error']} / {m['n_timeout']} / {m['n_step_limit']}"])
    md += ["## a. Main table", "",
           table(["cond", "model", "episodes", "success (95% CI)", "paired vs S_shot (pts)", "cost_usd / ep",
                  "wall_s mean", "wall_s median", "steps", "tools " + "/".join(TOOL_ORDER), "mean_obs_s",
                  "error / timeout / step_limit"], body), ""]
    g = res["gate"]
    md += ["## b. Gate: X2 - S_shot >= -5 pts and (X2 cost < S_shot cost or X2 wall < S_shot wall)", ""]
    if g["verdict"] == "n/a":
        md += [f"n/a ({g['reason']})", ""]
    else:
        md += [f"* accuracy: X2 - S_shot = {pts(g['diff_pts'])} pts -> {'ok' if g['diff_ok'] else 'NOT ok'}",
               f"* cost: X2 {f(g['x2_cost'], 4)} vs S_shot {f(g['s_cost'], 4)} USD -> {'lower' if g['cost_lower'] else 'not lower'}",
               f"* wall: X2 {f(g['x2_wall'], 1)} vs S_shot {f(g['s_wall'], 1)} s -> {'lower' if g['wall_lower'] else 'not lower'}",
               f"* **{g['verdict']}**", ""]
    md += ["## c. look and hover (X2, X2_lean)", ""]
    body = []
    for c, v in res["look_hover"].items():
        body.append([c, v["episodes"]] + [f"{v['look_dist'][b]} ({pct(v['look_share'][b])})" for b in ("0", "1", "2", "3", "4+")]
                    + [pct(v["zero_look_all"]), f"{pct(v['zero_look_success'])} (n={v['n_success']})", v["hovers"],
                       f"{v['hover_new_text']} ({pct(v['hover_new_text_share'])})"])
    md += [table(["cond", "episodes", "0 looks", "1", "2", "3", "4+", "zero-look (all)", "zero-look (successful)",
                  "hovers", "hovers with new text in the list"], body) if body else "(no X2 / X2_lean rows)", ""]
    md += ["## d. Tokens added per step (context growth between API calls)", "",
           "ctx = input + cache creation + cache read of an API call; delta = ctx(k+1) - ctx(k). One regression row = one API "
           "call k (its tool results and its own output; parallel tool calls share a row). Fit without intercept: "
           "delta = a * obs chars + b * images + c * assistant chars (R2 uncentered; centered in brackets). "
           f"R2 conversions for reference: F2 {R2_TOK['F2']}, F3 {R2_TOK['F3']} tokens per observation step.", ""]
    body = []
    for c in res["conds"]:
        t = res["tokens"][c]
        body.append([c, t["episodes"], t["skipped"], f(t["ctx_first_mean"], 0), f(t["delta_mean"], 0),
                     f(t["delta_median"], 0), f(t.get("a"), 3), f(t.get("b"), 0), f(t.get("c"), 3),
                     f"{f(t.get('r2'), 3)} ({f(t.get('r2_centered'), 3)})", f(t.get("mean_obs_chars"), 0),
                     f(t.get("mean_images"), 2), f(t.get("fit_obs_tokens"), 0)])
    md += [table(["cond", "episodes", "skipped (calls != steps)", "first ctx", "delta mean", "delta median", "a (tok/char)",
                  "b (tok/image)", "c (tok/char)", "R2", "mean obs chars / row", "mean images / row",
                  "fit obs tokens / row"], body), ""]
    md += ["## e. Clicks into a box whose name cleaning emptied", "",
           "Reference = the last observation with a tree before the click (raw tree.json, screen pixels); the box = "
           "smallest raw box containing the click; counted when its raw name is non-empty and empty after "
           "formats.clean (same element id).", ""]
    body = []
    for c, v in res["cleared_clicks"].items():
        for grp in ("success", "fail"):
            d = v.get(grp, {})
            body.append([c, grp, d.get("clicks", 0), d.get("name_cleared", 0), d.get("no_box", 0), d.get("no_tree", 0)])
    md += [table(["cond", "episode", "clicks", "name cleared", "no box under click", "no tree"], body) if body
           else "(no X rows)", ""]
    for c, v in res["cleared_clicks"].items():
        if v["top_names"]:
            md += [f"Top original names cleared ({c}): " + "; ".join(f"`{n}` x{k}" for n, k in v["top_names"]), ""]
    if "ref_r1_S_shot" in res:
        d = res["ref_r1_S_shot"]
        md += ["## f. This batch's S_shot vs R1 S_shot", ""]
        md += [f"{pts(d['mean'])} pts [{pts(d['lo'])}, {pts(d['hi'])}] over {d['n_tasks']} tasks" if d else "no common tasks", ""]
    if "failures_sample" in res:
        md += ["## g. Failure sample", "", f"{len(res['failures_sample'])} written to failures_sample.json", ""]
    return "\n".join(md)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rows", help="episodes.jsonl of the R3 run")
    ap.add_argument("--out", required=True)
    ap.add_argument("--ref-r1", default="", help="R1 rows file: compare this batch's S_shot with it")
    ap.add_argument("--sample-failures", type=int, default=0)
    args = ap.parse_args(argv)
    rows = summarize.load_rows(args.rows)
    ref = summarize.load_rows(args.ref_r1) if args.ref_r1 else None
    res = analyse(rows, ref, args.sample_failures)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "r3_analysis.md").write_text(render(res, args.rows) + "\n", encoding="utf-8")
    (out / "r3_analysis.json").write_text(json.dumps(nan_to_none(res), indent=1, ensure_ascii=False), encoding="utf-8")
    if args.sample_failures:
        (out / "failures_sample.json").write_text(json.dumps(res["failures_sample"], indent=1, ensure_ascii=False),
                                                  encoding="utf-8")
    print(f"wrote {out / 'r3_analysis.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
