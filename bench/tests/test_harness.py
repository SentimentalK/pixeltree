"""Unit tests of the bench harness: no GUI, no models, no network.

    python -m pytest bench/tests/test_harness.py -q
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.agent import mcp_server, observation, summarize  # noqa: E402
from bench.env import actions  # noqa: E402
from pixeltree.perceive.tree import Element, make_tree, to_json, to_text  # noqa: E402


class FakeDesk:
    """Records what the action layer asks of a desktop."""
    size = (1920, 1080)

    def __init__(self):
        self.calls = []

    def click(self, x, y, button=1, double=False):
        self.calls.append(("click", x, y, button, double))

    def type_text(self, text):
        self.calls.append(("type", text))

    def key(self, combo):
        self.calls.append(("key", combo))

    def screenshot(self):
        import numpy as np

        return np.zeros((1080, 1920, 3), dtype=np.uint8)


def test_tree_text_order_and_centres():
    # two rows: centre y 20..26 (A, B, C) and ~110 (E, D); heights 20 -> row tolerance 10 from the row's first element
    boxes = [("D", [300, 100, 40, 20]), ("B", [100, 16, 41, 20]), ("E", [50, 104, 30, 20]),
             ("A", [10, 10, 50, 20]), ("C", [500, 14, 60, 20])]
    elements = [Element(id="", role="aria:button", name=n, box=b) for n, b in boxes]
    tree = make_tree("ours", (1920, 1080), elements)
    text = to_text(tree).splitlines()
    assert text[0] == "screen 1920x1080, 5 elements"
    assert [line.split('"')[1] for line in text[1:]] == ["A", "B", "C", "E", "D"]
    assert text[1] == 'aria:button [e1] "A" @(10,10,50,20) c=(35,20)'
    assert text[2].endswith("@(100,16,41,20) c=(120,26)")       # int(100 + 41/2) = 120
    assert text[4].endswith("c=(65,114)")
    assert text[5].endswith("c=(320,110)")
    assert [e.id for e in tree.elements] == ["e1", "e2", "e3", "e4", "e5"]
    data = to_json(tree)
    assert data["image_size"] == [1920, 1080] and data["elements"][0]["center"] == [35, 20]


def test_tree_text_empty_name_and_truncation():
    elements = [Element(id="", role="button", name="", box=[0, i * 30, 10, 10]) for i in range(402)]
    lines = to_text(make_tree("atspi", (1920, 1080), elements)).splitlines()
    assert lines[0] == "screen 1920x1080, 402 elements"
    assert lines[1] == 'button [e1] "" @(0,0,10,10) c=(5,5)'
    assert len(lines) == 1 + 400 + 1 and lines[-1] == "... 2 more elements"


def test_screenshot_coordinates_scaled_back_to_screen():
    desk = FakeDesk()
    res = actions.execute(desk, {"tool": "click", "x": 640, "y": 360, "button": "right", "double": True},
                          scale=observation.scale_for("S_shot"))
    assert res["ok"] and res["screen_xy"] == [960, 540]
    assert desk.calls == [("click", 960, 540, 3, True)]
    assert observation.scale_for("T_ours") == 1.0 and observation.scale_for("S_shot_strong") == 1.5


def test_key_whitelist_rejects_shortcuts():
    desk = FakeDesk()
    res = actions.execute(desk, {"tool": "key", "name": "ctrl+s"})
    assert not res["ok"] and res["error"] == "key not allowed: ctrl+s"
    assert desk.calls == []
    assert actions.execute(desk, {"tool": "key", "name": "shift+Tab"})["ok"]
    assert actions.execute(desk, {"tool": "key", "name": "page_down"})["ok"]
    assert desk.calls == [("key", "shift+Tab"), ("key", "Page_Down")]


def test_click_outside_screen_is_refused():
    desk = FakeDesk()
    res = actions.execute(desk, {"tool": "click", "x": 1280, "y": 100}, scale=1.5)
    assert not res["ok"] and "outside the screen" in res["error"] and desk.calls == []


def _service(tmp_path, cond="T_ours"):
    def fake_observe(c, desk, cfg):
        return observation.Obs(text="screen 1920x1080, 0 elements", screen_png=b"png", n_elements=0, seconds=0.01)

    return mcp_server.Service(tmp_path, cond, FakeDesk(), {"process": "app"}, observe_fn=fake_observe, settle_s=0)


def test_step_limit_21st_call_is_not_executed(tmp_path):
    service = _service(tmp_path)
    for i in range(20):
        text, image = service.call("click", {"x": 10 + i, "y": 10})
        assert text == "screen 1920x1080, 0 elements" and image is None
    assert len(service.desk.calls) == 20
    text, _ = service.call("click", {"x": 1, "y": 1})
    assert text == "step limit reached (20); stop now"
    assert service.call("observe", {})[0] == "step limit reached (20); stop now"
    assert len(service.desk.calls) == 20                      # nothing executed after the limit
    assert (tmp_path / "step_limit.json").exists()
    assert sorted(p.name for p in (tmp_path / "steps").iterdir()) == [f"{i:02d}" for i in range(1, 21)]
    step = tmp_path / "steps" / "20"
    assert json.loads((step / "action.json").read_text())["screen_xy"] == [29, 10]
    assert (step / "screen.png").read_bytes() == b"png" and (step / "obs.txt").exists()


def test_rejected_key_counts_as_a_step_and_done_writes_file(tmp_path):
    service = _service(tmp_path)
    assert service.call("key", {"name": "ctrl+s"})[0] == "key not allowed: ctrl+s"
    assert service.call("done", {"answer": "FAIL: no"})[0] == "ok"
    assert json.loads((tmp_path / "done.json").read_text()) == {"answer": "FAIL: no", "step": 2}
    assert service.calls == 2


def test_screenshot_condition_returns_image(tmp_path):
    def fake_observe(c, desk, cfg):
        return observation.Obs(text=observation.SHOT_NOTE, image_png=b"small", screen_png=b"big", seconds=0.0)

    service = mcp_server.Service(tmp_path, "S_shot", FakeDesk(), {}, observe_fn=fake_observe, settle_s=0)
    text, image = service.call("click", {"x": 640, "y": 360})
    assert text == "Screenshot 1280x720. Use pixel coordinates of this image." and image == b"small"
    assert service.desk.calls == [("click", 960, 540, 1, False)]
    assert (tmp_path / "steps" / "01" / "shot.png").read_bytes() == b"small"


def test_bootstrap_all_ones_gives_degenerate_ci():
    mean, lo, hi = summarize.bootstrap_ci([1.0, 1.0, 1.0, 1.0])
    assert (mean, lo, hi) == (1.0, 1.0, 1.0)
    mean, lo, hi = summarize.bootstrap_ci([0.0, 1.0, 1.0, 0.0])
    assert lo < mean < hi


def test_hybrid_tree_in_screenshot_frame():
    from bench.agent import prompts

    tree = make_tree("ours", (1920, 1080), [Element(id="", role="button", name="Add", box=[300, 150, 60, 30])])
    small = observation.to_shot_frame(tree)
    assert to_text(small).splitlines() == ["screen 1280x720, 1 elements", 'button [e1] "Add" @(200,100,40,20) c=(220,110)']
    assert tree.elements[0].box == [300, 150, 60, 30]  # original tree untouched (archived in screen pixels)
    assert observation.scale_for("H_ours") == observation.scale_for("H_atspi") == 1.5
    for cond in ("H_ours", "H_atspi"):
        assert prompts.SEE[cond].startswith(prompts.SEE["S_shot"] + " ")
        assert prompts.model_for(cond) == "claude-haiku-5-5"


def _transcript(path, status, tools):
    from bench.agent import run

    init = {"type": "system", "subtype": "init", "cwd": str(run.AGENT_CWD_ROOT / "x"),
            "mcp_servers": [{"name": "p125", "status": status}], "tools": tools}
    path.write_text(json.dumps(init) + "\n", encoding="utf-8")


def test_requeue_episodes_whose_mcp_server_failed(tmp_path):
    from bench.agent import run

    six = run.TOOLS.split(",")
    rows = []
    for name, status, tools in (("good", "connected", six), ("bad", "failed", [])):
        d = tmp_path / "ep" / name
        d.mkdir(parents=True)
        _transcript(d / "transcript.jsonl", status, tools)
        row = {k: None for k in run.FIELDS}
        row.update(task=name, cond="T_ours", rep=0, ok=False, stop_reason="no_done", oracle_detail="", dir=str(d))
        rows.append(row)
        run.append_row(tmp_path, row)
    assert run.mcp_ok(tmp_path / "ep" / "good" / "transcript.jsonl")
    assert not run.mcp_ok(tmp_path / "ep" / "bad" / "transcript.jsonl")
    assert run.done_keys(run.read_rows(tmp_path / "episodes.jsonl")) == {("good", "T_ours", 0), ("bad", "T_ours", 0)}
    assert run.requeue_mcp_failures(tmp_path) == 1
    assert run.done_keys(run.read_rows(tmp_path / "episodes.jsonl")) == {("good", "T_ours", 0)}
    assert run.requeue_mcp_failures(tmp_path) == 0  # idempotent: the last row is already an error
