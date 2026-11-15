"""Screenshot (PNG bytes) -> element tree: the perception used by the "ours" condition of the experiments.

    from pixeltree.perceive.ours import build
    tree = build(open("shot.png", "rb").read())

The model stack (leaf detector + OCR) is loaded once per process, on the first `build()` call or by `warmup()`.

Weights are resolved in this order: the `weights` argument, the `PIXELTREE_WEIGHTS` environment variable,
`~/.cache/pixeltree/pixeltree-detector-v1.pt` (see `python weights/download.py`).
The device is, in this order: the `device` argument, `PIXELTREE_DEVICE` ("cpu" or a CUDA index), "cpu".
`PIXELTREE_THREADS` (default 6) sets the CPU thread count.

Tree rules:
  * Every detected leaf is an element. There is no window element and no window filter.
  * role = the detector class name of the leaf (e.g. "aria:button"); name = text read by OCR from the leaf crop, or
    "" when nothing was read. Names are never guessed from appearance: an icon without readable text has an empty
    name. For text boxes the in-box line reads are used as the name when the whole-box read gave none.
"""
import os
import threading
import time
from pathlib import Path

from .tree import make_tree

SOURCE = "ours"
DEFAULT_WEIGHTS = Path("~/.cache/pixeltree/pixeltree-detector-v1.pt")

_lock = threading.Lock()
_observer = None
_observer_key = None


def resolve_weights(weights=None):
    """Path of the detector weights, or FileNotFoundError that says how to get them."""
    if weights is not None:
        candidate = Path(weights).expanduser()
    elif os.environ.get("PIXELTREE_WEIGHTS"):
        candidate = Path(os.environ["PIXELTREE_WEIGHTS"]).expanduser()
    else:
        candidate = DEFAULT_WEIGHTS.expanduser()
    if not candidate.is_file():
        raise FileNotFoundError(
            f"detector weights not found: {candidate}\n"
            "Download them with `python weights/download.py` (default destination "
            f"{DEFAULT_WEIGHTS}), or pass --weights PATH / set PIXELTREE_WEIGHTS.")
    return candidate


def resolve_device(device=None):
    """"cpu" or a CUDA index: the argument, else $PIXELTREE_DEVICE, else "cpu"."""
    if device is None:
        device = (os.environ.get("PIXELTREE_DEVICE") or "").strip()
    device = str(device).strip().lower()
    if device in ("", "cpu"):
        return "cpu"
    if device.isdigit():
        return int(device)
    raise ValueError(f"device must be 'cpu' or a CUDA index, got {device!r}")


def get_observer(weights=None, device=None):
    """The process-wide Observer (created on first call; rebuilt when weights or device change)."""
    global _observer, _observer_key
    path = resolve_weights(weights)
    device = resolve_device(device)
    if device != "cpu":
        import torch

        if not torch.cuda.is_available():
            raise RuntimeError(f"device {device} requested but CUDA is not available; use device 'cpu'")
    key = (str(path.resolve()), device)
    with _lock:
        if _observer is None or _observer_key != key:
            from .observer import Observer

            threads = int(os.environ.get("PIXELTREE_THREADS") or 6)
            _observer = Observer(path, device=device, threads=threads)
            _observer_key = key
        return _observer


def warmup(weights=None, device=None):
    """Load the models and run one tiny inference so the first real observation is not slow."""
    import numpy as np

    get_observer(weights, device).observe(np.zeros((270, 480, 3), dtype=np.uint8))


def decode_png(png_bytes):
    import cv2
    import numpy as np

    img = cv2.imdecode(np.frombuffer(png_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("png_bytes is not a decodable image")
    return img


def build(png_bytes, *, weights=None, device=None):
    """Tree of all detected leaves of a PNG screenshot.

    timings (seconds): detect_s (leaf detector), ocr_s (name and text-box reads), tree_s, decode_s, model_s,
    total_s; load_s is the model load of the first call and is not part of total_s.
    """
    t0 = time.perf_counter()
    observer = get_observer(weights, device)
    t_load = time.perf_counter()
    img = decode_png(png_bytes)
    t_dec = time.perf_counter()
    elements, ms = observer.observe(img)
    t1 = time.perf_counter()
    H, W = img.shape[:2]
    timings = {
        "detect_s": ms["leaves"] / 1000.0,
        "ocr_s": (ms["ocr"] + ms["textval"]) / 1000.0,
        "tree_s": ms["tree"] / 1000.0,
        "decode_s": t_dec - t_load,
        "load_s": t_load - t0,
        "total_s": time.perf_counter() - t_load,  # without the one-off model load (load_s)
        "model_s": t1 - t_dec,
    }
    return make_tree(SOURCE, (W, H), elements, timings)
