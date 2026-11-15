"""bench.tasks: the task table of tasks_v1.json and the generated TASKS.md."""
import collections
from pathlib import Path

from bench import tasks


def test_task_table_shape():
    rows = tasks.load_tasks()
    assert len(rows) == 48
    ids = [t["id"] for t in rows]
    assert len(set(ids)) == 48
    per_app = collections.Counter(t["app"] for t in rows)
    assert len(per_app) == 8 and set(per_app.values()) == {6}


def test_markdown_has_one_row_per_task_and_matches_tasks_md():
    text = tasks.markdown()
    rows = [ln for ln in text.splitlines() if ln.startswith("| `")]
    assert len(rows) == 48
    assert set(tasks.ORACLE_CHECKS) == {t["id"] for t in tasks.load_tasks()}
    assert text == (Path(tasks.__file__).parent / "TASKS.md").read_text(encoding="utf-8")
