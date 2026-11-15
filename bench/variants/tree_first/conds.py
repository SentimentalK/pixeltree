"""Plugin of bench.agent.run for the R3 conditions (use: `python -m bench.agent.run --plugin bench.variants.tree_first.conds ...`).

  X1          Haiku, F2 element list (screen pixels), the R1 six tools
  X1_sonnet   as X1 with Sonnet
  X2          Haiku, F3 changes in 1280x720 coordinates, six tools + hover + look
  S_shot_lean Haiku, screenshot 1280x720; no observe tool, the first screenshot comes with the task
  X2_lean     as X2, but no observe tool: the full element list comes with the task

The runner contract (bench.agent.run): COND_SPECS, initial_message(), harness_error().
"""
import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.agent.observation import SHOT_NOTE  # noqa: E402
from bench.agent.prompts import user_message  # noqa: E402
from bench.variants.tree_first import prompts  # noqa: E402
from bench.variants.tree_first.observer import TreeFirstObserver  # noqa: E402

SIX = ("observe", "click", "type", "key", "scroll", "done")
LEAN_SIX = tuple(t for t in SIX if t != "observe")
MCP_MODULE = "bench.variants.tree_first.mcp_server"
HAIKU, SONNET = "claude-haiku-5-5", "claude-sonnet-5-5"


def _spec(cond, model, tools, stream_input):
    return {"system_prompt": prompts.SYSTEM[cond], "model": model, "tools": tuple(tools), "mcp_module": MCP_MODULE,
            "stream_input": stream_input}


COND_SPECS = {
    "X1": _spec("X1", HAIKU, SIX, False),
    "X1_sonnet": _spec("X1_sonnet", SONNET, SIX, False),
    "X2": _spec("X2", HAIKU, SIX + ("hover", "look"), False),
    "S_shot_lean": _spec("S_shot_lean", HAIKU, LEAN_SIX, True),
    "X2_lean": _spec("X2_lean", HAIKU, LEAN_SIX + ("hover", "look"), True),
}


def _archive_initial(epdir, obs):
    d = Path(epdir) / "initial"      # not under steps/: step_stats would count it as a step
    d.mkdir(parents=True, exist_ok=True)
    if obs.screen_png:
        (d / "screen.png").write_bytes(obs.screen_png)
    (d / "obs.txt").write_text(obs.text, encoding="utf-8")
    if obs.image_png:
        (d / "shot.png").write_bytes(obs.image_png)
    if obs.tree_json is not None:
        (d / "tree.json").write_text(json.dumps(obs.tree_json, ensure_ascii=False), encoding="utf-8")
    if getattr(obs, "f2_text", None) is not None:
        (d / "f2.txt").write_text(obs.f2_text, encoding="utf-8")
    (d / "seconds.json").write_text(json.dumps({"t_obs_s": round(obs.seconds, 4), "n_elements": obs.n_elements}),
                                    encoding="utf-8")


def initial_message(cond, job, ep, epdir, display):
    """Content blocks of the first user message (lean conditions), else None (the task is a command line argument)."""
    if not COND_SPECS[cond]["stream_input"]:
        return None
    observer = TreeFirstObserver(cond, display)
    obs = observer.observe(ep.desk, "initial")
    _archive_initial(epdir, obs)
    task = {"type": "text", "text": user_message(job["sentence"])}
    if cond == "S_shot_lean":
        return [task, {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                   "data": base64.b64encode(obs.image_png).decode("ascii")}},
                {"type": "text", "text": SHOT_NOTE}]
    (Path(epdir) / "tree_state.json").write_text(json.dumps(observer.state(), ensure_ascii=False), encoding="utf-8")
    return [task, {"type": "text", "text": obs.text}]


def harness_error(cond, epdir):
    """A reason when the episode is a harness failure (rerun on resume), else None."""
    epdir = Path(epdir)
    if (epdir / "server_error.txt").exists():
        return "R3 MCP server failed to start (server_error.txt)"
    errors = epdir / "server_errors.txt"
    if errors.exists() and "OursServerUnavailable" in errors.read_text(encoding="utf-8", errors="replace"):
        return "ours perception server unavailable (OursServerUnavailable in server_errors.txt)"
    if COND_SPECS[cond]["stream_input"] and not (epdir / "initial" / "obs.txt").exists():
        return "initial observation missing (initial/obs.txt)"
    return None
