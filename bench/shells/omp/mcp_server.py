"""MCP server (stdio) of the R5 episodes: the bench server's six tools with the same names, parameters and docstrings
(the schema the model sees is identical; checked by `same_schema`), bound to the service of bench.shells.omp.shared (ours trees from the
resident perception service, T_atspi / S_shot through the observation code of bench.agent) -- plus in-order execution.

Why: OMP sends all tool calls of one model message to the MCP server at once (MCP tools are not marked "exclusive"
in OMP), and the MCP library runs each request in its own worker thread, so [click, type, click, type, observe]
executed in arbitrary order (observe first, types before clicks).  R1's `claude -p` executed them in the order the
model wrote them.  `OrderedGate` restores that: the R5 OMP hook (omp_prompt.ts, `tool_call`) logs every call in the
model's order to <epdir>/calls.jsonl before OMP sends it; the gate runs calls one at a time in that order.  (JSON-RPC
request ids do not follow the model's order: OMP validates arguments asynchronously before sending.)

Environment: as bench.agent.mcp_server (P125_COND / P125_APP / P125_DISPLAY / P125_EPDIR).
"""
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.agent import mcp_server as base  # noqa: E402

GATHER_S = 0.15
FALLBACK_S = 5.0
SHORT = {f"mcp__{base.SERVER_NAME}_{t}": t for t in ("observe", "click", "type", "key", "scroll", "done")}


def read_call_log(path):
    """[(n, tool, input)] from the hook's calls.jsonl (tool = short bench name), in model order."""
    out = []
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            out.append((int(e.get("n") or 0), SHORT.get(e.get("tool"), e.get("tool")), e.get("input") or {}))
    except OSError:
        pass
    return sorted(out, key=lambda x: x[0])


def matches(entry, tool, args):
    """The logged call `entry` is this call: same tool, and every argument the model gave has the same value."""
    _, etool, einput = entry
    return etool == tool and all(args.get(k) == v for k, v in einput.items())


class OrderedGate:
    """Execute the calls of one model message one at a time, in the order the model wrote them.

    `expected()` returns the model's calls in order [(n, tool, input)] (the OMP hook's log).  A call waits GATHER_S
    for its siblings to arrive, then runs when no call is running and it matches the first logged call not yet
    executed.  When the gate has made no progress (no call started or finished) for FALLBACK_S although calls are
    waiting -- the head entry matches none of them (log missing or unparsable) -- a waiting call runs anyway (arrival
    order) and the event is counted in `fallbacks`.  (Until 2026-11-13 19:05 the timer ran from each call's arrival,
    so calls queued behind a long batch of keys jumped the queue.)"""

    def __init__(self, expected, gather_s=GATHER_S, fallback_s=FALLBACK_S):
        self.expected = expected
        self.gather_s = gather_s
        self.fallback_s = fallback_s
        self.cv = threading.Condition()
        self.busy = False
        self.consumed = set()
        self.fallbacks = 0
        self.last_progress = time.monotonic()

    def run(self, tool, args, fn):
        time.sleep(self.gather_s)
        with self.cv:
            self.last_progress = max(self.last_progress, time.monotonic() - self.gather_s)
            while True:
                if not self.busy:
                    pending = [e for e in self.expected() if e[0] not in self.consumed]
                    head = pending[0] if pending else None
                    if head is not None and matches(head, tool, args):
                        self.consumed.add(head[0])
                        break
                    if time.monotonic() - self.last_progress > self.fallback_s:
                        self.fallbacks += 1
                        hit = next((e for e in pending if matches(e, tool, args)), None)
                        if hit is not None:
                            self.consumed.add(hit[0])
                        break
                self.cv.wait(0.05)
            self.busy = True
            self.last_progress = time.monotonic()
        try:
            return fn()
        finally:
            with self.cv:
                self.busy = False
                self.last_progress = time.monotonic()
                self.cv.notify_all()


def build_server(load_service):
    from mcp.server.mcpserver import Context, Image, MCPServer

    service = load_service()
    srv = MCPServer(base.SERVER_NAME)
    log = Path(os.environ.get("P125_EPDIR", ".")) / "calls.jsonl"     # written by the OMP hook (omp_prompt.ts)
    gate = OrderedGate(lambda: read_call_log(log))

    def reply(text, image):
        return [Image(data=image, format="png"), text] if image else text

    def call(ctx, tool, args):
        out = gate.run(tool, args, lambda: service.call(tool, args))
        if gate.fallbacks:
            (Path(os.environ.get("P125_EPDIR", ".")) / "order_fallbacks.txt").write_text(str(gate.fallbacks))
        return reply(*out)

    @srv.tool()
    def observe(ctx: Context) -> list[str | Image]:
        """Return the current view of the application."""
        return call(ctx, "observe", {})

    @srv.tool()
    def click(x: int, y: int, ctx: Context, button: str = "left", double: bool = False) -> list[str | Image]:
        """Click at (x, y). button is "left" or "right"; double=true double-clicks."""
        return call(ctx, "click", {"x": x, "y": y, "button": button, "double": double})

    @srv.tool()
    def type(text: str, ctx: Context) -> list[str | Image]:
        """Type text into the focused field."""
        return call(ctx, "type", {"text": text})

    @srv.tool()
    def key(name: str, ctx: Context) -> list[str | Image]:
        """Press one key (Return, Escape, Tab, shift+Tab, arrows, BackSpace, Delete, Home, End, Page_Up, Page_Down, space)."""
        return call(ctx, "key", {"name": name})

    @srv.tool()
    def scroll(x: int, y: int, dy: int, ctx: Context) -> list[str | Image]:
        """Scroll at (x, y); dy > 0 scrolls down, dy < 0 up, in wheel notches (|dy| <= 10)."""
        return call(ctx, "scroll", {"x": x, "y": y, "dy": dy})

    @srv.tool()
    def done(answer: str, ctx: Context) -> list[str | Image]:
        """Finish the task with a short answer (start it with FAIL: if the task cannot be completed)."""
        return call(ctx, "done", {"answer": answer})

    return srv, service


def tool_schemas(srv):
    """[(name, description, input schema)] as the MCP client sees them."""
    import anyio

    tools = anyio.run(srv.list_tools)
    return sorted((t.name, t.description, json.dumps(t.input_schema, sort_keys=True)) for t in tools)


def run(load_service):
    """bench.agent.mcp_server.main with this build_server (stdout diverted while loading, server_error.txt on failure)."""
    sys.stdout.flush()
    saved = os.dup(1)
    os.dup2(2, 1)
    try:
        try:
            server, _ = build_server(load_service)
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


def main():
    from bench.shells.omp import shared

    run(shared.load_service)


if __name__ == "__main__":
    main()
