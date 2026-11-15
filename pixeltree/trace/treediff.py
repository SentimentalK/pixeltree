"""Tree difference between two observations (pure functions). Element = {"id","role","name","box":[x,y,w,h],...}."""

from __future__ import annotations

PAIR_DIST = 40.0   # max centre distance (pixels) for pairing elements with the same role and name
MOVE_PX = 4.0      # centre shift / width-height change above this counts as moved
IOU_MIN = 0.5


def center(e: dict) -> tuple[float, float]:
    x, y, w, h = e["box"]
    return (x + w / 2.0, y + h / 2.0)


def iou(a: list, b: list) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def tree_diff(prev: list[dict] | None, cur: list[dict]) -> dict:
    """Return {"added","removed","moved":[(p,c)],"renamed":[(p,c)],"same":n}.

    1. Elements with the same role and name are paired greedily by centre distance (<= 40 px); a
       pair whose centre moved > 4 px or whose width/height changed > 4 px is "moved", otherwise "same".
    2. Remaining elements with the same role are paired greedily by box IoU >= 0.5 (largest first)
       and reported as "renamed".
    3. The remaining cur elements are "added", the remaining prev elements "removed". With prev=None
       everything is "added".
    """
    if prev is None:
        return {"added": list(cur), "removed": [], "moved": [], "renamed": [], "same": 0}

    pu = set()  # prev indices already paired
    cu = set()
    moved, renamed = [], []
    same = 0

    # 1. same role + same name: global greedy, smallest distance first
    cands = []
    for pi, p in enumerate(prev):
        pc = center(p)
        for ci, c in enumerate(cur):
            if p.get("role") != c.get("role") or p.get("name") != c.get("name"):
                continue
            cc = center(c)
            d = ((pc[0] - cc[0]) ** 2 + (pc[1] - cc[1]) ** 2) ** 0.5
            if d <= PAIR_DIST:
                cands.append((d, pi, ci))
    cands.sort()
    for d, pi, ci in cands:
        if pi in pu or ci in cu:
            continue
        pu.add(pi)
        cu.add(ci)
        p, c = prev[pi], cur[ci]
        dw = abs(p["box"][2] - c["box"][2])
        dh = abs(p["box"][3] - c["box"][3])
        if d > MOVE_PX or dw > MOVE_PX or dh > MOVE_PX:
            moved.append((p, c))
        else:
            same += 1

    # 2. remaining same-role elements: largest IoU first
    cands = []
    for pi, p in enumerate(prev):
        if pi in pu:
            continue
        for ci, c in enumerate(cur):
            if ci in cu or p.get("role") != c.get("role"):
                continue
            v = iou(p["box"], c["box"])
            if v >= IOU_MIN:
                cands.append((-v, pi, ci))
    cands.sort()
    for _, pi, ci in cands:
        if pi in pu or ci in cu:
            continue
        pu.add(pi)
        cu.add(ci)
        renamed.append((prev[pi], cur[ci]))

    added = [c for ci, c in enumerate(cur) if ci not in cu]
    removed = [p for pi, p in enumerate(prev) if pi not in pu]
    return {"added": added, "removed": removed, "moved": moved,
            "renamed": renamed, "same": same}


def element_at(elements: list[dict] | None, x: float, y: float) -> dict | None:
    """The smallest-area element containing (x,y); None if there is none."""
    best = None
    best_area = None
    for e in elements or []:
        bx, by, bw, bh = e["box"]
        if bx <= x <= bx + bw and by <= y <= by + bh:
            area = bw * bh
            if best is None or area < best_area:
                best, best_area = e, area
    return best
