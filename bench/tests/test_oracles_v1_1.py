"""Oracle v1.1 (bench/env/oracles_v1_1.py) on stored after-states, no GUI.

* every task: v1.1 says True on the positive fixture and False on the no-op fixture (same fixtures as v1);
* generation-1 fixtures (`<task>__gen1.tar.gz`, the archived end state of formal_v1 episodes where Okular saved the
  re-added note as `10 1 obj`): v1.1 says True and v1 says False (the bug v1.1 fixes).
"""
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.env import oracles_v1_1, registry  # noqa: E402
from bench.tests.test_oracles import NEEDS_CLI, TASK_IDS, _home  # noqa: E402

pytest.importorskip("pypdf")


@pytest.mark.parametrize("task_id", TASK_IDS)
@pytest.mark.parametrize("mode,expected", [("positive", True), ("noop", False)])
def test_oracle_v1_1(task_id, mode, expected, tmp_path):
    cli = NEEDS_CLI.get(registry.get_task(task_id)["app"])
    if cli and shutil.which(cli) is None:
        pytest.skip(f"{cli} not installed")
    ok, detail = oracles_v1_1.oracle(task_id, _home(tmp_path, task_id, mode))
    assert ok is expected, f"{task_id} {mode}: {detail}"


@pytest.mark.parametrize("task_id", sorted(oracles_v1_1.OVERRIDES))
def test_generation_1_annotation(task_id, tmp_path):
    home = _home(tmp_path, task_id, "gen1")
    assert b"10 1 obj" in (home / "Documents" / "sample.pdf").read_bytes()
    ok11, detail11 = oracles_v1_1.oracle(task_id, home)
    ok1, detail1 = registry.oracle(task_id, home)
    assert ok11 is True, detail11
    assert ok1 is False, detail1
