"""Unified Label Format v1 (ULF v1) core: classes, geometry, pHash, validation, YOLO lines.

Record fields, parent links, crop hashes and validation / export rules are described in labeling/README.md.
"""
import json
import math
import os
import re
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

CLASS_NAMES = [
    "aria:button", "aria:link", "aria:menuitem", "aria:tab", "aria:checkbox",
    "aria:radio", "aria:textbox", "aria:combobox", "aria:slider", "aria:progressbar",
    "aria:gridcell", "aria:listitem", "aria:heading", "aria:img", "vax:visibleText",
    "other:visible",
]
KINDS = {"leaf", "container", "content", "separator"}
SOURCES = {"dom", "human", "model", "atspi"}
PLATFORMS = {"web", "windows", "macos", "linux", "unknown"}
# Image paths in label records are relative to this directory (override with PIXELTREE_DATA).
DATA_ROOT = Path(os.environ.get("PIXELTREE_DATA", "data")).resolve()

IMAGE_FIELDS = [
    "id", "image", "width", "height", "scale", "source", "origin", "group", "platform",
    "theme", "state", "window_region", "em_px", "boxes", "n_dropped",
]
BOX_FIELDS = ["cls", "box", "kind", "role_hint", "parent", "name", "crop_hash", "src_id"]
HEX16 = re.compile(r"^[0-9a-f]{16}$")
TOL = 0.5  # px; allowed box overhang outside the image


def phash(gray: np.ndarray) -> str:
    if gray.size == 0:
        return "0" * 16
    small = cv2.resize(gray.astype(np.float32), (32, 32), interpolation=cv2.INTER_AREA)
    coef = cv2.dct(small)[:8, :8].reshape(64)
    bits = coef > np.median(coef)
    value = 0
    for b in bits:
        value = (value << 1) | int(b)
    return "%016x" % value


def crop_hash(gray_img: np.ndarray, box) -> str:
    h, w = gray_img.shape[:2]
    x1, y1, x2, y2 = box
    x1 = min(max(math.floor(x1), 0), w)
    y1 = min(max(math.floor(y1), 0), h)
    x2 = min(max(math.ceil(x2), 0), w)
    y2 = min(max(math.ceil(y2), 0), h)
    return phash(gray_img[y1:y2, x1:x2])


def hamming(h1: str, h2: str) -> int:
    return bin(int(h1, 16) ^ int(h2, 16)).count("1")


def area(b) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = area(a) + area(b) - inter
    return inter / union if union > 0 else 0.0


def assign_parents(boxes: list[list[float]]) -> list[int | None]:
    if not boxes:
        return []
    b = np.asarray(boxes, dtype=np.float64).reshape(-1, 4)
    n = len(b)
    areas = np.maximum(b[:, 2] - b[:, 0], 0) * np.maximum(b[:, 3] - b[:, 1], 0)
    ix = np.minimum(b[:, None, 2], b[None, :, 2]) - np.maximum(b[:, None, 0], b[None, :, 0])
    iy = np.minimum(b[:, None, 3], b[None, :, 3]) - np.maximum(b[:, None, 1], b[None, :, 1])
    inter = np.maximum(ix, 0) * np.maximum(iy, 0)  # inter[i, j]
    cand = (areas[None, :] > areas[:, None]) & (inter >= 0.9 * areas[:, None])
    np.fill_diagonal(cand, False)
    score = np.where(cand, areas[None, :], np.inf)
    best = np.argmin(score, axis=1)  # argmin keeps the lowest j on ties
    parents: list[int | None] = []
    for i in range(n):
        parents.append(int(best[i]) if np.isfinite(score[i, best[i]]) else None)
    return parents


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _check_region(rid: str, name: str, r, width, height, errors: list[str]) -> bool:
    if not (isinstance(r, list) and len(r) == 4 and all(_is_num(v) for v in r)):
        errors.append(f"{rid}: {name} is not 4 numbers")
        return False
    x1, y1, x2, y2 = r
    if x2 <= x1 or y2 <= y1:
        errors.append(f"{rid}: {name} has zero or negative area {r}")
        return False
    if x1 < -TOL or y1 < -TOL or x2 > width + TOL or y2 > height + TOL:
        errors.append(f"{rid}: {name} outside image {r} for {width}x{height}")
        return False
    return True


def validate_record(rec: dict, data_root: Path, check_image: bool = True) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    rid = str(rec.get("id", "?"))

    missing = [f for f in IMAGE_FIELDS if f not in rec]
    for f in missing:
        errors.append(f"{rid}: missing field {f}")
    if "source" in rec and rec["source"] not in SOURCES:
        errors.append(f"{rid}: bad source {rec['source']!r}")
    if "platform" in rec and rec["platform"] not in PLATFORMS:
        errors.append(f"{rid}: bad platform {rec['platform']!r}")
    width, height = rec.get("width"), rec.get("height")
    if not (_is_int(width) and _is_int(height) and width > 0 and height > 0):
        errors.append(f"{rid}: width/height must be positive int")
        width = height = None
    if width is not None and "window_region" in rec:
        _check_region(rid, "window_region", rec["window_region"], width, height, errors)

    if check_image and "image" in rec and width is not None:
        path = Path(data_root) / rec["image"]
        if not path.is_file():
            errors.append(f"{rid}: image not found {rec['image']}")
        else:
            try:
                size = Image.open(path).size
            except Exception as e:
                errors.append(f"{rid}: image unreadable {rec['image']} ({e})")
            else:
                if size != (width, height):
                    errors.append(f"{rid}: image size {size} != {width}x{height}")

    boxes = rec.get("boxes")
    if not isinstance(boxes, list):
        errors.append(f"{rid}: boxes is not a list")
        return errors, warnings

    n = len(boxes)
    parents_ok = True
    good_boxes: list[list[float] | None] = []
    for i, bx in enumerate(boxes):
        if not isinstance(bx, dict):
            errors.append(f"{rid}: box {i} is not an object")
            good_boxes.append(None)
            parents_ok = False
            continue
        missing_b = [f for f in BOX_FIELDS if f not in bx]
        for f in missing_b:
            errors.append(f"{rid}: box {i} missing field {f}")
        if "kind" in bx and bx["kind"] not in KINDS:
            errors.append(f"{rid}: box {i} bad kind {bx['kind']!r}")
        if "cls" in bx and not (_is_int(bx["cls"]) and 0 <= bx["cls"] <= 15):
            errors.append(f"{rid}: box {i} bad cls {bx['cls']!r}")
        if "crop_hash" in bx and not (isinstance(bx["crop_hash"], str) and HEX16.match(bx["crop_hash"])):
            errors.append(f"{rid}: box {i} bad crop_hash {bx['crop_hash']!r}")

        geom_ok = False
        if "box" in bx and width is not None:
            geom_ok = _check_region(rid, f"box {i}", bx["box"], width, height, errors)
        good_boxes.append(list(bx["box"]) if geom_ok else None)
        if not geom_ok:
            parents_ok = False

        if "parent" not in bx:
            parents_ok = False
        else:
            p = bx["parent"]
            if p is not None and not (_is_int(p) and 0 <= p < n):
                errors.append(f"{rid}: box {i} parent out of range {p!r}")
                parents_ok = False
            elif p == i:
                errors.append(f"{rid}: box {i} is its own parent")
                parents_ok = False

    if parents_ok:
        parent_of = [bx["parent"] for bx in boxes]
        for i in range(n):
            seen = {i}
            p = parent_of[i]
            while p is not None:
                if p in seen:
                    errors.append(f"{rid}: parent cycle through box {i}")
                    break
                seen.add(p)
                p = parent_of[p]
        for i, p in enumerate(parent_of):
            if p is None or good_boxes[i] is None or good_boxes[p] is None:
                continue
            child = good_boxes[i]
            if area(child) > 0:
                ix = max(0.0, min(child[2], good_boxes[p][2]) - max(child[0], good_boxes[p][0]))
                iy = max(0.0, min(child[3], good_boxes[p][3]) - max(child[1], good_boxes[p][1]))
                if ix * iy < 0.9 * area(child):
                    warnings.append(f"{rid}: parent_cover box {i} parent {p} covers <90%")

    valid = [i for i, g in enumerate(good_boxes) if g is not None and _is_int(boxes[i].get("cls"))]
    for a in range(len(valid)):
        i = valid[a]
        for j in valid[a + 1:]:
            if boxes[i]["cls"] == boxes[j]["cls"] and iou(good_boxes[i], good_boxes[j]) >= 0.95:
                warnings.append(f"{rid}: duplicate boxes {i} {j} cls {boxes[i]['cls']}")

    return errors, warnings


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def write_jsonl(path, records) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def yolo_lines(
    rec: dict, region, classes: int = 16, kinds=("leaf", "content"), drops: Counter | None = None
) -> list[str]:
    rx1, ry1, rx2, ry2 = [float(v) for v in region]
    rw, rh = rx2 - rx1, ry2 - ry1
    lines = []
    for bx in rec["boxes"]:
        if bx["kind"] not in kinds:
            if drops is not None:
                drops["kind"] += 1
            continue
        if classes == 15 and bx["cls"] == 15:
            if drops is not None:
                drops["cls15"] += 1
            continue
        x1, y1, x2, y2 = [float(v) for v in bx["box"]]
        ix1, iy1 = max(x1, rx1), max(y1, ry1)
        ix2, iy2 = min(x2, rx2), min(y2, ry2)
        if ix2 <= ix1 or iy2 <= iy1:
            if drops is not None:
                drops["outside"] += 1
            continue
        if (ix2 - ix1) * (iy2 - iy1) < 0.5 * area((x1, y1, x2, y2)):
            if drops is not None:
                drops["under_half_visible"] += 1
            continue
        cw, ch = ix2 - ix1, iy2 - iy1
        if cw < 2 or ch < 2:
            if drops is not None:
                drops["tiny"] += 1
            continue
        cx = (ix1 - rx1 + cw / 2) / rw
        cy = (iy1 - ry1 + ch / 2) / rh
        lines.append(f"{bx['cls']} {cx:.6f} {cy:.6f} {cw / rw:.6f} {ch / rh:.6f}")
    return lines
