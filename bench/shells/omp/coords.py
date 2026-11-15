"""R5 click checks for the image conditions (S_shot, H_ours) of one model's run.

1. From-list ratio (H_ours, every click, automatic): a click's (x, y) counts as "taken from the list" when it lies
   within 3 px of the centre c=(x,y) of some element in the observation the agent got just before the click
   (steps/<NN-1>/obs.txt, screenshot coordinates).
2. Hit sample (R4 method): `--sample N` clicks spread evenly over the S_shot / H_ours episodes are drawn on the screen
   the agent saw before the click (steps/<NN-1>/screen.png): red + = executed point (pixel reading, action.json
   screen_xy), blue x = where a 0-1000 normalized reading would land (x * 1.92, y * 1.08).  Each tile shows a
   native-resolution crop around both points and the model's own words just before the call (its text / thinking,
   from transcript.jsonl), so a reviewer can mark it: hit as pixels / hit only under the 0-1000 reading / miss.
   Sheets of 8 tiles: <out>/sheet_<k>.png; index <out>/clicks.md; ratio <out>/from_list.json.

    python -m bench.shells.omp.coords out/r5/glm/formal --out out/r5/glm/coords --sample 24
"""
import argparse
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.shells.omp import omp  # noqa: E402

CENTRE_RE = re.compile(r"c=\((-?\d+),\s*(-?\d+)\)")
SCREEN_W, SCREEN_H = 1920, 1080
TILE_W, CROP_H, CAP_H = 640, 220, 70


def click_words(transcript):
    """The model's words (thinking + text) of the assistant message holding each click call, in call order."""
    out = []
    for e in omp.read_events(transcript):
        if e.get("type") != "message_end" or (e.get("message") or {}).get("role") != "assistant":
            continue
        content = e["message"].get("content") or []
        words = " ".join((b.get("thinking") or b.get("text") or "") for b in content
                         if isinstance(b, dict) and b.get("type") in ("thinking", "text"))
        for b in content:
            if isinstance(b, dict) and b.get("type") == "toolCall" and b.get("name") == "mcp__p125_click":
                out.append(" ".join(words.split())[-220:])
    return out


def clicks(epdir):
    """[(step, args, screen_xy, words)] of the executed click calls of one episode."""
    epdir = Path(epdir)
    words = click_words(epdir / "transcript.jsonl")
    out, k = [], 0
    for d in sorted((epdir / "steps").glob("[0-9][0-9]")):
        try:
            a = json.loads((d / "action.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if a.get("tool") != "click":
            continue
        out.append((a["step"], a.get("args") or {}, a.get("screen_xy"), words[k] if k < len(words) else ""))
        k += 1
    return out


def centres(obs_text):
    return [(int(x), int(y)) for x, y in CENTRE_RE.findall(obs_text or "")]


def from_list(x, y, obs_text, tol=3.0):
    """True when (x, y) is within `tol` px of the centre of an element listed in `obs_text`."""
    return any(math.hypot(x - cx, y - cy) <= tol for cx, cy in centres(obs_text))


def episodes(run, conds):
    ep = Path(run) / "ep"
    return [d for d in sorted(ep.iterdir()) if d.is_dir() and d.name.split("__")[1] in conds] if ep.exists() else []


def from_list_ratio(run):
    n = hit = 0
    per = []
    for epdir in episodes(run, ("H_ours",)):
        for step, a, _, _ in clicks(epdir):
            prev = epdir / "steps" / f"{step - 1:02d}" / "obs.txt"
            if not prev.exists() or a.get("x") is None:
                continue
            ok = from_list(int(a["x"]), int(a["y"]), prev.read_text(encoding="utf-8"))
            n += 1
            hit += ok
            per.append({"episode": epdir.name, "step": step, "xy": [a["x"], a["y"]], "from_list": ok})
    return {"clicks": n, "from_list": hit, "ratio": hit / n if n else None, "per_click": per}


def _crop(img, x, y, w, h):
    H, W = img.shape[:2]
    x0, y0 = max(0, min(W - w, x - w // 2)), max(0, min(H - h, y - h // 2))
    return img[y0:y0 + h, x0:x0 + w]


def tile(prev_png, a, sxy, words, label):
    import cv2
    import numpy as np

    img = cv2.imread(str(prev_png))
    px, py = int(sxy[0]), int(sxy[1])
    nx, ny = int(round(float(a.get("x", 0)) * SCREEN_W / 1000)), int(round(float(a.get("y", 0)) * SCREEN_H / 1000))
    cv2.drawMarker(img, (px, py), (0, 0, 255), cv2.MARKER_CROSS, 36, 3)
    cv2.drawMarker(img, (nx, ny), (255, 0, 0), cv2.MARKER_TILTED_CROSS, 30, 3)
    half = TILE_W // 2
    left, right = _crop(img, px, py, half, CROP_H), _crop(img, nx, ny, half, CROP_H)
    t = np.full((CROP_H + CAP_H, TILE_W, 3), 255, np.uint8)
    t[:CROP_H, :half] = left
    t[:CROP_H, half:] = right
    cv2.line(t, (half, 0), (half, CROP_H), (0, 0, 0), 2)
    lines = [label, words[:105], words[105:210]]
    for i, s in enumerate(lines):
        cv2.putText(t, s.encode("ascii", "replace").decode(), (4, CROP_H + 18 + 22 * i), cv2.FONT_HERSHEY_SIMPLEX,
                    0.45, (0, 0, 0), 1, cv2.LINE_AA)
    return t


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--out", required=True)
    ap.add_argument("--sample", type=int, default=24)
    args = ap.parse_args(argv)
    import cv2
    import numpy as np

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ratio = from_list_ratio(args.run)
    (out / "from_list.json").write_text(json.dumps(ratio, indent=1), encoding="utf-8")
    allc = []
    for epdir in episodes(args.run, ("S_shot", "H_ours")):
        for step, a, sxy, words in clicks(epdir):
            prev = epdir / "steps" / f"{step - 1:02d}" / "screen.png"
            if prev.exists() and sxy:
                allc.append((epdir, step, a, sxy, words, prev))
    by_cond = {c: [x for x in allc if x[0].name.split("__")[1] == c] for c in ("S_shot", "H_ours")}
    picked = []
    for c, xs in by_cond.items():          # half from each condition, spread evenly over the run
        k = min(len(xs), args.sample // 2 if by_cond["S_shot"] and by_cond["H_ours"] else args.sample)
        picked += [xs[int(i * len(xs) / k)] for i in range(k)] if k else []
    lines = ["# Click sample (left crop: red + = executed pixel point; right crop: blue x = 0-1000 reading)", "",
             "| # | episode | step | agent (x, y) | screen xy | model's words before the call | verdict |",
             "|---|---|---|---|---|---|---|"]
    tiles = []
    for i, (epdir, step, a, sxy, words, prev) in enumerate(picked):
        label = f"#{i} {epdir.name} s{step} ({a.get('x')},{a.get('y')})"
        tiles.append(tile(prev, a, sxy, words, label))
        lines.append(f"| {i} | {epdir.name} | {step} | ({a.get('x')}, {a.get('y')}) | ({sxy[0]}, {sxy[1]}) | "
                     f"{words.replace('|', '/')} | |")
    for k in range(0, len(tiles), 8):
        chunk = tiles[k:k + 8]
        while len(chunk) % 2:
            chunk.append(np.full_like(tiles[0], 255))
        rows = [np.hstack([chunk[j], np.full((chunk[j].shape[0], 8, 3), 128, np.uint8), chunk[j + 1]])
                for j in range(0, len(chunk), 2)]
        sheet = np.vstack([np.vstack([r, np.full((8, r.shape[1], 3), 128, np.uint8)]) for r in rows])
        cv2.imwrite(str(out / f"sheet_{k // 8}.png"), sheet)
    (out / "clicks.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"from-list (H_ours): {ratio['from_list']} / {ratio['clicks']}; sampled {len(picked)} clicks into "
          f"{(len(tiles) + 7) // 8} sheets in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
