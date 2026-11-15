#!/usr/bin/env python3
"""R1: per-step observation tokens and wall-clock decomposition.

Read-only over finished run outputs (episodes.jsonl, ep/<ep>/transcript.jsonl,
ep/<ep>/steps/<NN>/{action.json,obs.txt}). Calls no model and no token-count API.

Usage:
    python -m bench.analysis.obs_tokens out/r1/formal [out/r1/formal_hybrid ...] --out out/r1/obs_tokens

Method, in short:
  * API calls = unique assistant message.id values (one id = one API call; each
    content block is a separate stream-json event that repeats the same usage).
  * ctx_k = input + cache_creation + cache_read of call k.  Delta_k = ctx_{k+1} - ctx_k
    is the context added between call k and call k+1: call k's output (A_k = chars of
    its text + tool_use input, thinking excluded) plus the tool_results that follow it
    (T_k = text chars, I_k = image blocks).  The last call has no following Delta.
  * Per condition, OLS (numpy.linalg.lstsq) Delta_k ~ a*T_k + b*I_k + c*A_k + d,
    dropping any column with zero variance.
"""
import argparse
import collections
import json
import math
import os
import sys

import numpy as np

COND_ORDER = ["T_ours", "T_atspi", "T_omni", "S_shot", "S_shot_strong", "H_ours", "H_atspi"]
IMG_THEORY = 1280 * 720 / 750.0  # Anthropic image-token rule of thumb, 1280x720


KNOWN_TOOLS = {"observe", "click", "type", "key", "scroll", "done"}


def align_steps(steps, entries):
    """For each step, the index into entries (known tool_use results, in order) or None."""
    out = []
    j = 0
    for s in steps:
        best = None
        for jj in range(j, min(j + 4, len(entries))):
            e = entries[jj]
            if e["tool"] != s["tool"]:
                continue
            if best is None:
                best = jj
            if e["T"] == s["obs_chars"]:
                best = jj
                break
        if best is None:
            out.append(None)
            continue
        out.append(best)
        j = best + 1
    return out


def ep_dirname(row):
    return f"{row['task']}__{row['cond']}__r{row['rep']}"


def parse_transcript(path):
    """Return (calls, stats). calls: list of dicts, one per unique assistant message.id."""
    calls = []
    by_mid = {}
    seen_tids = set()
    stats = collections.Counter()
    cur = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            ev = json.loads(line)
            t = ev.get("type")
            if t == "assistant":
                m = ev["message"]
                mid = m["id"]
                u = m.get("usage") or {}
                sig = (u.get("input_tokens") or 0,
                       u.get("cache_creation_input_tokens") or 0,
                       u.get("cache_read_input_tokens") or 0)
                if mid not in by_mid:
                    c = {"mid": mid, "input": sig[0], "cc": sig[1], "cr": sig[2],
                         "ctx": sum(sig), "A": 0, "n_events": 0, "n_blocks": 0,
                         "block_keys": set(), "tools": [], "tids": [], "results": []}
                    by_mid[mid] = c
                    calls.append(c)
                c = by_mid[mid]
                if sig != (c["input"], c["cc"], c["cr"]):
                    stats["usage_mismatch_within_id"] += 1
                c["n_events"] += 1
                cur = c
                for b in m.get("content") or []:
                    bt = b.get("type")
                    if bt == "tool_use":
                        key = ("tool_use", b["id"])
                        if key in c["block_keys"]:
                            continue
                        c["block_keys"].add(key)
                        c["n_blocks"] += 1
                        c["A"] += len(json.dumps(b.get("input", {}), ensure_ascii=False))
                        c["tools"].append(b["name"])
                        c["tids"].append(b["id"])
                    elif bt == "text":
                        key = ("text", b["text"])
                        if key in c["block_keys"]:
                            continue
                        c["block_keys"].add(key)
                        c["n_blocks"] += 1
                        c["A"] += len(b["text"])
                    else:  # thinking / redacted: excluded from A_k by spec
                        stats[f"assistant_block_{bt}_excluded"] += 1
            elif t == "user":
                if cur is None:
                    continue
                content = ev["message"].get("content")
                if isinstance(content, str):
                    stats["user_str_ignored"] += 1
                    continue
                for b in content or []:
                    if b.get("type") != "tool_result":
                        stats[f"user_block_{b.get('type')}_ignored"] += 1
                        continue
                    tid = b.get("tool_use_id")
                    if tid in seen_tids:
                        stats["dup_tool_result"] += 1
                        continue
                    seen_tids.add(tid)
                    cc = b.get("content")
                    T = 0
                    I = 0
                    if isinstance(cc, str):
                        T = len(cc)
                    else:
                        for x in cc or []:
                            if x.get("type") == "text":
                                T += len(x["text"])
                            elif x.get("type") == "image":
                                I += 1
                            else:
                                stats["result_block_other"] += 1
                    cur["results"].append({"tid": tid, "T": T, "I": I})
    # Map tool_result to tool name inside the call that issued it.
    for c in calls:
        name_by_tid = dict(zip(c["tids"], c["tools"]))
        for r in c["results"]:
            r["tool"] = name_by_tid.get(r["tid"], "?")
            if r["tool"] == "?":
                stats["result_without_tool_use"] += 1
    return calls, stats


def raw_events(path, max_lines=40):
    """Raw stream-json events (ids, block types, usage triple, result sizes) for the appendix."""
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            ev = json.loads(line)
            if ev.get("type") == "assistant":
                m = ev["message"]
                u = m.get("usage") or {}
                out.append(f"  A  id=..{m['id'][-8:]} block={[b.get('type') for b in m.get('content') or []]} "
                           f"usage(in,cc,cr)=({u.get('input_tokens')},{u.get('cache_creation_input_tokens')},{u.get('cache_read_input_tokens')})")
            elif ev.get("type") == "user" and isinstance(ev["message"].get("content"), list):
                for b in ev["message"]["content"]:
                    if b.get("type") == "tool_result":
                        cc = b.get("content")
                        if isinstance(cc, str):
                            out.append(f"  U  tool_result {b['tool_use_id'][-8:]} str_chars={len(cc)}")
                        else:
                            parts = [("text", len(x["text"])) if x.get("type") == "text" else ("image", 1) for x in cc or []]
                            out.append(f"  U  tool_result {b['tool_use_id'][-8:]} parts={parts}")
            if len(out) >= max_lines:
                break
    return out


def mcp_init_failed(path):
    """True if the bench MCP server was not connected at init (harness error, the agent had no tools)."""
    with open(path, encoding="utf-8") as f:
        for line in f:
            ev = json.loads(line)
            if ev.get("type") == "system" and ev.get("subtype") == "init":
                for srv in ev.get("mcp_servers") or []:
                    if srv.get("name") == "p125" and srv.get("status") != "connected":
                        return True
                return False
    return False


def load_steps(ep_dir):
    sdir = os.path.join(ep_dir, "steps")
    steps = []
    if not os.path.isdir(sdir):
        return steps
    for nn in sorted(os.listdir(sdir)):
        base = os.path.join(sdir, nn)
        with open(os.path.join(base, "action.json"), encoding="utf-8") as f:
            a = json.load(f)
        with open(os.path.join(base, "obs.txt"), encoding="utf-8") as f:
            obs = f.read()
        steps.append({"nn": nn, "tool": a["tool"], "t_start": a["t_start"], "t_end": a["t_end"],
                      "t_obs_s": a["t_obs_s"], "t_action_s": a["t_action_s"],
                      "obs_chars": len(obs)})
    return steps


def ols(rows):
    """rows: list of (y, T, I, A). Returns dict with coefficients and fit statistics."""
    y = np.array([r[0] for r in rows], dtype=float)
    cols = {"T": np.array([r[1] for r in rows], dtype=float),
            "I": np.array([r[2] for r in rows], dtype=float),
            "A": np.array([r[3] for r in rows], dtype=float)}
    used = [k for k in ("T", "I", "A") if cols[k].std() > 0]
    X = np.column_stack([cols[k] for k in used] + [np.ones(len(y))])
    names = used + ["d"]
    coef, _, rank, sv = np.linalg.lstsq(X, y, rcond=None)
    pred = X @ coef
    ss_res = float(((y - pred) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    n, p = X.shape
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    sigma2 = ss_res / max(n - p, 1)
    try:
        cov = sigma2 * np.linalg.inv(X.T @ X)
        se = np.sqrt(np.diag(cov))
    except np.linalg.LinAlgError:
        se = np.full(p, float("nan"))
    out = {"n": n, "r2": r2, "rel_rmse": math.sqrt(ss_res / n) / y.mean() if y.mean() else float("nan"),
           "rank": int(rank), "p": p, "cond": float(sv[0] / sv[-1]) if sv[-1] > 0 else float("inf"),
           "used": used, "y_mean": float(y.mean()), "n_neg": int((y < 0).sum())}
    for k in ("T", "I", "A", "d"):
        if k in names:
            i = names.index(k)
            out[k] = float(coef[i])
            out[k + "_se"] = float(se[i])
        else:
            out[k] = float("nan")
            out[k + "_se"] = float("nan")
    return out


def fmt(x, nd=3):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "n/a"
    return f"{x:.{nd}f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dirs", nargs="+", help="run output dirs, each with episodes.jsonl and ep/")
    ap.add_argument("--out", required=True, help="output dir for obs_tokens.csv / .md / deltas.csv")
    ap.add_argument("--trace", nargs="*", default=["drawing_banner_save_as__T_ours__r0",
                                                    "drawing_banner_save_as__S_shot__r0"],
                    help="episode dir names for the appendix trace")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    cond_rows = collections.defaultdict(list)    # cond -> regression rows
    cond_eps = collections.defaultdict(list)     # cond -> per-episode dicts
    cond_src = {}
    delta_lines = ["out_dir,cond,episode,call_k,ctx_k,delta_k,T_k,I_k,A_k,n_events_k,n_blocks_k"]
    trace_text = {}
    global_stats = collections.Counter()
    harness_excluded = []
    step_checks = collections.Counter()
    call_model_gaps = collections.defaultdict(list)
    check_wall = collections.defaultdict(list)
    episodes_mean_check = []

    for out_dir in args.out_dirs:
        ep_root = os.path.join(out_dir, "ep")
        with open(os.path.join(out_dir, "episodes.jsonl"), encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        last = {}
        for row in rows:  # last row per episode (a requeued episode has an error row and a rerun row after the original)
            last[(row["task"], row["cond"], row["rep"])] = row
        rows = [r for r in last.values() if r.get("stop_reason") != "error"]
        for row in rows:
            cond = row["cond"]
            cond_src.setdefault(cond, out_dir)
            name = ep_dirname(row)
            ep_dir = os.path.join(ep_root, name)
            if mcp_init_failed(os.path.join(ep_dir, "transcript.jsonl")):
                harness_excluded.append(f"{cond}/{name}")
                continue
            calls, st = parse_transcript(os.path.join(ep_dir, "transcript.jsonl"))
            global_stats.update(st)
            steps = load_steps(ep_dir)
            for s in steps:
                global_stats["steps_total"] += 1
            # ---- step <-> tool_use alignment.  Some tool_use blocks never become a step
            # (non-existent tool names such as right_click_placeholder, or a call rejected
            # before recording), so align by tool name in order, preferring a candidate whose
            # result text length equals obs.txt length.
            entries = []
            for k, c in enumerate(calls):
                res_by_tid = {r["tid"]: r for r in c["results"]}
                for tid, tool in zip(c["tids"], c["tools"]):
                    short = tool.replace("mcp__p125__", "")
                    if short in KNOWN_TOOLS:
                        r = res_by_tid.get(tid, {"T": 0, "I": 0})
                        entries.append({"k": k, "tool": short, "T": r["T"], "I": r["I"]})
            align = align_steps(steps, entries)
            for i, s in enumerate(steps):
                if align[i] is None:
                    step_checks["step_unaligned"] += 1
                    continue
                e = entries[align[i]]
                step_checks["step_aligned"] += 1
                if e["tool"] != s["tool"]:
                    step_checks["step_tool_name_mismatch"] += 1
                if s["tool"] != "done" and e["T"] != s["obs_chars"]:
                    step_checks["obs_chars_vs_result_text_mismatch"] += 1
                if e["T"] and e["T"] != s["obs_chars"] and s["tool"] == "done":
                    step_checks["done_obs_chars_differs_from_result"] += 1
            if len(steps) > len(entries):
                step_checks["steps_more_than_known_tool_uses"] += 1
            # ---- regression rows and deltas
            K = len(calls)
            ep_T = ep_I = 0
            for k in range(K - 1):
                c, nxt = calls[k], calls[k + 1]
                y = nxt["ctx"] - c["ctx"]
                T = sum(r["T"] for r in c["results"])
                I = sum(r["I"] for r in c["results"])
                cond_rows[cond].append((y, T, I, c["A"]))
                delta_lines.append(
                    f"{os.path.basename(out_dir.rstrip('/'))},{cond},{name},{k},{c['ctx']},{y},{T},{I},{c['A']},{c['n_events']},{c['n_blocks']}")
            if K:
                for r in calls[-1]["results"]:
                    step_checks["results_after_last_call_excluded"] += 1
            # ---- image/text totals (all results, including step-limit text)
            for c in calls:
                for r in c["results"]:
                    ep_T += r["T"]
                    ep_I += r["I"]
            # ---- wall-clock
            obs_vals = [s["t_obs_s"] for s in steps if s["t_obs_s"] is not None]
            mean_obs = float(np.mean(obs_vals)) if obs_vals else float("nan")
            if steps:
                episodes_mean_check.append(abs(mean_obs - row.get("mean_obs_s", mean_obs)))
            gaps = [steps[j]["t_start"] - steps[j - 1]["t_end"] for j in range(1, len(steps))]
            for g in gaps:
                if g < 0:
                    step_checks["negative_model_gap"] += 1
            # per-API-call model gap: last step of call k-1 -> first step of call k
            step_call = [entries[align[i]]["k"] if align[i] is not None else None for i in range(len(steps))]
            for k in range(1, K):
                idx_k = [i for i, ck in enumerate(step_call) if ck == k]
                idx_p = [i for i, ck in enumerate(step_call) if ck == k - 1]
                if idx_k and idx_p:
                    call_model_gaps[cond].append(steps[idx_k[0]]["t_start"] - steps[idx_p[-1]]["t_end"])
            accounted = (sum((s["t_obs_s"] or 0.0) + s["t_action_s"] for s in steps) + sum(gaps))
            check_wall[cond].append(row["wall_s"] - accounted)
            cond_eps[cond].append({
                "n_calls": K, "n_steps": len(steps), "last_ctx": calls[-1]["ctx"] if K else 0,
                "wall": row["wall_s"], "obs_steps": [s["obs_chars"] for s in steps],
                "img_results": ep_I, "text_results": ep_T,
                "t_obs": [s["t_obs_s"] for s in steps], "t_obs_null": sum(1 for s in steps if s["t_obs_s"] is None), "t_act": [s["t_action_s"] for s in steps],
                "gaps": gaps,
            })
            if name in args.trace:
                lines = [f"episode {name}  (cond {cond}, {K} API calls, {len(steps)} step dirs, wall_s {row['wall_s']})",
                         "raw events (first 40 lines of transcript.jsonl that carry usage or results):"]
                lines += raw_events(os.path.join(ep_dir, "transcript.jsonl"))
                lines.append("deduplicated calls:")
                for k, c in enumerate(calls):
                    T = sum(r["T"] for r in c["results"])
                    I = sum(r["I"] for r in c["results"])
                    tools = ",".join(t.replace("mcp__p125__", "") for t in c["tools"]) or "-"
                    delta = calls[k + 1]["ctx"] - c["ctx"] if k + 1 < K else None
                    lines.append(
                        f"call {k+1:>2} id=..{c['mid'][-8:]} events={c['n_events']:>2} blocks={c['n_blocks']} "
                        f"in={c['input']:>3} cc={c['cc']:>6} cr={c['cr']:>6} ctx={c['ctx']:>6} A={c['A']:>4} "
                        f"tools=[{tools}] results: T={T:>5} I={I} -> delta_to_next="
                        + (f"{delta}" if delta is not None else "(last call)"))
                trace_text[name] = "\n".join(lines)

    # ---------- per-condition fit and summary
    conds = sorted(cond_rows, key=lambda c: COND_ORDER.index(c) if c in COND_ORDER else 99)
    summary = []
    pooled_text = [r for c in conds if not c.startswith("S_") for r in cond_rows[c]]
    pooled_fit = ols(pooled_text) if pooled_text else None
    for cond in conds:
        fit = ols(cond_rows[cond])
        eps = cond_eps[cond]
        n_steps = sum(e["n_steps"] for e in eps)
        n_calls = sum(e["n_calls"] for e in eps)
        obs_chars = [x for e in eps for x in e["obs_steps"]]
        mean_obs_chars = float(np.mean(obs_chars)) if obs_chars else float("nan")
        img_total = sum(e["img_results"] for e in eps)
        mean_imgs = img_total / n_steps if n_steps else float("nan")
        a = fit["T"]
        b = fit["I"]
        obs_tok = (0.0 if math.isnan(a) else a) * mean_obs_chars + (0.0 if math.isnan(b) or mean_imgs == 0 else b) * mean_imgs
        walls = [e["wall"] for e in eps]
        t_obs = [x for e in eps for x in e["t_obs"] if x is not None]
        t_act = [x for e in eps for x in e["t_act"]]
        t_mod = [x for e in eps for x in e["gaps"]]
        sens = None
        if cond.startswith("S_") and pooled_fit:
            # a is only identified by the step-limit text results here; fix it at the pooled text value.
            a_fix = pooled_fit["T"]
            f2 = ols([(y - a_fix * T, 0, I_, A_) for (y, T, I_, A_) in cond_rows[cond]])
            sens = {"a": a_fix, "b": f2["I"], "b_se": f2["I_se"], "c": f2["A"], "d": f2["d"],
                    "obs_tok": a_fix * mean_obs_chars + f2["I"] * mean_imgs, "rel_rmse": f2["rel_rmse"],
                    "r2": f2["r2"]}
        summary.append({
            "cond": cond, "sens": sens, "n_calls": n_calls, "a": a, "b": b, "c": fit["A"], "d": fit["d"],
            "a_se": fit["T_se"], "b_se": fit["I_se"], "r2": fit["r2"], "rel_rmse": fit["rel_rmse"],
            "used": "+".join(fit["used"]), "rank": fit["rank"], "p": fit["p"], "cond_num": fit["cond"],
            "n_rows": fit["n"], "n_neg": fit["n_neg"],
            "mean_obs_chars": mean_obs_chars, "mean_imgs": mean_imgs, "obs_tok": obs_tok,
            "mean_ctx_last": float(np.mean([e["last_ctx"] for e in eps])),
            "mean_wall": float(np.mean(walls)), "median_wall": float(np.median(walls)),
            "mean_obs_s": float(np.mean(t_obs)) if t_obs else float("nan"),
            "median_obs_s": float(np.median(t_obs)) if t_obs else float("nan"),
            "mean_action_s": float(np.mean(t_act)) if t_act else float("nan"),
            "median_action_s": float(np.median(t_act)) if t_act else float("nan"),
            "mean_model_s": float(np.mean(t_mod)) if t_mod else float("nan"),
            "median_model_s": float(np.median(t_mod)) if t_mod else float("nan"),
            "mean_call_model_s": float(np.mean(call_model_gaps[cond])) if call_model_gaps[cond] else float("nan"),
            "median_call_model_s": float(np.median(call_model_gaps[cond])) if call_model_gaps[cond] else float("nan"),
            "mean_unaccounted_s": float(np.mean(check_wall[cond])),
            "n_steps": n_steps,
        })

    # ---------- CSV
    csv_cols = ["cond", "n_calls", "a_tok_per_char", "b_tok_per_image", "c", "d", "r2",
                "mean_obs_chars_per_step", "mean_images_per_step", "obs_tokens_per_step",
                "mean_ctx_at_last_call", "mean_wall_s", "median_wall_s", "mean_obs_s",
                "mean_action_s", "mean_model_s"]
    with open(os.path.join(args.out, "obs_tokens.csv"), "w", encoding="utf-8") as f:
        f.write(",".join(csv_cols) + "\n")
        for s in summary:
            vals = [s["cond"], str(s["n_calls"]), fmt(s["a"], 4), fmt(s["b"], 1), fmt(s["c"], 4),
                    fmt(s["d"], 1), fmt(s["r2"], 4), fmt(s["mean_obs_chars"], 1), fmt(s["mean_imgs"], 3),
                    fmt(s["obs_tok"], 1), fmt(s["mean_ctx_last"], 0), fmt(s["mean_wall"], 2),
                    fmt(s["median_wall"], 2), fmt(s["mean_obs_s"], 3), fmt(s["mean_action_s"], 3),
                    fmt(s["mean_model_s"], 3)]
            f.write(",".join(v if v != "n/a" else "" for v in vals) + "\n")
    with open(os.path.join(args.out, "deltas.csv"), "w", encoding="utf-8") as f:
        f.write("\n".join(delta_lines) + "\n")

    # ---------- Markdown
    most_off = max(summary, key=lambda s: s["rel_rmse"] if not math.isnan(s["rel_rmse"]) else -1)
    s_rows = [s for s in summary if s["cond"].startswith("S_")]
    L = []
    L.append("# R1: per-step observation tokens and wall-clock decomposition\n")
    L.append("Data: " + ", ".join(f"`{d}`" for d in args.out_dirs) +
             f" ({sum(len(cond_eps[c]) for c in conds)} episodes). Script: `bench/analysis/obs_tokens.py`. "
             "No model and no token-count API was called.\n")
    L.append("## Main table (same as `obs_tokens.csv`)\n")
    head = ["cond", "n_calls", "a tok/char", "b tok/img", "c tok/char(A)", "d tok/call", "R²",
            "obs chars/step", "imgs/step", "**obs tok/step**", "last-call ctx", "wall mean s", "wall median s",
            "obs s", "action s", "model s"]
    L.append("| " + " | ".join(head) + " |")
    L.append("|" + "---|" * len(head))
    for s in summary:
        L.append("| " + " | ".join([
            s["cond"], str(s["n_calls"]), fmt(s["a"], 4), fmt(s["b"], 1), fmt(s["c"], 4), fmt(s["d"], 1),
            fmt(s["r2"], 4), fmt(s["mean_obs_chars"], 1), fmt(s["mean_imgs"], 3), f"**{fmt(s['obs_tok'], 1)}**",
            fmt(s["mean_ctx_last"], 0), fmt(s["mean_wall"], 2), fmt(s["median_wall"], 2),
            fmt(s["mean_obs_s"], 3), fmt(s["mean_action_s"], 3), fmt(s["mean_model_s"], 3)]) + " |")
    L.append("")
    L.append("Notes: `a`/`b`/`c`/`d` are OLS coefficients (zero-variance columns are dropped, see `used` in the table below); "
             "`obs tok/step = a * obs chars/step + b * imgs/step`; "
             "`model s` is the t_end -> t_start gap between consecutive steps (gaps inside one batch of parallel calls are "
             "close to 0; see the per-API-call model time below).\n")
    L.append("## Fit details\n")
    L.append("| cond | columns used | rows (in-episode deltas) | rank/p | condition number | a ± se | b ± se | c | d | R² | relative RMSE | negative deltas |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for s in summary:
        L.append(f"| {s['cond']} | {s['used']} | {s['n_rows']} | {s['rank']}/{s['p']} | {fmt(s['cond_num'], 1)} | "
                 f"{fmt(s['a'], 4)} ± {fmt(s['a_se'], 4)} | {fmt(s['b'], 1)} ± {fmt(s['b_se'], 1)} | {fmt(s['c'], 4)} | "
                 f"{fmt(s['d'], 1)} | {fmt(s['r2'], 4)} | {fmt(s['rel_rmse'], 4)} | {s['n_neg']} |")
    L.append("")
    if pooled_fit:
        L.append(f"Pooled fit of the text conditions (T_ours+T_atspi+T_omni, n={pooled_fit['n']}): a = {fmt(pooled_fit['T'], 4)} ± {fmt(pooled_fit['T_se'], 4)} tok/char, "
                 f"c = {fmt(pooled_fit['A'], 4)}, d = {fmt(pooled_fit['d'], 1)}, R² = {fmt(pooled_fit['r2'], 4)}.\n")
    L.append("## Cross-check: image tokens\n")
    L.append(f"Theoretical value for 1280x720 ≈ 1280·720/750 = **{IMG_THEORY:.0f}** tokens per image (the published rule of thumb for image tokens).")
    for s in s_rows:
        dev = (s["b"] / IMG_THEORY - 1) * 100 if not math.isnan(s["b"]) else float("nan")
        ok = abs(dev) <= 40 if not math.isnan(dev) else False
        L.append(f"- {s['cond']}: fitted b = {fmt(s['b'], 1)} (se {fmt(s['b_se'], 1)}), deviation {fmt(dev, 1)} %, "
                 f"{'within ±40 %' if ok else '**NOT within ±40 %**'}.")
    L.append("")
    L.append("Sensitivity (in the S conditions `a` is identified only by the 33-character text result after the step limit; here it is fixed to the pooled text value and only b, c, d are refitted):\n")
    L.append("| cond | a fixed to | b ± se | b deviation vs 1229 | c | d | R² | obs tok/step (fixed a) | obs tok/step (free fit) |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for s_ in s_rows:
        z = s_["sens"]
        if z:
            dev2 = (z["b"] / IMG_THEORY - 1) * 100
            L.append(f"| {s_['cond']} | {fmt(z['a'], 4)} | {fmt(z['b'], 1)} ± {fmt(z['b_se'], 1)} | {fmt(dev2, 1)} % | "
                     f"{fmt(z['c'], 4)} | {fmt(z['d'], 1)} | {fmt(z['r2'], 4)} | {fmt(z['obs_tok'], 1)} | {fmt(s_['obs_tok'], 1)} |")
    L.append("")
    L.append("## Wall-clock decomposition per episode\n")
    L.append("| cond | wall mean s | wall median s | obs s per step (mean/median) | action s per step (mean/median) | model s per step (consecutive-step gap, mean/median) | model s per API call (mean/median) | unaccounted wall s (first call, shutdown, start-up; mean) |")
    L.append("|---|---|---|---|---|---|---|---|")
    for s in summary:
        L.append(f"| {s['cond']} | {fmt(s['mean_wall'], 2)} | {fmt(s['median_wall'], 2)} | "
                 f"{fmt(s['mean_obs_s'], 3)} / {fmt(s['median_obs_s'], 3)} | "
                 f"{fmt(s['mean_action_s'], 3)} / {fmt(s['median_action_s'], 3)} | "
                 f"{fmt(s['mean_model_s'], 3)} / {fmt(s['median_model_s'], 3)} | "
                 f"{fmt(s['mean_call_model_s'], 3)} / {fmt(s['median_call_model_s'], 3)} | "
                 f"{fmt(s['mean_unaccounted_s'], 2)} |")
    L.append("")
    L.append("## Method (three sentences)\n")
    L.append("1. API calls are the unique `message.id` values; ctx_k = input + cache_creation + cache_read, and Δ_k = ctx_{k+1} − ctx_k is the context added between two calls (the output of call k plus the tool_results that follow it).")
    L.append("2. Per condition, OLS of Δ_k ≈ a·T_k (tool_result text characters) + b·I_k (image blocks) + c·A_k (characters of call k's text and tool_use input, thinking excluded) + d, zero-variance columns dropped, no other terms.")
    L.append("3. Observation tokens per step = a · mean obs.txt characters per step + b · images per step; wall-clock is split from action.json into t_obs_s, t_action_s and the model gap between consecutive steps, and the difference to `wall_s` is reported.\n")
    most = most_off
    L.append(f"**Reliability**: the condition with the largest fit error is **{most['cond']}** (relative RMSE {fmt(most['rel_rmse'], 4)}, R² {fmt(most['r2'], 4)}); "
             f"in the screenshot conditions T and I are almost collinear (every image comes with a fixed 57-character note line, and T varies only through the 33-character text result after the step limit), "
             f"so `a` is identified only by those results; read b (its se is in the table above) and treat a as indicative only.\n")
    L.append("## Checks\n")
    L.append("| item | result |")
    L.append("|---|---|")
    L.append(f"| usage differs between events of the same message.id | {global_stats.get('usage_mismatch_within_id', 0)} |")
    L.append(f"| steps aligned / steps not aligned | {step_checks.get('step_aligned', 0)} / {step_checks.get('step_unaligned', 0)} |")
    L.append(f"| step tool name differs from the aligned tool_use | {step_checks.get('step_tool_name_mismatch', 0)} |")
    L.append(f"| episodes with more steps than known tool calls | {step_checks.get('steps_more_than_known_tool_uses', 0)} |")
    L.append(f"| obs.txt length differs from the aligned tool_result text (non-done steps) | {step_checks.get('obs_chars_vs_result_text_mismatch', 0)} |")
    L.append(f"| done steps: obs.txt length differs from the tool_result text (the done receipt is short, as expected) | {step_checks.get('done_obs_chars_differs_from_result', 0)} |")
    L.append(f"| steps with t_obs_s null (done and failed observe; counted as 0 in wall-clock, excluded from the obs mean) | {sum(e['t_obs_null'] for c in conds for e in cond_eps[c])} |")
    L.append(f"| negative model gaps (t_start < previous t_end) | {step_checks.get('negative_model_gap', 0)} |")
    L.append(f"| negative Δ (ctx decreased) | {sum(s['n_neg'] for s in summary)} |")
    L.append(f"| tool_results after the last call (not in Δ) | {step_checks.get('results_after_last_call_excluded', 0)} |")
    L.append(f"| other tool_result blocks / non-tool_result user blocks / unknown tool_use_id | {global_stats.get('result_block_other', 0)} / "
             f"{sum(v for k, v in global_stats.items() if k.startswith('user_block_'))} / {global_stats.get('result_without_tool_use', 0)} |")
    L.append(f"| excluded assistant blocks (thinking etc.) | {sum(v for k, v in global_stats.items() if k.startswith('assistant_block_'))} |")
    L.append(f"| largest difference (s) between mean_obs_s in episodes.jsonl and the value recomputed from steps | {fmt(max(episodes_mean_check) if episodes_mean_check else float('nan'), 4)} |")
    L.append("")
    L.append("Step limit: at most 20 steps per episode; after that the tool returns the text `step limit reached (20); stop now` (33 characters, no image). These results count in T_k and Δ but have no steps directory, so they are not part of the per-step averages of obs characters and images.\n")
    L.append("## Known limits and open items\n")
    L.append(f"- Harness-error episodes excluded: {len(harness_excluded)}. The transcript init event shows the MCP server as `failed` (the agent had no tools). "
             f"These are a harness fault, not agent behaviour, and are left out of every statistic: {', '.join(harness_excluded) if harness_excluded else 'none'}.")
    zero_eps = [e for c in conds for e in cond_eps[c] if e["n_steps"] == 0]
    L.append(f"- Episodes with 0 steps left (after excluding harness errors): {len(zero_eps)}.")
    L.append("- Unaccounted wall-clock (last column above): `t_start` in episodes.jsonl has one-second resolution and does not share its start with `wall_s`, "
             "so the unaccounted part cannot be fully attributed to start-up or shutdown. The numbers in the table are wall_s minus the sum of the steps.")
    L.append("- `model s` per step includes the ~0 gaps inside a batch of parallel calls, which pulls the mean down; the model time per API call is more meaningful (column `model s per API call` above).")
    L.append("- A user text block injected by the harness (\"Output token limit hit… Resume directly\") is not a tool_result and is not counted in T_k; it affects one Δ of that episode.")
    L.append("- The thinking blocks of call k (empty text, only output_tokens) are not part of A_k; their tokens land in d and in the residual of Δ, so d (about 6–250 tok per call) contains the thinking and format overhead of each call and is not a pure constant.\n")
    L.append("## Appendix: per-call Δ trace of two episodes\n")
    L.append("Each row is one API call (after de-duplication by message.id). `events` is the number of stream-json events under that id, `blocks` the number of de-duplicated content blocks; "
             "`delta_to_next` = ctx of the next call − ctx of this call, i.e. Δ_k. The rows below are the intermediate table written by the script and can be checked against the transcript.\n")
    for name in args.trace:
        if name in trace_text:
            L.append("```")
            L.append(trace_text[name])
            L.append("```\n")
        else:
            L.append(f"(episode `{name}` not found)\n")
    with open(os.path.join(args.out, "obs_tokens.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")

    print(f"wrote {args.out}/obs_tokens.csv, obs_tokens.md, deltas.csv")
    for s in summary:
        print(f"{s['cond']:>14} calls={s['n_calls']:>5} a={fmt(s['a'],4)} b={fmt(s['b'],1)} c={fmt(s['c'],4)} "
              f"d={fmt(s['d'],1)} r2={fmt(s['r2'],4)} obs_tok/step={fmt(s['obs_tok'],1)} wall={fmt(s['mean_wall'],2)}")
    print("harness-excluded:", harness_excluded)
    print("checks:", dict(step_checks), dict(global_stats))


if __name__ == "__main__":
    sys.exit(main())
