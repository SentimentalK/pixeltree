"""KeePassXC (Qt5) on a key-file-only database ~/Documents/test.kdbx (keyfile ~/Documents/test.keyx)."""
import subprocess
from pathlib import Path

from bench.env import oracle_kit as kit

DB, KEY = "Documents/test.kdbx", "Documents/test.keyx"


def _cli(home: Path, *args: str, stdin: str = "") -> None:
    subprocess.run(["keepassxc-cli", *args], input=stdin, text=True, check=True, capture_output=True, timeout=60,
                   env={"PATH": "/usr/bin:/bin", "HOME": str(home), "QT_QPA_PLATFORM": "offscreen"})


def prepare(home: Path) -> None:
    """Key-file-only database with no entries (deterministic key file is random but irrelevant)."""
    base = home / "Documents"
    base.mkdir(parents=True, exist_ok=True)
    for f in (DB, KEY):
        (home / f).unlink(missing_ok=True)
    _cli(home, "db-create", "--set-key-file", str(home / KEY), "--decryption-time", "100", str(home / DB))


def add_entries(home: Path, *entries) -> None:
    """entries: (title, username[, url]) tuples added with keepassxc-cli (setup only)."""
    for e in entries:
        title, user = e[0], e[1]
        args = ["add", "--no-password", "-k", str(home / KEY), "-u", user]
        if len(e) > 2:
            args += ["--url", e[2]]
        _cli(home, *args, str(home / DB), title)


APP = {
    "name": "keepassxc",
    "argv": lambda home: ["keepassxc", "--keyfile", str(home / KEY), str(home / DB)],
    "env": {"QT_ACCESSIBILITY": "1", "QT_LINUX_ACCESSIBILITY_ALWAYS_ON": "1"},
    "startup_s": 6,
    "window_title": "KeePassXC",
    "process": "keepassxc",
    "prepare": prepare,
    "close": "wm_close",
    "state_files": [DB, ".config/keepassxc/*.ini", ".cache/keepassxc/*.ini"],
    "tier": "good",
    "atspi_recall_05": 0.648,
}


# ---------------------------------------------------------------------------------------------- oracle helpers
def _show(home, entry):
    """{attribute: value} of `keepassxc-cli show -s <entry>` or None when the entry (or the db) cannot be read."""
    out = kit.keepass_cli(home, DB, KEY, "show", "-s", entry)
    if out is None:
        return None
    fields = {}
    for line in out.splitlines():
        if ": " in line:
            k, v = line.split(": ", 1)
            fields[k.strip()] = v.strip()
        elif line.endswith(":"):
            fields[line[:-1].strip()] = ""
    return fields


def _ls(home, *extra):
    out = kit.keepass_cli(home, DB, KEY, "ls", *extra)
    return None if out is None else [ln.strip() for ln in out.splitlines() if ln.strip()]


def setup_entries(home: Path) -> None:
    add_entries(home, ("Old Router", "admin"), ("Dock Server", "ops"), ("Harbor Cam", "viewer"))


# ---------------------------------------------------------------------------------------------- oracles
def oracle_backup(home):
    value = kit.ini_value(home, ".config/keepassxc/keepassxc.ini", "General", "BackupBeforeSave")
    return value == "true", f"keepassxc.ini [General] BackupBeforeSave={value!r}"


def oracle_delete(home):
    root = _ls(home)
    ok = root is not None and "Old Router" not in root and "Dock Server" in root and "Harbor Cam" in root
    return ok, f"root listing={root!r}"


def oracle_add_entry(home):
    e = _show(home, "Harbor Wifi")
    ok = e is not None and e.get("Title") == "Harbor Wifi" and e.get("UserName") == "dock-admin"
    return ok, f"entry Harbor Wifi -> {None if e is None else {k: e.get(k) for k in ('Title', 'UserName')}!r}"


def oracle_new_group(home):
    root = _ls(home)
    return root is not None and "Marina Logins/" in root, f"root listing={root!r}"


def oracle_add_url(home):
    e = _show(home, "Dock Server")
    ok = (e is not None and e.get("URL") == "https://dock.example.net" and e.get("UserName") == "ops"
          and e.get("Title") == "Dock Server")
    return ok, f"Dock Server -> {None if e is None else {k: e.get(k) for k in ('Title', 'UserName', 'URL')}!r}"


def oracle_group_entry(home):
    e = _show(home, "Berths/Slip 14")
    ok = (e is not None and e.get("UserName") == "berth-14" and e.get("Password") == "Tide!2026-Slip")
    return ok, f"Berths/Slip 14 -> {None if e is None else {k: e.get(k) for k in ('Title', 'UserName', 'Password')}!r}"


# ---------------------------------------------------------------------------------------------- positive scripts
def _new_entry(ep):
    ep.click_node(role="button", name="New Entry…")
    ep.wait_node(role="text", name="Title field")


def _fill(ep, field_name, text, role="text"):
    ep.click_node(role=role, name=field_name)
    ep.type(text)


def _ok(ep):
    ep.click_node(role="button", name="OK")
    ep.sleep(1.5)


def pos_backup(ep):
    ep.click_node(role="check box", name="Settings")
    ep.click_node(role="check box", name="Backup database file before saving")
    _ok(ep)


def pos_delete(ep):
    cell = ep.wait_node(role="table cell", name="Old Router")
    ep.click_box(cell)
    ep.click_node(role="button", name="Delete Entry…")
    ep.sleep(1.5)


def pos_add_entry(ep):
    _new_entry(ep)
    _fill(ep, "Title field", "Harbor Wifi")
    _fill(ep, "Username field", "dock-admin", role="combo box")
    _ok(ep)


def pos_new_group(ep):
    _new_group(ep, "Marina Logins")


def _new_group(ep, name):
    ep.click(168, 15)                       # "Groups" menu in the menu bar
    ep.sleep(0.6)
    ep.click_node(role="menu item", contains="New Group")
    ep.sleep(1.0)
    ep.click_node(role="text", name="Name field")
    ep.type(name)
    _ok(ep)


def pos_add_url(ep):
    ep.click_box(ep.wait_node(role="table cell", name="Dock Server"))
    ep.click_node(role="button", name="Edit Entry…")
    ep.wait_node(role="text", name="Url field")
    _fill(ep, "Url field", "https://dock.example.net")
    _ok(ep)


def pos_group_entry(ep):
    _new_group(ep, "Berths")
    ep.click_box(ep.wait_node(role="table cell", name="Berths"))
    ep.sleep(0.5)
    _new_entry(ep)
    _fill(ep, "Title field", "Slip 14")
    _fill(ep, "Username field", "berth-14", role="combo box")
    ep.click_box(ep.wait_node(role="password text"))
    ep.type("Tide!2026-Slip")
    _ok(ep)


TASKS = [
    {"id": "keepassxc_enable_backup", "difficulty": 1,
     "sentence": "Open KeePassXC's application settings, turn on \"Backup database file before saving\", and confirm with OK.",
     "setup": None, "oracle": oracle_backup, "positive": pos_backup},
    {"id": "keepassxc_delete_entry", "difficulty": 1,
     "sentence": "Delete the entry named Old Router from the database (the other entries stay).",
     "setup": setup_entries, "oracle": oracle_delete, "positive": pos_delete},
    {"id": "keepassxc_add_entry", "difficulty": 2,
     "sentence": "Add a new entry with the title Harbor Wifi and the username dock-admin.",
     "setup": None, "oracle": oracle_add_entry, "positive": pos_add_entry},
    {"id": "keepassxc_new_group", "difficulty": 2,
     "sentence": "Create a new group named Marina Logins in the database.",
     "setup": None, "oracle": oracle_new_group, "positive": pos_new_group},
    {"id": "keepassxc_add_entry_url", "difficulty": 2,
     "sentence": "Edit the existing entry Dock Server and set its URL to https://dock.example.net (keep its other fields).",
     "setup": setup_entries, "oracle": oracle_add_url, "positive": pos_add_url},
    {"id": "keepassxc_group_entry_password", "difficulty": 3,
     "sentence": "Create a group named Berths, then add an entry inside that group with the title Slip 14, the username "
                 "berth-14 and the password Tide!2026-Slip.",
     "setup": None, "oracle": oracle_group_entry, "positive": pos_group_entry},
]
