"""Oracles on stored after-states (no GUI, no app is started).

For every task there are two fixtures made by `selftest --keep`: `<task>__positive.tar.gz` (HOME after the positive script and a
graceful close) and `<task>__noop.tar.gz` (HOME after 5 s of doing nothing), reduced to the files the oracle reads.
The oracle must say True for the first and False for the second.

    python -m pytest bench/tests -q
"""
import shutil
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.env import registry  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
NEEDS_CLI = {"keepassxc": "keepassxc-cli", "gitg": "git"}

TASK_IDS = sorted(t["id"] for t in registry.TASKS)


def _home(tmp_path, task_id, mode):
    archive = FIXTURES / f"{task_id}__{mode}.tar.gz"
    if not archive.exists():
        pytest.skip(f"no fixture {archive.name}")
    home = tmp_path / "home"
    home.mkdir()
    with tarfile.open(archive) as tar:
        tar.extractall(home, filter="data")
    return home


@pytest.mark.parametrize("task_id", TASK_IDS)
@pytest.mark.parametrize("mode,expected", [("positive", True), ("noop", False)])
def test_oracle(task_id, mode, expected, tmp_path):
    app = registry.get_task(task_id)["app"]
    cli = NEEDS_CLI.get(app)
    if cli and shutil.which(cli) is None:
        pytest.skip(f"{cli} not installed")
    home = _home(tmp_path, task_id, mode)
    ok, detail = registry.oracle(task_id, home)
    assert ok is expected, f"{task_id} {mode}: {detail}"


def test_registry_shape():
    assert registry.check() == []
    assert len(registry.TASKS) >= 48
