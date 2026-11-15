"""Real inference for the demo service. The only module that imports the model stack."""

from __future__ import annotations

import time

import numpy as np

_observer = None


def load():
    """Load the detector and OCR models and warm them up with one tiny frame."""
    global _observer
    from pixeltree.perceive.ours import get_observer

    _observer = get_observer()
    _observer.observe(np.zeros((270, 480, 3), np.uint8))


def infer(img):
    """PIL RGB image -> {"elements", "tree_text", "timings"}."""
    from pixeltree.perceive.tree import make_tree, to_json, to_text

    bgr = np.ascontiguousarray(np.asarray(img)[:, :, ::-1])
    h, w = bgr.shape[:2]
    t0 = time.perf_counter()
    elements, ms = _observer.observe(bgr)
    wall = time.perf_counter() - t0
    timings = {"detect_s": ms["leaves"] / 1000, "ocr_s": (ms["ocr"] + ms["textval"]) / 1000,
               "tree_s": ms["tree"] / 1000, "model_s": wall}
    tree = make_tree("ours", (w, h), elements, timings)
    data = to_json(tree)
    return {"elements": data["elements"], "tree_text": to_text(tree), "timings": data["timings"]}
