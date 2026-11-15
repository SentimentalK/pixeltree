"""MCP server (stdio) of the bench harness: the six tools an agent has, bound to ONE already running desktop.

Environment (set by run.py through the MCP config):
  P125_COND     T_ours | T_atspi | T_omni | S_shot | S_shot_strong | H_ours | H_atspi
  P125_APP      application name (informational)
  P125_DISPLAY  the X display the runner started, e.g. :140 (the server never starts or stops a desktop)
  P125_EPDIR    episode directory; reads episode.json (app_config, desktop environment), writes steps/NN/ and done.json

Tools: observe(), click(x, y, button, double), type(text), key(name), scroll(x, y, dy), done(answer).
Every tool call is one step; the 21st and later calls are not executed.  Every action is executed through
bench.env.actions.execute, waits SETTLE_S, then returns the new observation (tree text, or the scaled screenshot plus
a one-line note).  Each step is archived in steps/NN/ (see agent/README.md).

`Service` holds all logic and has no MCP / X11 import, so it is unit-tested with a fake desktop;
build_server() / main() wrap it for the MCP stdio transport.
"""
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.agent import observation  # noqa: E402
from bench.env import actions  # noqa: E402

MAX_STEPS = 20
SETTLE_S = 0.8
LIMIT_TEXT = "step limit reached (20); stop now"
SERVER_NAME = "p125"


class Service:
    """Step counting, action execution, observation and archive for one episode."""

    def __init__(self, epdir, cond, desk, app_config, observe_fn=None, settle_s=SETTLE_S, max_steps=MAX_STEPS):
        self.epdir = Path(epdir)
        self.cond = cond
        self.desk = desk
        self.app_config = app_config or {}
        self.observe_fn = observe_fn or observation.observe
        self.settle_s = settle_s
        self.max_steps = max_steps
        self.scale = observation.scale_for(cond)
        self.calls = 0
        self.lock = threading.Lock()
        (self.epdir / "steps").mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ archive
    def _step_dir(self, step):
        d = self.epdir / "steps" / f"{step:02d}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _save(self, step, record, obs, text):
        d = self._step_dir(step)
        screen = obs.screen_png if obs is not None and obs.screen_png else self._screen_bytes()
        if screen:
            (d / "screen.png").write_bytes(screen)
        (d / "obs.txt").write_text(text, encoding="utf-8")
        if obs is not None and obs.image_png:
            (d / "shot.png").write_bytes(obs.image_png)
        if obs is not None and obs.tree_json is not None:
            (d / "tree.json").write_text(json.dumps(obs.tree_json, ensure_ascii=False), encoding="utf-8")
        (d / "action.json").write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")

    def _screen_bytes(self):
        try:
            return observation.encode_png(self.desk.screenshot())
        except Exception:  # noqa: BLE001  (archive only)
            return b""

    # ------------------------------------------------------------------ tools
    def call(self, tool, args):
        """Run one tool call; returns (text, image_png_bytes_or_None)."""
        with self.lock:
            self.calls += 1
            step = self.calls
            if step > self.max_steps:
                (self.epdir / "step_limit.json").write_text(json.dumps({"calls": step}), encoding="utf-8")
                return LIMIT_TEXT, None
            t_start = time.time()
            record = {"step": step, "tool": tool, "args": args, "screen_xy": None, "ok": True, "error": None,
                      "t_start": t_start, "t_action_s": 0.0, "t_obs_s": None, "n_elements": None,
                      "t_end": None}
            obs = None
            if tool == "done":
                answer = str(args.get("answer", ""))
                (self.epdir / "done.json").write_text(json.dumps({"answer": answer, "step": step},
                                                                 ensure_ascii=False), encoding="utf-8")
                text = "ok"
            elif tool == "observe":
                text, obs = self._observe(record)
            else:
                res = actions.execute(self.desk, dict(args, tool=tool), self.scale)
                record.update(ok=res["ok"], error=res["error"], screen_xy=res["screen_xy"])
                if not res["ok"]:
                    text = res["error"]
                else:
                    time.sleep(self.settle_s)
                    record["t_action_s"] = round(time.time() - t_start, 4)
                    text, obs = self._observe(record)
            record["t_end"] = time.time()
            self._save(step, record, obs, text)
            return text, (obs.image_png if obs is not None else None)

    def _observe(self, record):
        try:
            obs = self.observe_fn(self.cond, self.desk, self.app_config)
        except Exception as exc:  # noqa: BLE001  (the agent gets the error, the traceback is archived)
            with open(self.epdir / "server_errors.txt", "a", encoding="utf-8") as fh:
                fh.write(f"step {record['step']} {record['tool']}:\n{traceback.format_exc()}\n")
            record.update(ok=False, error=f"observation failed: {type(exc).__name__}: {exc}")
            return record["error"], None
        record["t_obs_s"] = round(obs.seconds, 4)
        record["n_elements"] = obs.n_elements
        return obs.text, obs


def load_service():
    """Service for the episode named by the P125_* environment (attaches to the running desktop)."""
    cond = os.environ["P125_COND"]
    display = os.environ["P125_DISPLAY"]
    epdir = Path(os.environ["P125_EPDIR"])
    info = json.loads((epdir / "episode.json").read_text(encoding="utf-8"))
    desk = actions.attach_desktop(display, info.get("desk_env"))
    service = Service(epdir, cond, desk, info.get("app_config") or {})
    observation.warmup(cond)
    return service


def build_server():
    from mcp.server.mcpserver import Image, MCPServer

    service = load_service()
    srv = MCPServer(SERVER_NAME)

    def reply(text, image):
        return [Image(data=image, format="png"), text] if image else text

    @srv.tool()
    def observe() -> list[str | Image]:
        """Return the current view of the application."""
        return reply(*service.call("observe", {}))

    @srv.tool()
    def click(x: int, y: int, button: str = "left", double: bool = False) -> list[str | Image]:
        """Click at (x, y). button is "left" or "right"; double=true double-clicks."""
        return reply(*service.call("click", {"x": x, "y": y, "button": button, "double": double}))

    @srv.tool()
    def type(text: str) -> list[str | Image]:
        """Type text into the focused field."""
        return reply(*service.call("type", {"text": text}))

    @srv.tool()
    def key(name: str) -> list[str | Image]:
        """Press one key (Return, Escape, Tab, shift+Tab, arrows, BackSpace, Delete, Home, End, Page_Up, Page_Down, space)."""
        return reply(*service.call("key", {"name": name}))

    @srv.tool()
    def scroll(x: int, y: int, dy: int) -> list[str | Image]:
        """Scroll at (x, y); dy > 0 scrolls down, dy < 0 up, in wheel notches (|dy| <= 10)."""
        return reply(*service.call("scroll", {"x": x, "y": y, "dy": dy}))

    @srv.tool()
    def done(answer: str) -> list[str | Image]:
        """Finish the task with a short answer (start it with FAIL: if the task cannot be completed)."""
        return reply(*service.call("done", {"answer": answer}))

    return srv, service


def main():
    # model / OCR loading prints to stdout, which would corrupt the stdio JSON-RPC wire: divert fd 1 while loading.
    sys.stdout.flush()
    saved = os.dup(1)
    os.dup2(2, 1)
    try:
        try:
            server, service = build_server()
        except BaseException:
            epdir = os.environ.get("P125_EPDIR")
            if epdir:
                Path(epdir).mkdir(parents=True, exist_ok=True)
                (Path(epdir) / "server_error.txt").write_text(traceback.format_exc(), encoding="utf-8")
            raise
    finally:
        sys.stdout.flush()
        os.dup2(saved, 1)
        os.close(saved)
    server.run("stdio")


if __name__ == "__main__":
    main()
