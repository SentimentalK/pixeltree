"""R2 calibration of the F2 / F3 thresholds on labelled frames of applications outside the exam
(<calib dir>/trees.jsonl and frames.jsonl, written by bench.analysis.calib_build).

Reference: the gold labels of the labelled frames (boxes xyxy, names).  A tree element is matched to the gold box of
highest IoU when IoU >= 0.5.  An OCR name is *right* when the gold name is non-empty and either the normalised names
have difflib ratio >= 0.8 or the OCR name (>= 3 normalised chars) is a substring of the gold name, or (names with no
letter / digit) the two strings are equal; otherwise *wrong*
(an OCR name on an element whose gold name is empty is wrong).  Unmatched elements are not scored.

Selection rules (fixed before looking at the tables; "an empty name beats a wrong one"):
  ICON_MAX_SIDE        the upper edge of the run of 4-px max-side buckets, from 0 up, in which > 50 % of the
                       non-text OCR names are wrong.
  ODD_MODE             "strip" if > 50 % of the names that keep a letter / digit after removing the odd characters
                       are right, else "blank" (any odd character -> no name).
  SYMBOL_ONLY_BLANK    True if > 50 % of the non-text names left with no letter / digit (after the icon rule and the
                       odd-character strip) are wrong.
  CONTAINER_MIN_TEXTS  the smallest k such that, for elements containing >= k named text elements, > 50 % of their
                       own OCR names are wrong.
  DUP_NAME_SIM, DUP_IOU  the loosest values of the grids below whose false-merge rate is <= 5 %; a merge is false
                       when the two elements match two different gold boxes whose gold names differ (sim < 0.8), or,
                       for empty names, two different gold boxes.  CONTAIN_FRAC is fixed at 0.8 and reported.
  MATCH_MOVE_PX, MATCH_RENAME_IOU  the grid point with the fewest F3 characters on the child frame of the 100
                       (parent, child) pairs; ties -> the smaller px / larger IoU.  F3 is lossless for every value.
  FULL_IF_CHANGED_FRAC 0.5 ("more than half changed -> full"), fixed, not calibrated.

    python -m bench.analysis.calibrate --calib-dir out/r2/calib     # writes <calib dir>/calibration.md
"""
import difflib
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pixeltree import formats as F  # noqa: E402

CAL = Path("out/r2/calib")   # overridden by --calib-dir


def load():
    rows = [json.loads(line) for line in open(CAL / "trees.jsonl")]
    for r in rows:
        r["gt"] = [dict(g, box=[g["box"][0], g["box"][1], g["box"][2] - g["box"][0], g["box"][3] - g["box"][1]])
                   for g in r["gt"]]
        for e in r["tree"]["elements"]:
            best, v = None, 0.0
            for k, g in enumerate(r["gt"]):
                s = F.iou(e["box"], g["box"])
                if s > v:
                    best, v = k, s
            e["_gt"] = best if v >= 0.5 else None
    return rows


def right(p, g):
    if not F.norm(p) or not F.norm(g):  # symbol-only names: exact match of the stripped strings
        return bool(F.one_line(p)) and F.one_line(p) == F.one_line(g)
    p, g = F.norm(p), F.norm(g)
    return difflib.SequenceMatcher(None, p, g).ratio() >= 0.8 or (len(p) >= 3 and p in g)


def gname(r, e):
    return r["gt"][e["_gt"]]["name"] or ""


def scored(rows, pred):
    """[(row, element)] of matched elements with a non-empty name that satisfy pred(element)."""
    return [(r, e) for r in rows for e in r["tree"]["elements"]
            if e["name"] and e["_gt"] is not None and pred(e)]


def wrong_rate(pairs, name_of=lambda r, e: e["name"]):
    n = len(pairs)
    w = sum(1 for r, e in pairs if not right(name_of(r, e), gname(r, e)))
    return w, n


def pct(w, n):
    return f"{w}/{n} ({100 * w / n:.0f} %)" if n else "0/0"


def main():
    rows = load()
    out = ["# R2: calibration of the cleaning / matching thresholds", "",
           f"Frames: {len(rows)} labelled frames ({len({r['group'] for r in rows})} app groups), "
           "T_ours pipeline (pixeltree.perceive.ours), gold names of the label file.", ""]
    n_el = sum(len(r["tree"]["elements"]) for r in rows)
    n_m = sum(1 for r in rows for e in r["tree"]["elements"] if e["_gt"] is not None)
    out += [f"Elements {n_el}, matched to a gold box (IoU >= 0.5) {n_m} ({100 * n_m / n_el:.1f} %). "
            "The detector was trained on these frames, so its boxes are cleaner here than on unseen apps; "
            "OCR is not trained, so the name statistics are fair.", ""]

    # ---- icon size
    out += ["## ICON_MAX_SIDE (non-text roles, OCR names wrong per 4-px bucket of max(w, h))", "",
            "| max side px | wrong / named |", "|---|---|"]
    edge, run = 0, True
    for lo in range(0, 64, 4):
        w, n = wrong_rate(scored(rows, lambda e: e["role"] not in F.TEXT_ROLES
                                 and lo <= max(e["box"][2], e["box"][3]) < lo + 4))
        out.append(f"| {lo}-{lo + 3} | {pct(w, n)} |")
        if run and n and w / n > 0.5:
            edge = lo + 4
        elif n:
            run = False
    out += ["", f"Selected ICON_MAX_SIDE = {edge} (frozen value {F.ICON_MAX_SIDE}).", ""]

    big = lambda e: e["role"] not in F.TEXT_ROLES and max(e["box"][2], e["box"][3]) >= F.ICON_MAX_SIDE  # noqa: E731
    # ---- odd characters
    odd = scored(rows, lambda e: F.strip_odd(e["name"]) != F.one_line(e["name"]))
    wb, n = wrong_rate(odd)
    wa, _ = wrong_rate(odd, lambda r, e: F.strip_odd(e["name"]))
    out += ["## Odd-character strip (names containing CJK / enclosed / geometric ... characters, all roles)", "",
            f"Names affected: {n}; wrong before strip {pct(wb, n)}, after strip {pct(wa, n)} "
            "(an empty result counts as wrong here, it becomes 'no name')."]
    kept = [(r, e) for r, e in odd if any(c.isalnum() for c in F.strip_odd(e["name"]))]
    wk, nk = wrong_rate(kept, lambda r, e: F.strip_odd(e["name"]))
    mode = "strip" if nk and (nk - wk) / nk > 0.5 else "blank"
    out += [f"Names that keep a letter / digit after the strip: {nk}, wrong after strip {pct(wk, nk)} -> "
            f"ODD_MODE = {mode!r} (frozen {F.ODD_MODE!r}).",
            "Examples (OCR -> stripped / gold): " + "; ".join(sorted({f"{e['name']!r}->{F.strip_odd(e['name'])!r}/"
                                                                       f"{gname(r, e)!r}" for r, e in kept})[:25]), ""]
    # ---- symbol only
    sym = scored(rows, lambda e: big(e) and F.strip_odd(e["name"]) and not any(
        c.isalnum() for c in F.strip_odd(e["name"])))
    w, n = wrong_rate(sym, lambda r, e: F.strip_odd(e["name"]))
    out += ["## SYMBOL_ONLY_BLANK (non-text, max side >= ICON_MAX_SIDE, no letter / digit after strip)", "",
            f"Wrong {pct(w, n)} -> blank = {bool(n and w / n > 0.5)} (frozen {F.SYMBOL_ONLY_BLANK}).",
            "Examples: " + ", ".join(sorted({repr(F.strip_odd(e['name'])) + '/' + repr(gname(r, e))
                                             for r, e in sym})[:20]), ""]
    # ---- container
    out += ["## CONTAINER_MIN_TEXTS (element whose name survives fix_name, k named visibleText inside it)", "",
            "| k | own OCR name wrong |", "|---|---|"]
    by_k = defaultdict(list)
    for r in rows:
        els = r["tree"]["elements"]
        texts = [t for t in els if t["role"] == "vax:visibleText" and t["name"]]
        for e in els:
            if not F.fix_name(e)[0] or e["role"] == "vax:visibleText" or e["_gt"] is None:
                continue
            k = sum(1 for t in texts if t is not e and F.inside_frac(t["box"], e["box"]) >= F.CONTAIN_FRAC
                    and F.box_area(t["box"]) < F.box_area(e["box"]))
            by_k[min(k, 4)].append((r, e))
    sel = None
    for k in sorted(by_k):
        w, n = wrong_rate(by_k[k])
        agg = [p for kk in by_k if kk >= k for p in by_k[kk]]
        wa, na = wrong_rate(agg)
        out.append(f"| {k}{'+' if k == 4 else ''} | {pct(w, n)} (k >= {k}: {pct(wa, na)}) |")
        if sel is None and k >= 1 and na and wa / na > 0.5 and all(
                wrong_rate([p for kk in by_k if kk >= j for p in by_k[kk]])[0]
                > 0.5 * len([p for kk in by_k if kk >= j for p in by_k[kk]]) for j in range(k, 5) if j in by_k):
            sel = k
    out += ["", f"Selected CONTAINER_MIN_TEXTS = {sel} (frozen {F.CONTAINER_MIN_TEXTS}).", ""]

    # ---- duplicates
    out += ["## DUP_NAME_SIM x DUP_IOU (pairs after the name fixes; false merges / merges)", "",
            "| name sim \\ IoU | " + " | ".join(str(t) for t in (0.4, 0.5, 0.6, 0.7, 0.8)) + " | nested (0.8) |",
            "|---|---|---|---|---|---|---|"]
    fixed = []
    for r in rows:
        els = [dict(e) for e in r["tree"]["elements"]]
        for e in els:
            e["name"] = F.fix_name(e)[0]
        fixed.append((r, els))

    def merges(sim, thr, nested_only=False):
        tot = bad = 0
        for r, els in fixed:
            for i in range(len(els)):
                for j in range(i + 1, len(els)):
                    a, b = els[i], els[j]
                    if (not a["name"]) != (not b["name"]):
                        continue
                    if a["name"]:
                        if F.name_sim(a["name"], b["name"]) < sim:
                            continue
                        nested = max(F.inside_frac(a["box"], b["box"]), F.inside_frac(b["box"], a["box"])) >= 0.8
                        ok = nested if nested_only else (nested or F.iou(a["box"], b["box"]) >= thr)
                    else:
                        if nested_only:
                            continue
                        ok = F.iou(a["box"], b["box"]) >= thr
                    if not ok:
                        continue
                    tot += 1
                    ga, gb = a["_gt"], b["_gt"]
                    if ga is not None and gb is not None and ga != gb:
                        if not a["name"] or F.name_sim(r["gt"][ga]["name"], r["gt"][gb]["name"]) < 0.8:
                            bad += 1
        return bad, tot

    best = None
    for sim in (0.6, 0.7, 0.8, 0.9, 1.0):
        cells = []
        for thr in (0.4, 0.5, 0.6, 0.7, 0.8):
            b, t = merges(sim, thr)
            cells.append(pct(b, t))
            if t and b / t <= 0.05 and best is None:
                best = (sim, thr)
        b, t = merges(sim, 1.1, nested_only=True)
        out.append(f"| {sim} | " + " | ".join(cells) + f" | {pct(b, t)} |")
    b, t = merges(F.DUP_NAME_SIM, 2.0)
    out += ["", "Grid order for 'loosest': name sim ascending, then IoU ascending; first cell <= 5 % wins.",
            f"Selected (DUP_NAME_SIM, DUP_IOU) = {best} (frozen {F.DUP_NAME_SIM}, {F.DUP_IOU}). "
            f"Empty-name pairs use DUP_IOU only. Same-name nested-only merges at the frozen sim: {pct(b, t)}.", ""]

    # ---- F3 matching
    pairs = [json.loads(line) for line in open(CAL / "frames.jsonl")]
    trees = {r["image"]: r["tree"] for r in rows}
    out += ["## MATCH_MOVE_PX x MATCH_RENAME_IOU (F3 characters of the child frame, sum over the pairs)", "",
            "| px \\ IoU | " + " | ".join(str(t) for t in (0.3, 0.5, 0.7, 1.01)) + " |", "|---|---|---|---|---|"]
    cleaned = {k: F.clean(t) for k, t in trees.items()}
    full_child = sum(len(F.f1(trees[p["child"]], cleaned[p["child"]])) for p in pairs)
    grid = []
    save = (F.MATCH_MOVE_PX, F.MATCH_RENAME_IOU)
    for px in (0, 10, 20, 40, 80):
        cells = []
        for ri in (0.3, 0.5, 0.7, 1.01):
            F.MATCH_MOVE_PX, F.MATCH_RENAME_IOU = px, ri
            tot = 0
            for p in pairs:
                d = F.Delta3(trees[p["parent"]]["image_size"])
                d.step(cleaned[p["parent"]])
                tot += len(d.step(cleaned[p["child"]])[0])
            cells.append(str(tot))
            grid.append((tot, px, -ri))
        out.append(f"| {px} | " + " | ".join(cells) + " |")
    F.MATCH_MOVE_PX, F.MATCH_RENAME_IOU = save
    tot, px, ri = min(grid)
    out += ["", f"F2 full text of the child frames for comparison: {full_child} characters. IoU 1.01 = no rename "
            f"matching. Selected MATCH_MOVE_PX = {px}, MATCH_RENAME_IOU = {-ri} (frozen {F.MATCH_MOVE_PX}, "
            f"{F.MATCH_RENAME_IOU}).", ""]
    (CAL / "calibration.md").write_text("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--calib-dir", default=str(CAL), help="directory holding trees.jsonl and frames.jsonl")
    CAL = Path(ap.parse_args().calib_dir)
    main()
