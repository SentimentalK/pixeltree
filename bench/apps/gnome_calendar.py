"""GNOME Calendar (GTK4) on the evolution-data-server local calendar (private dbus session)."""
from pathlib import Path

from bench.env import oracle_kit as kit

APP = {
    "name": "gnome-calendar",
    "argv": lambda home: ["gnome-calendar"],
    "env": {"GSETTINGS_BACKEND": "keyfile"},
    "session_env": {"TZ": "UTC", "LANG": "C.UTF-8"},   # EDS stores local times: make them UTC so oracles are exact
    "startup_s": 6,
    "window_title": "Calendar",
    "process": "gnome-calendar",
    "prepare": None,
    "close": "wm_close",
    "daemons": ["evolution-"],
    "state_files": [".local/share/evolution/calendar/**", ".config/evolution/**", ".cache/evolution/calendar/**"],
    "tier": "poor",
    "atspi_recall_05": 0.004,
}

ICS = ".local/share/evolution/calendar/system/calendar.ics"


def seed_event(home: Path) -> None:
    """Pre-existing event \"Dock Safety Meeting\" 2026-11-18 10:00-11:00 UTC in the local calendar (setup only)."""
    path = home / ICS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//p125//seed//EN\r\nBEGIN:VEVENT\r\n"
                    "UID:p125-dock-safety-0001\r\nDTSTAMP:20261101T080000Z\r\nDTSTART:20261118T100000Z\r\n"
                    "DTEND:20261118T110000Z\r\nSUMMARY:Dock Safety Meeting\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")



# ---------------------------------------------------------------------------------------------- oracle helpers
def _events(home):
    return kit.ics_events(home, ICS)


def _find(home, summary):
    return [e for e in (_events(home) or []) if e.get("SUMMARY", "").strip() == summary]


def _brief(home):
    return [(e.get("SUMMARY"), e.get("DTSTART"), e.get("DTEND")) for e in (_events(home) or [])]


# ---------------------------------------------------------------------------------------------- oracles
def oracle_week_view(home):
    text = kit.file_text(home, ".config/glib-2.0/settings/keyfile") or ""
    v = kit.ini_value(home, ".config/glib-2.0/settings/keyfile", "org/gnome/calendar", "active-view")
    return v is not None and v.strip("'\"") == "week", f"keyfile [org/gnome/calendar] active-view={v!r}"


def oracle_allday(home):
    hit = _find(home, "Harbor Inspection")
    ok = any(e.get("DTSTART") == "20261112" for e in hit)
    return ok, f"events (summary, start, end)={_brief(home)!r}"


def oracle_delete(home):
    evs = _events(home)
    ok = evs is not None and not _find(home, "Dock Safety Meeting")
    return ok, f"events (summary, start, end)={_brief(home)!r}"


def oracle_two(home):
    a = any(e.get("DTSTART") == "20261126" for e in _find(home, "Crew Dinner"))
    b = any(e.get("DTSTART") == "20261127" for e in _find(home, "Crew Breakfast"))
    return a and b, f"events (summary, start, end)={_brief(home)!r}"


def oracle_location(home):
    hit = [e for e in _find(home, "Customs Visit") if e.get("DTSTART") == "20261124"]
    ok = any(e.get("LOCATION", "").strip() == "Pier 9" for e in hit)
    return ok, f"events={[(e.get('SUMMARY'), e.get('DTSTART'), e.get('LOCATION')) for e in (_events(home) or [])]!r}"


def oracle_timed(home):
    hit = _find(home, "Tide Briefing")
    ok = any(str(e.get("DTSTART", "")).startswith("20261112T1000") and str(e.get("DTEND", "")).startswith("20261112T1100")
             and e.get("LOCATION", "").strip() == "Harbor Office" for e in hit)
    return ok, f"events (summary, start, end)={_brief(home)!r}"


# ---------------------------------------------------------------------------------------------- positive scripts
def _cell(day):
    """Centre of the month-view cell of `day`: the grid starts at the Sunday of the week that holds today (5 rows)."""
    import datetime as dt
    y, m, d = (int(x) for x in day.split("-"))
    today = dt.date.today()
    start = today - dt.timedelta(days=(today.weekday() + 1) % 7)
    delta = (dt.date(y, m, d) - start).days
    if not 0 <= delta < 35:
        raise RuntimeError(f"{day} is outside the visible month grid (today={today}); run the calendar tasks within ~5 weeks before the date")
    return 141 + 273 * (delta % 7), 77 + int(190.5 * (delta // 7)) + 75


def _quick_event(ep, day, title):
    x, y = _cell(day)
    ep.click(x, y)
    ep.sleep(1.0)
    ep.type(title)
    ep.key("Return")
    ep.sleep(1.5)
    return x, y


def _details(ep, day, title):
    x, y = _cell(day)
    ep.click(x, y)
    ep.sleep(1.0)
    ep.type(title)
    ep.click(x - 86, y + 232)                # "Edit Details" of the quick popover (centred on the click)
    ep.sleep(1.5)


def pos_week(ep):
    ep.click(1021, 1051)                     # "Week"
    ep.sleep(1.5)


def pos_allday(ep):
    _quick_event(ep, "2026-11-12", "Harbor Inspection")


def pos_delete(ep):
    x, y = _cell("2026-11-18")
    ep.click(x, y - 31)                      # the event chip under the day number
    ep.sleep(1.2)
    ep.click(x + 115, y - 142)               # pencil (edit) of the event popover
    ep.sleep(1.5)
    for _ in range(6):
        ep.desk.click(960, 700, button=5)    # scroll the dialog down
        ep.sleep(0.2)
    ep.click(960, 960)                       # "Delete Event"
    ep.sleep(2.0)


def pos_two(ep):
    _quick_event(ep, "2026-11-26", "Crew Dinner")
    _quick_event(ep, "2026-11-27", "Crew Breakfast")


def pos_location(ep):
    _details(ep, "2026-11-24", "Customs Visit")
    ep.click(900, 225)                       # Location
    ep.type("Pier 9")
    ep.click(1271, 95)                       # Save
    ep.sleep(2.0)


def pos_timed(ep):
    _details(ep, "2026-11-12", "Tide Briefing")
    ep.click(900, 225)
    ep.type("Harbor Office")
    ep.click(1096, 370)                      # "Time Slot"
    ep.sleep(1.0)
    for y, value in ((482, "10:00"), (603, "11:00")):
        ep.click(1163, y)                    # pencil: edit the time as text
        ep.sleep(0.4)
        ep.key("ctrl+a")
        ep.type(value)
        ep.key("Return")
        ep.sleep(0.5)
    ep.click(1271, 95)
    ep.sleep(2.0)


TASKS = [
    {"id": "gnome_calendar_week_view", "difficulty": 1,
     "sentence": "In GNOME Calendar, switch the view from Month to Week.",
     "setup": None, "oracle": oracle_week_view, "positive": pos_week},
    {"id": "gnome_calendar_allday_event", "difficulty": 1,
     "sentence": "Add an all-day event titled Harbor Inspection on 2026-11-12.",
     "setup": None, "oracle": oracle_allday, "positive": pos_allday},
    {"id": "gnome_calendar_delete_event", "difficulty": 2,
     "sentence": "Delete the event \"Dock Safety Meeting\" on 2026-11-18.",
     "setup": seed_event, "oracle": oracle_delete, "positive": pos_delete},
    {"id": "gnome_calendar_two_events", "difficulty": 2,
     "sentence": "Add an all-day event Crew Dinner on 2026-11-26 and an all-day event Crew Breakfast on 2026-11-27.",
     "setup": None, "oracle": oracle_two, "positive": pos_two},
    {"id": "gnome_calendar_event_location", "difficulty": 2,
     "sentence": "Add an all-day event titled Customs Visit on 2026-11-24 with the location Pier 9.",
     "setup": None, "oracle": oracle_location, "positive": pos_location},
    {"id": "gnome_calendar_timed_event", "difficulty": 3,
     "sentence": "Create an event titled Tide Briefing on 2026-11-12 from 10:00 to 11:00 in the location Harbor Office.",
     "setup": None, "oracle": oracle_timed, "positive": pos_timed},
]
