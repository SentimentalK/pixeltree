"""R2 calibration frames: T_ours trees (pixeltree.perceive.ours, same detector + OCR as the R1 exam) on labelled frames of
applications outside the exam.

Frames: AT-SPI captures listed in a label file (jsonl, train split, gold boxes and names), full 1920x1080 screens only,
whose parent state (meta.json parent_state_id = the frame before one UI action) is also a labelled full screen.
Up to N_PAIRS (parent, child) pairs, round-robin over app groups in sorted order, groups shuffled with seed 0, so the
frame count stays <= 2 * N_PAIRS (<= 200).  None of the 8 exam apps is in the label file (checked below).
The label file and the captures are not part of this repository.

    python -m bench.analysis.calib_build --labels <labels_train.jsonl> --out out/r2/calib   # writes {frames,trees}.jsonl
"""
import json
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LABELS = None   # set by --labels
OUT = Path("out/r2/calib")
N_PAIRS = 100
EXAM_APPS = ("gitg", "keepassxc", "obsidian", "okular", "lutris", "drawing", "gnome-calendar", "gnome-contacts",
             "gnome_calendar", "gnome_contacts", "calendar", "contacts")


def full_frames():
    """{screen.png path: label row} of labelled atspi118 full 1920x1080 screens."""
    out = {}
    for line in open(LABELS):
        r = json.loads(line)
        if r.get("origin") != "atspi118" or not r["image"].endswith("/screen.png"):
            continue
        if (r["width"], r["height"], r.get("scale", 1.0)) != (1920, 1080, 1.0):
            continue
        out[r["image"]] = r
    return out


def parent_path(img):
    meta = json.load(open(os.path.join(os.path.dirname(img), "meta.json")))
    p = meta.get("parent_state_id")
    if p is None:
        return None, meta
    d = os.path.dirname(img)
    base = os.path.basename(d).rsplit("_", 1)[0]
    return os.path.join(os.path.dirname(d), f"{base}_{int(p):04d}", "screen.png"), meta


def select_pairs():
    frames = full_frames()
    by_group = {}
    for img, r in sorted(frames.items()):
        par, meta = parent_path(img)
        if par and par in frames:
            by_group.setdefault(r["group"], []).append((par, img, meta.get("action")))
    for g in by_group:
        assert not any(g.split("_")[0] == a for a in EXAM_APPS), g
    rng = random.Random(0)
    groups = sorted(by_group)
    rng.shuffle(groups)
    for g in groups:
        rng.shuffle(by_group[g])
    pairs, k = [], 0
    while len(pairs) < N_PAIRS and any(by_group.values()):
        g = groups[k % len(groups)]
        if by_group[g]:
            pairs.append((g,) + by_group[g].pop())
        k += 1
    return pairs, frames


def main():
    from pixeltree.perceive import ours
    from pixeltree.perceive.tree import to_json

    OUT.mkdir(parents=True, exist_ok=True)
    pairs, frames = select_pairs()
    imgs = sorted({p for _, p, _, _ in pairs} | {c for _, _, c, _ in pairs})
    with open(OUT / "frames.jsonl", "w") as f:
        for g, par, child, action in pairs:
            f.write(json.dumps({"group": g, "parent": par, "child": child, "action": action}) + "\n")
    print(f"{len(pairs)} pairs, {len(imgs)} frames, {len({g for g, *_ in pairs})} groups", flush=True)
    ours.warmup()
    with open(OUT / "trees.jsonl", "w") as f:
        for k, img in enumerate(imgs):
            tree = ours.build(open(img, "rb").read())
            r = frames[img]
            gt = [{"box": b["box"], "name": b.get("name") or "", "cls": b["cls"]} for b in r["boxes"]]
            f.write(json.dumps({"image": img, "group": r["group"], "tree": to_json(tree), "gt": gt}) + "\n")
            if k % 20 == 0:
                print(k, img, len(tree.elements), round(tree.timings["total_s"], 2), flush=True)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--labels", required=True, help="label file (jsonl): image, width, height, scale, group, origin, boxes")
    ap.add_argument("--out", default=str(OUT), help="output directory (default ./out/r2/calib)")
    a = ap.parse_args()
    LABELS, OUT = Path(a.labels), Path(a.out)
    main()
