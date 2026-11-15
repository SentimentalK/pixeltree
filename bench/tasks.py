"""The 48 frozen tasks of the benchmark (`tasks_v1.json`): loading, and the Markdown table of TASKS.md.

    python -m bench.tasks --markdown > bench/TASKS.md

The task list is read from tasks_v1.json only (no application code is imported).  `ORACLE_CHECKS` holds, for every task,
one sentence saying what its oracle reads from the application's saved state and requires; the oracles themselves are the
functions in `bench/apps/<app>.py` (grading is by on-disk state, never by what the agent answers).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

TASKS_JSON = Path(__file__).resolve().parent / "tasks_v1.json"

ORACLE_CHECKS = {
    "drawing_banner_save_as": "Pictures/harbor-banner.png exists, is 640x360, and contains at least 15 pixels of the red text colour.",
    "drawing_no_ctrl_zoom": "The application's settings keyfile has ctrl-zoom=false.",
    "drawing_rotate_save": "The saved sample picture is 600x800 and the orange circle has moved to the position a clockwise (not counter-clockwise) quarter turn gives.",
    "drawing_scale_save": "The saved sample picture is exactly 400x300 pixels.",
    "drawing_show_tool_names": "The application's settings keyfile has show-labels=true.",
    "drawing_text_save": "The saved sample picture contains at least 15 pixels of the red text colour (the original has none; the text itself is not read).",
    "gitg_checkout_branch": "The repository's HEAD is the branch release-2026-11.",
    "gitg_commit_readme": "A new HEAD commit (6 commits in total) has the subject \"Update usage notes for November\", touches only README.md, and README.md is clean afterwards.",
    "gitg_commit_two_then_branch": "HEAD is a new commit with the given subject touching exactly docs/CHANGELOG.md and src/util.py, branch release-2026-12 points at it, and README.md is still modified and uncommitted.",
    "gitg_create_branch": "Branch tide-notes exists and points at the same commit as main.",
    "gitg_stage_readme": "Exactly README.md is staged, no commit was made (still 5 commits), so src/util.py stays unstaged.",
    "gitg_tag_commit": "Tag v2026.11 exists and its commit has the subject \"Document usage\".",
    "gnome_calendar_allday_event": "The calendar store holds an event \"Harbor Inspection\" that starts on 20261112 as an all-day event.",
    "gnome_calendar_delete_event": "The calendar store is readable and has no event \"Dock Safety Meeting\" any more.",
    "gnome_calendar_event_location": "The calendar store holds an event \"Customs Visit\" starting 20261124 whose location is exactly \"Pier 9\".",
    "gnome_calendar_timed_event": "The calendar store holds an event \"Tide Briefing\" from 2026-11-12 10:00 to 11:00 with the location \"Harbor Office\".",
    "gnome_calendar_two_events": "The calendar store holds \"Crew Dinner\" starting 20261126 and \"Crew Breakfast\" starting 20261127.",
    "gnome_calendar_week_view": "The application's settings keyfile (org/gnome/calendar) has active-view set to week.",
    "gnome_contacts_email": "The address book has a contact \"Harbor Clerk\" with the email address given in the sentence.",
    "gnome_contacts_new_name": "The address book has a contact named \"Marina Office\".",
    "gnome_contacts_phone": "The address book has a contact \"Dock Master\" with a phone number containing 555-0142.",
    "gnome_contacts_phone_email": "The address book has a contact \"Pier Agent\" with phone 555-0177 and the email address given in the sentence.",
    "gnome_contacts_sort_surname": "The application's settings keyfile (org/gnome/Contacts) has sort-on-surname=true.",
    "gnome_contacts_work_phone": "The raw vCard of \"Quay Manager\" has a TEL line typed WORK that contains 555-0188 and holds the email address given in the sentence, and it does not contain the string \"agent\".",
    "keepassxc_add_entry": "The database (read with keepassxc-cli) has an entry \"Harbor Wifi\" with username dock-admin.",
    "keepassxc_add_entry_url": "The entry \"Dock Server\" has the URL https://dock.example.net and still has its original title and username (ops).",
    "keepassxc_delete_entry": "The root listing no longer contains \"Old Router\" but still contains \"Dock Server\" and \"Harbor Cam\".",
    "keepassxc_enable_backup": "keepassxc.ini has BackupBeforeSave=true in the [General] section.",
    "keepassxc_group_entry_password": "The database has the entry Berths/Slip 14 with username berth-14 and password Tide!2026-Slip.",
    "keepassxc_new_group": "The root listing contains the group \"Marina Logins/\".",
    "lutris_add_game": "The Lutris database has a game \"Tide Quest\" with runner linux.",
    "lutris_favorite_game": "\"Keep Game\" is in the favourites and \"Old Game\" is not.",
    "lutris_hide_side_panel": "lutris.conf has side_panel_visible=False.",
    "lutris_hide_text": "lutris.conf has hide_text_under_icons=True.",
    "lutris_remove_game": "The game list no longer contains \"Old Game\" and still contains \"Keep Game\".",
    "lutris_wine_game_favorite": "The Lutris database has a game \"Harbor Run\" with runner wine and year 2019, and it is in the favourites.",
    "obsidian_append_welcome": "Welcome.md still starts with \"# Welcome\" and contains the line \"Visit the harbor office on 2026-11-20.\".",
    "obsidian_logs_note": "The vault has Logs/Tide log.md containing the lines \"Low tide at 06:40\" and \"High tide at 19:05\".",
    "obsidian_new_folder": "A directory Logs exists in the vault.",
    "obsidian_rename_note": "Harbor Projects.md exists with the original content (\"- [ ] write report\") and Projects.md no longer exists.",
    "obsidian_tide_log": "The vault has Tide log.md containing the line \"Low tide at 06:40\".",
    "obsidian_toggle_task": "Projects.md contains \"- [x] write report\" and still \"- [x] book room\".",
    "okular_bookmark_current": "The bookmarks file has a bookmark on page 1 (index 0), the page shown when the document opens.",
    "okular_bookmark_pages": "The bookmarks file has bookmarks on pages 2 and 3 (indexes 1 and 2).",
    "okular_facing_zoom": "Okular's settings have view mode Facing Pages and a fixed zoom of 200 % (value 2.0 +-0.02).",
    "okular_goto_page3": "The document's saved view state has page 3 (index 2) as the current page.",
    "okular_note_bookmark_facing": "The saved PDF has a text annotation \"Verify totals\" on page 3 (read with pypdf in oracle v1.1), page 3 is bookmarked, and the view mode is Facing Pages.",
    "okular_popup_note": "The saved PDF has a text annotation with the contents \"Check Q3 figures\" on page 2 (read with pypdf from the final revision; v1.1 oracle).",
}


def load_tasks() -> list[dict]:
    """The tasks of tasks_v1.json in file order: id, app, tier, atspi_recall_05, difficulty, sentence."""
    return json.loads(TASKS_JSON.read_text(encoding="utf-8"))["tasks"]


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def markdown() -> str:
    tasks = load_tasks()
    lines = [
        "# The 48 tasks",
        "",
        "Generated by `python -m bench.tasks --markdown`; do not edit by hand.  Six tasks per application, difficulty 1-3.",
        "The oracle reads the application's saved state after the app was closed (never the agent's answer).",
        "",
        "| id | app | difficulty | sentence | oracle checks |",
        "|---|---|---|---|---|",
    ]
    for t in tasks:
        lines.append("| " + " | ".join([f"`{t['id']}`", t["app"], str(t["difficulty"]), _cell(t["sentence"]),
                                         _cell(ORACLE_CHECKS[t["id"]])]) + " |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--markdown", action="store_true", help="print the task table as Markdown")
    args = ap.parse_args(argv)
    if not args.markdown:
        ap.error("nothing to do: pass --markdown")
    print(markdown(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
