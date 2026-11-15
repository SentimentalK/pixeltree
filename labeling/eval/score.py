"""exam scoring: fixed-hyperparameter YOLO predict, greedy IoU match, val calibration.

  predict  --weights W --images DIR [--stems FILE] --out OUT.jsonl [--txt-dir DIR]
            [--device 0|cpu] [--txt-drop-cls N]
            CONF_SAVE=0.05, NMS_IOU=0.7, IMGSZ=1280, MAX_DET=1000 are fixed.
  score    --pred P.jsonl --gt LABELDIR --mode agnostic|strict --conf C --json OUT
            [--drop-pred-cls N] [--gt-cls 0-14] [--exclude-groups A,B] [--only-groups A,B]
            [--group-by app]
  calib    --pred P.jsonl --gt LABELDIR --json OUT
            Agnostic F1 on conf = 0.05, 0.10, ..., 0.90. For internal val only.
"""
import argparse
import json
import os
import sys

import numpy as np

# Class names and the precision / recall / F1 helper, copied verbatim from the scoring module this file replaced.
NAMES = ["aria:button", "aria:link", "aria:menuitem", "aria:tab", "aria:checkbox", "aria:radio", "aria:textbox",
         "aria:combobox", "aria:slider", "aria:progressbar", "aria:gridcell", "aria:listitem", "aria:heading",
         "aria:img", "vax:visibleText"]


def prf(tp, n_pr, n_gt):
    p = tp / n_pr if n_pr else 0.0
    r = tp / n_gt if n_gt else 0.0
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)

CONF_SAVE = 0.05
NMS_IOU = 0.7
IMGSZ = 1280
MAX_DET = 1000
MATCH_IOU = 0.5
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}


def iou_matrix(gt_boxes, pr_boxes):
    """Pairwise IoU, same formula as eval/score.iou. gt (G,4), pr (P,4) -> (G,P)."""
    g = gt_boxes[:, None, :]
    p = pr_boxes[None, :, :]
    ix = np.maximum(0.0, np.minimum(g[..., 2], p[..., 2]) - np.maximum(g[..., 0], p[..., 0]))
    iy = np.maximum(0.0, np.minimum(g[..., 3], p[..., 3]) - np.maximum(g[..., 1], p[..., 1]))
    inter = ix * iy
    area_g = (gt_boxes[:, 2] - gt_boxes[:, 0]) * (gt_boxes[:, 3] - gt_boxes[:, 1])
    area_p = (pr_boxes[:, 2] - pr_boxes[:, 0]) * (pr_boxes[:, 3] - pr_boxes[:, 1])
    union = area_g[:, None] + area_p[None, :] - inter
    return np.where(union > 0, inter / union, 0.0)


def greedy_np(gt, pr, mode):
    """Greedy one-to-one TP count. Same selection order as eval/score.greedy.

    gt, pr: sequences of (cls, [x0, y0, x1, y1]).
    mode: "agnostic" (any class, IoU >= 0.5) or "strict" (same class and IoU >= 0.5).
    Candidates are the numpy IoU matrix; ties break by higher GT index, then higher pred index.
    """
    if not gt or not pr:
        return 0
    if mode not in ("agnostic", "strict"):
        raise ValueError(mode)
    gb = np.asarray([g[1] for g in gt], dtype=np.float64)
    pb = np.asarray([p[1] for p in pr], dtype=np.float64)
    mat = iou_matrix(gb, pb)
    if mode == "strict":
        gc = np.asarray([int(g[0]) for g in gt])
        pc = np.asarray([int(p[0]) for p in pr])
        mask = (mat >= MATCH_IOU) & (gc[:, None] == pc[None, :])
    else:
        mask = mat >= MATCH_IOU
    ii, jj = np.nonzero(mask)
    pairs = sorted(((float(mat[i, j]), int(i), int(j)) for i, j in zip(ii, jj)), reverse=True)
    used_g, used_p, n = set(), set(), 0
    for _, i, j in pairs:
        if i in used_g or j in used_p:
            continue
        used_g.add(i)
        used_p.add(j)
        n += 1
    return n


def image_group(stem):
    """Group is the second `__` field: a groundcua app, or a realweb site.

    groundcua stems are `groundcua__<app>__<id>`. realweb stems on disk are
    `realweb__<site>_<WxH>_<theme>_<id>` (the site and the rest joined by `_`).
    """
    parts = stem.split("__")
    if len(parts) >= 3:
        return parts[1]
    if len(parts) == 2 and parts[0] == "realweb":
        return parts[1].split("_", 1)[0]
    if len(parts) == 2:
        return parts[1]
    return stem


def parse_gt_cls(spec):
    """`0-14` or `0,2-4` -> inclusive set of class ids. None stays None."""
    if spec is None:
        return None
    out = set()
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return out


def parse_groups(spec):
    if spec is None:
        return None
    return {p.strip() for p in str(spec).split(",") if p.strip()}


def _round(x, nd):
    return float(f"{float(x):.{nd}f}")


def list_images(images_dir, stems_file):
    stems = None
    if stems_file:
        with open(stems_file, encoding="utf-8") as f:
            stems = [s.strip() for s in f if s.strip()]
    by_stem = {}
    for name in os.listdir(images_dir):
        stem, ext = os.path.splitext(name)
        if ext.lower() not in IMAGE_EXTS:
            continue
        if stems is not None and stem not in set(stems):
            continue
        by_stem[stem] = os.path.join(images_dir, name)
    if stems is not None:
        missing = [s for s in stems if s not in by_stem]
        if missing:
            raise SystemExit(f"missing {len(missing)} stems, e.g. {missing[:3]}")
        return [by_stem[s] for s in stems]
    return [by_stem[s] for s in sorted(by_stem)]


def _n_lines(path):
    with open(path, encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def _boxes_from_result(result):
    boxes = result.boxes
    if boxes is None or len(boxes) == 0:
        return []
    xyxy = boxes.xyxy.cpu().numpy()
    cls = boxes.cls.cpu().numpy()
    conf = boxes.conf.cpu().numpy()
    out = []
    for (x0, y0, x1, y1), c, cf in zip(xyxy, cls, conf):
        out.append([_round(x0, 2), _round(y0, 2), _round(x1, 2), _round(y1, 2), int(c), _round(cf, 4)])
    return out


def _write_txt(path, boxes, w, h, drop_cls):
    lines = []
    for x0, y0, x1, y1, c, cf in boxes:
        if int(c) in drop_cls:
            continue
        lines.append(
            f"{int(c)} {(x0 + x1) / 2 / w:.6f} {(y0 + y1) / 2 / h:.6f} "
            f"{(x1 - x0) / w:.6f} {(y1 - y0) / h:.6f} {cf:.4f}"
        )
    text = "\n".join(lines) + ("\n" if lines else "")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def cmd_predict(a):
    paths = list_images(a.images, a.stems)
    if not paths:
        raise SystemExit(f"no images in {a.images}")
    out = a.out
    if os.path.exists(out) and _n_lines(out) == len(paths):
        print(f"skip {out}")
        return
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    drop_cls = set(a.txt_drop_cls or [])
    if a.txt_dir:
        os.makedirs(a.txt_dir, exist_ok=True)
    from ultralytics import YOLO

    model = YOLO(a.weights)
    # A list source makes ultralytics load every image up front (8,299 exam images -> 12 GB RSS, OOM);
    # a .txt source of paths is read lazily, one image at a time.
    sources = out + ".sources.txt"
    with open(sources, "w", encoding="utf-8") as f:
        f.write("\n".join(os.path.abspath(p) for p in paths) + "\n")
    kw = dict(source=sources, stream=True, conf=CONF_SAVE, iou=NMS_IOU, imgsz=IMGSZ,
              max_det=MAX_DET, verbose=False, save=False)
    if a.device:
        kw["device"] = a.device
    n = len(paths)
    with open(out, "w", encoding="utf-8") as f:
        for i, result in enumerate(model.predict(**kw), start=1):
            h, w = (int(v) for v in result.orig_shape)
            stem = os.path.splitext(os.path.basename(result.path))[0]
            boxes = _boxes_from_result(result)
            if a.txt_dir:
                _write_txt(os.path.join(a.txt_dir, stem + ".txt"), boxes, w, h, drop_cls)
            rec = {"image": stem, "w": w, "h": h, "boxes": boxes}
            f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
            if i == 1 or i == n or i % 50 == 0:
                print(f"predict {i}/{n} {stem}", file=sys.stderr)
    print(f"wrote {n} {out}")


def _read_gt(path, w, h, keep_cls):
    boxes = []
    if not os.path.exists(path):
        return boxes
    with open(path, encoding="utf-8") as f:
        for line in f:
            v = line.split()
            if len(v) < 5:
                continue
            c = int(float(v[0]))
            if keep_cls is not None and c not in keep_cls:
                continue
            cx, cy, bw, bh = (float(x) for x in v[1:5])
            boxes.append((c, [(cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h]))
    return boxes


def _pred_boxes(row, conf, drop_cls):
    out = []
    for x0, y0, x1, y1, c, cf in row.get("boxes", []):
        if float(cf) < conf:
            continue
        c = int(c)
        if c in drop_cls:
            continue
        out.append((c, [float(x0), float(y0), float(x1), float(y1)]))
    return out


def _metrics(tp, fp, fn, recall_only):
    if recall_only:
        n_gt = tp + fn
        return {"tp": tp, "fp": None, "fn": fn, "precision": None,
                "recall": (tp / n_gt if n_gt else 0.0), "f1": None}
    p, r, f1 = prf(tp, tp + fp, tp + fn)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": r, "f1": f1}


def _accumulate(bucket, gt, pr, mode, recall_only):
    tp = greedy_np(gt, pr, mode)
    if recall_only:
        bucket["tp"] += tp
        bucket["fn"] += len(gt) - tp
    else:
        bucket["tp"] += tp
        bucket["fp"] += len(pr) - tp
        bucket["fn"] += len(gt) - tp
    if mode == "strict":
        for c in range(len(NAMES)):
            gt_c = [g for g in gt if g[0] == c]
            pr_c = [p for p in pr if p[0] == c]
            tp_c = greedy_np(gt_c, pr_c, "strict") if gt_c and pr_c else 0
            slot = bucket["by_class"][c]
            slot["tp"] += tp_c
            slot["fn"] += len(gt_c) - tp_c
            if not recall_only:
                slot["fp"] += len(pr_c) - tp_c


def _empty_bucket(strict):
    b = {"tp": 0, "fp": 0, "fn": 0, "n_images": 0}
    if strict:
        b["by_class"] = {c: {"tp": 0, "fp": 0, "fn": 0} for c in range(len(NAMES))}
    return b


def score_rows(rows, gt_dir, mode, conf, drop_pred_cls=(), gt_cls=None, exclude_groups=None,
               only_groups=None, args=None):
    """Score jsonl rows against a YOLO label directory. See module docstring."""
    if isinstance(gt_cls, str):
        gt_cls = parse_gt_cls(gt_cls)
    drop_pred_cls = set(drop_pred_cls or [])
    if isinstance(exclude_groups, str):
        exclude_groups = parse_groups(exclude_groups)
    if isinstance(only_groups, str):
        only_groups = parse_groups(only_groups)
    recall_only = gt_cls is not None
    strict = mode == "strict"
    total = _empty_bucket(strict)
    groups = {}
    for row in rows:
        stem = row["image"]
        group = image_group(stem)
        if only_groups is not None and group not in only_groups:
            continue
        if exclude_groups is not None and group in exclude_groups:
            continue
        w, h = float(row["w"]), float(row["h"])
        gt = _read_gt(os.path.join(gt_dir, stem + ".txt"), w, h, gt_cls)
        pr = _pred_boxes(row, conf, drop_pred_cls)
        if group not in groups:
            groups[group] = _empty_bucket(strict)
        for bucket in (total, groups[group]):
            bucket["n_images"] += 1
            _accumulate(bucket, gt, pr, mode, recall_only)
    by_group = {}
    for name in sorted(groups):
        g = groups[name]
        by_group[name] = {"n_images": g["n_images"], **_metrics(g["tp"], g["fp"], g["fn"], recall_only)}
    result = {
        "mode": mode,
        "conf": conf,
        "n_images": total["n_images"],
        **_metrics(total["tp"], total["fp"], total["fn"], recall_only),
        "by_group": by_group,
    }
    if strict:
        result["by_class"] = {
            NAMES[c]: _metrics(slot["tp"], slot["fp"], slot["fn"], recall_only)
            for c, slot in total["by_class"].items()
        }
    result["args"] = list(args) if args is not None else []
    return result


def format_summary(m):
    def num(x):
        if x is None:
            return "null"
        if isinstance(x, float):
            return f"{x:.4f}"
        return str(x)

    return (f"mode={m['mode']} conf={m['conf']:.2f} n_images={m['n_images']} "
            f"tp={num(m['tp'])} fp={num(m['fp'])} fn={num(m['fn'])} "
            f"precision={num(m['precision'])} recall={num(m['recall'])} f1={num(m['f1'])}")


def _dump_json(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def _load_jsonl(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def cmd_score(a):
    rows = _load_jsonl(a.pred)
    result = score_rows(
        rows, a.gt, a.mode, a.conf,
        drop_pred_cls=a.drop_pred_cls, gt_cls=a.gt_cls,
        exclude_groups=a.exclude_groups, only_groups=a.only_groups,
        args=sys.argv[1:],
    )
    _dump_json(a.json, result)
    print(format_summary(result))


def calib_rows(rows, gt_dir):
    thresholds = []
    for i in range(1, 19):
        conf = round(i * 0.05, 2)
        m = score_rows(rows, gt_dir, "agnostic", conf)
        thresholds.append({
            "conf": conf,
            "n_images": m["n_images"],
            "tp": m["tp"],
            "fp": m["fp"],
            "fn": m["fn"],
            "precision": m["precision"],
            "recall": m["recall"],
            "f1": m["f1"],
        })
    best = max(thresholds, key=lambda r: (r["f1"], r["conf"]))
    return {"thresholds": thresholds, "best": best}


def cmd_calib(a):
    result = calib_rows(_load_jsonl(a.pred), a.gt)
    _dump_json(a.json, result)
    b = result["best"]
    print(f"best conf={b['conf']:.2f} precision={b['precision']:.4f} recall={b['recall']:.4f} f1={b['f1']:.4f}")


def build_parser():
    ap = argparse.ArgumentParser(description="YOLO exam predict / score / val calibration")
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("predict")
    p.add_argument("--weights", required=True)
    p.add_argument("--images", required=True)
    p.add_argument("--stems")
    p.add_argument("--out", required=True)
    p.add_argument("--txt-dir")
    p.add_argument("--device", choices=["0", "cpu"])
    p.add_argument("--txt-drop-cls", type=int, action="append")
    s = sp.add_parser("score")
    s.add_argument("--pred", required=True)
    s.add_argument("--gt", required=True)
    s.add_argument("--mode", required=True, choices=["agnostic", "strict"])
    s.add_argument("--conf", type=float, required=True)
    s.add_argument("--json", required=True)
    s.add_argument("--drop-pred-cls", type=int, action="append")
    s.add_argument("--gt-cls")
    s.add_argument("--exclude-groups")
    s.add_argument("--only-groups")
    s.add_argument("--group-by", default="app")
    c = sp.add_parser("calib")
    c.add_argument("--pred", required=True)
    c.add_argument("--gt", required=True)
    c.add_argument("--json", required=True)
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    {"predict": cmd_predict, "score": cmd_score, "calib": cmd_calib}[a.cmd](a)


if __name__ == "__main__":
    main()
