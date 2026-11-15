"""Template for a new app: copy to bench/apps/<name>.py (dashes in the app name become underscores in the file
name: gnome-calendar -> gnome_calendar.py), fill APP, then add TASKS.  registry.py skips files starting with "_".

Order of work (see ../README.md): 1. fill APP and run `selftest --mode noop` on a placeholder task to see which
state_files change; 2. write a task + oracle + positive script; 3. selftest twice.
Keep this file importable without cv2 / Xlib (import heavy modules inside functions).
"""
from pathlib import Path

from bench.env import oracle_kit as kit  # file_text, sqlite_rows, ini_value, xml_find, run_cli, git, ...


def prepare(home: Path) -> None:
    """Create the app's initial files inside the sandbox HOME (deterministic: fixed seeds / dates, no network).
    Runs after bench.env.sandbox.prepare_sandbox (Documents/, Pictures/sample_*.png, Documents/sample.pdf ...)."""


APP = {
    "name": "myapp",                                  # app name; the file is apps/myapp.py
    "argv": lambda home: ["myapp", str(home / "Documents" / "sample.pdf")],   # list or callable(home) -> list
    "env": {},                                        # extra env (QT_ACCESSIBILITY=1 for Qt, ACCESSIBILITY_ENABLED=1 for Electron)
    "startup_s": 8,                                   # seconds the app normally needs; the harness waits this + 45 s
    "window_title": "MyApp",                          # substring of the main window title (WM_NAME / _NET_WM_NAME)
    "process": "myapp",                               # substring of the AT-SPI application name
    "prepare": prepare,                               # callable(home) or None
    "close": "wm_close",                              # "wm_close" | "ctrl+q" | callable(ep)
    "state_files": [".config/myapp/*.conf"],          # globs relative to HOME; documentation + selftest diff
    "tier": "good",                                   # "good" | "poor" (poor = AT-SPI cannot give box coordinates)
    "atspi_recall_05": 0.0,                           # measured AT-SPI recall at IoU 0.5 for this app (informational)
    # optional: "settle_s": 1.5, "no_maximize": True, "daemons": ["evolution-"], "close_prompt": callable(ep),
    #           "after_start": callable(ep)
}


def oracle_example(home: Path):
    text = kit.file_text(home, "Documents/out.txt")
    return (text is not None and text.strip() == "hello", f"Documents/out.txt={text!r}")


def positive_example(ep) -> None:
    ep.click_node(role="push button", name="Save")      # AT-SPI to find coordinates, XTEST to click
    ep.type("hello")


TASKS = [
    # {"id": "myapp_short_name",          # must start with "<app with underscores>_"
    #  "difficulty": 1,                   # 1: 1-3 steps, 2: 4-8 steps, 3: 9+ steps (mouse clicks + typing + Return/Tab/Esc/arrows)
    #  "sentence": "One or two English sentences, every value written out, absolute dates in 2026-11..2026-12.",
    #  "setup": None,                     # callable(home) run before the app starts, or None
    #  "oracle": oracle_example,          # callable(home) -> (bool, detail); must fail on the clean profile
    #  "positive": positive_example},     # callable(ep); may use shortcuts / AT-SPI, never write state files
]
