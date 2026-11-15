"""Nested X11 desktop for agent tasks: real GTK / Qt / Electron apps in Xvfb, screenshots, XTEST input.

  XvfbDesktop.start()     private Xvfb display + private dbus session + sandbox HOME, no window manager
  launch(app)             files / editor / calculator / terminal, logs into <sandbox>/logs/<app>.log
  wait_window / list_windows / move_window   top-level geometry, direct X configure (no WM intercepts)
  screenshot()            mss grab of the nested screen, BGR uint8
  click / type_text / key XTEST injection into the nested display only

Isolation: every child gets DISPLAY of the nested Xvfb, GDK_BACKEND=x11 and a sandboxed HOME; WAYLAND_DISPLAY,
XDG_SESSION_TYPE and any inherited bus address are removed, so nothing can reach the user's real Wayland desktop.
Nothing outside the sandbox directory passed to XvfbDesktop is written (dbus uses its own socket under it).
"""
import argparse
import ctypes
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import cv2
import mss
import numpy as np
from Xlib import X, XK, display as xdisplay, error as xerror
from Xlib.ext import xtest

UNIX_PATH_MAX = 107  # sun_path is 108 bytes including the trailing NUL

try:  # loaded in the parent so the post-fork preexec call never has to dlopen
    _LIBC = ctypes.CDLL("libc.so.6", use_errno=True)
except OSError:
    _LIBC = None


def _die_with_parent():
    """preexec_fn for every child this module starts: SIGTERM it when the calling process dies (PR_SET_PDEATHSIG).

    Keeps the caller's session (no setsid), so the child still dies with a SIGKILL'd caller, unlike a
    --fork daemon that is re-parented to systemd --user. PDEATHSIG follows the forking *thread*, so start and
    launch from the thread that owns the desktop. If the caller died before prctl ran, the child is already
    re-parented to pid 1 and exits at once.
    """
    if _LIBC is not None:
        _LIBC.prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG = 1
    if os.getppid() == 1:
        os._exit(1)

APPS = {
    "files": lambda home: ["nautilus", "--new-window", str(home)],
    "editor": lambda home: ["gnome-text-editor", "--standalone"],
    "calculator": lambda home: ["gnome-calculator"],
    "terminal": lambda home: ["xterm"],
}
# Non-GNOME apps (Qt5/Qt6, Electron). cv2 (imported above) injects Qt plugin
# paths into os.environ; a system Qt app does not start with them, so launch_argv strips them.
STRIP_ENV = ("LD_PRELOAD", "VAX_PROBE_DIR", "QT_QPA_PLATFORM_PLUGIN_PATH", "QT_QPA_FONTDIR", "QT_PLUGIN_PATH")
SYSTEM_PY = "/usr/bin/python3"
# Runs under the system interpreter (only it can import gi.repository.Atspi). Flat DFS dump of the apps
# whose name contains argv[1], showing nodes expanded, capped at argv[2] nodes. Oracle use only: the agent
# never sees this.
ATSPI_QUERY = r"""
import json, sys
import gi
gi.require_version("Atspi", "2.0")
from gi.repository import Atspi
needle = sys.argv[1].lower()
limit = int(sys.argv[2])
STATES = [("showing", Atspi.StateType.SHOWING), ("selected", Atspi.StateType.SELECTED),
          ("checked", Atspi.StateType.CHECKED), ("focused", Atspi.StateType.FOCUSED),
          ("expanded", Atspi.StateType.EXPANDED)]
out = []
def walk(acc, depth):
    if len(out) >= limit or depth > 40:
        return
    try:
        role = acc.get_role_name() or ""
        name = (acc.get_name() or "")[:200]
        ss = acc.get_state_set()
        states = [n for n, st in STATES if ss.contains(st)]
        e = acc.get_extents(Atspi.CoordType.SCREEN)
        box = [int(e.x), int(e.y), int(e.width), int(e.height)]
        count = acc.get_child_count()
    except Exception:
        return
    out.append({"role": role, "name": name, "states": states, "box": box, "depth": depth})
    if "showing" not in states and role != "application":
        return
    for i in range(count):
        try:
            child = acc.get_child_at_index(i)
        except Exception:
            continue
        if child is not None:
            walk(child, depth + 1)
try:
    desktop = Atspi.get_desktop(0)
    for i in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(i)
        if app is not None and needle in (app.get_name() or "").lower():
            walk(app, 0)
except Exception as exc:
    print("atspi_query: %s" % exc, file=sys.stderr)
json.dump(out, sys.stdout)
"""

MODIFIERS = {"ctrl": "Control_L", "alt": "Alt_L", "shift": "Shift_L", "super": "Super_L"}
PUNCT = {
    " ": "space", "/": "slash", ".": "period", ",": "comma", "-": "minus", "_": "underscore",
    ":": "colon", ";": "semicolon", "!": "exclam", "?": "question", "'": "apostrophe",
    '"': "quotedbl", "(": "parenleft", ")": "parenright", "=": "equal", "+": "plus",
    "@": "at", "#": "numbersign", "&": "ampersand", "*": "asterisk", "\n": "Return", "\t": "Tab",
    "~": "asciitilde", "`": "grave", "<": "less", ">": "greater", "|": "bar",
    "\\": "backslash", "[": "bracketleft", "]": "bracketright", "{": "braceleft",
    "}": "braceright", "$": "dollar", "%": "percent", "^": "asciicircum",
}


class XvfbDesktop:
    """A private Xvfb display with a sandboxed HOME and its own dbus session; context-manager friendly."""

    def __init__(self, display=":91", size=(1920, 1080), sandbox=None, private_runtime_dir=False):
        """Remember display/size/sandbox; start() does all the work.

        private_runtime_dir (default False, other callers unchanged): give the desktop its own 0700 XDG_RUNTIME_DIR
        before the session bus starts, force XDG_SESSION_TYPE=x11 and drop WAYLAND_DISPLAY / WAYLAND_SOCKET from
        the bus' own environment too (it is the parent of every bus-activated service: portals, yelp, dolphin ...).
        Without it those services inherit the caller's real wayland-0 / session bus / systemd sockets in
        /run/user/<uid> and an app that opens a URL can start a host browser on the user's real desktop.
        """
        self.private_runtime_dir = bool(private_runtime_dir)
        self.runtime_dir = None
        self._runtime_dir_owned = False
        self.display_name = display
        self.size = size
        if sandbox is None:
            raise ValueError("XvfbDesktop needs a sandbox directory")
        self.sandbox = Path(sandbox)
        self.home = self.sandbox / "home"
        self.env = {}
        self.procs = []
        self.logs = []
        self.bus_pid = None
        self.atspi = False
        self.desktop_id = None
        self.xvfb = None
        self._bus = None  # private session bus Popen; kept out of self.procs so _stop_apps() leaves it alone
        self._display = None
        self._stopped = False

    # ---------------------------------------------------------------- lifecycle
    def start(self):
        """Start Xvfb, build the sandbox, start a private session bus and assemble self.env."""
        number = re.search(r":(\d+)", self.display_name)
        if not number:
            raise ValueError(f"display must look like :N, got {self.display_name!r}")
        if Path(f"/tmp/.X11-unix/X{number.group(1)}").exists():
            raise RuntimeError(f"display {self.display_name} is already in use")
        W, H = self.size
        self.xvfb = subprocess.Popen(
            ["Xvfb", self.display_name, "-screen", "0", f"{W}x{H}x24", "-nolisten", "tcp"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=_die_with_parent)
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            try:
                self._display = xdisplay.Display(self.display_name)
                self._display.screen().root.query_tree()
                break
            except Exception:
                self._display = None
                time.sleep(0.05)
        if self._display is None:
            raise RuntimeError(f"Xvfb {self.display_name} did not become connectable")

        for d in [self.home, self.home / ".config", self.home / ".local/share", self.home / ".cache",
                  self.home / ".local/state", self.home / "Projects/vax-demo/notes",
                  self.home / "Documents/reports", self.sandbox / "logs"]:
            d.mkdir(parents=True, exist_ok=True)
        (self.home / "Projects/vax-demo/notes/meeting-notes.txt").write_text(
            "Meeting notes: ship the release, review the desktop harness.\n")
        (self.home / "Documents/reports/weekly-report.txt").write_text(
            "Weekly report: the nested Xvfb desktop is up.\n")

        # unique per desktop: _reap_sandbox_procs matches on it, so a previous attempt's late cleanup
        # (same sandbox path) cannot kill the next attempt's apps. Set before the bus so that the services it
        # activates (gvfsd, portals) inherit it and can be reaped with the rest of the desktop.
        self.desktop_id = f"{os.getpid()}-{time.time_ns()}"
        if self.private_runtime_dir:
            self.runtime_dir = self._make_runtime_dir()
        address = self._start_bus()

        env = os.environ.copy()
        for key in ("WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "XDG_SESSION_TYPE"):
            env.pop(key, None)
        if self.runtime_dir is not None:
            env.pop("WAYLAND_SOCKET", None)
            env.update(XDG_RUNTIME_DIR=str(self.runtime_dir), XDG_SESSION_TYPE="x11")
        env.update(
            DISPLAY=self.display_name, GDK_BACKEND="x11", GSK_RENDERER="cairo", GSETTINGS_BACKEND="memory",
            HOME=str(self.home), XDG_CONFIG_HOME=str(self.home / ".config"),
            XDG_DATA_HOME=str(self.home / ".local/share"), XDG_CACHE_HOME=str(self.home / ".cache"),
            XDG_STATE_HOME=str(self.home / ".local/state"), NO_AT_BRIDGE="1",
            DBUS_SESSION_BUS_ADDRESS=address)
        env["VAX_DESKTOP_ID"] = self.desktop_id
        self.env = env
        return self

    def _start_bus(self):
        """Start the private session bus as a child that dies with this process; return its address.

        --nofork keeps dbus-daemon as our child (no re-parenting to systemd --user), so stop() and
        _die_with_parent both reach it. The socket lives in the sandbox unless the path is too long for a
        unix socket, in which case an abstract socket is used.
        """
        sock = self.sandbox / "bus.sock"
        if len(os.fsencode(str(sock))) > UNIX_PATH_MAX:
            address = f"unix:abstract=vax-bus-{os.getpid()}-{time.time_ns()}"
        else:
            if sock.is_socket():  # stale socket left by a killed desktop in this same sandbox
                sock.unlink()
            address = f"unix:path={sock}"
        self._bus = subprocess.Popen(
            ["dbus-daemon", "--session", "--nofork", "--address", address, "--print-address=1"],
            env=self._bus_env(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, preexec_fn=_die_with_parent)
        self.bus_pid = self._bus.pid
        printed = self._bus.stdout.readline().strip()
        if not printed.startswith("unix:"):
            self._stop_bus()
            raise RuntimeError(f"dbus-daemon printed no address (got {printed!r})")
        return printed

    def _stop_bus(self):
        """Terminate the private session bus (if any) and forget its pid."""
        if self._bus is not None:
            self._terminate(self._bus)
            try:
                self._bus.stdout.close()
            except Exception:
                pass
            self._bus = None
        self.bus_pid = None

    def _bus_env(self):
        """Environment for dbus-daemon itself: drop any inherited bus address, tag it with this desktop's id.

        With private_runtime_dir the bus also gets the sandbox view of the session (no Wayland, x11 session type,
        private XDG_RUNTIME_DIR, sandbox HOME / XDG dirs, the nested DISPLAY): everything it activates inherits it.
        """
        env = os.environ.copy()
        env.pop("DBUS_SESSION_BUS_ADDRESS", None)
        if self.desktop_id:
            env["VAX_DESKTOP_ID"] = self.desktop_id
        if self.runtime_dir is not None:
            env.pop("WAYLAND_DISPLAY", None)
            env.pop("WAYLAND_SOCKET", None)
            env.update(XDG_RUNTIME_DIR=str(self.runtime_dir), XDG_SESSION_TYPE="x11", GDK_BACKEND="x11",
                       DISPLAY=self.display_name, HOME=str(self.home), XDG_CONFIG_HOME=str(self.home / ".config"),
                       XDG_DATA_HOME=str(self.home / ".local/share"), XDG_CACHE_HOME=str(self.home / ".cache"),
                       XDG_STATE_HOME=str(self.home / ".local/state"))
        return env

    def _make_runtime_dir(self):
        """A fresh 0700 directory for this desktop's XDG_RUNTIME_DIR (sockets of the nested session live here).

        Inside the sandbox when the path is short enough for unix sockets under it (at-spi/bus_N, dconf, ...);
        otherwise a mkdtemp directory under /tmp, removed again by stop().
        """
        inside = self.sandbox / "run"
        if len(os.fsencode(str(inside))) + 24 <= UNIX_PATH_MAX:
            shutil.rmtree(inside, ignore_errors=True)
            inside.mkdir(parents=True)
            inside.chmod(0o700)
            self._runtime_dir_owned = False
            return inside
        path = Path(tempfile.mkdtemp(prefix="vax-rt-"))
        path.chmod(0o700)
        self._runtime_dir_owned = True
        return path

    def stop(self):
        """Terminate apps, dbus and Xvfb; safe to call more than once."""
        if self._stopped:
            return
        self._stopped = True
        for proc in self.procs:
            self._terminate(proc)
        self.procs = []
        for fh in self.logs:
            try:
                fh.close()
            except Exception:
                pass
        self.logs = []
        self._stop_bus()
        if self.atspi:
            self._reap_sandbox_procs()
        if self._display is not None:
            try:
                self._display.close()
            except Exception:
                pass
            self._display = None
        if self.xvfb is not None:
            self._terminate(self.xvfb)
            self.xvfb = None
        if self.desktop_id:
            # the bus is gone, so the services it activated are exiting; reap whatever still carries our id
            self._reap_sandbox_procs()
        if self.runtime_dir is not None and self._runtime_dir_owned:
            shutil.rmtree(self.runtime_dir, ignore_errors=True)

    def __enter__(self):
        """start() and return self."""
        return self.start()

    def __exit__(self, *exc):
        """stop()."""
        self.stop()

    @staticmethod
    def _terminate(proc, timeout=2.0):
        """Terminate a Popen, killing it after `timeout` seconds if needed."""
        if proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                pass

    def _reap_sandbox_procs(self):
        """Kill leftovers (accessibility bus, registryd, app helpers) that still carry this desktop's id."""
        needle = f"VAX_DESKTOP_ID={self.desktop_id}".encode()
        for sig in (signal.SIGTERM, signal.SIGKILL):
            victims = []
            for entry in Path("/proc").iterdir():
                if not entry.name.isdigit() or int(entry.name) == os.getpid():
                    continue
                try:
                    if needle in (entry / "environ").read_bytes().split(b"\0"):
                        victims.append(int(entry.name))
                except OSError:
                    continue
            for pid in victims:
                try:
                    os.kill(pid, sig)
                except ProcessLookupError:
                    pass
            if sig == signal.SIGTERM and victims:
                time.sleep(0.5)

    # ---------------------------------------------------------------- AT-SPI (oracle only)
    def enable_atspi(self):
        """Start the private accessibility bus so Chromium/Qt apps register with AT-SPI.

        Only the oracle reads it (atspi_nodes); the agent only ever sees the detector's tree. GNOME tasks
        never call this, so their environment stays as before (NO_AT_BRIDGE=1).
        """
        self.env.pop("NO_AT_BRIDGE", None)
        env = {k: v for k, v in self.env.items() if k not in STRIP_ENV}
        bus = subprocess.Popen(["/usr/libexec/at-spi-bus-launcher", "--launch-immediately"], env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=_die_with_parent)
        self.procs.append(bus)
        self.atspi = True
        time.sleep(1.0)

    def atspi_nodes(self, app_substr, limit=4000, timeout=20.0):
        """Flat AT-SPI dump [{role,name,states,box,depth}] of apps whose name contains `app_substr`; [] on failure."""
        env = {k: v for k, v in self.env.items() if k not in STRIP_ENV}
        try:
            result = subprocess.run([SYSTEM_PY, "-c", ATSPI_QUERY, app_substr, str(limit)], env=env,
                                    capture_output=True, text=True, timeout=timeout)
            return json.loads(result.stdout or "[]")
        except (subprocess.TimeoutExpired, ValueError, OSError):
            return []

    # ---------------------------------------------------------------- apps
    def launch_argv(self, name, argv, extra_env=None, cwd=None):
        """Start an arbitrary app with the stripped env plus `extra_env`; logs to logs/<name>.log."""
        log_path = self.sandbox / "logs" / f"{name}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(log_path, "ab")
        self.logs.append(fh)
        env = {k: v for k, v in self.env.items() if k not in STRIP_ENV}
        env.update(extra_env or {})
        proc = subprocess.Popen([str(a) for a in argv], env=env, cwd=cwd, stdin=subprocess.DEVNULL,
                                stdout=fh, stderr=subprocess.STDOUT, preexec_fn=_die_with_parent)
        self.procs.append(proc)
        return proc

    def launch(self, app, args=()):
        """Start one of APPS under self.env (extra argv appended), log to <sandbox>/logs/<app>.log, return the Popen."""
        if app not in APPS:
            raise ValueError(f"unknown app {app!r}; expected one of {sorted(APPS)}")
        log_path = self.sandbox / "logs" / f"{app}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(log_path, "ab")
        self.logs.append(fh)
        proc = subprocess.Popen(APPS[app](self.home) + [str(a) for a in args], env=self.env,
                                stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT,
                                preexec_fn=_die_with_parent)
        self.procs.append(proc)
        return proc

    def _stop_apps(self):
        """Terminate all launched apps and wait until their windows are gone."""
        for proc in self.procs:
            self._terminate(proc)
        self.procs = []
        time.sleep(0.7)

    # ---------------------------------------------------------------- windows
    def list_windows(self, net_names=False):
        """Viewable top-level windows, top of the X stack first, as {xid,title,x,y,w,h} in root coordinates.

        Titles come from WM_NAME. Chromium/Electron only set _NET_WM_NAME, so `net_names=True` (the Electron
        apps) falls back to it when WM_NAME is empty; the default keeps the GNOME tasks' titles unchanged.
        """
        root = self._display.screen().root
        out = []
        for win in reversed(root.query_tree().children):
            try:
                attrs = win.get_attributes()
                if attrs.map_state != X.IsViewable:
                    continue
                geo = win.get_geometry()
                pos = root.translate_coords(win, 0, 0)
                try:
                    title = win.get_wm_name() or ""
                except xerror.XError:
                    title = ""
                if not title and net_names:
                    title = self._net_wm_name(win)
                out.append({"xid": win.id, "title": title, "x": pos.x, "y": pos.y,
                            "w": geo.width, "h": geo.height})
            except xerror.XError:
                continue
        return out

    def _net_wm_name(self, win):
        """_NET_WM_NAME (UTF-8) of a window, or "" when unset."""
        try:
            atom = self._display.intern_atom("_NET_WM_NAME")
            prop = win.get_full_property(atom, 0)
        except xerror.XError:
            return ""
        if prop is None or not prop.value:
            return ""
        value = prop.value
        return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)

    def wait_window(self, title_substr=None, timeout=20.0):
        """Wait for a window whose title contains `title_substr` (or any extra window when None) and return it."""
        baseline = len(self.list_windows())
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            windows = self.list_windows()
            if title_substr is None:
                if len(windows) > baseline:
                    return windows[0]
            else:
                for win in windows:
                    if title_substr in win["title"]:
                        return win
            time.sleep(0.1)
        raise TimeoutError(f"no window matching {title_substr!r} within {timeout}s; "
                           f"windows={self.list_windows()}")

    def move_window(self, xid, x, y, w=None, h=None):
        """Configure a top-level window's position (and optionally size) directly, then sync."""
        win = self._display.create_resource_object("window", xid)
        opts = {"x": x, "y": y}
        if w is not None:
            opts["width"] = w
        if h is not None:
            opts["height"] = h
        win.configure(**opts)
        self._display.sync()

    def _window_at(self, x, y):
        """Topmost viewable window containing the root point, or None."""
        for win in self.list_windows():
            if win["x"] <= x < win["x"] + win["w"] and win["y"] <= y < win["y"] + win["h"]:
                return win
        return None

    # ---------------------------------------------------------------- screen
    def screenshot(self):
        """Grab the nested screen with mss and return a BGR uint8 array."""
        with mss.MSS(display=self.display_name) as s:
            shot = np.asarray(s.grab(s.monitors[1]))
        return np.ascontiguousarray(shot[:, :, :3])

    # ---------------------------------------------------------------- input
    def click(self, x, y, button=1, double=False):
        """XTEST click at root (x, y), then raise/focus the window under it like a click-to-focus WM."""
        xtest.fake_input(self._display, X.MotionNotify, x=x, y=y)
        for i in range(2 if double else 1):
            if i:
                time.sleep(0.08)
            xtest.fake_input(self._display, X.ButtonPress, button)
            xtest.fake_input(self._display, X.ButtonRelease, button)
        self._display.sync()
        win = self._window_at(x, y)
        if win is not None:
            obj = self._display.create_resource_object("window", win["xid"])
            try:
                obj.configure(stack_mode=X.Above)
                self._display.set_input_focus(obj, X.RevertToParent, X.CurrentTime)
            except xerror.XError:
                pass
            self._display.sync()

    def _press(self, keycode):
        """XTEST key press and release."""
        xtest.fake_input(self._display, X.KeyPress, keycode)
        xtest.fake_input(self._display, X.KeyRelease, keycode)

    def type_text(self, text):
        """Type text character by character through XTEST, shifting when the keysym is not at level 0."""
        shift = self._display.keysym_to_keycode(XK.string_to_keysym("Shift_L"))
        for ch in text:
            name = PUNCT.get(ch, ch if ch.isalnum() else None)
            if name is None:
                raise ValueError(f"no keysym mapping for {ch!r}")
            keysym = XK.string_to_keysym(name)
            keycode = self._display.keysym_to_keycode(keysym)
            if keycode == 0:
                raise ValueError(f"no keycode for {ch!r} (keysym {name})")
            need_shift = self._display.keycode_to_keysym(keycode, 0) != keysym
            if need_shift:
                xtest.fake_input(self._display, X.KeyPress, shift)
            self._press(keycode)
            if need_shift:
                xtest.fake_input(self._display, X.KeyRelease, shift)
            self._display.sync()
            time.sleep(0.01)

    def key(self, combo):
        """Press a key combo such as "Return", "ctrl+l", "ctrl+comma", "alt+F4"."""
        parts = [p.strip() for p in combo.split("+")]
        if not parts or any(not p for p in parts):
            raise ValueError(f"bad key combo {combo!r}")
        mods = []
        for part in parts[:-1]:
            mods.append(XK.string_to_keysym(MODIFIERS.get(part.lower(), part)))
        keysym = XK.string_to_keysym(parts[-1])
        keycode = self._display.keysym_to_keycode(keysym)
        if keycode == 0 or any(m == 0 for m in mods):
            raise ValueError(f"unknown keysym in {combo!r}")
        codes = [self._display.keysym_to_keycode(m) for m in mods]
        for code in codes:
            xtest.fake_input(self._display, X.KeyPress, code)
        self._press(keycode)
        for code in reversed(codes):
            xtest.fake_input(self._display, X.KeyRelease, code)
        self._display.sync()

