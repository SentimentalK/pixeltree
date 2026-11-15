"""Agent-side observation: one screenshot per call, turned into the text / image the agent sees.

    obs = observe(cond, desk, app_config)

Conditions: T_ours / T_omni / T_atspi give a tree as text (perception.sources, one text format for all three);
S_shot / S_shot_strong give the screenshot scaled to 1280x720 plus a one-line note; the hybrids H_ours / H_atspi give
that same screenshot and note plus the T_ours / T_atspi tree text with every box and centre converted to the
1280x720 screenshot frame (one coordinate system for the agent, scale 1.5 as in S_shot).  The raw 1920x1080 screenshot is
always kept (`screen_png`) for the step archive.  Detection / OCR / AT-SPI logic lives in bench.perception, not here.
"""
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.perception import sources  # noqa: E402
from pixeltree.perceive.tree import Element, Tree, to_json, to_text  # noqa: E402

SHOT_SIZE = (1280, 720)
SHOT_NOTE = "Screenshot 1280x720. Use pixel coordinates of this image."
SHOT_SCALE = 1.5  # screen pixels per screenshot pixel (1920 / 1280)
TREE_SOURCE = {"T_ours": "ours", "T_omni": "omni", "T_atspi": "atspi"}
SHOT_CONDS = ("S_shot", "S_shot_strong")
HYBRID_SOURCE = {"H_ours": "ours", "H_atspi": "atspi"}


@dataclass
class Obs:
    text: str                 # tree text, or the one-line screenshot note
    image_png: bytes = None   # scaled screenshot (S_* conditions), else None
    screen_png: bytes = b""   # raw screenshot, for the archive
    n_elements: int = 0       # tree elements (0 for screenshots)
    seconds: float = 0.0      # wall time of the whole observation (screenshot + encoding + tree)
    tree_json: dict = None    # full tree (all elements, timings) for the archive; None for screenshots


def scale_for(cond):
    """Factor from the coordinates the agent uses to screen pixels."""
    return SHOT_SCALE if cond in SHOT_CONDS or cond in HYBRID_SOURCE else 1.0


def encode_png(img_bgr):
    import cv2

    ok, buf = cv2.imencode(".png", img_bgr)
    if not ok:
        raise RuntimeError("PNG encoding failed")
    return buf.tobytes()


def to_shot_frame(tree, scale=SHOT_SCALE, size=SHOT_SIZE):
    """Copy of `tree` with every box divided by `scale` (screen pixels -> screenshot pixels); order and ids kept."""
    elements = [Element(id=e.id, role=e.role, name=e.name, conf=e.conf,
                        box=[int(round(v / scale)) for v in e.box]) for e in tree.elements]
    return Tree(source=tree.source, image_size=tuple(size), elements=elements, timings=dict(tree.timings))


def _shot(img):
    import cv2

    return encode_png(cv2.resize(img, SHOT_SIZE, interpolation=cv2.INTER_AREA))


def _tree(source, desk, app_config, screen_png):
    if source == "atspi":
        cfg = app_config or {}
        process = cfg.get("process") or cfg.get("name") or ""
        nodes = desk.atspi_nodes(process)
        return sources.build_tree("atspi", png_bytes=screen_png, atspi_nodes=nodes, process=process)
    return sources.build_tree(source, png_bytes=screen_png)


def observe(cond, desk, app_config):
    """Screenshot `desk`, then build the observation of `cond`.  `app_config["process"]` names the AT-SPI app."""
    if cond not in TREE_SOURCE and cond not in SHOT_CONDS and cond not in HYBRID_SOURCE:
        raise ValueError(f"unknown condition {cond!r}")
    t0 = time.perf_counter()
    img = desk.screenshot()
    screen_png = encode_png(img)
    if cond in SHOT_CONDS:
        return Obs(text=SHOT_NOTE, image_png=_shot(img), screen_png=screen_png, n_elements=0,
                   seconds=time.perf_counter() - t0)
    if cond in HYBRID_SOURCE:
        tree = _tree(HYBRID_SOURCE[cond], desk, app_config, screen_png)
        text = SHOT_NOTE + "\n" + to_text(to_shot_frame(tree))
        # tree.json keeps the screen-pixel tree (same archive format as the T_* conditions)
        return Obs(text=text, image_png=_shot(img), screen_png=screen_png, n_elements=len(tree.elements),
                   seconds=time.perf_counter() - t0, tree_json=to_json(tree))
    tree = _tree(TREE_SOURCE[cond], desk, app_config, screen_png)
    return Obs(text=to_text(tree), screen_png=screen_png, n_elements=len(tree.elements),
               seconds=time.perf_counter() - t0, tree_json=to_json(tree))


def warmup(cond):
    """Load the models of `cond` (T_ours) or fail early (T_omni without omni.py); no-op for the other conditions."""
    if cond in ("T_ours", "H_ours"):
        from pixeltree.perceive import ours

        ours.warmup()
    elif cond == "T_omni":
        sources._import_omni()
