"""Screenshot (BGR array) -> list of leaf elements: leaf detector + OCR names + text-box values.

Pipeline (one whole-screen pass, no window model, no icon classifier):

1. `LeafDetector` finds all visible leaf elements with confidence >= 0.25.
2. Leaves of text-bearing roles (OCR_ROLES) are cropped (2 px pad) and read by the line recogniser as one line.
   `aria:img` leaves are read from a band over the bottom text line of the box (`icon_label_band`) because desktop
   icons carry their caption just below the glyph. Reads with score < 0.5 are dropped, and icon-band reads need at
   least two letters or digits.
3. `aria:textbox` leaves are read line by line (`ocr.read_region`); that value is the element's name when the
   whole-box read gave none, and it replaces a whole-box read when it has several lines (a single-line read of a
   multi-line box is garbage).

Names only ever come from OCR. An icon without readable text has an empty name: nothing is guessed from appearance.
"""
import time

import numpy as np

from .detector import KEEP_CONF, LeafDetector
from .ocr import RecReader, TextLineDetector, read_region
from .tree import Element

OCR_ROLES = {
    "aria:button", "aria:link", "aria:menuitem", "aria:tab", "aria:checkbox",
    "aria:radio", "aria:textbox", "aria:combobox", "aria:gridcell", "aria:listitem",
    "aria:heading", "vax:visibleText", "other:visible",
}
OCR_PAD = 2
OCR_MIN_SIDE = 4
OCR_MIN_SCORE = 0.5

ICON_ROLE = "aria:img"
ICON_MIN_W = 32
ICON_MIN_H = 40
ICON_BAND_WIDTH = 1.2
ICON_LINE_FRAC = 0.28
ICON_LINE_MIN = 12
ICON_LINE_MAX = 28
ICON_BAND_BELOW = 1 / 3
ICON_MIN_ALNUM = 2


# ---------------------------------------------------------------- geometry helpers
def _clip_xyxy(box, W, H):
    """xyxy clipped to the image rectangle."""
    x0, y0, x1, y1 = (float(v) for v in box)
    return (max(0.0, min(x0, W)), max(0.0, min(y0, H)),
            max(0.0, min(x1, W)), max(0.0, min(y1, H)))


def _px_box(box, W, H):
    """xyxy float -> integer [x, y, w, h] inside the image, w/h >= 1."""
    x0, y0, x1, y1 = (int(round(float(v))) for v in box)
    x0 = min(max(x0, 0), W - 1)
    x1 = min(max(x1, x0 + 1), W)
    y0 = min(max(y0, 0), H - 1)
    y1 = min(max(y1, y0 + 1), H)
    return [x0, y0, x1 - x0, y1 - y0]


def icon_label_band(box, W, H, line_frac=ICON_LINE_FRAC):
    """xyxy int band over the bottom text line of an icon box, or None when unusable."""
    x0, y0, x1, y1 = _clip_xyxy(box, W, H)
    w, h = x1 - x0, y1 - y0
    if w < ICON_MIN_W or h < ICON_MIN_H:
        return None
    line_h = min(ICON_LINE_MAX, max(ICON_LINE_MIN, round(line_frac * h)))
    cx = (x0 + x1) / 2.0
    bx0 = int(np.floor(cx - ICON_BAND_WIDTH * w / 2.0))
    by0 = int(np.floor(y1 - line_h))
    bx1 = int(np.ceil(cx + ICON_BAND_WIDTH * w / 2.0))
    by1 = int(np.ceil(y1 + round(line_h * ICON_BAND_BELOW)))
    bx0 = max(0, min(bx0, W))
    bx1 = max(0, min(bx1, W))
    by0 = max(0, min(by0, H))
    by1 = max(0, min(by1, H))
    if bx1 - bx0 < OCR_MIN_SIDE or by1 - by0 < OCR_MIN_SIDE:
        return None
    return (bx0, by0, bx1, by1)


# ---------------------------------------------------------------- observer
class Observer:
    """Leaf detector + OCR. `device` is "cpu" or a CUDA index; OCR follows it (CPU fp32, or CUDA fp16)."""

    def __init__(self, weights, device="cpu", imgsz=1280, conf=KEEP_CONF, threads=6):
        self.device = device
        cpu = device == "cpu"
        self.detector = LeafDetector(weights, device=device, imgsz=imgsz, conf=conf, threads=threads)
        self.leaf_names = self.detector.names
        if cpu:
            self.reader = RecReader("cpu", threads=threads)
            self.line_det = TextLineDetector(provider="cpu")
        else:
            self.reader = RecReader("cuda", device_id=int(device), fp16=True)
            self.line_det = TextLineDetector(provider="cuda", device_id=int(device))
        self.reader.warmup()
        self.line_det.warmup()

    def _read_texts(self, img, boxes, classes):
        """{leaf index: (text, score)} for text-bearing leaves and icon label bands."""
        H, W = img.shape[:2]
        indices, crops, is_icon = [], [], []
        # All text-bearing OCR_ROLES crops first, then aria:img label bands.
        for i, (box, cls) in enumerate(zip(boxes, classes)):
            if self.leaf_names.get(int(cls)) not in OCR_ROLES:
                continue
            x0, y0, x1, y1 = _clip_xyxy(box, W, H)
            x0, y0 = max(0, int(np.floor(x0)) - OCR_PAD), max(0, int(np.floor(y0)) - OCR_PAD)
            x1, y1 = min(W, int(np.ceil(x1)) + OCR_PAD), min(H, int(np.ceil(y1)) + OCR_PAD)
            if x1 - x0 < OCR_MIN_SIDE or y1 - y0 < OCR_MIN_SIDE:
                continue
            indices.append(i)
            crops.append(img[y0:y1, x0:x1])
            is_icon.append(False)
        for i, (box, cls) in enumerate(zip(boxes, classes)):
            if self.leaf_names.get(int(cls)) != ICON_ROLE:
                continue
            band = icon_label_band(box, W, H)
            if band is None:
                continue
            bx0, by0, bx1, by1 = band
            indices.append(i)
            crops.append(img[by0:by1, bx0:bx1])
            is_icon.append(True)
        texts = {}
        if not crops:
            return texts
        results = self.reader.read(crops)
        for i, res, icon in zip(indices, results, is_icon):
            if not res:
                continue
            text, score = res
            text = str(text).strip()
            if not text or float(score) < OCR_MIN_SCORE:
                continue
            if icon and sum(ch.isalnum() for ch in text) < ICON_MIN_ALNUM:
                continue
            texts[i] = (text, float(score))
        return texts

    def _read_textbox_values(self, img, boxes, classes):
        """{leaf index: reading-order value} for aria:textbox leaves read line by line."""
        values = {}
        for i, (box, cls) in enumerate(zip(boxes, classes)):
            if self.leaf_names.get(int(cls)) != "aria:textbox":
                continue
            value = read_region(self.line_det, self.reader, img, box)
            if value is not None:
                values[i] = value
        return values

    def observe(self, img_bgr):
        """BGR screenshot -> (elements in detection order, ids not yet set; timings in milliseconds)."""
        H, W = img_bgr.shape[:2]
        t0 = time.perf_counter()
        boxes, conf, cls = self.detector.predict(img_bgr)
        t1 = time.perf_counter()
        texts = self._read_texts(img_bgr, boxes, cls)
        t2 = time.perf_counter()
        values = self._read_textbox_values(img_bgr, boxes, cls)
        t3 = time.perf_counter()
        # Whole-box single-line OCR of a multi-line textbox is garbage; the in-box line reads win.
        for i in [k for k, v in values.items() if "\n" in v]:
            texts.pop(i, None)

        elements = []
        for i in range(len(boxes)):
            name = texts[i][0] if i in texts else ""
            name = name or values.get(i) or ""
            elements.append(Element(id="", role=self.leaf_names[int(cls[i])], name=name,
                                    box=_px_box(boxes[i], W, H), conf=float(conf[i])))
        t4 = time.perf_counter()
        timings = {"leaves": (t1 - t0) * 1000, "ocr": (t2 - t1) * 1000, "textval": (t3 - t2) * 1000,
                   "tree": (t4 - t3) * 1000}
        return elements, timings
