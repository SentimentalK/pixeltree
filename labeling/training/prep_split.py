#!/usr/bin/env python3
"""prep: internal val split + holdout files for exporting a labelled set (ULF records) to YOLO.

    python prep_split.py --train data/labels_train.jsonl --exam data/labels_exam.jsonl \
        --out data/yolo_prep [--val-frac 0.05] [--seed 0]

Writes to --out:
  val_ids.txt          stems (id with '/' -> '__') of the internal val split: per (origin, group) round(n * frac) records,
                       chosen with random.Random(seed) over the sorted ids (only for ultralytics curves, never model selection)
  holdout_none.json    {"holdout": {}}: export_yolo.py then puts every train record in train/ or val/
  holdout_exam.json    every (origin, group) of the exam jsonl: export_yolo.py --only-split exam keeps all exam records
  prep.json            counts per origin
"""
import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path


def read(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def val_split(recs, frac, seed):
    by_group = defaultdict(list)
    for r in recs:
        by_group[(r["origin"], r["group"])].append(r["id"])
    rng = random.Random(seed)
    picked = []
    for key in sorted(by_group):
        ids = sorted(by_group[key])
        k = int(round(len(ids) * frac))
        picked += rng.sample(ids, k) if k else []
    return picked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", required=True)
    ap.add_argument("--exam", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--val-frac", type=float, default=0.05)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    train, exam = read(a.train), read(a.exam)
    val = val_split(train, a.val_frac, a.seed)
    (out / "val_ids.txt").write_text("".join(i.replace("/", "__") + "\n" for i in val), encoding="utf-8")
    (out / "holdout_none.json").write_text(json.dumps({"holdout": {}}) + "\n", encoding="utf-8")
    hold = defaultdict(set)
    for r in exam:
        hold[r["origin"]].add(r["group"])
    (out / "holdout_exam.json").write_text(
        json.dumps({"holdout": {o: sorted(g) for o, g in sorted(hold.items())}}, indent=1) + "\n", encoding="utf-8")
    vs = set(val)
    stats = {
        "train_records": len(train), "val_records": len(val), "exam_records": len(exam),
        "train_by_origin": Counter(r["origin"] for r in train if r["id"] not in vs),
        "val_by_origin": Counter(r["origin"] for r in train if r["id"] in vs),
        "exam_by_origin": Counter(r["origin"] for r in exam),
        "exam_groups": {o: len(g) for o, g in hold.items()},
        "val_frac": a.val_frac, "seed": a.seed,
    }
    (out / "prep.json").write_text(json.dumps(stats, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main()
