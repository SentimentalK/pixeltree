"""Auto-discovery of apps/<app>.py: APPS, TASKS, get_task, oracle, positive; `--export` writes tasks_v1.json.

    python -m bench.env.registry --export      # rewrite bench/tasks_v1.json from the apps
    python -m bench.env.registry --check       # structure checks only (no GUI)

Every apps/<name>.py (not starting with "_") defines APP (how to start / close the app) and TASKS (the task list);
see apps/_template.py.  Module names use underscores (gnome_calendar.py), app names keep their dashes
("gnome-calendar"): APP["name"] is the app name, the file name is just `name.replace("-", "_")`.
"""
from __future__ import annotations

import argparse
import importlib
import json
import pkgutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bench.apps as _apps_pkg  # noqa: E402

TASKS_JSON = ROOT / "bench" / "tasks_v1.json"
REQUIRED_APP_KEYS = ("name", "argv", "env", "startup_s", "window_title", "process", "prepare", "close",
                     "state_files", "tier", "atspi_recall_05")
REQUIRED_TASK_KEYS = ("id", "difficulty", "sentence", "setup", "oracle", "positive")
DIFFICULTY_PER_APP = {1: 2, 2: 3, 3: 1}


def _discover():
    apps, tasks = {}, []
    for info in pkgutil.iter_modules(_apps_pkg.__path__):
        if info.name.startswith("_"):
            continue
        mod = importlib.import_module(f"bench.apps.{info.name}")
        app = mod.APP
        missing = [k for k in REQUIRED_APP_KEYS if k not in app]
        if missing:
            raise ValueError(f"apps/{info.name}.py: APP lacks {missing}")
        if app["name"] in apps:
            raise ValueError(f"duplicate app {app['name']}")
        apps[app["name"]] = app
        for t in mod.TASKS:
            missing = [k for k in REQUIRED_TASK_KEYS if k not in t]
            if missing:
                raise ValueError(f"{t.get('id')}: task lacks {missing}")
            tasks.append(dict(t, app=app["name"], tier=app["tier"], atspi_recall_05=app["atspi_recall_05"]))
    ids = [t["id"] for t in tasks]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        raise ValueError(f"duplicate task ids {sorted(dup)}")
    return apps, tasks


APPS, TASKS = _discover()
_BY_ID = {t["id"]: t for t in TASKS}


def get_task(task_id: str) -> dict:
    try:
        return _BY_ID[task_id]
    except KeyError:
        raise KeyError(f"unknown task {task_id!r}; known: {sorted(_BY_ID)}") from None


def oracle(task_id: str, home) -> tuple[bool, str]:
    """Run the task's oracle on a sandbox HOME; an oracle that raises counts as (False, 'oracle error: ...')."""
    try:
        ok, detail = get_task(task_id)["oracle"](Path(home))
        return bool(ok), str(detail)
    except Exception as exc:  # noqa: BLE001
        return False, f"oracle error: {type(exc).__name__}: {exc}"


def positive(task_id: str, ep) -> None:
    """Run the positive (reference) UI script of the task on a running episode."""
    get_task(task_id)["positive"](ep)


def check() -> list[str]:
    """Structure problems (empty list = fine): 6 tasks per app, difficulty 2x1 / 3x2 / 1x3, id prefix, abs. dates."""
    problems = []
    for name in APPS:
        mine = [t for t in TASKS if t["app"] == name]
        if len(mine) != 6:
            problems.append(f"{name}: {len(mine)} tasks (need 6)")
        counts = {d: sum(1 for t in mine if t["difficulty"] == d) for d in (1, 2, 3)}
        if counts != DIFFICULTY_PER_APP:
            problems.append(f"{name}: difficulty counts {counts} (need {DIFFICULTY_PER_APP})")
        for t in mine:
            if not t["id"].startswith(name.replace("-", "_") + "_"):
                problems.append(f"{t['id']}: id must start with {name.replace('-', '_')}_")
            if not t["sentence"].strip():
                problems.append(f"{t['id']}: empty sentence")
    return problems


def export(path: Path = TASKS_JSON) -> dict:
    data = {"version": 1, "tasks": [
        {"id": t["id"], "app": t["app"], "tier": t["tier"], "atspi_recall_05": t["atspi_recall_05"],
         "difficulty": t["difficulty"], "sentence": t["sentence"]} for t in sorted(TASKS, key=lambda t: t["id"])]}
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return data


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--export", action="store_true", help="write bench/tasks_v1.json")
    ap.add_argument("--check", action="store_true", help="structure checks, exit 1 on problems")
    ap.add_argument("--list", action="store_true", help="print id, difficulty, sentence")
    args = ap.parse_args(argv)
    if args.list or not (args.export or args.check):
        for t in sorted(TASKS, key=lambda t: (t["app"], t["difficulty"], t["id"])):
            print(f"{t['id']:34s} d{t['difficulty']} {t['sentence']}")
    if args.check or args.export:
        problems = check()
        for p in problems:
            print("PROBLEM", p)
        if problems and args.check:
            return 1
    if args.export:
        data = export()
        print(f"wrote {TASKS_JSON} ({len(data['tasks'])} tasks, {len(APPS)} apps)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
