"""MCP server (stdio) for the R5 vision / tool-call probes: the bench server's six tools, byte-identical
(bench.shells.omp.mcp_server: its schema, in-order execution), bound to a fake desktop whose screen is a plain 1920x1080 image with one random
phrase written on it.  observe() therefore goes through bench.agent's own S_shot path (observation.observe: scale to
1280x720, PNG) and returns the same MCP image block an S_shot episode returns.  Actions do nothing.

Environment: P125_EPDIR (archive, as in p125), BENCH_OMP_PROBE_TEXT (the phrase), P125_COND (default S_shot).
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.agent import mcp_server as base  # noqa: E402


def render(text, size=(1920, 1080)):
    """BGR image: white screen, the phrase in large black letters, centred."""
    import cv2
    import numpy as np

    w, h = size
    img = np.full((h, w, 3), 255, np.uint8)
    font, scale, thick = cv2.FONT_HERSHEY_SIMPLEX, 3.0, 6
    (tw, th), _ = cv2.getTextSize(text, font, scale, thick)
    cv2.putText(img, text, ((w - tw) // 2, (h + th) // 2), font, scale, (0, 0, 0), thick, cv2.LINE_AA)
    return img


class FakeDesk:
    def __init__(self, text):
        self.text = text
        self.env = {}

    def screenshot(self):
        return render(self.text)


def load_service():
    epdir = Path(os.environ["P125_EPDIR"])
    epdir.mkdir(parents=True, exist_ok=True)
    return base.Service(epdir, os.environ.get("P125_COND", "S_shot"), FakeDesk(os.environ["BENCH_OMP_PROBE_TEXT"]), {})


def _no_action(desk, args, scale):
    """Actions do nothing on the fake screen (the order probe only checks the archived execution order)."""
    return {"ok": True, "error": None, "screen_xy": None}


def main():
    from bench.shells.omp import mcp_server as omp_server

    base.actions.execute = _no_action
    omp_server.run(load_service)


if __name__ == "__main__":
    main()
