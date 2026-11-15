"""Action execution on a desktop: one place for the agent harness and any later local service.

    execute(desk, {"tool": "click", "x": 640, "y": 360}, scale=1.5)
        -> {"ok": True, "error": None, "screen_xy": [960, 540], "seconds": 0.02}

`desk` is a bench.env.desktop.XvfbDesktop (started, or attached with attach_desktop).  `scale` converts the coordinates the
caller uses (e.g. pixels of a 1280x720 screenshot, scale 1.5) to screen pixels.  Nothing here sleeps: callers add
their own settle time before observing again.

Actions (whitelist; anything else is refused):
  click   x, y [, button "left"|"right", double bool]
  type    text
  key     name, one of KEYS (case-insensitive, canonical spelling is used), no other shortcut
  scroll  x, y, dy   dy > 0 scrolls down, dy < 0 up, 1 unit = 1 wheel notch, 1 <= |dy| <= MAX_SCROLL; the pointer
                     moves to (x, y) first
Failures never raise: `ok` is False and `error` holds the text shown to an agent (`key not allowed: <name>` for a key
outside the whitelist).
"""
import os
import time
from pathlib import Path

KEYS = ["Return", "Escape", "Tab", "shift+Tab", "Up", "Down", "Left", "Right", "BackSpace", "Delete", "Home",
        "End", "Page_Up", "Page_Down", "space"]
_KEY_LOOKUP = {k.lower(): k for k in KEYS}
MAX_SCROLL = 10
MAX_TYPE_CHARS = 2000
BUTTONS = {"left": 1, "right": 3}
SCREEN = (1920, 1080)
# Environment of an episode desktop that other processes (the MCP server) need to talk to its dbus / AT-SPI.
ENV_PREFIXES = ("XDG_", "DBUS_", "GDK_", "GSK_", "GSETTINGS_", "VAX_", "LC_")
ENV_NAMES = ("HOME", "DISPLAY", "PATH", "LANG", "NO_AT_BRIDGE")


def desktop_env_subset(env):
    """The part of a desktop's environment worth saving to disk (no tokens or credentials of the caller)."""
    return {k: v for k, v in env.items() if k in ENV_NAMES or k.startswith(ENV_PREFIXES)}


def attach_desktop(display, env=None, size=SCREEN):
    """An XvfbDesktop object bound to a display that another process already started (never starts or stops it).

    `env` is merged over os.environ (without Wayland / inherited bus variables) and used for AT-SPI queries.
    Closing the object only closes the X connection; `stop()` is a no-op, so the Xvfb survives.
    """
    from bench.env.desktop import XvfbDesktop
    from Xlib import display as xdisplay

    desk = XvfbDesktop(display=display, size=size)
    merged = {k: v for k, v in os.environ.items() if k not in ("WAYLAND_DISPLAY", "WAYLAND_SOCKET",
                                                              "DBUS_SESSION_BUS_ADDRESS", "XDG_SESSION_TYPE")}
    merged.update(env or {})
    merged["DISPLAY"] = display
    desk.env = merged
    if merged.get("HOME"):
        desk.home = Path(merged["HOME"])
    desk._display = xdisplay.Display(display)
    desk._stopped = True
    return desk


def _screen_size(desk):
    size = getattr(desk, "size", None)
    return tuple(size) if size else SCREEN


def _int(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != int(value):
        raise ValueError(f"{name} must be an integer")
    return int(value)


def _to_screen(desk, x, y, scale):
    """Round(x*scale), round(y*scale); ValueError when outside the screen."""
    x, y = _int(x, "x"), _int(y, "y")
    sx, sy = int(round(x * scale)), int(round(y * scale))
    w, h = _screen_size(desk)
    if not (0 <= sx < w and 0 <= sy < h):
        raise ValueError(f"position ({x}, {y}) is outside the screen")
    return sx, sy


def canonical_key(name):
    """Whitelisted spelling of a key name, or None."""
    return _KEY_LOOKUP.get(str(name).strip().lower())


def _scroll(desk, sx, sy, dy):
    from Xlib import X
    from Xlib.ext import xtest

    display = desk._display
    xtest.fake_input(display, X.MotionNotify, x=sx, y=sy)
    display.sync()
    time.sleep(0.05)
    button = 5 if dy > 0 else 4
    for _ in range(abs(dy)):
        xtest.fake_input(display, X.ButtonPress, button)
        xtest.fake_input(display, X.ButtonRelease, button)
        display.sync()
        time.sleep(0.03)


def execute(desk, action, scale=1.0):
    """Run one action dict on `desk`; see the module docstring.  Never raises."""
    t0 = time.perf_counter()
    result = {"ok": False, "error": None, "screen_xy": None, "seconds": 0.0}
    tool = None
    try:
        tool = action.get("tool")
        if tool == "click":
            sx, sy = _to_screen(desk, action.get("x"), action.get("y"), scale)
            result["screen_xy"] = [sx, sy]
            button = action.get("button", "left")
            if button not in BUTTONS:
                raise ValueError(f'button must be "left" or "right", got {button!r}')
            desk.click(sx, sy, button=BUTTONS[button], double=bool(action.get("double", False)))
        elif tool == "type":
            text = action.get("text")
            if not isinstance(text, str) or not text:
                raise ValueError("text must be a non-empty string")
            if len(text) > MAX_TYPE_CHARS:
                raise ValueError(f"text is longer than {MAX_TYPE_CHARS} characters")
            desk.type_text(text)
        elif tool == "key":
            name = action.get("name")
            key = canonical_key(name)
            if key is None:
                raise ValueError(f"key not allowed: {name}")
            desk.key(key)
        elif tool == "scroll":
            sx, sy = _to_screen(desk, action.get("x"), action.get("y"), scale)
            result["screen_xy"] = [sx, sy]
            dy = _int(action.get("dy"), "dy")
            if dy == 0 or abs(dy) > MAX_SCROLL:
                raise ValueError(f"dy must be between 1 and {MAX_SCROLL} in absolute value")
            _scroll(desk, sx, sy, dy)
        else:
            raise ValueError(f"tool not allowed: {tool}")
        result["ok"] = True
    except ValueError as exc:
        msg = str(exc)
        result["error"] = msg if msg.startswith(("key not allowed:", "tool not allowed:")) else f"{tool} failed: {msg}"
    except Exception as exc:  # noqa: BLE001  (X errors, closed display)
        result["error"] = f"{tool} failed: {type(exc).__name__}: {exc}"
    result["seconds"] = round(time.perf_counter() - t0, 4)
    return result
