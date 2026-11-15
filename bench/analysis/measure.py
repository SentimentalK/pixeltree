"""R2 measurement: F0-F3 observation tokens on the archived R1 T_ours episodes, plus the two guardrails.

Input: the final episodes file of R1 (e.g. episodes_v1_1.jsonl; the 144 T_ours rows; `dir` points at the episode archive, reruns resolved) and each
episode's steps/NN/{tree.json, obs.txt, action.json} + transcript.jsonl.  No model, no API, no app.

Per observation step (a step with tree.json; `done` steps have none) the four texts are built from tree.json:
F0 (and checked against obs.txt), F1, F2 = F1 of formats.clean(), F3 = formats.Delta3 over the episode's F2 element
lists in step order.  tokens = characters x TOK_PER_CHAR (OLS fit for T_ours from bench.analysis.obs_tokens).

Guardrail 1 (F3 lossless): formats.Decoder3 fed with every F3 text must give, at every step, the F2 element multiset.
Guardrail 2 (cleaning keeps what the agent used), successful episodes only: for every click the reference tree is the
last observation the agent had received before the API call that issued the click (steps <-> tool_use blocks of
transcript.jsonl in order, grouped by message id).  Counted: clicks inside some element box before cleaning, and how
many of those are still inside a kept element box after cleaning; plus the clicked element (smallest box containing
the click) whose name cleaning emptied, or that cleaning dropped.

    python -m bench.analysis.measure --rows <R1 final episodes_v1_1.jsonl> --out out/r2
    # writes <out>/{steps.csv, episodes.csv, measure.md, clicks.jsonl, sample_gitg_stage_readme_r0.txt}
"""
import csv
import hashlib
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pixeltree import formats as F  # noqa: E402

TOK_PER_CHAR = 0.5890   # T_ours fit "a" (tok / tool_result character), from bench.analysis.obs_tokens
SHOT_TOK = 1153.7       # S_shot (Haiku) fit "b" (tok / 1280x720 image)
GATE = 600
FORMATS = ("F0", "F1", "F2", "F3")
APPS = ("drawing", "gitg", "gnome-calendar", "gnome-contacts", "keepassxc", "lutris", "obsidian", "okular")


def tool_calls(ep):
    """[(api call index, tool name)] per distinct tool_use block, in transcript order (= step order)."""
    seen, calls, msg_index = set(), [], {}
    for line in open(ep / "transcript.jsonl"):
        d = json.loads(line)
        if d.get("type") != "assistant":
            continue
        mid = d["message"]["id"]
        for b in d["message"].get("content") or []:
            if b.get("type") == "tool_use" and b["id"] not in seen:
                seen.add(b["id"])
                msg_index.setdefault(mid, len(msg_index))
                calls.append((msg_index[mid], b["name"].split("__")[-1]))
    return calls


def inside(pt, box):
    x, y = pt
    return box[0] <= x < box[0] + box[2] and box[1] <= y < box[1] + box[3]


def episode(row):
    ep = Path(row["dir"])
    steps = sorted(p for p in (ep / "steps").iterdir() if p.is_dir())
    enc = F.Delta3((1920, 1080))
    dec = F.Decoder3()
    recs, trees, cleaned, actions = [], {}, {}, {}
    f0_mismatch = 0
    for k, sd in enumerate(steps, 1):
        a = json.load(open(sd / "action.json"))
        actions[a["step"]] = a
        if not (sd / "tree.json").exists():
            continue
        tree = json.load(open(sd / "tree.json"))
        log = []
        els = F.clean(tree, log=log)
        t0, t1, t2 = F.f0(tree), F.f1(tree), F.f1(tree, els)
        if t0 != (sd / "obs.txt").read_text():
            f0_mismatch += 1
        t3, full, nops = enc.step(els)
        lossless = dec.feed(t3) == F.f2_keys(els)
        trees[a["step"]], cleaned[a["step"]] = tree, (els, log)
        kinds = Counter(x[0] for x in log)
        recs.append({"app": row["app"], "task": row["task"], "rep": row["rep"], "ok": row["ok"], "step": a["step"],
                     "obs_index": len(recs) + 1, "tool": a["tool"], "n_before": len(tree["elements"]),
                     "n_after": len(els), "F0": len(t0), "F1": len(t1), "F2": len(t2), "F3": len(t3),
                     "f3_full": int(full), "f3_ops": nops, "lossless": int(lossless),
                     **{f"n_{x}": kinds.get(x, 0) for x in ("odd", "icon", "symbol", "dup", "container")}})
    return recs, f0_mismatch, trees, cleaned, actions, ep


def click_guard(ep, trees, cleaned, actions):
    """Per click of the episode: dict(inside_before, inside_after, clicked element, its fate)."""
    calls = tool_calls(ep)
    out = []
    for step, a in sorted(actions.items()):
        if a["tool"] != "click" or not a.get("ok") or not a.get("screen_xy"):
            continue
        call = calls[step - 1][0]
        assert calls[step - 1][1] == "click", (ep, step, calls[step - 1])
        ref = [s for s in trees if s < step and calls[s - 1][0] < call]
        if not ref:
            continue
        s = max(ref)
        tree, (els, log) = trees[s], cleaned[s]
        pt = a["screen_xy"]
        hits = [e for e in tree["elements"] if inside(pt, e["box"])]
        if not hits:
            out.append({"inside_before": False})
            continue
        kept = {e["id"]: e for e in els}
        target = min(hits, key=lambda e: F.box_area(e["box"]))
        fate = "kept"
        if target["id"] not in kept:
            fate = "dropped"
        elif target["name"] and not kept[target["id"]]["name"]:
            fate = "blanked"
        reason = next((x[0] for x in log if x[1]["id"] == target["id"]), "")
        out.append({"inside_before": True, "inside_after": any(inside(pt, e["box"]) for e in els),
                    "fate": fate, "reason": reason, "name": target["name"], "role": target["role"],
                    "episode": ep.name, "step": step, "ref_step": s,
                    "at_center": list(pt) == F.center(target["box"])})
    return out


def mean(xs):
    return statistics.fmean(xs) if xs else float("nan")


def tok(chars):
    return chars * TOK_PER_CHAR


def main(rows_path, out_dir):
    OUT = Path(out_dir)
    OUT.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(line) for line in open(rows_path)]
    rows = [r for r in rows if r["cond"] == "T_ours"]
    assert len(rows) == 144, len(rows)
    steps, eps, clicks, f0_bad = [], [], [], 0
    samples = {}
    for row in sorted(rows, key=lambda r: (r["task"], r["rep"])):
        recs, mism, trees, cleaned, actions, ep = episode(row)
        f0_bad += mism
        steps += recs
        e = {"app": row["app"], "task": row["task"], "rep": row["rep"], "ok": row["ok"], "n_obs": len(recs)}
        for f in FORMATS:
            e[f"{f}_total"] = sum(r[f] for r in recs)
            e[f"{f}_per_step"] = e[f"{f}_total"] / len(recs) if recs else 0.0
        eps.append(e)
        if row["ok"]:
            for c in click_guard(ep, trees, cleaned, actions):
                c["app"] = row["app"]
                clicks.append(c)
        if row["task"] == "gitg_stage_readme" and row["rep"] == 0:
            samples = {"ep": ep, "trees": trees}
    sha = hashlib.sha256(Path(F.__file__).read_bytes()).hexdigest()[:16]

    with open(OUT / "steps.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(steps[0]))
        w.writeheader()
        w.writerows(steps)
    with open(OUT / "episodes.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(eps[0]))
        w.writeheader()
        w.writerows(eps)

    def table(sel_steps, sel_eps):
        line = {}
        for fm in FORMATS:
            per_step = tok(mean([r[fm] for r in sel_steps]))
            from2 = tok(mean([r[fm] for r in sel_steps if r["obs_index"] >= 2]))
            ep_mean = tok(mean([e[f"{fm}_per_step"] for e in sel_eps if e["n_obs"]]))
            ep_total = tok(mean([e[f"{fm}_total"] for e in sel_eps]))
            chars = mean([r[fm] for r in sel_steps])
            line[fm] = (per_step, from2, ep_mean, ep_total, chars)
        return line

    md = ["# R2: observation-token measurement on the R1 T_ours archive", "",
          f"formats.py sha256[:16] = {sha}. Token rate {TOK_PER_CHAR} tok/char "
          f"(T_ours fit); screenshot {SHOT_TOK} tok (S_shot fit).", "",
          f"Episodes {len(eps)} (successful {sum(e['ok'] for e in eps)}), observation steps {len(steps)}, "
          f"F0 != obs.txt: {f0_bad} steps.", ""]
    md += ["## Tokens (all episodes)", "",
           "| format | tok / step (pooled) | tok / step from obs 2 | **episode-mean tok / step** | obs tok / episode | chars / step |",
           "|---|---|---|---|---|---|"]
    allt = table(steps, eps)
    for fm in FORMATS:
        p, s2, em, tot, ch = allt[fm]
        md.append(f"| {fm} | {p:.0f} | {s2:.0f} | **{em:.0f}** | {tot:.0f} | {ch:.0f} |")
    md += ["", f"Screenshot for reference: {SHOT_TOK:.0f} tok / step. Gate: F3 episode-mean <= {GATE} tok / step -> "
           f"**{'PASS' if allt['F3'][2] <= GATE else 'FAIL'}** ({allt['F3'][2]:.0f}).", ""]
    md += ["## By app (tok / step pooled | from obs 2 | episode-mean | per episode)", "",
           "| app | eps | obs steps | " + " | ".join(FORMATS) + " |", "|---|---|---|---|---|---|---|"]
    for app in APPS:
        ss = [r for r in steps if r["app"] == app]
        ee = [e for e in eps if e["app"] == app]
        t = table(ss, ee)
        md.append(f"| {app} | {len(ee)} | {len(ss)} | " + " | ".join(
            f"{t[fm][0]:.0f} / {t[fm][1]:.0f} / {t[fm][2]:.0f} / {t[fm][3]:.0f}" for fm in FORMATS) + " |")
    later = [r for r in steps if r["obs_index"] >= 2]
    md += ["", "## F3 behaviour and element counts", "",
           f"- Steps from obs 2: {len(later)}; sent full (fallback, > {F.FULL_IF_CHANGED_FRAC:.0%} changed): "
           f"{sum(r['f3_full'] for r in later)} ({100 * mean([r['f3_full'] for r in later]):.1f} %); "
           f"'no change': {sum(1 for r in later if r['f3_ops'] == 0)} "
           f"({100 * mean([r['f3_ops'] == 0 for r in later]):.1f} %).",
           f"- Elements per step: before cleaning {mean([r['n_before'] for r in steps]):.1f}, after "
           f"{mean([r['n_after'] for r in steps]):.1f} (median {statistics.median([r['n_before'] for r in steps])} -> "
           f"{statistics.median([r['n_after'] for r in steps])}).",
           "- Cleaning actions per step (mean): " + ", ".join(
               f"{x} {mean([r['n_' + x] for r in steps]):.1f}" for x in ("odd", "icon", "symbol", "dup", "container")),
           "", "| app | F3 full share from obs 2 | no-change share | elements before -> after |", "|---|---|---|---|"]
    for app in APPS:
        ll = [r for r in later if r["app"] == app]
        ss = [r for r in steps if r["app"] == app]
        md.append(f"| {app} | {100 * mean([r['f3_full'] for r in ll]):.0f} % | "
                  f"{100 * mean([r['f3_ops'] == 0 for r in ll]):.0f} % | "
                  f"{mean([r['n_before'] for r in ss]):.1f} -> {mean([r['n_after'] for r in ss]):.1f} |")
    bad = [r for r in steps if not r["lossless"]]
    md += ["", "## Guardrail 1 — F3 lossless", "",
           f"Steps where the F3 rebuild differs from the F2 full tree: **{len(bad)}** of {len(steps)}.", ""]
    inb = [c for c in clicks if c["inside_before"]]
    ina = [c for c in inb if c["inside_after"]]
    md += ["## Guardrail 2 — cleaning vs the clicks of successful episodes", "",
           f"Clicks with a reference tree: {len(clicks)}; inside some element box before cleaning: {len(inb)}; "
           f"of those still inside a kept element box after cleaning: **{len(ina)} ({100 * len(ina) / len(inb):.1f} %)**.",
           f"Clicked (smallest containing) element: kept with its name {sum(c['fate'] == 'kept' for c in inb)}, "
           f"name emptied {sum(c['fate'] == 'blanked' for c in inb)}, dropped by de-duplication "
           f"{sum(c['fate'] == 'dropped' for c in inb)}. Clicks exactly on the element centre: "
           f"{sum(c['at_center'] for c in inb)}.", ""]
    bl = [c for c in inb if c["fate"] == "blanked"]
    by_name = Counter((c["name"], c["role"], c["reason"]) for c in bl)
    md += [f"Clicked elements whose name was emptied: {len(bl)} clicks, "
           f"{len({(c['episode'], c['name'], c['role']) for c in bl})} distinct (episode, name, role).", "",
           "| # | OCR name | role | rule | clicks |", "|---|---|---|---|---|"]
    for k, ((name, role, reason), n) in enumerate(by_name.most_common(20), 1):
        md.append(f"| {k} | `{name}` | {role} | {reason} | {n} |")
    dr = [c for c in inb if c["fate"] == "dropped"]
    if dr:
        md += ["", "Clicked elements dropped by de-duplication (a same-name element covering them was kept): "
               + ", ".join(f"`{n}` ({r}) x{k}" for (n, r), k in Counter((c['name'], c['role']) for c in dr).most_common(15))]
    by_app = defaultdict(list)
    for c in inb:
        by_app[c["app"]].append(c)
    md += ["", "| app | clicks inside before | still inside after | name emptied |", "|---|---|---|---|"]
    for app in APPS:
        cc = by_app.get(app, [])
        md.append(f"| {app} | {len(cc)} | {sum(c['inside_after'] for c in cc)} | "
                  f"{sum(c['fate'] == 'blanked' for c in cc)} |")
    (OUT / "measure.md").write_text("\n".join(md) + "\n")
    with open(OUT / "clicks.jsonl", "w") as f:
        for c in clicks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    if samples:
        enc = F.Delta3((1920, 1080))
        parts = []
        for s, tree in sorted(samples["trees"].items())[:4]:
            els = F.clean(tree)
            parts += [f"===== {samples['ep'].name} step {s}: F0 ({len(F.f0(tree))} chars) =====", F.f0(tree),
                      f"----- F2 ({len(F.f1(tree, els))} chars) -----", F.f1(tree, els),
                      "----- F3 -----", enc.step(els)[0], ""]
        (OUT / "sample_gitg_stage_readme_r0.txt").write_text("\n".join(parts) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rows", required=True, help="R1 final episodes file (jsonl; T_ours rows, `dir` = episode archive)")
    ap.add_argument("--out", default="out/r2", help="output directory (default ./out/r2)")
    a = ap.parse_args()
    main(a.rows, a.out)
