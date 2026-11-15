"""Obsidian (Electron, user flatpak md.obsidian.Obsidian) opening the vault ~/Documents/vault (3 notes)."""
from pathlib import Path

from bench.env import app_prep, oracle_kit as kit

VAULT = "Documents/vault"


def prepare(home: Path) -> None:
    app_prep.prep_obsidian(home)             # make_vault (Welcome / Projects / Reading list) + obsidian.json


def argv(home: Path) -> list:
    return app_prep.flatpak_argv("md.obsidian.Obsidian", "--force-renderer-accessibility")


def _env() -> dict:
    return {"ACCESSIBILITY_ENABLED": "1", "FLATPAK_USER_DIR": str(Path.home() / ".local" / "share" / "flatpak")}


def after_start(ep):
    """The window exists long before Electron has built the vault UI ("Loading Obsidian..."): wait for the AT-SPI tree,
    then stretch the real window again."""
    import time
    t0 = time.monotonic()
    while time.monotonic() - t0 < 120:
        if len(ep.atspi()) > 60:
            break
        time.sleep(3)
    for w in ep.windows():
        if w["w"] > 700 and "Obsidian" in w["title"]:
            ep.desk.move_window(w["xid"], 0, 0, 1920, 1080)
    ep.sleep(2.0)


APP = {
    "name": "obsidian",
    "argv": argv,
    "env": _env(),
    "startup_s": 25,
    "shared_runtime_dir": True,           # `flatpak run` needs the real XDG_RUNTIME_DIR (portals, /run/user/<uid>/doc)
    "settle_s": 4,
    "window_title": "Obsidian",
    "process": "obsidian",
    "prepare": prepare,
    "close": "wm_close",
    "state_files": [f"{VAULT}/*.md", f"{VAULT}/**/*.md", f"{VAULT}/.obsidian/*.json"],
    "after_start": after_start,
    "tier": "good",
    "atspi_recall_05": 0.927,
}

def _note(home, rel):
    return kit.file_text(home, f"{VAULT}/{rel}")


def _lines(text):
    return [ln.strip() for ln in (text or "").splitlines()]


# ---------------------------------------------------------------------------------------------- oracles
def oracle_toggle(home):
    text = _note(home, "Projects.md")
    ok = text is not None and "- [x] write report" in text and "- [x] book room" in text
    return ok, f"Projects.md={text!r}"


def oracle_folder(home):
    hit = kit.file_exists(home, f"{VAULT}/Logs")
    return bool(hit) and hit[0].is_dir(), f"vault/Logs exists={bool(hit)}"


def oracle_tide(home):
    text = _note(home, "Tide log.md")
    return text is not None and "Low tide at 06:40" in _lines(text), f"Tide log.md={text!r}"


def oracle_append(home):
    text = _note(home, "Welcome.md")
    ok = text is not None and "Visit the harbor office on 2026-11-20." in _lines(text) and text.startswith("# Welcome")
    return ok, f"Welcome.md={text!r}"


def oracle_rename(home):
    new, old = _note(home, "Harbor Projects.md"), _note(home, "Projects.md")
    ok = new is not None and "- [ ] write report" in new and old is None
    return ok, f"Harbor Projects.md exists={new is not None} Projects.md exists={old is not None}"


def oracle_logs_note(home):
    text = _note(home, "Logs/Tide log.md")
    ls = _lines(text)
    ok = text is not None and "Low tide at 06:40" in ls and "High tide at 19:05" in ls
    return ok, f"Logs/Tide log.md={text!r}"


# ---------------------------------------------------------------------------------------------- positive scripts
def _explorer(ep, name):
    """Node of a file / folder row in the file explorer (left pane)."""
    deadline = 15
    for _ in range(deadline * 2):
        for n in ep.atspi():
            if n["name"].strip() == name and n["box"][0] < 340 and 80 < n["box"][1] < 1000 and n["box"][2] > 0 and "showing" in n["states"]:
                return n
        ep.sleep(0.5)
    raise TimeoutError(f"obsidian: no explorer entry {name!r}")


def _new_note_titled(ep, title):
    ep.type(title)
    ep.sleep(0.4)
    ep.key("Return")
    ep.sleep(0.8)


def _new_folder(ep, name):
    ep.click(164, 60)                       # "New folder" icon above the file list
    ep.sleep(1.0)
    ep.type(name)
    ep.key("Return")
    ep.sleep(1.5)


def pos_toggle(ep):
    ep.click_box(_explorer(ep, "Projects"))
    ep.sleep(2.0)
    boxes = [n for n in ep.atspi() if n["role"] in ("check box", "checkbox") and "showing" in n["states"] and n["box"][0] > 400]
    boxes.sort(key=lambda n: n["box"][1])
    ep.click_box(boxes[0])
    ep.sleep(1.5)


def pos_folder(ep):
    _new_folder(ep, "Logs")


def pos_tide(ep):
    ep.click(1111, 512)                     # "New note" on the empty tab
    ep.sleep(2.0)
    _new_note_titled(ep, "Tide log")
    ep.type("Low tide at 06:40")
    ep.sleep(1.5)


def pos_append(ep):
    ep.click_box(_explorer(ep, "Welcome"))
    ep.sleep(2.0)
    ep.click(1100, 700)                     # empty area under the text: cursor goes to the end
    ep.key("ctrl+End")
    ep.key("Return")
    ep.type("Visit the harbor office on 2026-11-20.")
    ep.sleep(1.5)


def pos_rename(ep):
    ep.click_box(_explorer(ep, "Projects"), button=3)
    ep.sleep(1.0)
    ep.click_node(contains="Rename", timeout=8)
    ep.sleep(1.0)
    ep.key("ctrl+a")
    ep.type("Harbor Projects")
    ep.key("Return")
    ep.sleep(1.5)


def pos_logs_note(ep):
    _new_folder(ep, "Logs")
    ep.click_box(_explorer(ep, "Logs"), button=3)
    ep.sleep(1.0)
    items = [n for n in ep.atspi() if "new note" in n["name"].lower() and n["box"][1] > 100 and n["box"][0] < 340 and n["box"][2] > 0
             and "showing" in n["states"]]                  # the context-menu entry, not the toolbar button at y=60
    ep.click_box(items[0])
    ep.sleep(2.0)
    _new_note_titled(ep, "Tide log")
    ep.type("Low tide at 06:40")
    ep.key("Return")
    ep.type("High tide at 19:05")
    ep.sleep(1.5)


TASKS = [
    {"id": "obsidian_toggle_task", "difficulty": 1,
     "sentence": "In the note Projects, tick the unticked task \"write report\".",
     "setup": None, "oracle": oracle_toggle, "positive": pos_toggle},
    {"id": "obsidian_new_folder", "difficulty": 1,
     "sentence": "Create a new folder named Logs in the vault.",
     "setup": None, "oracle": oracle_folder, "positive": pos_folder},
    {"id": "obsidian_tide_log", "difficulty": 2,
     "sentence": "Create a new note named Tide log and write the line: Low tide at 06:40",
     "setup": None, "oracle": oracle_tide, "positive": pos_tide},
    {"id": "obsidian_append_welcome", "difficulty": 2,
     "sentence": "Open the note Welcome and add a new last line: Visit the harbor office on 2026-11-20.",
     "setup": None, "oracle": oracle_append, "positive": pos_append},
    {"id": "obsidian_rename_note", "difficulty": 2,
     "sentence": "Rename the note Projects to Harbor Projects.",
     "setup": None, "oracle": oracle_rename, "positive": pos_rename},
    {"id": "obsidian_logs_note", "difficulty": 3,
     "sentence": "Create a folder named Logs, create a note named Tide log inside that folder, and write two lines in it: "
                 "Low tide at 06:40 and, on the next line, High tide at 19:05",
     "setup": None, "oracle": oracle_logs_note, "positive": pos_logs_note},
]
