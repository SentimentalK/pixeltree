"""Draw the detector's boxes on examples/screenshots/gitg.png -> hf/assets/example_gitg.png.

    python hf/make_example.py [--weights PATH] [--out PATH]

Uses the same detector call as `python -m pixeltree.perceive` (imgsz 1280, conf 0.25, NMS IoU 0.7), so the boxes are
the ones behind examples/screenshots/gitg.tree.txt. Boxes are coloured by role; a legend strip lists the roles that
occur. The output is scaled to 1280 px wide and palette-quantised to stay small.
"""
import argparse
import sys
from pathlib import Path

import cv2
from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from pixeltree.perceive.detector import LeafDetector  # noqa: E402

DEFAULT_WEIGHTS = Path.home() / ".cache" / "pixeltree" / "pixeltree-detector-v1.pt"
WIDTH = 1280
COLORS = {  # role -> RGB, chosen to stay distinguishable on a light UI
    "aria:button": (230, 25, 75), "aria:link": (0, 90, 220), "aria:menuitem": (245, 130, 48),
    "aria:tab": (145, 30, 180), "aria:checkbox": (60, 180, 75), "aria:radio": (0, 190, 160),
    "aria:textbox": (170, 110, 40), "aria:combobox": (240, 50, 230), "aria:slider": (128, 128, 0),
    "aria:progressbar": (0, 0, 128), "aria:gridcell": (100, 100, 100), "aria:listitem": (0, 170, 220),
    "aria:heading": (200, 160, 0), "aria:img": (120, 60, 160), "vax:visibleText": (125, 125, 125),
    "other:visible": (30, 30, 30),
}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS)
    ap.add_argument("--image", type=Path, default=REPO / "examples" / "screenshots" / "gitg.png")
    ap.add_argument("--out", type=Path, default=REPO / "hf" / "assets" / "example_gitg.png")
    a = ap.parse_args(argv)

    bgr = cv2.imread(str(a.image))
    h, w = bgr.shape[:2]
    det = LeafDetector(str(a.weights))
    boxes, conf, cls = det.predict(bgr)
    names = det.names

    s = WIDTH / w
    img = Image.open(a.image).convert("RGB").resize((WIDTH, round(h * s)), Image.LANCZOS)
    d = ImageDraw.Draw(img)
    for (x1, y1, x2, y2), c in zip(boxes, cls):
        d.rectangle([x1 * s, y1 * s, x2 * s, y2 * s], outline=COLORS[names[int(c)]], width=1)

    present = [r for r in COLORS if r in {names[int(c)] for c in cls}]
    font = ImageFont.load_default(size=13)
    pad, col_w, row_h = 10, 215, 20
    per_row = max(1, (WIDTH - 2 * pad) // col_w)
    rows = -(-len(present) // per_row)
    strip = Image.new("RGB", (WIDTH, rows * row_h + 2 * pad + row_h), (255, 255, 255))
    sd = ImageDraw.Draw(strip)
    for i, r in enumerate(present):
        x, y = pad + (i % per_row) * col_w, pad + (i // per_row) * row_h
        sd.rectangle([x, y + 3, x + 14, y + 15], outline=COLORS[r], width=2)
        sd.text((x + 22, y + 1), f"{r} ({sum(names[int(c)] == r for c in cls)})", fill=(30, 30, 30), font=font)
    sd.text((pad, pad + rows * row_h),
            f"pixeltree-detector-v1, imgsz 1280, conf 0.25: {len(boxes)} boxes", fill=(90, 90, 90), font=font)

    out = Image.new("RGB", (WIDTH, img.height + strip.height), (255, 255, 255))
    out.paste(img, (0, 0))
    out.paste(strip, (0, img.height))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    out.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(a.out, optimize=True)
    print(f"{a.out.relative_to(REPO)}: {out.size[0]}x{out.size[1]}, {a.out.stat().st_size / 1024:.0f} KB, {len(boxes)} boxes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
