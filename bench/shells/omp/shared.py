"""Pieces shared by the OMP runner, its MCP server and its probes: the coordinate note appended to the system prompt of
the image conditions, the stratified run order, the environment of the MCP server, harness-error detection, the STOP
file, and the observation function that takes trees from the resident `ours` perception service."""
from __future__ import annotations

import json
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.agent import mcp_server as base  # noqa: E402
from bench.agent import observation  # noqa: E402
from bench.agent import run as r1run  # noqa: E402
from bench.agent.observation import SHOT_NOTE, Obs, encode_png, to_shot_frame  # noqa: E402
from bench.env import actions  # noqa: E402
from pixeltree.perceive.tree import Element, Tree, to_text  # noqa: E402

CONDS = ("S_shot", "T_ours", "H_ours")
# One sentence appended to the system prompt of the two image conditions (some models mix pixel and 0-1000
# coordinates in a pilot); T_ours is unchanged.
COORD_NOTE = ("Coordinates are absolute pixels of the 1280x720 screenshot (x 0-1279, y 0-719), not normalized 0-1000 "
              "values.")


def schedule(tasks, conds=CONDS, reps=1, seed=0):
    """Jobs in run order: tasks stratified by app (round-robin over the apps, shuffled with `seed`), the conditions
    rotating per task so no condition is always first.  `tasks`: [{"id", "app", ...}]."""
    rng = random.Random(seed)
    by_app = {}
    for t in tasks:
        by_app.setdefault(t["app"], []).append(t)
    apps = sorted(by_app)
    for app in apps:
        by_app[app] = sorted(by_app[app], key=lambda t: t["id"])
        rng.shuffle(by_app[app])
    order = []
    for b in range(max(len(v) for v in by_app.values())):
        block = [by_app[a][b] for a in apps if b < len(by_app[a])]
        rng.shuffle(block)
        order.extend(block)
    jobs = []
    for rep in range(reps):
        for k, t in enumerate(order):
            shift = (k + rep) % len(conds)
            for cond in list(conds[shift:]) + list(conds[:shift]):
                jobs.append({"task": t["id"], "app": t["app"], "difficulty": t.get("difficulty"),
                             "tier": t.get("tier"), "sentence": t["sentence"], "cond": cond, "rep": rep})
    return jobs


def server_env(job, display, epdir):
    env = {"P125_COND": job["cond"], "P125_APP": job["app"], "P125_DISPLAY": display, "P125_EPDIR": str(epdir),
           "PYTHONPATH": str(ROOT)}
    env.update({k: os.environ[k] for k in r1run.PASS_ENV if k in os.environ})
    return env


def harness_error(epdir):
    epdir = Path(epdir)
    if (epdir / "server_error.txt").exists():
        return "MCP server failed to start (server_error.txt)"
    errors = epdir / "server_errors.txt"
    if errors.exists() and "OursServerUnavailable" in errors.read_text(encoding="utf-8", errors="replace"):
        return "ours perception server unavailable"
    return None


def write_stop(out, reason):
    p = Path(out) / "STOP"
    if not p.exists():
        p.write_text(f"{reason}\n{datetime.now().isoformat(timespec='seconds')}\n", encoding="utf-8")


def tree_from_json(tj):
    """Tree from its to_json dict (order and ids kept)."""
    return Tree(source=tj["source"], image_size=tuple(tj["image_size"]),
                elements=[Element(id=e["id"], role=e["role"], name=e.get("name") or "", conf=e.get("conf"),
                                  box=list(e["box"])) for e in tj["elements"]],
                timings=dict(tj.get("timings") or {}))


def make_observe(display, build_fn=None):
    """observe_fn(cond, desk, app_config) for bench.agent.mcp_server.Service.

    T_ours / H_ours get their tree from the resident ours perception server (bench.variants.tree_first.ours_server)
    instead of loading the detector + OCR in every episode.  The tree and the text are built exactly as
    bench.agent.observation.observe does (to_text / SHOT_NOTE + to_text(to_shot_frame(tree))); S_shot and T_atspi use
    the observation code of bench.agent itself."""
    if build_fn is None:
        from bench.variants.tree_first import ours_client

        def build_fn(png):
            return ours_client.build_tree_json(png, display)

    def observe(cond, desk, app_config):
        if cond not in ("T_ours", "H_ours"):
            return observation.observe(cond, desk, app_config)
        t0 = time.perf_counter()
        img = desk.screenshot()
        screen_png = encode_png(img)
        tj = build_fn(screen_png)
        tree = tree_from_json(tj)
        if cond == "T_ours":
            return Obs(text=to_text(tree), screen_png=screen_png, n_elements=len(tree.elements),
                       seconds=time.perf_counter() - t0, tree_json=tj)
        return Obs(text=SHOT_NOTE + "\n" + to_text(to_shot_frame(tree)), image_png=observation._shot(img),
                   screen_png=screen_png, n_elements=len(tree.elements), seconds=time.perf_counter() - t0,
                   tree_json=tj)

    return observe


def load_service():
    cond = os.environ["P125_COND"]
    display = os.environ["P125_DISPLAY"]
    epdir = Path(os.environ["P125_EPDIR"])
    info = json.loads((epdir / "episode.json").read_text(encoding="utf-8"))
    desk = actions.attach_desktop(display, info.get("desk_env"))
    return base.Service(epdir, cond, desk, info.get("app_config") or {}, observe_fn=make_observe(display))
