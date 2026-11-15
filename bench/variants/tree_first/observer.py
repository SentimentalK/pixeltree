"""R3 observation functions: screenshot of a desktop -> the `Obs` an agent of a R3 condition gets.

    obs = TreeFirstObserver(cond, display).observe(desk, tool)        # tool in observe / initial / click / type / ... / hover / look

  S_shot_lean       the R1 S_shot observation (1280x720 screenshot + note), unchanged.
  X1, X1_sonnet     F2 full text (formats.f2) of the tree that the resident ours server returns, screen pixels.
  X2, X2_lean       F3 text (formats.Delta3, ONE encoder per episode) converted to 1280x720 with view.to_view:
                    `observe` / `initial` give the full list with ids (state still updated), other tools the changes;
                    `look` gives a 1280x720 screenshot + note and leaves the Delta3 state alone.
Every X* observation also keeps the F2 full text in `obs.f2_text` (screen pixels) for the step archive.
"""
import time

from bench.agent import observation
from bench.agent.observation import Obs, SHOT_NOTE
from pixeltree import formats
from bench.variants.tree_first import ours_client
from bench.variants.tree_first.view import to_view

X1_CONDS = ("X1", "X1_sonnet")
X2_CONDS = ("X2", "X2_lean")
SHOT_CONDS = ("S_shot_lean",)


def scale_of(cond):
    """Screen pixels per coordinate unit the agent uses (X1: screen pixels; the others: 1280x720 view)."""
    return 1.0 if cond in X1_CONDS else 1.5


class TreeFirstObserver:
    def __init__(self, cond, display, build_fn=None):
        if cond not in X1_CONDS + X2_CONDS + SHOT_CONDS:
            raise ValueError(f"unknown R3 condition {cond!r}")
        self.cond = cond
        self.display = display
        self.build_fn = build_fn
        self.enc = formats.Delta3((1920, 1080)) if cond in X2_CONDS else None

    # ---- Delta3 state (X2_lean hands the state of the initial observation to the MCP server through a file)
    def state(self):
        return {"prev": self.enc.prev, "prev_ids": self.enc.prev_ids, "next_id": self.enc.next_id}

    def restore(self, state):
        self.enc.prev = state["prev"]
        self.enc.prev_ids = state["prev_ids"]
        self.enc.next_id = state["next_id"]

    def _tree(self, screen_png):
        if self.build_fn is not None:
            return self.build_fn(screen_png)
        return ours_client.build_tree_json(screen_png, self.display)

    def observe(self, desk, tool):
        t0 = time.perf_counter()
        if self.cond in SHOT_CONDS or tool == "look":
            obs = observation.observe("S_shot", desk, {})
            obs.seconds = time.perf_counter() - t0
            return obs
        screen_png = observation.encode_png(desk.screenshot())
        tree_json = self._tree(screen_png)
        els = formats.clean(tree_json)
        f2_text = formats.f1(tree_json, els)          # = formats.f2(tree_json)
        if self.cond in X1_CONDS:
            text = f2_text
        else:
            self.enc.image_size = tuple(tree_json["image_size"])
            text, _is_full, _n = self.enc.step(els)
            if tool in ("observe", "initial"):
                text = self.enc._full(self.enc.prev, self.enc.prev_ids)
            text = to_view(text)
        obs = Obs(text=text, screen_png=screen_png, n_elements=len(els), seconds=time.perf_counter() - t0,
                  tree_json=tree_json)
        obs.f2_text = f2_text
        return obs


__all__ = ["TreeFirstObserver", "scale_of", "SHOT_NOTE"]
