"""MCP server (stdio) of the R3 conditions X1, X1_sonnet, X2, S_shot_lean, X2_lean.

Same environment as bench.agent.mcp_server (P125_COND / P125_APP / P125_DISPLAY / P125_EPDIR) and the same server name
`p125`, so the tools are `mcp__p125__*`.  Only the tools of the condition (conds.COND_SPECS) are registered:
observe, click, type, key, scroll, done as in R1, plus hover(x, y) and look() for X2 / X2_lean.

`TreeFirstService` = bench.agent.mcp_server.Service with
  * the coordinate scale fixed per condition (X1: 1.0, the others 1.5; observation.scale_for does not know these names),
  * the observation made by TreeFirstObserver (needs the tool name; no model is loaded here, the ours server is resident),
  * hover (move the pointer without a click, wait HOVER_WAIT_S, return the changes) and look (screenshot 1280x720),
    counted and archived like every other call (20 calls in total, the 21st returns LIMIT_TEXT),
  * f2.txt in the step archive: the F2 full text in screen pixels.
If `<epdir>/tree_state.json` exists (X2_lean writes it with the initial observation), the Delta3 state is restored from
it, so that the first action returns changes against the initial list.
"""
import json
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.agent import mcp_server as base  # noqa: E402
from bench.agent.mcp_server import LIMIT_TEXT, MAX_STEPS, SERVER_NAME, SETTLE_S  # noqa: E402,F401
from bench.env import actions  # noqa: E402
from bench.variants.tree_first import conds, prompts  # noqa: E402
from bench.variants.tree_first.observer import TreeFirstObserver, scale_of  # noqa: E402,F401

HOVER_WAIT_S = 1.2
HOVER_SCALE = 1.5


def xtest_move(desk, sx, sy):
    """Move the pointer to screen (sx, sy) without clicking (same XTEST call as bench.env.episode hover_click)."""
    from Xlib import X
    from Xlib.ext import xtest

    xtest.fake_input(desk._display, X.MotionNotify, x=sx, y=sy)
    desk._display.sync()


class TreeFirstService(base.Service):
    def __init__(self, epdir, cond, desk, app_config, observer, settle_s=SETTLE_S, max_steps=MAX_STEPS,
                 hover_wait_s=HOVER_WAIT_S, pointer_fn=None):
        super().__init__(epdir, cond, desk, app_config, observe_fn=None, settle_s=settle_s, max_steps=max_steps)
        self.scale = scale_of(cond)
        self.observer = observer
        self.hover_wait_s = hover_wait_s
        self.pointer_fn = pointer_fn or xtest_move

    def _save(self, step, record, obs, text):
        super()._save(step, record, obs, text)
        f2 = getattr(obs, "f2_text", None)
        if f2 is not None:
            (self._step_dir(step) / "f2.txt").write_text(f2, encoding="utf-8")

    def _observe(self, record):
        try:
            obs = self.observer.observe(self.desk, record["tool"])
        except Exception as exc:  # noqa: BLE001  (the agent gets the error, the traceback is archived)
            with open(self.epdir / "server_errors.txt", "a", encoding="utf-8") as fh:
                fh.write(f"step {record['step']} {record['tool']}:\n{traceback.format_exc()}\n")
            record.update(ok=False, error=f"observation failed: {type(exc).__name__}: {exc}")
            return record["error"], None
        record["t_obs_s"] = round(obs.seconds, 4)
        record["n_elements"] = obs.n_elements
        return obs.text, obs

    def call(self, tool, args):
        if tool not in ("hover", "look"):
            return super().call(tool, args)
        with self.lock:
            self.calls += 1
            step = self.calls
            if step > self.max_steps:
                (self.epdir / "step_limit.json").write_text(json.dumps({"calls": step}), encoding="utf-8")
                return LIMIT_TEXT, None
            t_start = time.time()
            record = {"step": step, "tool": tool, "args": args, "screen_xy": None, "ok": True, "error": None,
                      "t_start": t_start, "t_action_s": 0.0, "t_obs_s": None, "n_elements": None, "t_end": None}
            obs = None
            if tool == "hover":
                try:
                    sx, sy = actions._to_screen(self.desk, args.get("x"), args.get("y"), HOVER_SCALE)
                    record["screen_xy"] = [sx, sy]
                    self.pointer_fn(self.desk, sx, sy)
                except ValueError as exc:
                    record.update(ok=False, error=f"hover failed: {exc}")
                except Exception as exc:  # noqa: BLE001  (X errors, closed display)
                    record.update(ok=False, error=f"hover failed: {type(exc).__name__}: {exc}")
                if not record["ok"]:
                    text = record["error"]
                else:
                    time.sleep(self.hover_wait_s)
                    record["t_action_s"] = round(time.time() - t_start, 4)
                    text, obs = self._observe(record)
            else:
                text, obs = self._observe(record)
            record["t_end"] = time.time()
            self._save(step, record, obs, text)
            return text, (obs.image_png if obs is not None else None)


def make_service(epdir, cond, desk, app_config, display, build_fn=None, **kw):
    """TreeFirstService for `cond` on `desk`; restores the Delta3 state from <epdir>/tree_state.json when that file exists."""
    epdir = Path(epdir)
    observer = TreeFirstObserver(cond, display, build_fn=build_fn)
    state = epdir / "tree_state.json"
    if state.exists() and observer.enc is not None:
        observer.restore(json.loads(state.read_text(encoding="utf-8")))
    return TreeFirstService(epdir, cond, desk, app_config, observer, **kw)


def load_service():
    """TreeFirstService for the episode named by the P125_* environment (attaches to the running desktop)."""
    cond = os.environ["P125_COND"]
    display = os.environ["P125_DISPLAY"]
    epdir = Path(os.environ["P125_EPDIR"])
    info = json.loads((epdir / "episode.json").read_text(encoding="utf-8"))
    desk = actions.attach_desktop(display, info.get("desk_env"))
    return make_service(epdir, cond, desk, info.get("app_config") or {}, display)


def build_server():
    from mcp.server.mcpserver import Image, MCPServer

    service = load_service()
    wanted = conds.COND_SPECS[service.cond]["tools"]
    srv = MCPServer(SERVER_NAME)

    def reply(text, image):
        return [Image(data=image, format="png"), text] if image else text

    def observe() -> list[str | Image]:
        """Return the current view of the application."""
        return reply(*service.call("observe", {}))

    def click(x: int, y: int, button: str = "left", double: bool = False) -> list[str | Image]:
        """Click at (x, y). button is "left" or "right"; double=true double-clicks."""
        return reply(*service.call("click", {"x": x, "y": y, "button": button, "double": double}))

    def type(text: str) -> list[str | Image]:
        """Type text into the focused field."""
        return reply(*service.call("type", {"text": text}))

    def key(name: str) -> list[str | Image]:
        """Press one key (Return, Escape, Tab, shift+Tab, arrows, BackSpace, Delete, Home, End, Page_Up, Page_Down, space)."""
        return reply(*service.call("key", {"name": name}))

    def scroll(x: int, y: int, dy: int) -> list[str | Image]:
        """Scroll at (x, y); dy > 0 scrolls down, dy < 0 up, in wheel notches (|dy| <= 10)."""
        return reply(*service.call("scroll", {"x": x, "y": y, "dy": dy}))

    def done(answer: str) -> list[str | Image]:
        """Finish the task with a short answer (start it with FAIL: if the task cannot be completed)."""
        return reply(*service.call("done", {"answer": answer}))

    def hover(x: int, y: int) -> list[str | Image]:
        return reply(*service.call("hover", {"x": x, "y": y}))

    hover.__doc__ = prompts.HOVER_DOC

    def look() -> list[str | Image]:
        return reply(*service.call("look", {}))

    look.__doc__ = prompts.LOOK_DOC

    funcs = {f.__name__: f for f in (observe, click, type, key, scroll, done, hover, look)}
    for name in wanted:
        srv.tool()(funcs[name])
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
