#!/usr/bin/env python3
"""Label batch 1 — selection from the frame-selection output, and ULF export of the labelled batch.

  select  selection.jsonl -> <out-dir>/manifest_batch1.jsonl (+ crops/, selection_summary.md)
  ulf     labels_round1.jsonl + manifest + QA verdicts -> ULF v1 records (labels_batch1.jsonl)
  pool    gate-v1 selection (minus batch 1) -> label_v1/batch2..N/ (manifest.jsonl + crops/) + pool_train_v1.jsonl
  exam    exam-gate selection -> label_v1/<name>/ (manifest.jsonl + crops/)

Quotas per source and per-application caps are the QUOTAS constant. The manifest rows use the labelling manifest field
names (gid / pool / platform / application / image / width / height ...) so the labelling scripts can use them unchanged.
crop_rect in selection.jsonl is [x1, y1, x2, y2] in original-image pixels; frames the window rule
cropped are cut to that rectangle and the crop is what gets labelled.
"""
import argparse
import collections
import json
import os
import random
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# source -> (quota, per-application cap)
QUOTAS = {
    "atspi118": (100, 12),
    "groundcua": (150, 3),
    "web121": (50, 6),
}
SOURCE_DATASET = {"atspi118": "atspi118", "groundcua": "GroundCUA", "web121": "web121"}
PLATFORM = {"web121": "web"}  # every other source is linux
LICENSE = {
    "atspi118": "self-captured",
    "web121": "public-web-screenshot",
    "groundcua": "groundcua-see-dataset-card",  # no GroundCUA license string in the dataset card
}
TIER = "batch1"
PROMPT = "label_rules_v1_1.md"  # rules file recorded as the labelling prompt of these batches
MODEL = "claude-opus-5-5"
RANK_LAST = 10 ** 12


def _gate_rules():
    """The frame-selection rules module (app_base, held-out application helpers). It is not part of this release;
    the pool / exam / hard-check commands need it, the select / ulf commands do not."""
    try:
        import gate_rules as R
    except ImportError as e:
        raise SystemExit("this command needs the frame-selection rules module gate_rules.py (not included): " + str(e))
    return R


def allocate(avail, quota, cap, seed_key):
    """Images to take per application: spread evenly, no application above cap.

    k = smallest integer with sum(min(avail, k)) >= quota (k <= cap). Every application gets min(avail, k-1); the
    remainder r is one extra image for r applications that have >= k images, drawn with Random(seed_key).
    If even k = cap is not enough, everything up to cap is taken (and a warning printed).
    """
    apps = sorted(avail)
    k = None
    for cand in range(1, cap + 1):
        if sum(min(avail[a], cand) for a in apps) >= quota:
            k = cand
            break
    if k is None:
        got = {a: min(avail[a], cap) for a in apps}
        print(f"WARNING: quota {quota} not reachable with cap {cap} (available {sum(got.values())}); taking all",
              file=sys.stderr)
        return got
    got = {a: min(avail[a], k - 1) for a in apps}
    r = quota - sum(got.values())
    eligible = [a for a in apps if avail[a] >= k]
    for a in random.Random(seed_key).sample(sorted(eligible), r):
        got[a] += 1
    return got


def _rank_key(row):
    rank = row.get("rank")
    return (RANK_LAST if rank is None else rank, row["gid"])


def pick(rows, source):
    """rows: selected rows of one source -> chosen rows (per-application allocation, best rank first)."""
    quota, cap = QUOTAS[source]
    by_app = collections.defaultdict(list)
    for r in rows:
        by_app[r["app"]].append(r)
    take = allocate({a: len(v) for a, v in by_app.items()}, quota, cap, f"123:{source}")
    chosen = []
    for app in sorted(by_app):
        chosen += sorted(by_app[app], key=_rank_key)[:take[app]]
    return chosen


def manifest_row(row, crops_dir, tier=TIER, split=None):
    """Selection row -> manifest row; crops the original when crop_rect is set (crop is what gets labelled).

    tier / split override the batch-1 defaults (tier "batch1", split taken from the selection row)."""
    src = row["source"]
    orig = row["image"]
    with Image.open(orig) as im:
        ow, oh = im.size
        rect = row.get("crop_rect")
        if rect:
            x1, y1, x2, y2 = rect
            os.makedirs(crops_dir, exist_ok=True)
            out = os.path.abspath(os.path.join(crops_dir, row["gid"] + ".png"))
            crop = im.convert("RGB").crop((x1, y1, x2, y2))
            crop.save(out)
            image, width, height = out, crop.size[0], crop.size[1]
        else:
            image, width, height = orig, ow, oh
    return {
        "gid": row["gid"], "tier": tier, "pool": src, "platform": PLATFORM.get(src, "linux"),
        "source_dataset": SOURCE_DATASET[src], "source_id": row["gid"], "application": row["app"],
        "image": image, "width": width, "height": height,
        "orig_image": orig, "orig_width": ow, "orig_height": oh, "crop_rect": rect,
        "split": split or row.get("split"), "stratum": row.get("stratum"), "rank": row.get("rank"),
        "license": LICENSE[src],
    }


def summary_md(manifest):
    lines = ["# batch 1 selection", "",
             "| source | images | applications | max per application | crops |", "|---|---|---|---|---|"]
    per = {}
    for src in QUOTAS:
        rs = [m for m in manifest if m["pool"] == src]
        cnt = collections.Counter(m["application"] for m in rs)
        per[src] = cnt
        lines.append(f"| {src} | {len(rs)} | {len(cnt)} | {max(cnt.values()) if cnt else 0} | "
                     f"{sum(1 for m in rs if m['crop_rect'])} |")
    lines.append(f"| total | {len(manifest)} | | | {sum(1 for m in manifest if m['crop_rect'])} |")
    for src, cnt in per.items():
        lines += ["", f"## {src} (quota {QUOTAS[src][0]}, cap {QUOTAS[src][1]})", "",
                  "| application | images |", "|---|---|"]
        lines += [f"| {a} | {n} |" for a, n in sorted(cnt.items())]
    return "\n".join(lines) + "\n"


def cmd_select(a):
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(line) for line in open(a.selection, encoding="utf-8") if line.strip()]
    sel = [r for r in rows if r.get("decision") == "selected"]
    manifest = []
    for src in QUOTAS:
        chosen = pick([r for r in sel if r["source"] == src], src)
        manifest += [manifest_row(r, str(out / "crops")) for r in chosen]
    with open(out / "manifest_batch1.jsonl", "w", encoding="utf-8") as f:
        for m in manifest:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    text = summary_md(manifest)
    (out / "selection_summary.md").write_text(text, encoding="utf-8")
    print("\n".join(text.splitlines()[:9]))
    print(f"-> {out}/manifest_batch1.jsonl ({len(manifest)} rows)")


# ---------------------------------------------------------------- ULF export
def _n_dropped(batch_dir):
    out = {}
    for p in Path(batch_dir).glob("*/*/merge_stats.json"):
        try:
            per = json.loads(p.read_text(encoding="utf-8")).get("per_gid", {})
        except (OSError, ValueError):
            continue
        for gid, st in per.items():
            out[gid] = {k: v for k, v in st.items() if k != "boxes" and v}
    return out


def cmd_ulf(a):
    import numpy as np
    import ulf

    data_root = Path(ulf.DATA_ROOT).resolve()
    man = {m["gid"]: m for m in ulf.read_jsonl(a.manifest)}
    qa_dir = Path(a.qa)
    dropped = _n_dropped(Path(a.labels).parent)
    recs, n_err, n_warn, n_box = [], 0, 0, 0
    for lab in ulf.read_jsonl(a.labels):
        gid = lab["gid"]
        m = man[gid]
        gray = np.asarray(Image.open(lab["image"]).convert("L"))
        boxes = [list(map(float, b["box"])) for b in lab["boxes"]]
        parents = ulf.assign_parents(boxes)
        out_boxes = []
        for i, (b, bx, par) in enumerate(zip(lab["boxes"], boxes, parents)):
            out_boxes.append({
                "cls": int(b["cls"]), "box": bx, "kind": b.get("kind") or "leaf", "role_hint": None,
                "parent": par, "name": (b.get("name") or "") if b.get("name_source") == "text" else "",
                "crop_hash": ulf.crop_hash(gray, bx), "src_id": f"{gid}#{i}",
            })
        qa_path = qa_dir / f"{gid}.json"
        qa = json.loads(qa_path.read_text(encoding="utf-8")) if qa_path.exists() else {}
        img = Path(lab["image"]).resolve()
        try:
            image = str(img.relative_to(data_root))
        except ValueError:
            image = str(img)
        rec = {
            "id": gid, "image": image, "width": lab["width"], "height": lab["height"], "scale": 1.0,
            "source": "model", "origin": m["source_dataset"].lower(), "group": m["application"],
            "platform": m["platform"], "theme": "unknown", "state": "base",
            "window_region": [0, 0, lab["width"], lab["height"]], "em_px": None, "boxes": out_boxes,
            "n_dropped": dropped.get(gid, {}),
            # provenance (extra keys are ignored by ulf.validate_record)
            "pool": m["pool"], "orig_image": m["orig_image"], "orig_width": m["orig_width"],
            "orig_height": m["orig_height"], "crop_rect": m["crop_rect"], "split": m.get("split"),
            "stratum": m.get("stratum"), "license": m["license"], "model": MODEL, "prompt": PROMPT,
            "qa_verdict": qa.get("verdict"), "qa_reason": qa.get("reason"),
        }
        errs, warns = ulf.validate_record(rec, data_root, check_image=True)
        for e in errs:
            print("ERROR", e, file=sys.stderr)
        n_err += len(errs)
        n_warn += len(warns)
        n_box += len(out_boxes)
        recs.append(rec)
    ulf.write_jsonl(a.out, recs)
    print(f"records={len(recs)} boxes={n_box} validate_errors={n_err} warnings={n_warn} -> {a.out}")
    return 1 if n_err else 0


# ---------------------------------------------------------------- training pool / exam
POOL_ORDER = ["groundcua", "web121", "atspi118"]
EXAM_ORDER = ["atspi118", "web121"]
WEB_PER_SITE = 15       # web121: new images per site
ATSPI_PER_APP = 40      # atspi118: batch-1 images + new images per application


def read_jsonl(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def round_robin(rows):
    """rows of one source -> applications sorted by name, each application's rows by rank; round 1 takes the best
    row of every application, round 2 the second best, ... (exhausted applications drop out)."""
    by_app = collections.defaultdict(list)
    for r in rows:
        by_app[r["app"]].append(r)
    queues = [sorted(by_app[a], key=_rank_key) for a in sorted(by_app)]
    out = []
    for i in range(max((len(q) for q in queues), default=0)):
        out += [q[i] for q in queues if i < len(q)]
    return out


def allocate_base(cands_by_key, labelled_by_key, cap):
    """One base application -> ({key: rows taken}, rows left out).

    cands_by_key: {key: candidate rows, already sorted by _rank_key ascending}; labelled_by_key: {key: images already
    labelled}; cap: images per base application over labelled + new.
    1) room = max(0, cap - sum(labelled)); room 0 -> everything is left out.
    2) room >= number of keys with candidates: every such key gets 1 slot first.
    3) the remaining room is split over the keys proportionally to their candidate counts (floor, then largest
       remainder, ties by key name), each key capped at its candidate count.
    4) slots still unused go round-robin by key name to keys that still have candidates.
    Each key takes its best-ranked rows; the rest is left out."""
    keys = sorted(k for k, v in cands_by_key.items() if v)
    room = max(0, cap - sum(labelled_by_key.values()))
    n = {k: len(cands_by_key[k]) for k in keys}
    share = {k: 0 for k in keys}
    if room and keys:
        rest = room
        if rest >= len(keys):
            share = {k: 1 for k in keys}
            rest -= len(keys)
        total = sum(n.values())
        part = {k: rest * n[k] // total for k in keys}
        for k in sorted(keys, key=lambda k: (-(rest * n[k] % total), k))[:rest - sum(part.values())]:
            part[k] += 1
        share = {k: min(share[k] + part[k], n[k]) for k in keys}
        free = min(room, total) - sum(share.values())
        while free > 0:
            for k in keys:
                if free > 0 and share[k] < n[k]:
                    share[k] += 1
                    free -= 1
    taken = {k: list(cands_by_key[k][:share[k]]) for k in keys}
    left_out = [r for k in keys for r in cands_by_key[k][share[k]:]]
    return taken, left_out


def pool_order(candidates, prior_rows, cap_mode="key", reserve=None):
    """Selected rows (already-labelled gids removed) -> training rows in labelling order.

    groundcua -> web121 -> atspi118; web121 at most WEB_PER_SITE new rows per site, both best rank first; inside a
    source applications take turns (round_robin).
    atspi118 cap_mode "key" (default): at most ATSPI_PER_APP - (prior rows of the application key, all earlier
    batches) new rows per application key. cap_mode "base": the cap is per base application (the frame-selection rules module's app_base,
    variant suffixes dropped) over prior + new rows, shared between the variant keys by allocate_base; the rows left
    out are appended to the list `reserve` when one is given."""
    b1_per_app = collections.Counter(m["application"] for m in prior_rows if m["pool"] == "atspi118")
    out = []
    for src in POOL_ORDER:
        rows = [r for r in candidates if r["source"] == src]
        if src == "atspi118" and cap_mode == "base":
            R = _gate_rules()
            by_base = collections.defaultdict(lambda: collections.defaultdict(list))
            for r in rows:
                by_base[R.app_base(r["app"])][r["app"]].append(r)
            kept = []
            for base in sorted(by_base):
                cands = {k: sorted(v, key=_rank_key) for k, v in by_base[base].items()}
                labelled = {k: n for k, n in b1_per_app.items() if R.app_base(k) == base}
                taken, left_out = allocate_base(cands, labelled, ATSPI_PER_APP)
                for k in sorted(taken):
                    kept += taken[k]
                if reserve is not None:
                    reserve += left_out
            rows = kept
        elif src in ("web121", "atspi118"):
            by_app = collections.defaultdict(list)
            for r in rows:
                by_app[r["app"]].append(r)
            kept = []
            for app, rs in by_app.items():
                room = WEB_PER_SITE if src == "web121" else max(0, ATSPI_PER_APP - b1_per_app[app])
                kept += sorted(rs, key=_rank_key)[:room]
            rows = kept
        out += round_robin(rows)
    return out


def exam_pick(sel_rows, prior_rows, cap):
    """Exam-gate selection rows -> new exam rows in exam order.

    Candidates = decision "selected" and gid not in prior_rows (earlier exam manifests). cap > 0: per app_base at
    most cap rows in total, i.e. cap - (prior rows of that app_base) new ones, best rank first; cap 0 = no limit.
    The kept rows are ordered EXAM_ORDER + round_robin as before."""
    R = _gate_rules()
    prior_gids = {m["gid"] for m in prior_rows}
    cand = [r for r in sel_rows if r.get("decision") == "selected" and r["gid"] not in prior_gids]
    if cap > 0:
        have = collections.Counter(R.app_base(m["application"]) for m in prior_rows)
        by_base = collections.defaultdict(list)
        for r in cand:
            by_base[R.app_base(r["app"])].append(r)
        cand = []
        for base, rs in by_base.items():
            cand += sorted(rs, key=_rank_key)[:max(0, cap - have[base])]
    ordered = []
    for src in EXAM_ORDER:
        ordered += round_robin([r for r in cand if r["source"] == src])
    return ordered


def split_batches(rows, batch_size, first_batch):
    """-> [(batch number, rows)]; the last batch may be short."""
    return [(first_batch + k, rows[i:i + batch_size]) for k, i in enumerate(range(0, len(rows), batch_size))]


def hard_checks(train, exam, batch1, held_apps):
    """-> list of error strings. train / exam / batch1: manifest-like rows (gid, pool, application, image);
    held_apps: {(source, app_base)} of the held-out exam applications."""
    R = _gate_rules()
    errs = []
    for name, rows in (("train", train), ("exam", exam)):
        for r in rows:
            img = r["image"]
            if not os.path.isabs(img):
                errs.append(f"{name} {r['gid']}: image path not absolute: {img}")
            elif not os.path.isfile(img):
                errs.append(f"{name} {r['gid']}: image missing: {img}")
    train_gids = {r["gid"] for r in train}
    both = train_gids & {r["gid"] for r in exam}
    if both:
        errs.append(f"{len(both)} gid(s) in both train and exam, e.g. {sorted(both)[0]}")
    both_b1 = train_gids & {r["gid"] for r in batch1}
    if both_b1:
        errs.append(f"{len(both_b1)} train gid(s) already in batch 1, e.g. {sorted(both_b1)[0]}")
    if len(train_gids) != len(train):
        errs.append(f"duplicate gids inside the training rows ({len(train) - len(train_gids)})")
    bad = sorted({(r["pool"], r["application"]) for r in train
                  if (r["pool"], R.app_base(r["application"])) in held_apps})
    if bad:
        errs.append(f"train rows from held-out applications: {bad[:5]}")
    return errs


def held_apps_of(selection_rows, exam_selection_rows=None):
    """{(source, app_base)}: apps the gate holds out (split heldout in gate v1, split exam in the exam gate)."""
    R = _gate_rules()
    held = {(r["source"], R.app_base(r["app"])) for r in selection_rows if r.get("split") == "heldout"}
    held |= {(r["source"], R.app_base(r["app"])) for r in (exam_selection_rows or []) if r.get("split") == "exam"}
    return held


def _fail(errs):
    for e in errs:
        print("CHECK FAILED:", e, file=sys.stderr)
    raise SystemExit(1)


def _count_table(batches):
    lines = []
    for k, rows in batches:
        c = collections.Counter(r["source"] for r in rows)
        lines.append(f"batch{k}: total={len(rows)} " + " ".join(f"{s}={c.get(s, 0)}" for s in POOL_ORDER))
    return lines


def cmd_pool(a):
    label_root = Path(a.label_root).resolve()
    rows = read_jsonl(a.selection)
    batch1 = []
    for path in a.exclude:
        batch1 += read_jsonl(path)
    excl = {m["gid"] for m in batch1}
    cand = [r for r in rows if r.get("decision") == "selected" and r["gid"] not in excl]
    reserve = [] if a.cap_mode == "base" else None
    ordered = pool_order(cand, batch1, cap_mode=a.cap_mode, reserve=reserve)
    batches = split_batches(ordered, a.batch_size, a.first_batch)
    print("\n".join(_count_table(batches)))
    print(f"total train rows: {len(ordered)} in {len(batches)} batches")
    if reserve is not None:
        print(f"reserve (base cap {ATSPI_PER_APP}): {len(reserve)} rows" + (" (not written: --dry-run)" if a.dry_run else ""))
    if a.dry_run:
        return 0
    train_manifest = []
    for k, rs in batches:
        d = label_root / f"batch{k}"
        d.mkdir(parents=True, exist_ok=True)
        ms = [manifest_row(r, str(d / "crops"), tier=f"batch{k}", split="train") for r in rs]
        with open(d / "manifest.jsonl", "w", encoding="utf-8") as f:
            for m in ms:
                f.write(json.dumps(m, ensure_ascii=False) + "\n")
        train_manifest += [dict(m, batch=k) for m in ms]
        print(f"-> {d}/manifest.jsonl ({len(ms)} rows)", flush=True)
    with open(label_root / a.pool_out, "w", encoding="utf-8") as f:
        for m in train_manifest:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    if reserve is not None and a.reserve_out:
        rp = Path(a.reserve_out).resolve()
        rp.parent.mkdir(parents=True, exist_ok=True)
        with open(rp, "w", encoding="utf-8") as f:
            for r in reserve:
                m = dict(manifest_row(r, str(rp.parent / "reserve_crops"), tier="reserve", split="train"),
                         reason="base_cap_40")
                f.write(json.dumps(m, ensure_ascii=False) + "\n")
        print(f"-> {rp} ({len(reserve)} rows)")
    exam_sel_path = Path(a.exam_selection) if a.exam_selection else label_root.parent / "gate_exam_v1" / "selection.jsonl"
    exam_sel = read_jsonl(exam_sel_path) if exam_sel_path.is_file() else None
    exam = []
    for exam_path in sorted(label_root.glob("exam*/manifest.jsonl")):
        exam += read_jsonl(exam_path)
    errs = hard_checks(train_manifest, exam, batch1, held_apps_of(rows, exam_sel))
    print(f"-> {label_root / a.pool_out} ({len(train_manifest)} rows)")
    if errs:
        _fail(errs)
    print(f"hard checks OK (exam rows checked: {len(exam)}, held-out source: "
          f"{'gate_v1 + exam gate' if exam_sel else 'gate_v1'})")
    return 0


def cmd_exam(a):
    label_root = Path(a.label_root).resolve()
    sel_rows = read_jsonl(a.selection)
    prior = []
    for path in a.exclude:
        prior += read_jsonl(path)
    ordered = exam_pick(sel_rows, prior, a.cap_per_app)
    d = label_root / a.name
    d.mkdir(parents=True, exist_ok=True)
    ms = [manifest_row(r, str(d / "crops"), tier=a.name, split="exam") for r in ordered]
    with open(d / "manifest.jsonl", "w", encoding="utf-8") as f:
        for m in ms:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    c = collections.Counter(m["pool"] for m in ms)
    print(f"-> {d}/manifest.jsonl ({len(ms)} rows) " + " ".join(f"{s}={c.get(s, 0)}" for s in EXAM_ORDER))
    train = []
    for name in ("pool_train_v1.jsonl", "pool_train_v2.jsonl"):
        pool_path = label_root / name
        if pool_path.is_file():
            train += read_jsonl(pool_path)
    b1_path = label_root / "batch1" / "manifest_batch1.jsonl"
    batch1 = read_jsonl(b1_path) if b1_path.is_file() else []
    errs = hard_checks(train, ms, batch1, held_apps_of([], sel_rows))
    overlap = {m["gid"] for m in ms} & {m["gid"] for m in prior}
    if overlap:
        errs.append(f"{len(overlap)} new exam gid(s) already in an earlier exam manifest, e.g. {sorted(overlap)[0]}")
    if errs:
        _fail(errs)
    print(f"hard checks OK (train rows checked: {len(train)}, exam rows: {len(ms)}, earlier exam rows: {len(prior)})")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sp = p.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("select")
    s.add_argument("--selection", required=True)
    s.add_argument("--out-dir", required=True)
    u = sp.add_parser("ulf")
    u.add_argument("--labels", required=True)
    u.add_argument("--manifest", required=True)
    u.add_argument("--qa", required=True, help="directory of QA verdict JSON files (<gid>.json)")
    u.add_argument("--out", required=True)
    q = sp.add_parser("pool", help="training pool batches (batch2..N) from the gate-v1 selection")
    q.add_argument("--selection", required=True)
    q.add_argument("--exclude", required=True, action="append",
                   help="already-labelled manifest (repeatable): its gids are removed and its rows count towards "
                        "the per-application totals")
    q.add_argument("--pool-out", default="pool_train_v1.jsonl", metavar="NAME",
                   help="training manifest file name, written under --label-root (default: pool_train_v1.jsonl)")
    q.add_argument("--label-root", required=True)
    q.add_argument("--batch-size", type=int, default=500)
    q.add_argument("--first-batch", type=int, default=2)
    q.add_argument("--exam-selection", default=None,
                   help="exam-gate selection.jsonl (default: <label-root>/../gate_exam_v1/selection.jsonl if present)")
    q.add_argument("--cap-mode", choices=["key", "base"], default="key",
                   help="atspi118 cap: per application key (default) or per base application (variants share the "
                        "cap in proportion to their candidates)")
    q.add_argument("--reserve-out", default=None, metavar="PATH",
                   help="base mode only: manifest of the candidate rows the base cap left out")
    q.add_argument("--dry-run", action="store_true", help="print images per batch and source, write nothing")
    x = sp.add_parser("exam", help="exam manifest from the exam-gate selection")
    x.add_argument("--selection", required=True)
    x.add_argument("--label-root", required=True)
    x.add_argument("--name", default="exam1")
    x.add_argument("--exclude", action="append", default=[],
                   help="existing exam manifest (repeatable): its gids are skipped, its rows count towards the cap")
    x.add_argument("--cap-per-app", type=int, default=0,
                   help="max rows per app_base over exclude + new rows (default 0 = no limit)")
    a = p.parse_args(argv)
    if a.cmd == "pool" and os.path.basename(a.pool_out) != a.pool_out:
        p.error("--pool-out takes a file name only")
    if a.cmd == "pool" and a.reserve_out and a.cap_mode != "base":
        p.error("--reserve-out needs --cap-mode base")
    if a.cmd == "select":
        return cmd_select(a)
    if a.cmd == "pool":
        return cmd_pool(a)
    if a.cmd == "exam":
        return cmd_exam(a)
    return cmd_ulf(a)


if __name__ == "__main__":
    sys.exit(main() or 0)
