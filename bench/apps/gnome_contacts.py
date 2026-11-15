"""GNOME Contacts (GTK4) on the evolution-data-server local address book (private dbus session)."""
from pathlib import Path

from bench.env import oracle_kit as kit

def after_start(ep):
    """First start shows the "Contacts Setup" page: choose the Local Address Book and press Done."""
    if any("Setup" in w["title"] for w in ep.windows()):
        ep.click(960, 622)
        ep.sleep(0.8)
        ep.click(1874, 27)
        ep.sleep(2.5)
        for w in ep.windows():                 # the main window is a new, small (800x600) window: stretch it
            if w["title"] == "Contacts":
                ep.desk.move_window(w["xid"], 0, 0, 1920, 1080)
                ep.window = dict(w, x=0, y=0, w=1920, h=1080)
        ep.sleep(1.0)


APP = {
    "name": "gnome-contacts",
    "argv": lambda home: ["gnome-contacts"],
    "env": {"GSETTINGS_BACKEND": "keyfile"},
    "session_env": {"LANG": "C.UTF-8"},
    "startup_s": 6,
    "window_title": "Contacts",
    "process": "gnome-contacts",
    "prepare": None,
    "close": "wm_close",
    "daemons": ["evolution-"],
    "state_files": [".local/share/evolution/addressbook/**", ".config/evolution/**"],
    "after_start": after_start,
    "tier": "poor",
    "atspi_recall_05": 0.000,
}

VCF_DB = ".local/share/evolution/addressbook/system/contacts.db"


def _cards(home):
    rows = kit.sqlite_rows(home, VCF_DB, "select vcard from folder_id")
    if rows is None:
        return None
    return kit.parse_vcards("\n".join(r[0] for r in rows))


def _card(home, name):
    return [c for c in (_cards(home) or []) if c.get("FN", "").strip() == name]


def _brief(home):
    return [(c.get("FN"), c.get("TEL"), c.get("EMAIL")) for c in (_cards(home) or [])]


# ---------------------------------------------------------------------------------------------- oracles
def oracle_sort(home):
    v = kit.ini_value(home, ".config/glib-2.0/settings/keyfile", "org/gnome/Contacts", "sort-on-surname")
    return v == "true", f"keyfile [org/gnome/Contacts] sort-on-surname={v!r}"


def oracle_name(home):
    return bool(_card(home, "Marina Office")), f"contacts (FN, TEL, EMAIL)={_brief(home)!r}"


def oracle_phone(home):
    ok = any("555-0142" in t for c in _card(home, "Dock Master") for t in c.get("TEL", []))
    return ok, f"contacts (FN, TEL, EMAIL)={_brief(home)!r}"


def oracle_email(home):
    ok = any(e.strip() == "clerk@harbor.example" for c in _card(home, "Harbor Clerk") for e in c.get("EMAIL", []))
    return ok, f"contacts (FN, TEL, EMAIL)={_brief(home)!r}"


def oracle_both(home):
    cs = _card(home, "Pier Agent")
    ok = any("555-0177" in t for c in cs for t in c.get("TEL", [])) and \
        any(e.strip() == "agent@pier.example" for c in cs for e in c.get("EMAIL", []))
    return ok, f"contacts (FN, TEL, EMAIL)={_brief(home)!r}"


def oracle_work_phone(home):
    cs = _card(home, "Quay Manager")
    ok = False
    rows = kit.sqlite_rows(home, VCF_DB, "select vcard from folder_id") or []
    for (v,) in rows:
        if "FN:Quay Manager" in v:
            ok = any("TEL" in ln and "WORK" in ln.upper() and "555-0188" in ln for ln in v.replace("\r", "").split("\n")) and \
                "agent" not in v and "quay@harbor.example" in v
    return ok, f"contacts (FN, TEL, EMAIL)={_brief(home)!r} raw TEL lines={[ln for (v,) in rows for ln in v.splitlines() if ln.startswith('TEL')]!r}"


# ---------------------------------------------------------------------------------------------- positive scripts
def _new(ep, name):
    ep.hover_click(28, 27)                  # "+"
    ep.sleep(2.0)
    ep.hover_click(1100, 266)               # Full name
    ep.type(name)


def _field_phone(ep, number):
    ep.hover_click(1100, 477)
    ep.type(number)
    ep.sleep(0.3)


def _field_email(ep, mail):
    ep.hover_click(1100, 344)
    ep.type(mail)
    ep.sleep(0.3)


def _add(ep):
    ep.hover_click(1878, 27)                # "Add"
    ep.sleep(2.5)


def pos_sort(ep):
    ep.hover_click(342, 27)                 # main menu
    ep.sleep(1.0)
    ep.hover_click(296, 139)                # "Surname" radio item
    ep.sleep(1.0)


def pos_name(ep):
    _new(ep, "Marina Office")
    _add(ep)


def pos_phone(ep):
    _new(ep, "Dock Master")
    _field_phone(ep, "555-0142")
    _add(ep)


def pos_email(ep):
    _new(ep, "Harbor Clerk")
    _field_email(ep, "clerk@harbor.example")
    _add(ep)


def pos_both(ep):
    _new(ep, "Pier Agent")
    _field_phone(ep, "555-0177")
    _field_email(ep, "agent@pier.example")
    _add(ep)


def pos_work_phone(ep):
    _new(ep, "Quay Manager")
    _field_phone(ep, "555-0188")
    ep.hover_click(1340, 532)               # phone "Label" drop-down (Mobile)
    ep.sleep(1.0)
    ep.hover_click(1342, 614)               # "Work" in the drop-down list
    ep.sleep(0.8)
    _field_email(ep, "quay@harbor.example")
    _add(ep)


TASKS = [
    {"id": "gnome_contacts_sort_surname", "difficulty": 1,
     "sentence": "In GNOME Contacts, open the main menu and sort the contact list by surname.",
     "setup": None, "oracle": oracle_sort, "positive": pos_sort},
    {"id": "gnome_contacts_new_name", "difficulty": 1,
     "sentence": "Create a new contact named Marina Office.",
     "setup": None, "oracle": oracle_name, "positive": pos_name},
    {"id": "gnome_contacts_phone", "difficulty": 2,
     "sentence": "Create a new contact named Dock Master with the phone number 555-0142.",
     "setup": None, "oracle": oracle_phone, "positive": pos_phone},
    {"id": "gnome_contacts_email", "difficulty": 2,
     "sentence": "Create a new contact named Harbor Clerk with the email address clerk@harbor.example.",
     "setup": None, "oracle": oracle_email, "positive": pos_email},
    {"id": "gnome_contacts_phone_email", "difficulty": 2,
     "sentence": "Create a new contact named Pier Agent with the phone number 555-0177 and the email address agent@pier.example.",
     "setup": None, "oracle": oracle_both, "positive": pos_both},
    {"id": "gnome_contacts_work_phone", "difficulty": 3,
     "sentence": "Create a new contact named Quay Manager with the phone number 555-0188 labelled Work and the email address quay@harbor.example.",
     "setup": None, "oracle": oracle_work_phone, "positive": pos_work_phone},
]
