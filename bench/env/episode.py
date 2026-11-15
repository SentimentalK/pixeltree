"""Episode = one fresh desktop (Xvfb + private dbus + AT-SPI bus + sandbox HOME) with one app running.

    ep = start_episode("gitg", ":130", Path("/some/dir/ep0"), task_id="gitg_new_branch")
    ...agent / positive script drives ep.desk (click, type_text, key, screenshot)...
    ep.close_app()           # graceful close so the app writes its state to disk
    ok, detail = oracle(task_id, ep.home)
    ep.stop()                # Xvfb, dbus, helper processes; the sandbox HOME stays on disk

`root` is wiped when it holds an earlier episode (marker file `.p125_episode`, a historical name); anything else raises.
`root/home` is the sandbox HOME, `root/episode_env.json` records the environment of the episode so that
oracle_kit.run_cli can talk to the same dbus session afterwards.

Heavy imports (cv2, Xlib via bench.env.desktop) happen inside start_episode, so the registry and
the oracles import in any Python.  Run it with a Python that has cv2, python-xlib and mss; AT-SPI queries run in the
system /usr/bin/python3 (done by XvfbDesktop.atspi_nodes).
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MARKER = ".p125_episode"
SIZE = (1920, 1080)
# cv2 exports its own Qt plugin dir into os.environ; a Qt app that loads cv2's xcb plugin aborts (found while building the first app set).
STRIP = ("LD_PRELOAD", "VAX_PROBE_DIR", "QT_QPA_PLATFORM_PLUGIN_PATH", "QT_QPA_FONTDIR", "QT_PLUGIN_PATH")
ENV_KEYS = ("TMPDIR", "HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR",
            "XDG_SESSION_TYPE", "DBUS_SESSION_BUS_ADDRESS", "DBUS_SYSTEM_BUS_ADDRESS", "DISPLAY", "GDK_BACKEND",
            "GSETTINGS_BACKEND", "VAX_DESKTOP_ID", "PATH", "LANG", "LC_ALL")


@dataclass
class Episode:
    app: str                       # app name, e.g. "gitg"
    config: dict                   # the APP dict of apps/<app>.py
    desk: Any                      # bench.env.desktop.XvfbDesktop
    root: Path
    home: Path
    proc: Any = None               # subprocess.Popen of the app
    task_id: str | None = None
    window: dict | None = None     # {xid,title,x,y,w,h} of the main window after the start
    started_at: float = field(default_factory=time.time)
    startup_seconds: float = 0.0
    tmpdir: Path | None = None     # private TMPDIR of the episode (single-instance sockets of KeePassXC & co live in /tmp)
    _stopped: bool = False

    @property
    def pid(self) -> int | None:
        return self.proc.pid if self.proc is not None else None

    # ------------------------------------------------------------------ convenience (used by positive scripts)
    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def windows(self) -> list[dict]:
        return self.desk.list_windows(net_names=True)

    def screenshot(self):
        return self.desk.screenshot()

    def save_screenshot(self, path) -> Path:
        import cv2
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(path), self.desk.screenshot())
        return path

    def atspi(self, limit: int = 4000) -> list[dict]:
        """Flat AT-SPI dump of this app: [{role,name,states,box=[x,y,w,h],depth}] (oracle/positive use only)."""
        return self.desk.atspi_nodes(self.config.get("process") or self.app, limit=limit)

    def find(self, role=None, name=None, contains=None, nth=0, showing=True):
        """First (or nth) AT-SPI node with this role / exact name / name substring; None when absent."""
        hits = []
        for n in self.atspi():
            if showing and "showing" not in n["states"]:
                continue
            if role and n["role"] != role:
                continue
            if name is not None and n["name"].strip() != name:
                continue
            if contains is not None and contains.lower() not in n["name"].lower():
                continue
            if n["box"][2] <= 0 or n["box"][3] <= 0:
                continue
            hits.append(n)
        return hits[nth] if len(hits) > nth else None

    def wait_node(self, role=None, name=None, contains=None, timeout=15.0, nth=0):
        """Poll AT-SPI until the node shows up; raises TimeoutError."""
        deadline = time.monotonic() + timeout
        while True:
            node = self.find(role=role, name=name, contains=contains, nth=nth)
            if node is not None:
                return node
            if time.monotonic() > deadline:
                raise TimeoutError(f"{self.app}: no AT-SPI node role={role!r} name={name!r} contains={contains!r}")
            time.sleep(0.5)

    def nodes_in(self, container, role=None, nodes=None) -> list[dict]:
        """Showing AT-SPI nodes whose box lies inside `container` (a node or [x,y,w,h]), optionally of one role."""
        cx, cy, cw, ch = container["box"] if isinstance(container, dict) else container
        out = []
        for n in (nodes if nodes is not None else self.atspi()):
            x, y, w, h = n["box"]
            if "showing" in n["states"] and w > 0 and h > 0 and x >= cx and y >= cy and x + w <= cx + cw and y + h <= cy + ch:
                if role is None or n["role"] == role:
                    out.append(n)
        return out

    def click_box(self, node_or_box, dx=0.5, dy=0.5, **kw):
        box = node_or_box["box"] if isinstance(node_or_box, dict) else node_or_box
        x, y, w, h = box
        self.desk.click(int(x + w * dx), int(y + h * dy), **kw)

    def click_node(self, role=None, name=None, contains=None, nth=0, timeout=15.0, **kw):
        node = self.wait_node(role=role, name=name, contains=contains, timeout=timeout, nth=nth)
        self.click_box(node, **kw)
        return node

    def click(self, x, y, **kw):
        self.desk.click(int(x), int(y), **kw)

    def hover_click(self, x, y, **kw):
        """Move the pointer first, wait, then click: GTK4 widgets can ignore a press that arrives with the enter event."""
        from Xlib import X
        from Xlib.ext import xtest
        xtest.fake_input(self.desk._display, X.MotionNotify, x=int(x), y=int(y))
        self.desk._display.sync()
        time.sleep(0.35)
        self.desk.click(int(x), int(y), **kw)

    def type(self, text, delay=0.0):
        self.desk.type_text(text)
        if delay:
            time.sleep(delay)

    def key(self, combo):
        self.desk.key(combo)

    def select_all_and_type(self, text):
        """Replace the content of the focused text field."""
        self.desk.key("ctrl+a")
        self.desk.type_text(text)

    # ------------------------------------------------------------------ lifecycle
    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def close_app(self, timeout: float = 10) -> None:
        """Close the app the way its config says, wait for exit, SIGTERM after `timeout` seconds."""
        mode = self.config.get("close", "wm_close")
        deadline = time.monotonic() + timeout
        if self.alive():
            try:
                if callable(mode):
                    mode(self)
                elif mode == "ctrl+q":
                    self._focus_main()
                    self.desk.key("ctrl+q")
                else:
                    self.close_windows()
            except Exception as exc:  # noqa: BLE001  (a failing close must still end in the SIGTERM fallback)
                (self.root / "close_error.txt").write_text(f"{type(exc).__name__}: {exc}\n")
            while time.monotonic() < deadline and self.alive():
                self._answer_close_prompts()
                time.sleep(0.2)
        if self.alive():
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.wait_for_background_writers()

    def _focus_main(self):
        wins = self.desk.list_windows(net_names=True)
        if wins:
            w = wins[0]
            self.desk.click(w["x"] + w["w"] // 2, w["y"] + w["h"] // 2)

    def close_windows(self) -> int:
        """Send WM_DELETE_WINDOW to every viewable top-level window (the 'window close button' of a WM)."""
        from Xlib import X, protocol
        d = self.desk._display
        proto, delete = d.intern_atom("WM_PROTOCOLS"), d.intern_atom("WM_DELETE_WINDOW")
        count = 0
        for w in self.desk.list_windows():
            win = d.create_resource_object("window", w["xid"])
            ev = protocol.event.ClientMessage(window=win, client_type=proto, data=(32, [delete, X.CurrentTime, 0, 0, 0]))
            win.send_event(ev, event_mask=X.NoEventMask)
            count += 1
        d.sync()
        return count

    def _answer_close_prompts(self):
        """Nothing by default; per-app configs can add a 'close_prompt' callable(ep) for 'save changes?' dialogs."""
        fn = self.config.get("close_prompt")
        if callable(fn) and len(self.desk.list_windows()) > 0:
            try:
                fn(self)
            except Exception:  # noqa: BLE001
                pass

    def wait_for_background_writers(self, seconds: float = 1.0):
        """Give daemons that persist on behalf of the app (EDS) a moment, then stop them so files are flushed."""
        names = self.config.get("daemons") or []
        if names:
            kill_tagged(self.desk.desktop_id, names)
        time.sleep(seconds if names else 0.3)

    def stop(self) -> None:
        """Stop Xvfb, dbus, AT-SPI bus and every process of this episode; the sandbox HOME stays."""
        if self._stopped:
            return
        self._stopped = True
        try:
            if self.alive():
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
        finally:
            try:
                self.desk.stop()
            finally:
                from bench.env import sandbox
                sandbox.reap_sandbox(self.root)
                if self.tmpdir is not None:
                    shutil.rmtree(self.tmpdir, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stop()


def kill_tagged(desktop_id: str, name_substrings, grace: float = 2.0) -> list[int]:
    """SIGTERM (then SIGKILL) processes carrying this desktop's id whose cmdline matches a substring."""
    needle = f"VAX_DESKTOP_ID={desktop_id}".encode()
    victims = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            env = (entry / "environ").read_bytes().split(b"\0")
            cmd = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except OSError:
            continue
        if needle in env and any(s in cmd for s in name_substrings):
            victims.append(int(entry.name))
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for pid in victims:
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass
        if sig == signal.SIGTERM and victims:
            end = time.monotonic() + grace
            while time.monotonic() < end and any(Path(f"/proc/{p}").exists() for p in victims):
                time.sleep(0.1)
    return victims


def load_config(app: str) -> dict:
    """APP dict of bench/apps/<app>.py (module names use underscores)."""
    import importlib
    name = app.replace("-", "_")
    mod = importlib.import_module(f"bench.apps.{name}")
    return mod.APP


def _wipe_root(root: Path) -> None:
    if root.exists():
        if any(root.iterdir()) and not (root / MARKER).exists():
            raise RuntimeError(f"{root} is not empty and not an episode root; refusing to wipe it")
        shutil.rmtree(root)
    root.mkdir(parents=True)
    (root / MARKER).write_text("episode root, safe to wipe\n")


def _dummy_system_bus(desk) -> None:
    """Private dummy system bus (apps that talk to a system service stay alive without the real one)."""
    name = f"vax-system-{os.getpid()}-{desk.display_name.lstrip(':')}-{time.monotonic_ns()}"
    env = {k: v for k, v in desk.env.items() if k not in STRIP + ("DBUS_SYSTEM_BUS_ADDRESS",)}
    bus = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--address", f"unix:abstract={name}",
                            "--print-address=1"], env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           text=True)
    address = bus.stdout.readline().strip()
    desk.procs.append(bus)
    desk.env["DBUS_SYSTEM_BUS_ADDRESS"] = address or f"unix:abstract={name}"


def _write_env(ep_root: Path, env: dict) -> None:
    keep = {k: v for k, v in env.items() if k in ENV_KEYS}
    (ep_root / "episode_env.json").write_text(json.dumps(keep, indent=1))


def start_episode(app: str, display: str, root: Path, task_id: str | None = None,
                  wait_window: bool = True) -> Episode:
    """Fresh sandbox + Xvfb(1920x1080) + private dbus + AT-SPI bus; run prepare (+ the task's setup); start the app.

    Waits for the app window (title substring of the config) and stretches it to the whole screen.
    """
    from bench.env import desktop as desktop_env
    from bench.env import registry, sandbox

    config = load_config(app)
    task = registry.get_task(task_id) if task_id else None
    if task is not None and task["app"] != app:
        raise ValueError(f"task {task_id} belongs to {task['app']}, not {app}")
    root = Path(root).resolve()
    _wipe_root(root)
    desk = desktop_env.XvfbDesktop(display=display, size=SIZE, sandbox=root,
                                 private_runtime_dir=not config.get("shared_runtime_dir"))   # flatpak apps need the real one
    # APP["session_env"]: variables that must reach the whole session, incl. daemons activated by the bus (EDS reads TZ)
    session_env = dict(config.get("session_env") or {})
    saved = {k: os.environ.get(k) for k in session_env}
    os.environ.update(session_env)
    try:
        desk.start()
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    desk.env.update(session_env)
    ep = Episode(app=app, config=config, desk=desk, root=root, home=desk.home, task_id=task_id)
    try:
        sandbox.prepare_sandbox(desk.home)                       # deterministic: Documents/Pictures/sample.pdf ... (seed 7)
        if config.get("prepare"):
            config["prepare"](desk.home)
        if task is not None and task.get("setup"):
            task["setup"](desk.home)
        _dummy_system_bus(desk)
        desk.enable_atspi()
        # KeePassXC (and other single-instance apps) keep their lock + socket in $TMPDIR (/tmp by default), which would
        # connect episodes - and other people's sandboxes - with each other: a private, short TMPDIR per episode.
        ep.tmpdir = Path(tempfile.mkdtemp(prefix="p125-tmp-"))
        env = {"TMPDIR": str(ep.tmpdir), **(config.get("env") or {})}
        argv = config["argv"](desk.home) if callable(config["argv"]) else list(config["argv"])
        _write_env(root, {**desk.env, **env})
        t0 = time.monotonic()
        ep.proc = desk.launch_argv(app, argv, extra_env=env, cwd=str(desk.home))
        if wait_window:
            ep.window = _wait_main_window(ep, config)
            ep.startup_seconds = time.monotonic() - t0
            time.sleep(float(config.get("settle_s", 1.5)))
            _maximize(ep)
            time.sleep(0.7)
        if config.get("after_start"):
            config["after_start"](ep)
    except BaseException:
        ep.stop()
        raise
    return ep


def _wait_main_window(ep: Episode, config: dict) -> dict:
    needle = config.get("window_title", "")
    deadline = time.monotonic() + float(config.get("startup_s", 10)) + 45
    while time.monotonic() < deadline:
        if not ep.alive():
            log = ep.root / "logs" / f"{ep.app}.log"
            tail = log.read_text(errors="replace")[-600:] if log.exists() else ""
            raise RuntimeError(f"{ep.app} exited rc={ep.proc.returncode} before a window appeared: {tail}")
        for w in ep.desk.list_windows(net_names=True):
            if needle in w["title"] and w["w"] > 200 and w["h"] > 150:
                return w
        time.sleep(0.3)
    raise TimeoutError(f"{ep.app}: no window with title containing {needle!r}; windows={ep.desk.list_windows(net_names=True)}")


def _maximize(ep: Episode) -> None:
    """No window manager: stretch the main window over the 1920x1080 screen (undecorated apps keep working)."""
    w = ep.window
    if config_skip_maximize(ep.config):
        return
    try:
        ep.desk.move_window(w["xid"], 0, 0, SIZE[0], SIZE[1])
    except Exception:  # noqa: BLE001
        return
    ep.window = dict(w, x=0, y=0, w=SIZE[0], h=SIZE[1])


def config_skip_maximize(config: dict) -> bool:
    return bool(config.get("no_maximize"))
