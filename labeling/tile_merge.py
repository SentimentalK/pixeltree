#!/usr/bin/env python3
"""gold-exam trial labelling helpers.

Drives label_one.py (make / run), which is not modified here.

  frames   manifest + gids -> <dir>/frames.jsonl (+ <dir>/tiles/<stem>.png in tile mode)
  merge    <dir>/work/json/<stem>.json -> <dir>/labels.jsonl (+ <dir>/merge_stats.json);
           2x2 tiles: stitch seam-cut pieces first, then dedupe
  overlay  labels.jsonl -> one PNG per image
  compare  two labels.jsonl -> markdown numbers + side-by-side overlays
  cost     label_one ledger.tsv -> per-call and per-image cost tables (markdown on stdout)
  qa-make  round-1 labels + overlays -> <work>/{in,img,overlay}/ and one QA batch per image (size 1)
  qa-summary  QA verdicts -> markdown counts (ok / fix / reject, issue totals and per-image medians)
  pending  batches whose JSON outputs are not all written yet (prints batch names)
  fix-make round-1 labels + QA verdicts -> one fix batch per image whose verdict is fix
  finalize round-1 labels, replaced by fix outputs where present -> labels_final.jsonl
  export   labels_final.jsonl -> YOLO export (all + per platform) and exam_gold_v1.jsonl
"""
import argparse
import ast
import collections
import glob
import json
import math
import os
import statistics
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ULF = os.path.join(HERE, "ulf.py")

TILE_FRAC = 0.56        # tile = ceil(W*0.56) x ceil(H*0.56), 2x2 grid, ~12 % overlap
TILE_EDGE_PX = 3.0      # stitch: a piece lies against an inner seam = within 3 px
DUP_TOUCH_PX = 8.0      # dedupe rules 1 / 2: "touches an inner cut" = within 8 px (a model often stops a few px short of the seam)
TILE_MATCH_IOU = 0.3    # merge rule 2: counterpart IoU threshold
DUP_IOU = 0.5           # merge rule 1: same-class duplicate IoU threshold
OVERLAY_LONG = 1800

# 16 colours; index 15 (other:visible) is magenta and drawn dashed (DASH_CLS), so it never looks like a solid class box.
PALETTE = [
    (230, 25, 75), (60, 180, 75), (255, 225, 25), (0, 130, 200),
    (245, 130, 48), (145, 30, 180), (70, 240, 240), (240, 50, 230),
    (210, 245, 60), (0, 128, 128), (250, 190, 212), (220, 190, 255),
    (170, 110, 40), (0, 0, 128), (255, 20, 147), (255, 0, 255),
]
DASH_CLS, DASH_ON, DASH_OFF = 15, 6, 4


def class_names():
    """CLASS_NAMES from ulf.py, read by AST so this file does not import ulf (cv2 etc.)."""
    tree = ast.parse(open(ULF, encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "CLASS_NAMES" for t in node.targets):
            names = list(ast.literal_eval(node.value))
            assert len(names) == 16, names
            return names
    raise SystemExit("CLASS_NAMES not found in " + ULF)


CLASS_NAMES = class_names()


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_manifest(path):
    return {r["gid"]: r for r in read_jsonl(path)}


def ui_scale(pool, width):
    if pool in ("sspro_win", "sspro_mac"):
        return 2 if width >= 3000 else (1.5 if width >= 2400 else 1)
    if pool == "s2ax_mac":
        return 2
    return 1


def tile_origins(W, H):
    """Tile size and top-left origins in the order k = 0 TL, 1 TR, 2 BL, 3 BR."""
    tw = math.ceil(W * TILE_FRAC)
    th = math.ceil(H * TILE_FRAC)
    return tw, th, [(0, 0), (W - tw, 0), (0, H - th), (W - tw, H - th)]


# ---------------------------------------------------------------- frames
def cmd_frames(a):
    man = load_manifest(a.manifest)
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    if a.mode == "tile":
        os.makedirs(os.path.join(out, "tiles"), exist_ok=True)
    rows = []
    for gid in [g for g in a.gids.split(",") if g]:
        if gid not in man:
            raise SystemExit(f"gid not in manifest: {gid}")
        r = man[gid]
        with Image.open(r["image"]) as im:
            W, H = im.size
            if (W, H) != (r["width"], r["height"]):
                print(f"WARN {gid}: manifest {r['width']}x{r['height']} != file {W}x{H}; using file",
                      file=sys.stderr)
            base = f"UI scale {ui_scale(r['pool'], W)}; app {r.get('application') or 'unknown'}"
            if a.mode == "whole":
                rows.append({"stem": gid, "image": r["image"], "w": W, "h": H, "hint": base})
                continue
            tw, th, origins = tile_origins(W, H)
            for k, (ox, oy) in enumerate(origins):
                stem = f"{gid}__t{k}"
                path = os.path.join(out, "tiles", stem + ".png")
                im.crop((ox, oy, ox + tw, oy + th)).save(path)
                hint = (base + f"; this is tile {k + 1} of 4 (offset x={ox}, y={oy}) of a {W}x{H} "
                        "screenshot — label only what is in this tile, boxes in tile coordinates")
                rows.append({"stem": stem, "image": path, "w": tw, "h": th, "hint": hint})
    with open(os.path.join(out, "frames.jsonl"), "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"{len(rows)} frames ({a.mode}) -> {out}/frames.jsonl")


# ---------------------------------------------------------------- merge
def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    if inter <= 0:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (area_a + area_b - inter)


def read_elements(path, cw, ch, stats):
    """Parse one label_one JSON. Clip to the (cw, ch) frame; drop unknown cls and zero-area boxes."""
    data = json.load(open(path, encoding="utf-8"))
    out = []
    for e in data.get("elements", []):
        cls = e.get("cls")
        if cls not in CLASS_NAMES:
            stats["unknown_cls"] += 1
            continue
        try:
            x1, y1, x2, y2 = (float(v) for v in e["box"])
        except (KeyError, TypeError, ValueError):
            stats["bad_box"] += 1
            continue
        x1, x2 = sorted((x1, x2))
        y1, y2 = sorted((y1, y2))
        x1, x2 = min(max(x1, 0.0), cw), min(max(x2, 0.0), cw)
        y1, y2 = min(max(y1, 0.0), ch), min(max(y2, 0.0), ch)
        if x2 - x1 <= 0 or y2 - y1 <= 0:
            stats["zero_area"] += 1
            continue
        out.append({"cls": CLASS_NAMES.index(cls), "box": [x1, y1, x2, y2],
                    "kind": e.get("kind", "leaf"), "name": e.get("name", ""),
                    "name_source": e.get("name_source", "")})
    return out


def cut_lines(W, H, tw, th, ox, oy):
    """Inner cut lines of one tile: a side is inner when another tile overlaps it."""
    cuts = []
    if ox > 0:
        cuts.append(("x", ox))
    if ox + tw < W:
        cuts.append(("x", ox + tw))
    if oy > 0:
        cuts.append(("y", oy))
    if oy + th < H:
        cuts.append(("y", oy + th))
    return cuts


def touches_cut(box, cuts, tol=TILE_EDGE_PX):
    x1, y1, x2, y2 = box
    for ax, e in cuts:
        if ax == "x" and min(abs(x1 - e), abs(x2 - e)) <= tol:
            return True
        if ax == "y" and min(abs(y1 - e), abs(y2 - e)) <= tol:
            return True
    return False


def cut_distance(box, cuts):
    """Distance from the box centre to the nearest inner cut line of its own tile."""
    cx = (box[0] + box[2]) / 2
    cy = (box[1] + box[3]) / 2
    return min(abs((cx if ax == "x" else cy) - e) for ax, e in cuts)


STITCH_OVERLAP = 0.6    # stitch: other-axis overlap >= 60 % of the shorter piece
STITCH_GAP_PX = 3.0     # stitch: overlap or gap <= 3 px along the seam axis


def seam_sides(box, W, H, tw, th, ox, oy):
    """Inner seam sides ('L', 'R', 'T', 'B') that a piece of one tile lies against (<= 3 px).

    'R' = the piece's right edge sits on the tile's inner right edge (another tile overlaps it);
    'L' / 'T' / 'B' likewise for the left / top / bottom edge. Outer edges of the image never count.
    """
    x1, y1, x2, y2 = box
    sides = set()
    if ox + tw < W and abs(x2 - (ox + tw)) <= TILE_EDGE_PX:
        sides.add("R")
    if ox > 0 and abs(x1 - ox) <= TILE_EDGE_PX:
        sides.add("L")
    if oy + th < H and abs(y2 - (oy + th)) <= TILE_EDGE_PX:
        sides.add("B")
    if oy > 0 and abs(y1 - oy) <= TILE_EDGE_PX:
        sides.add("T")
    return frozenset(sides)


def stitch_pair(a, b):
    """Union of two pieces of one element cut by a seam, or None.

    Candidates are dicts with cls, box, ks (tile set), seams, name, name_source, kind, d, touch.
    Stitch when: same cls; disjoint tile sets; one piece lies against the inner right seam ('R')
    and the other against the inner left seam ('L') (or 'B' / 'T' for a horizontal seam); their
    overlap on the other axis is >= 60 % of the shorter piece; and along the seam axis they overlap
    or leave a gap <= 3 px.
    """
    if a["cls"] != b["cls"] or (a["ks"] & b["ks"]):
        return None
    for p, q in ((a, b), (b, a)):
        for s_out, s_in, seam_axis in (("R", "L", "x"), ("B", "T", "y")):
            if s_out not in p["seams"] or s_in not in q["seams"]:
                continue
            i1, i2 = (0, 2) if seam_axis == "x" else (1, 3)     # seam-axis indices
            o1, o2 = (1, 3) if seam_axis == "x" else (0, 2)     # other-axis indices
            pb, qb = p["box"], q["box"]
            overlap = min(pb[o2], qb[o2]) - max(pb[o1], qb[o1])
            shorter = min(pb[o2] - pb[o1], qb[o2] - qb[o1])
            if overlap < STITCH_OVERLAP * shorter:
                continue
            gap = max(pb[i1], qb[i1]) - min(pb[i2], qb[i2])     # <= 0 means they overlap
            if gap > STITCH_GAP_PX:
                continue
            longer = p if len(p["name"]) >= len(q["name"]) else q
            box = [min(pb[0], qb[0]), min(pb[1], qb[1]), max(pb[2], qb[2]), max(pb[3], qb[3])]
            seams = (p["seams"] - {s_out}) | (q["seams"] - {s_in})   # consumed seam is now interior
            return {"cls": p["cls"], "box": box, "kind": longer["kind"], "name": longer["name"],
                    "name_source": longer["name_source"], "ks": p["ks"] | q["ks"], "seams": seams,
                    "touch": bool(seams), "d": max(p["d"], q["d"]), "alive": True}
    return None


def stitch(cands):
    """Repeatedly stitch cut pieces until no pair matches (four-way crossings need two rounds).

    Returns (candidates, n_stitched). Input dicts are not mutated; consumed pieces get alive=False.
    """
    cur = [dict(c) for c in cands]
    count = 0
    changed = True
    while changed:
        changed = False
        for i in range(len(cur)):
            a = cur[i]
            if not a["alive"] or not a["seams"]:
                continue
            for j in range(i + 1, len(cur)):
                b = cur[j]
                if not b["alive"] or not b["seams"]:
                    continue
                m = stitch_pair(a, b)
                if m is None:
                    continue
                a["alive"] = False
                b["alive"] = False
                cur.append(m)
                count += 1
                changed = True
                break
    return cur, count


def resolve_dup(a, b, stats):
    """Decide which of two same-class pieces from different tiles survives; returns (winner, loser).

    Exactly one touches an inner cut -> the other one survives (it is complete inside its own tile).
    Both touch -> the d-winner survives with the union box of both (name: the longer one).
    Neither touches -> a stitched union (pieces from several tiles) beats a single-tile piece; otherwise the one
    farther from its cut lines survives (a tie keeps a).
    """
    by_d = (b, a) if a["d"] < b["d"] else (a, b)
    if not a["touch"] and not b["touch"] and (len(a["ks"]) > 1) != (len(b["ks"]) > 1):
        return (a, b) if len(a["ks"]) > 1 else (b, a)
    if a["touch"] != b["touch"]:
        win, lose = (b, a) if a["touch"] else (a, b)
        if win is not by_d[0]:
            stats["kept_untouched"] += 1
        return win, lose
    win, lose = by_d
    if a["touch"]:
        win["box"] = [min(a["box"][0], b["box"][0]), min(a["box"][1], b["box"][1]),
                      max(a["box"][2], b["box"][2]), max(a["box"][3], b["box"][3])]
        longer = a if len(a["name"]) >= len(b["name"]) else b
        win["name"], win["name_source"] = longer["name"], longer["name_source"]
        stats["union_seam"] += 1
    return win, lose


def merge_tiles(W, H, paths, stats):
    tw, th, origins = tile_origins(W, H)
    cands = []
    for k, (ox, oy) in enumerate(origins):
        cuts = cut_lines(W, H, tw, th, ox, oy)
        for el in read_elements(paths[k], tw, th, stats):
            x1, y1, x2, y2 = el["box"]
            g = [x1 + ox, y1 + oy, x2 + ox, y2 + oy]
            cands.append({"cls": el["cls"], "box": g, "kind": el["kind"],
                          "name": el["name"], "name_source": el["name_source"],
                          "ks": frozenset([k]), "seams": seam_sides(g, W, H, tw, th, ox, oy),
                          "d": cut_distance(g, cuts), "touch": touches_cut(g, cuts, DUP_TOUCH_PX), "alive": True})
    # Stitch: a wide element cut by a seam appears as two overlapping pieces, one per tile.
    cands, n_stitched = stitch(cands)
    stats["stitched"] += n_stitched
    cands = [c for c in cands if c["alive"]]
    n = len(cands)
    # Rule 1: same class, IoU >= 0.5, different tiles -> keep one (resolve_dup: the complete one, else the union).
    pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            a, b = cands[i], cands[j]
            if (a["ks"] & b["ks"]) or a["cls"] != b["cls"]:
                continue
            v = iou(a["box"], b["box"])
            if v >= DUP_IOU:
                pairs.append((v, i, j))
    pairs.sort(key=lambda p: -p[0])
    for _, i, j in pairs:
        a, b = cands[i], cands[j]
        if not (a["alive"] and b["alive"]):
            continue
        _, loser = resolve_dup(a, b, stats)
        loser["alive"] = False
        stats["dup_rule1"] += 1
    # Rule 2: a box touching an inner cut (<= 3 px) whose other-tile same-class counterpart
    # (IoU >= 0.3) exists is dropped. If the counterpart also touches, resolve_dup keeps one with the union box.
    for i in range(n):
        a = cands[i]
        if not a["alive"] or not a["touch"]:
            continue
        matches = [j for j in range(n) if j != i and cands[j]["alive"]
                   and not (cands[j]["ks"] & a["ks"]) and cands[j]["cls"] == a["cls"]
                   and iou(a["box"], cands[j]["box"]) >= TILE_MATCH_IOU]
        if not matches:
            continue
        if any(not cands[j]["touch"] for j in matches):
            a["alive"] = False
        else:
            j = max(matches, key=lambda j: iou(a["box"], cands[j]["box"]))
            _, loser = resolve_dup(a, cands[j], stats)
            loser["alive"] = False
        stats["edge_rule2"] += 1
    return [{"cls": c["cls"], "box": [round(v, 2) for v in c["box"]], "kind": c["kind"],
             "name": c["name"], "name_source": c["name_source"]} for c in cands if c["alive"]]


def cmd_merge(a):
    man = load_manifest(a.manifest)
    d = os.path.abspath(a.dir)
    stems = [r["stem"] for r in read_jsonl(os.path.join(d, "frames.jsonl"))]
    mode = "tile" if any("__t" in s for s in stems) else "whole"
    gids = list(dict.fromkeys(s.split("__t")[0] for s in stems))
    jdir = os.path.join(d, "work", "json")
    records, missing = [], []
    totals = collections.Counter()
    per_gid = {}
    for gid in gids:
        row = man[gid]
        W, H = row["width"], row["height"]
        st = collections.Counter({"unknown_cls": 0, "bad_box": 0, "zero_area": 0,
                                  "stitched": 0, "dup_rule1": 0, "edge_rule2": 0,
                                  "union_seam": 0, "kept_untouched": 0})
        if mode == "whole":
            paths = [os.path.join(jdir, gid + ".json")]
        else:
            paths = [os.path.join(jdir, f"{gid}__t{k}.json") for k in range(4)]
        absent = [p for p in paths if not os.path.exists(p)]
        if absent:
            missing.append({"gid": gid, "missing": [os.path.basename(p) for p in absent]})
            continue
        if mode == "whole":
            boxes = read_elements(paths[0], W, H, st)
        else:
            boxes = merge_tiles(W, H, paths, st)
        totals.update(st)
        per_gid[gid] = dict(st, boxes=len(boxes))
        records.append({"gid": gid, "image": row["image"], "width": W, "height": H,
                        "mode": mode, "boxes": boxes})
    with open(os.path.join(d, "labels.jsonl"), "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    with open(os.path.join(d, "merge_stats.json"), "w", encoding="utf-8") as f:
        json.dump({"mode": mode, "totals": dict(totals), "per_gid": per_gid, "missing": missing},
                  f, indent=1, ensure_ascii=False)
    print(f"{mode}: {len(records)} records -> {d}/labels.jsonl; missing={len(missing)}; "
          f"totals={dict(totals)}")
    for rec in records:
        print(f"  {rec['gid']}: {len(rec['boxes'])} boxes")
    for m in missing:
        print(f"  MISSING {m['gid']}: {m['missing']}", file=sys.stderr)


# ---------------------------------------------------------------- overlay
def font(size):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/usr/share/fonts/TTF/DejaVuSans.ttf"):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def wrap_chars(draw, text, f, width):
    """Split text into lines of at most `width` px, breaking between characters."""
    lines, cur = [], ""
    for ch in text:
        if cur and draw.textlength(cur + ch, font=f) > width:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    lines.append(cur)
    return lines


def dashed_rect(draw, box, color, width=2, on=DASH_ON, off=DASH_OFF):
    """Rectangle outline drawn as dashes (on px painted, off px gap) running along each edge from its start corner."""
    x1, y1, x2, y2 = box
    for (ax, ay), (bx, by) in (((x1, y1), (x2, y1)), ((x2, y1), (x2, y2)), ((x2, y2), (x1, y2)), ((x1, y2), (x1, y1))):
        length = max(abs(bx - ax), abs(by - ay))
        if length <= 0:
            continue
        ux, uy = (bx - ax) / length, (by - ay) / length
        t = 0.0
        while t < length:
            e = min(t + on, length)
            draw.line([(ax + ux * t, ay + uy * t), (ax + ux * e, ay + uy * e)], fill=color, width=width)
            t += on + off


def render(rec, max_long=OVERLAY_LONG):
    """Screenshot (scaled to max_long) with the boxes drawn on it and nothing else inside it.
    Caption (gid / mode / boxes) and the class legend go in a white panel to the right,
    outside the screenshot, so they never hide UI. Returns the new canvas."""
    im = Image.open(rec["image"]).convert("RGB")
    W, H = im.size
    s = min(1.0, max_long / max(W, H))
    if s < 1.0:
        im = im.resize((round(W * s), round(H * s)), Image.LANCZOS)
    w, h = im.size
    draw = ImageDraw.Draw(im)
    for b in rec["boxes"]:
        x1, y1, x2, y2 = (v * s for v in b["box"])
        if b["cls"] == DASH_CLS:
            dashed_rect(draw, (x1, y1, x2, y2), PALETTE[DASH_CLS])
        else:
            draw.rectangle([x1, y1, x2, y2], outline=PALETTE[b["cls"]], width=2)
    fs = max(12, w // 110)
    f = font(fs)
    row = fs + 6
    pad = 10
    name_w = max(int(draw.textlength(n, font=f)) for n in CLASS_NAMES)
    P = max(name_w + fs + 2 * pad + 6, 260)
    inner = P - 2 * pad
    title = wrap_chars(draw, rec["gid"], f, inner)
    title += [f"mode={rec['mode']}", f"boxes={len(rec['boxes'])}"]
    panel_h = pad + len(title) * row + row + len(CLASS_NAMES) * row + pad
    canvas = Image.new("RGB", (w + P, max(h, panel_h)), (255, 255, 255))
    canvas.paste(im, (0, 0))
    d = ImageDraw.Draw(canvas)
    x0, y = w + pad, pad
    for line in title:
        d.text((x0, y), line, font=f, fill=(0, 0, 0))
        y += row
    y += row  # blank line between caption and legend
    for i, n in enumerate(CLASS_NAMES):
        if i == DASH_CLS:   # dashed sample, same dash / gap as the boxes
            dashed_rect(d, (x0, y + 2, x0 + fs - 2, y + fs), PALETTE[i])
        else:
            d.rectangle([x0, y + 2, x0 + fs - 2, y + fs], fill=PALETTE[i])
        d.text((x0 + fs + 4, y), n, font=f, fill=(0, 0, 0))
        y += row
    return canvas


def cmd_overlay(a):
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    for rec in read_jsonl(a.labels):
        path = os.path.join(out, f"{rec['gid']}__{rec['mode']}.png")
        render(rec).save(path)
        print(path)


# ---------------------------------------------------------------- compare
def match_greedy(boxes_a, boxes_b):
    """One-to-one greedy matching by IoU, descending, class-agnostic. Returns (iou, i, j)."""
    pairs = []
    for i, a in enumerate(boxes_a):
        for j, b in enumerate(boxes_b):
            v = iou(a["box"], b["box"])
            if v > 0:
                pairs.append((v, i, j))
    pairs.sort(key=lambda p: -p[0])
    ua, ub, out = set(), set(), []
    for v, i, j in pairs:
        if i in ua or j in ub:
            continue
        ua.add(i)
        ub.add(j)
        out.append((v, i, j))
    return out


def cmd_compare(a):
    A = {r["gid"]: r for r in read_jsonl(a.a)}
    B = {r["gid"]: r for r in read_jsonl(a.b)}
    gids = [g for g in A if g in B]
    side_dir = os.path.splitext(os.path.abspath(a.out))[0] + "_side"
    os.makedirs(side_dir, exist_ok=True)
    rows = []
    tot = collections.Counter()
    sum_iou = 0.0
    for gid in gids:
        ra, rb = A[gid], B[gid]
        na, nb = len(ra["boxes"]), len(rb["boxes"])
        good = [(v, i, j) for v, i, j in match_greedy(ra["boxes"], rb["boxes"]) if v >= 0.5]
        cls_eq = sum(1 for _, i, j in good if ra["boxes"][i]["cls"] == rb["boxes"][j]["cls"])
        hi = sum(1 for v, _, _ in good if v >= 0.8)
        mean_iou = sum(v for v, _, _ in good) / len(good) if good else float("nan")
        denom = max(na, nb)
        rows.append({"gid": gid, "na": na, "nb": nb, "match": len(good), "denom": denom,
                     "cls_eq": cls_eq, "mean_iou": mean_iou, "hi": hi})
        tot["na"] += na
        tot["nb"] += nb
        tot["match"] += len(good)
        tot["denom"] += denom
        tot["cls_eq"] += cls_eq
        tot["hi"] += hi
        sum_iou += sum(v for v, _, _ in good)
        pa, pb = render(ra, max_long=1200), render(rb, max_long=1200)
        canvas = Image.new("RGB", (pa.width + pb.width + 16, max(pa.height, pb.height)), (255, 255, 255))
        canvas.paste(pa, (0, 0))
        canvas.paste(pb, (pa.width + 16, 0))
        canvas.save(os.path.join(side_dir, f"{gid}.png"))

    def pct(x, y):
        return f"{x / y:.3f}" if y else "–"

    lines = [f"# compare: {os.path.abspath(a.a)} (left) vs {os.path.abspath(a.b)} (right)", "",
             "Matching: class-agnostic, greedy one-to-one by IoU from largest to smallest; a match is a pair with IoU ≥ 0.5; "
             "match rate = matches / max(boxes in A, boxes in B); same-class rate, mean IoU and the share with IoU ≥ 0.8 use matched pairs only.", "",
             "| gid | boxes A | boxes B | matches (IoU≥0.5) | match rate | same-class rate | mean IoU of matches | share with IoU≥0.8 | side by side |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        mi = f"{r['mean_iou']:.3f}" if r["match"] else "–"
        lines.append(f"| {r['gid']} | {r['na']} | {r['nb']} | {r['match']} | {pct(r['match'], r['denom'])} | "
                     f"{pct(r['cls_eq'], r['match'])} | {mi} | {pct(r['hi'], r['match'])} | "
                     f"{os.path.join(side_dir, r['gid'] + '.png')} |")
    mean_total = f"{sum_iou / tot['match']:.3f}" if tot["match"] else "–"
    lines.append(f"| **total** | {tot['na']} | {tot['nb']} | {tot['match']} | {pct(tot['match'], tot['denom'])} | "
                 f"{pct(tot['cls_eq'], tot['match'])} | {mean_total} | {pct(tot['hi'], tot['match'])} | – |")
    text = "\n".join(lines) + "\n"
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(text)
    print(text)


# ---------------------------------------------------------------- cost
def cmd_cost(a):
    calls, per_img = [], collections.OrderedDict()
    for work in a.work:
        work = os.path.abspath(work)
        tag = os.path.basename(os.path.dirname(work))
        with open(os.path.join(work, "ledger.tsv"), encoding="utf-8") as f:
            rows = [line.rstrip("\n").split("\t") for line in f if line.strip()]
        head = rows[0]
        for row in rows[1:]:
            r = dict(zip(head, row))
            stems = json.load(open(os.path.join(work, "batches", r["batch"] + ".json")))
            gid = stems[0].split("__t")[0]
            c = {"run": tag, "batch": r["batch"], "stems": ",".join(stems), "status": r["status"],
                 "json": int(r["json_written"]), "sec": int(float(r["seconds"])),
                 "input": int(r["input"]), "cache_write": int(r["cache_write"]),
                 "cache_read": int(r["cache_read"]), "output": int(r["output"]),
                 "thinking": int(r["thinking"]), "usd": float(r["api_equiv_usd"])}
            calls.append(c)
            g = per_img.setdefault((tag, gid), collections.Counter())
            g["calls"] += 1
            for key in ("json", "sec", "input", "cache_write", "cache_read", "output", "thinking"):
                g[key] += c[key]
            g["usd"] += c["usd"]
    print("## Per call")
    print("| run | batch | stems | status | json | sec | input | cache_write | cache_read | output | thinking | api_equiv_usd |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for c in calls:
        print(f"| {c['run']} | {c['batch']} | {c['stems']} | {c['status']} | {c['json']} | {c['sec']} | "
              f"{c['input']} | {c['cache_write']} | {c['cache_read']} | {c['output']} | {c['thinking']} | "
              f"{c['usd']:.4f} |")
    print("\n## Per image (sum of the 4 tiles)")
    print("| run | gid | calls | json | sec | input | cache_write | cache_read | output | thinking | api_equiv_usd |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for (tag, gid), g in per_img.items():
        print(f"| {tag} | {gid} | {g['calls']} | {g['json']} | {g['sec']} | {g['input']} | "
              f"{g['cache_write']} | {g['cache_read']} | {g['output']} | {g['thinking']} | {g['usd']:.4f} |")


# ---------------------------------------------------------------- W4 post: qa / fix / finalize / export
RULES_DIR = os.path.join(HERE, "prompts")
MANIFEST_DEFAULT = os.path.join("data", "gold_candidates", "manifest.jsonl")
QA_KEYS = ("verdict", "n_missing", "n_geometry", "n_class", "n_forbidden", "notes")
ISSUE_KEYS = ("n_missing", "n_geometry", "n_class", "n_forbidden")
ISSUE_LABELS = {"n_missing": "missing label", "n_geometry": "geometry",
                "n_class": "class", "n_forbidden": "forbidden box"}
LOOK_ONLY = ("Look-only: use Read to view files and Write to save JSON. "
             "Do not run code and do not open any other file.")


def rules_path(name):
    p = os.path.abspath(os.path.join(RULES_DIR, name))
    if not os.path.exists(p):
        raise SystemExit(f"rules file not found: {p}")
    return p


def relink(src, dst):
    if os.path.lexists(dst):
        os.remove(dst)
    os.symlink(src, dst)


def overlay_for(odir, gid):
    hits = sorted(glob.glob(os.path.join(glob.escape(odir), glob.escape(gid) + "__*.png")))
    if len(hits) != 1:
        raise SystemExit(f"overlay for {gid} in {odir}: expected 1 file, found {len(hits)}")
    return hits[0]


def rule_json(rec):
    """labels.jsonl record (int cls) -> rule-format label JSON with class names (label_one format)."""
    return {"image": os.path.basename(rec["image"]), "width": rec["width"], "height": rec["height"],
            "elements": [{"cls": CLASS_NAMES[b["cls"]], "box": b["box"], "kind": b["kind"],
                          "name": b["name"], "name_source": b["name_source"]} for b in rec["boxes"]]}


def ensure_dirs(work, names):
    for d in names:
        os.makedirs(os.path.join(work, d), exist_ok=True)


def done_gids(work):
    jd = os.path.join(work, "json")
    if not os.path.isdir(jd):
        return set()
    return {f[:-5] for f in os.listdir(jd) if f.endswith(".json")}


def queued_gids(work):
    bd = os.path.join(work, "batches")
    out = set()
    if os.path.isdir(bd):
        for f in os.listdir(bd):
            if f.endswith(".json"):
                with open(os.path.join(bd, f), encoding="utf-8") as fh:
                    out.update(json.load(fh))
    return out


def next_index(work):
    bd = os.path.join(work, "batches")
    return len([f for f in os.listdir(bd) if f.endswith(".md")])


def write_batch(work, stems, text):
    """Same batch layout as label_one.py make: batches/batch_NNN.md + batch_NNN.json (stem list)."""
    name = f"batch_{next_index(work):03d}"
    bd = os.path.join(work, "batches")
    with open(os.path.join(bd, name + ".md"), "w", encoding="utf-8") as f:
        f.write(text)
    with open(os.path.join(bd, name + ".json"), "w", encoding="utf-8") as f:
        json.dump(stems, f)
    return name


def read_gid_list(path):
    """--only file: one gid per line (blank lines ignored); None when not given."""
    if not path:
        return None
    with open(path, encoding="utf-8") as f:
        return {l.strip() for l in f if l.strip()}


def read_extra_notes(path):
    """--extra-notes jsonl: one {"gid", "note"} per line -> {gid: [note, ...]}."""
    out = collections.defaultdict(list)
    if path:
        for r in read_jsonl(path):
            out[r["gid"]].append(r["note"])
    return out


def cmd_qa_make(a):
    man = load_manifest(a.manifest)
    W = os.path.abspath(a.work)
    ensure_dirs(W, ["img", "overlay", "in", "json", "batches", "logs"])
    rules = rules_path(a.rules)
    only = read_gid_list(a.only)
    skip = done_gids(W) | queued_gids(W)
    made = 0
    for rec in read_jsonl(a.labels):
        gid = rec["gid"]
        if gid in skip or (only is not None and gid not in only):
            continue
        img = os.path.join(W, "img", gid + os.path.splitext(rec["image"])[1])
        ov = os.path.join(W, "overlay", gid + ".png")
        lab = os.path.join(W, "in", gid + ".json")
        relink(os.path.abspath(rec["image"]), img)
        relink(overlay_for(a.overlay_dir, gid), ov)
        with open(lab, "w", encoding="utf-8") as f:
            json.dump(rule_json(rec), f, ensure_ascii=False, indent=1)
        scale = ui_scale(man[gid]["pool"], rec["width"])
        text = (f"Read the review rules in {rules} and follow them.\n\n"
                f"{LOOK_ONLY}\n\n"
                "Images (review each):\n"
                f"- screenshot {img}; overlay {ov}; label JSON {lab}; UI scale {scale}; "
                f"write your verdict JSON to {W}/json/{gid}.json\n\n"
                "Final reply: one line per image with the verdict. Nothing else.\n")
        write_batch(W, [gid], text)
        made += 1
    print(f"qa-make: {made} new batch(es) -> {W}/batches")


def cmd_pending(a):
    W = os.path.abspath(a.work)
    done = done_gids(W)
    bd = os.path.join(W, "batches")
    for f in sorted(os.listdir(bd)):
        if f.endswith(".json"):
            with open(os.path.join(bd, f), encoding="utf-8") as fh:
                stems = json.load(fh)
            if not all(s in done for s in stems):
                print(f[:-5])


def cmd_qa_summary(a):
    W = os.path.abspath(a.work)
    gids = sorted(f[:-5] for f in os.listdir(os.path.join(W, "in")) if f.endswith(".json"))
    rows, missing = [], []
    for gid in gids:
        p = os.path.join(W, "json", gid + ".json")
        if not os.path.exists(p):
            missing.append(gid)
            continue
        with open(p, encoding="utf-8") as f:
            v = json.load(f)
        rows.append({"gid": gid, "verdict": v.get("verdict"),
                     **{k: v.get(k) for k in ISSUE_KEYS}, "reason": v.get("reason"),
                     "absent": [k for k in QA_KEYS if k not in v]})
    ok = [r["gid"] for r in rows if r["verdict"] == "ok"]
    fix = [r["gid"] for r in rows if r["verdict"] == "fix"]
    reject = [r["gid"] for r in rows if r["verdict"] == "reject"]
    bad = [r["gid"] for r in rows if r["verdict"] not in ("ok", "fix", "reject")]
    incomplete = [r["gid"] for r in rows if r["absent"]]
    lines = [f"# QA summary: {W}", "",
             f"- images: {len(gids)}; verdict ok: {len(ok)}; verdict fix: {len(fix)}; verdict reject: {len(reject)}; "
             f"no verdict file: {len(missing)}{' ' + ', '.join(missing) if missing else ''}; "
             f"invalid verdict: {len(bad)}; incomplete JSON: {len(incomplete)}",
             "", "| category | total | median per image |", "|---|---|---|"]
    per_img_total = [sum(r[k] or 0 for k in ISSUE_KEYS) for r in rows]
    for k in ISSUE_KEYS:
        vals = [r[k] or 0 for r in rows]
        med = statistics.median(vals) if vals else "–"
        lines.append(f"| {ISSUE_LABELS[k]} | {sum(vals)} | {med} |")
    med_total = statistics.median(per_img_total) if per_img_total else "–"
    lines.append(f"| total | {sum(per_img_total)} | {med_total} |")
    lines += ["", "| gid | verdict | missing | geometry | class | forbidden | missing field | reason |",
              "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['gid']} | {r['verdict']} | {r['n_missing']} | {r['n_geometry']} | "
                     f"{r['n_class']} | {r['n_forbidden']} | {','.join(r['absent']) or '–'} | "
                     f"{str(r['reason']).replace('|', '/') if r['reason'] else '–'} |")
    lines += ["", f"fix gids: {', '.join(fix) if fix else 'none'}",
              f"reject gids: {', '.join(reject) if reject else 'none'}", ""]
    text = "\n".join(lines)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(text)
    print(text)


def cmd_fix_make(a):
    man = load_manifest(a.manifest)
    W = os.path.abspath(a.work)
    Q = os.path.abspath(a.qa)
    ensure_dirs(W, ["img", "json", "batches", "logs"])
    rules = rules_path(a.rules)
    only = read_gid_list(a.only)
    extra = read_extra_notes(a.extra_notes)
    skip = done_gids(W) | queued_gids(W)
    made = fix_n = 0
    for rec in read_jsonl(a.labels):
        gid = rec["gid"]
        if only is not None and gid not in only:
            continue
        vp = os.path.join(Q, "json", gid + ".json")
        verdict = None
        if os.path.exists(vp):
            with open(vp, encoding="utf-8") as f:
                verdict = json.load(f)
        if (verdict or {}).get("verdict") != "fix" and gid not in extra:
            continue
        if gid in extra:
            # reviewer notes = QA verdict (when there is one) with the extra notes appended; else a minimal verdict
            nv = dict(verdict) if verdict else {"gid": gid, "verdict": "fix", "reason": "extra reviewer notes"}
            if nv.get("verdict") != "fix":
                nv["reason"] = f"extra reviewer notes (QA verdict was {nv.get('verdict')})"
            nv["verdict"] = "fix"
            nv["notes"] = list(nv.get("notes") or []) + [
                {"type": "extra", "index": None, "cls": "", "box": None, "note": n} for n in extra[gid]]
            os.makedirs(os.path.join(W, "notes"), exist_ok=True)
            vp = os.path.join(W, "notes", gid + ".json")
            with open(vp, "w", encoding="utf-8") as f:
                json.dump(nv, f, ensure_ascii=False, indent=1)
        fix_n += 1
        if gid in skip:
            continue
        img = os.path.join(W, "img", gid + os.path.splitext(rec["image"])[1])
        # the current label always comes from --labels (it may have been rewritten after QA ran, e.g. the seam union)
        cur = os.path.join(W, "current", gid + ".json")
        os.makedirs(os.path.dirname(cur), exist_ok=True)
        with open(cur, "w", encoding="utf-8") as f:
            json.dump(rule_json(rec), f, ensure_ascii=False, indent=1)
        relink(os.path.abspath(rec["image"]), img)
        scale = ui_scale(man[gid]["pool"], rec["width"])
        text = (f"Read the correction rules in {rules} and follow them.\n\n"
                f"{LOOK_ONLY}\n\n"
                "Images (correct each):\n"
                f"- screenshot {img}; current label JSON {cur}; reviewer notes JSON {vp}; UI scale {scale}; "
                f"write the corrected complete label JSON to {W}/json/{gid}.json\n\n"
                "Final reply: one line per image with its element count. Nothing else.\n")
        write_batch(W, [gid], text)
        made += 1
    print(f"fix-make: {fix_n} image(s) with verdict fix; {made} new batch(es) -> {W}/batches")


def cmd_finalize(a):
    fx = os.path.abspath(a.fix)
    out, n2 = [], 0
    stats = collections.Counter({"unknown_cls": 0, "bad_box": 0, "zero_area": 0})
    for rec in read_jsonl(a.round1):
        r = dict(rec)
        p = os.path.join(fx, "json", rec["gid"] + ".json")
        if os.path.exists(p):
            r["boxes"] = read_elements(p, rec["width"], rec["height"], stats)
            r["round"] = 2
            n2 += 1
        else:
            r["round"] = 1
        out.append(r)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"finalize: {len(out)} images ({n2} from fix pass, {len(out) - n2} from round 1) -> {a.out}; "
          f"stats={dict(stats)}")


def cmd_export(a):
    man = load_manifest(a.manifest)
    E = os.path.abspath(a.out)
    recs = read_jsonl(a.labels)
    plats = sorted({man[r["gid"]]["platform"] for r in recs})
    pool_dirs = sorted({"pool_" + man[r["gid"]]["pool"] for r in recs})
    tier_dirs = sorted({"tier_" + man[r["gid"]]["tier"] for r in recs if man[r["gid"]].get("tier")})
    for sub in ["all"] + plats + pool_dirs + tier_dirs:
        ensure_dirs(os.path.join(E, sub), ["images", "labels"])
    rows = []
    for rec in recs:
        gid = rec["gid"]
        m = man[gid]
        plat = m["platform"]
        W, H = rec["width"], rec["height"]
        src = os.path.abspath(rec["image"])
        ext = os.path.splitext(src)[1].lower()
        lines = []
        for b in rec["boxes"]:
            x1, y1, x2, y2 = b["box"]
            vals = [(x1 + x2) / 2 / W, (y1 + y2) / 2 / H, (x2 - x1) / W, (y2 - y1) / H]
            vals = [min(max(v, 0.0), 1.0) for v in vals]
            lines.append(f"{b['cls']} " + " ".join(f"{v:.6f}" for v in vals))
        lab_all = os.path.join(E, "all", "labels", gid + ".txt")
        with open(lab_all, "w", encoding="utf-8") as f:
            f.write("".join(line + "\n" for line in lines))
        relink(src, os.path.join(E, "all", "images", gid + ext))
        relink(src, os.path.join(E, plat, "images", gid + ext))
        relink(lab_all, os.path.join(E, plat, "labels", gid + ".txt"))
        pool_sub = "pool_" + m["pool"]
        relink(src, os.path.join(E, pool_sub, "images", gid + ext))
        relink(lab_all, os.path.join(E, pool_sub, "labels", gid + ".txt"))
        if m.get("tier"):  # W4b tiered manifests: tier_<T> subsets like pool_<pool>
            tier_sub = "tier_" + m["tier"]
            relink(src, os.path.join(E, tier_sub, "images", gid + ext))
            relink(lab_all, os.path.join(E, tier_sub, "labels", gid + ".txt"))
        row = dict(rec)
        row.update({"platform": plat, "pool": m["pool"], "source_dataset": m["source_dataset"],
                    "source_id": m["source_id"], "license": m["license"]})
        if m.get("tier"):
            row["tier"] = m["tier"]
        rows.append(row)
    with open(os.path.join(E, "exam_gold_v1.jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    per = collections.Counter(r["platform"] for r in rows)
    print(f"export: {len(rows)} images -> {E}/all; per platform {dict(per)}; "
          f"boxes={sum(len(r['boxes']) for r in rows)}")
    print(f"export: per pool {dict(collections.Counter(r['pool'] for r in rows))} -> {E}/pool_<pool>")
    if tier_dirs:
        print(f"export: per tier {dict(collections.Counter(r['tier'] for r in rows))} -> {E}/tier_<T>")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("frames")
    p.add_argument("--manifest", required=True)
    p.add_argument("--gids", required=True)
    p.add_argument("--mode", choices=["whole", "tile"], required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_frames)
    p = sp.add_parser("merge")
    p.add_argument("--dir", required=True)
    p.add_argument("--manifest", required=True)
    p.set_defaults(fn=cmd_merge)
    p = sp.add_parser("overlay")
    p.add_argument("--labels", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_overlay)
    p = sp.add_parser("compare")
    p.add_argument("--a", required=True)
    p.add_argument("--b", required=True)
    p.add_argument("--out", required=True, help="markdown path; side-by-side PNGs go to <out>_side/")
    p.set_defaults(fn=cmd_compare)
    p = sp.add_parser("cost")
    p.add_argument("--work", action="append", required=True)
    p.set_defaults(fn=cmd_cost)
    p = sp.add_parser("qa-make")
    p.add_argument("--labels", required=True)
    p.add_argument("--overlay-dir", required=True)
    p.add_argument("--work", required=True)
    p.add_argument("--manifest", default=MANIFEST_DEFAULT, help="UI scale hint needs the pool")
    p.add_argument("--rules", default="qa_rules_gold119.md", help="QA rules file name in prompts")
    p.add_argument("--only", help="file with one gid per line: build QA batches only for these gids")
    p.set_defaults(fn=cmd_qa_make)
    p = sp.add_parser("qa-summary")
    p.add_argument("--work", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_qa_summary)
    p = sp.add_parser("pending")
    p.add_argument("--work", required=True)
    p.set_defaults(fn=cmd_pending)
    p = sp.add_parser("fix-make")
    p.add_argument("--labels", required=True)
    p.add_argument("--qa", required=True)
    p.add_argument("--work", required=True)
    p.add_argument("--manifest", default=MANIFEST_DEFAULT, help="UI scale hint needs the pool")
    p.add_argument("--rules", default="fix_rules_gold119.md", help="fix rules file name in prompts")
    p.add_argument("--only", help="file with one gid per line: build fix batches only for these gids")
    p.add_argument("--extra-notes", help='jsonl of {"gid", "note"}: gids without a QA fix verdict are fixed with the note as '
                                         'reviewer notes; with a QA fix verdict the note is appended to its notes')
    p.set_defaults(fn=cmd_fix_make)
    p = sp.add_parser("finalize")
    p.add_argument("--round1", required=True)
    p.add_argument("--fix", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_finalize)
    p = sp.add_parser("export")
    p.add_argument("--labels", required=True)
    p.add_argument("--manifest", default=MANIFEST_DEFAULT)
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_export)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
