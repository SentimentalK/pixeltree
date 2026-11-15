"""R3 extra offline analysis (reads existing episode archives only, no model / GUI calls): four tables.

    cd experiments/phase6
    python -m bench.variants.tree_first.extra <rows.jsonl> --out <dir>

Rows: bench.agent.summarize.load_rows (last row per (task, cond, rep)), rows with stop_reason `error` dropped.  Steps:
bench.variants.tree_first.analyze.episode_steps (steps/NN/{action.json, obs.txt, tree.json}); initial/tree.json when present.
Writes <out>/r3_extra.md and <out>/r3_extra.json.

  A  clicks vs the current real list (X1, X1_sonnet, X2, X2_lean)
  B  fall-back to full lists and look calls (X2, X2_lean)
  C  time breakdown (all conditions)
  D  stop_reason composition (all conditions)
"""
import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.agent import summarize  # noqa: E402
from pixeltree import formats  # noqa: E402
from bench.variants.tree_first.analyze import COND_ORDER, episode_steps, read_json, table  # noqa: E402

A_CONDS = ("X1", "X1_sonnet", "X2", "X2_lean")
B_CONDS = ("X2", "X2_lean")
X_CONDS = ("X1", "X1_sonnet", "X2", "X2_lean")
ACTION_TOOLS = ("click", "type", "key", "scroll", "hover")
BUCKETS = [("1-5", 1, 5), ("6-10", 6, 10), ("11-15", 11, 15), ("16-20", 16, 20)]
STOP_ORDER = ["done", "fail_answer", "step_limit", "no_done", "timeout"]


# ---------------------------------------------------------------- helpers
def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def f(v, nd=2):
    return "-" if v is None else f"{v:.{nd}f}"


def pct(n, d, nd=1):
    return "-" if not d else f"{100 * n / d:.{nd}f}%"


def ratio(n, d):
    return n / d if d else None


def in_box(elements, xy):
    px, py = xy
    for e in elements:
        x, y, w, h = e["box"]
        if x <= px < x + w and y <= py < y + h:
            return True
    return False


def bucket_of(step):
    for name, lo, hi in BUCKETS:
        if lo <= step <= hi:
            return name
    return None


def load_good_rows(path):
    rows = summarize.load_rows(path)
    return [r for r in rows if r.get("stop_reason") != "error"]


def conds_present(rows):
    present = {r["cond"] for r in rows}
    return [c for c in COND_ORDER if c in present] + sorted(present - set(COND_ORDER))


# ---------------------------------------------------------------- A: clicks vs the current real list
def new_counter():
    return {"clicks": 0, "in_box": 0, "stale": 0, "no_tree": 0}


def table_a(rows):
    out = {}
    for cond in A_CONDS:
        rs = [r for r in rows if r["cond"] == cond]
        if not rs:
            continue
        cells = {b[0]: new_counter() for b in BUCKETS}
        cells["other"] = new_counter()
        tot = new_counter()
        by_ok = {"ok": new_counter(), "fail": new_counter()}
        for r in rs:
            steps = episode_steps(r)
            initial = read_json(Path(r["dir"]) / "initial" / "tree.json")
            grp = "ok" if r.get("ok") else "fail"
            for k, s in enumerate(steps):
                a = s["action"]
                if a.get("tool") != "click" or not a.get("ok") or not a.get("screen_xy"):
                    continue
                trees = [read_json(steps[j]["dir"] / "tree.json") for j in range(k)]
                trees = [t for t in trees if t]
                if initial:
                    trees.insert(0, initial)
                bucket = bucket_of(a.get("step", k + 1)) or "other"
                targets = [cells[bucket], tot, by_ok[grp]]
                if not trees:
                    for c in targets:
                        c["no_tree"] += 1
                    continue
                xy = a["screen_xy"]
                hit = in_box(formats.clean(trees[-1]), xy)
                stale = (not hit) and any(in_box(formats.clean(t), xy) for t in trees[:-1])
                for c in targets:
                    c["clicks"] += 1
                    c["in_box"] += hit
                    c["stale"] += stale
        out[cond] = {"buckets": cells, "total": tot, "by_episode_ok": by_ok,
                     "episodes": len(rs), "ok_episodes": sum(1 for r in rs if r.get("ok"))}
    return out


def render_a(res):
    md = ["## A. Do clicks land inside the current real list?", "",
          "Scope: ok clicks with screen_xy.  Reference tree for step k = the nearest earlier step's tree.json (else "
          "`initial/tree.json`; no tree at all -> `no_tree`, outside the denominator), cleaned with formats.clean "
          "(screen pixels, box = [x, y, w, h]).  in_box = click inside any cleaned element box "
          "(`x <= px < x+w`, `y <= py < y+h`); stale = not in_box but inside a box of an earlier tree of the same "
          "episode (all trees before step k except the nearest one, `initial/tree.json` included).  "
          "Buckets by action.json `step`.", ""]
    body = []

    def row(label, c):
        return [label, c["clicks"], pct(c["in_box"], c["clicks"]), pct(c["stale"], c["clicks"]), c["no_tree"]]

    for cond, v in res.items():
        for name, _, _ in BUCKETS:
            body.append(row(f"{cond} steps {name}", v["buckets"][name]))
        if v["buckets"]["other"]["clicks"] or v["buckets"]["other"]["no_tree"]:
            body.append(row(f"{cond} steps >20", v["buckets"]["other"]))
        body.append(row(f"**{cond} total**", v["total"]))
        body.append(row(f"{cond} total, episodes ok ({v['ok_episodes']})", v["by_episode_ok"]["ok"]))
        body.append(row(f"{cond} total, episodes failed ({v['episodes'] - v['ok_episodes']})", v["by_episode_ok"]["fail"]))
    md += [table(["cond / steps", "clicks", "in_box", "stale", "no_tree"], body), ""]
    return md


# ---------------------------------------------------------------- B: fall-back to full lists, look
def table_b(rows):
    out = {}
    for cond in B_CONDS:
        rs = [r for r in rows if r["cond"] == cond]
        if not rs:
            continue
        n = full = nochg = chg = 0
        looks = []
        for r in rs:
            steps = episode_steps(r)
            looks.append(sum(1 for s in steps if s["action"].get("tool") == "look"))
            for s in steps:
                a = s["action"]
                if a.get("tool") not in ACTION_TOOLS or not a.get("ok"):
                    continue
                first = (s["obs"].splitlines() or [""])[0].strip()
                n += 1
                full += first.endswith("(full)")
                nochg += first.startswith("no change")
                chg += first.startswith("changes:")
        out[cond] = {"episodes": len(rs), "action_steps": n, "full": full, "no_change": nochg, "changes": chg,
                     "other": n - full - nochg - chg, "full_share": ratio(full, n), "no_change_share": ratio(nochg, n),
                     "changes_share": ratio(chg, n), "look_total": sum(looks), "look_mean": mean(looks),
                     "look_median": median(looks)}
    return out


def render_b(res):
    md = ["## B. Fall-back to a full list, and look calls", "",
          "Scope: action steps (click / type / key / scroll / hover, ok).  full = first line of obs.txt ends with "
          "`(full)`; no change = starts with `no change`; changes = starts with `changes:`; other = none of these.  "
          "look = number of look calls per episode (mean / median over episodes).", ""]
    body = [[c, v["episodes"], v["action_steps"], f"{v['full']} ({pct(v['full'], v['action_steps'])})",
             f"{v['no_change']} ({pct(v['no_change'], v['action_steps'])})",
             f"{v['changes']} ({pct(v['changes'], v['action_steps'])})", v["other"], f(v["look_mean"]),
             f(v["look_median"], 1)] for c, v in res.items()]
    md += [table(["cond", "episodes", "action steps", "full", "no change", "changes", "other", "look mean / ep",
                  "look median / ep"], body), ""]
    return md


# ---------------------------------------------------------------- C: time breakdown
def episode_times(r):
    steps = episode_steps(r)
    acts = [s["action"] for s in steps]
    model = sum(acts[k + 1]["t_start"] - acts[k]["t_end"]
                for k in range(len(acts) - 1)
                if acts[k + 1].get("t_start") is not None and acts[k].get("t_end") is not None)
    obs = sum(a.get("t_obs_s") or 0 for a in acts)
    act = sum(a.get("t_action_s") or 0 for a in acts)
    wall = r.get("wall_s")
    t = {"steps": len(acts), "wall_s": wall, "model_s_sum": model, "obs_s_sum": obs, "action_s_sum": act,
         "overhead_s": None if wall is None else wall - model - obs - act}
    comp = queue = 0.0
    n_tree = 0
    for s in steps:
        tr = read_json(s["dir"] / "tree.json")
        if not tr:
            continue
        total = (tr.get("timings") or {}).get("total_s")
        if total is None:
            continue
        n_tree += 1
        comp += total
        queue += (s["action"].get("t_obs_s") or 0) - total
    t.update(tree_steps=n_tree, tree_compute_s_sum=comp if n_tree else None,
             queue_and_shot_s_sum=queue if n_tree else None)
    return t


def table_c(rows, conds):
    out = {}
    for cond in conds:
        rs = [r for r in rows if r["cond"] == cond]
        if not rs:
            continue
        ts = [episode_times(r) for r in rs]
        d = {"episodes": len(rs), "steps_total": sum(t["steps"] for t in ts), "steps_mean": mean([t["steps"] for t in ts])}
        for key in ("wall_s", "model_s_sum", "obs_s_sum", "action_s_sum", "overhead_s"):
            d[key] = mean([t[key] for t in ts])
        d["obs_s_per_step"] = ratio(sum(t["obs_s_sum"] for t in ts), d["steps_total"])
        d["mean_obs_s_rows"] = mean([r.get("mean_obs_s") for r in rs])      # analyze.py's mean_obs_s
        tr = [t for t in ts if t["tree_compute_s_sum"] is not None]
        if tr:
            d["tree_steps_total"] = sum(t["tree_steps"] for t in tr)
            d["tree_compute_s_sum"] = mean([t["tree_compute_s_sum"] for t in tr])
            d["queue_and_shot_s_sum"] = mean([t["queue_and_shot_s_sum"] for t in tr])
            d["tree_compute_s_per_step"] = ratio(sum(t["tree_compute_s_sum"] for t in tr), d["tree_steps_total"])
            d["queue_and_shot_s_per_step"] = ratio(sum(t["queue_and_shot_s_sum"] for t in tr), d["tree_steps_total"])
        out[cond] = d
    return out


def render_c(res):
    md = ["## C. Time breakdown (seconds per episode, mean over episodes)", "",
          "wall_s = row field; model_s_sum = sum over adjacent steps of t_start(k+1) - t_end(k); obs_s_sum = sum of "
          "t_obs_s (None as 0); action_s_sum = sum of t_action_s; overhead_s = wall_s - model - obs - action (includes "
          "claude start-up to the first call and the time after the last call).  obs s/step = total obs time / total "
          "steps; mean_obs_s = the row field averaged over episodes (analyze.py).", ""]
    body = [[c, v["episodes"], f(v["steps_mean"], 1), f(v["wall_s"], 1), f(v["model_s_sum"], 1), f(v["obs_s_sum"], 2),
             f(v["action_s_sum"], 2), f(v["overhead_s"], 1), f(v["obs_s_per_step"], 3), f(v["mean_obs_s_rows"], 3)]
            for c, v in res.items()]
    md += [table(["cond", "episodes", "steps", "wall_s", "model_s_sum", "obs_s_sum", "action_s_sum", "overhead_s",
                  "obs s/step", "mean_obs_s (rows)"], body), ""]
    md += ["X conditions (steps with a tree.json): tree_compute_s_sum = sum of the trees' `timings.total_s`; "
           "queue_and_shot_s_sum = sum of (t_obs_s - timings.total_s), i.e. screenshot + PNG encoding + shared "
           "perception-server queue + socket round trip.  Reference for \"screenshot + encoding\": the obs_s_sum of "
           "S_shot / S_shot_lean in the table above.", ""]
    body = []
    for c, v in res.items():
        if "tree_compute_s_sum" in v:
            body.append([c, v["tree_steps_total"], f(v["tree_compute_s_sum"], 2), f(v["queue_and_shot_s_sum"], 2),
                         f(v["obs_s_sum"], 2), f(v["tree_compute_s_per_step"], 3), f(v["queue_and_shot_s_per_step"], 3)])
    for c in ("S_shot", "S_shot_lean"):
        if c in res:
            v = res[c]
            body.append([f"{c} (reference)", "-", "-", "-", f(v["obs_s_sum"], 2), "-", f(v["obs_s_per_step"], 3)])
    md += [table(["cond", "tree steps", "tree_compute_s_sum", "queue_and_shot_s_sum", "obs_s_sum",
                  "tree_compute s/step", "queue+shot s/step (S_shot: obs s/step)"], body), ""]
    return md


# ---------------------------------------------------------------- D: stop_reason composition
def table_d(rows, conds):
    out = {}
    for cond in conds:
        rs = [r for r in rows if r["cond"] == cond]
        if not rs:
            continue
        c = Counter(r.get("stop_reason") for r in rs)
        ok = Counter(r.get("stop_reason") for r in rs if r.get("ok"))
        reasons = STOP_ORDER + sorted(set(c) - set(STOP_ORDER), key=str)
        out[cond] = {"episodes": len(rs),
                     "reasons": {k: {"n": c.get(k, 0), "share": c.get(k, 0) / len(rs), "ok": ok.get(k, 0)}
                                 for k in reasons}}
    return out


def render_d(res):
    md = ["## D. stop_reason composition", "",
          "Episodes per stop_reason (share of the condition's episodes) and, after the slash, how many of them are ok "
          "(oracle passed).  `error` rows were dropped.", ""]
    reasons = list(STOP_ORDER)
    for v in res.values():
        reasons += [k for k in v["reasons"] if k not in reasons]
    body = [[c, v["episodes"]] + [f"{v['reasons'][k]['n']} ({pct(v['reasons'][k]['n'], v['episodes'], 0)}) / "
                                  f"{v['reasons'][k]['ok']}" if k in v["reasons"] else "0 (0%) / 0" for k in reasons]
            for c, v in res.items()]
    md += [table(["cond", "episodes"] + [f"{k}: n (share) / ok" for k in reasons], body), ""]
    return md


# ---------------------------------------------------------------- main
def analyse(rows):
    conds = conds_present(rows)
    return {"conds": conds, "A": table_a(rows), "B": table_b(rows), "C": table_c(rows, conds), "D": table_d(rows, conds)}


def render(res, src):
    md = [f"# R3 extra analysis: {src}", "",
          "Offline, from the episode archives only. Rows = last row per (task, cond, rep), `error` rows dropped.", ""]
    return "\n".join(md + render_a(res["A"]) + render_b(res["B"]) + render_c(res["C"]) + render_d(res["D"]))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rows", help="episodes.jsonl of the R3 run")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    rows = load_good_rows(args.rows)
    res = analyse(rows)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "r3_extra.md").write_text(render(res, args.rows) + "\n", encoding="utf-8")
    (out / "r3_extra.json").write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out / 'r3_extra.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
