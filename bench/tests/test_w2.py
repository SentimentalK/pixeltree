"""Unit tests of the R3 harness pieces: no GUI, no models, no claude, no network.

    python -m pytest bench/tests/test_w2.py -q
"""
import importlib.util
import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.agent import mcp_server as base_server, observation, prompts, run  # noqa: E402
from bench.perception import sources  # noqa: E402
from pixeltree.perceive.tree import Element, make_tree  # noqa: E402
from bench.variants.tree_first import analyze, conds, mcp_server, ours_client  # noqa: E402
from bench.variants.tree_first.ours_server import OursServer  # noqa: E402
from bench.variants.tree_first.view import to_view  # noqa: E402

needs_cv2 = pytest.mark.skipif(importlib.util.find_spec("cv2") is None, reason="cv2 not installed (PNG encoding)")


# ---------------------------------------------------------------- helpers
def el(id_, role, name, box):
    x, y, w, h = box
    return {"id": id_, "role": role, "name": name, "box": list(box), "center": [x + w // 2, y + h // 2], "conf": 0.9}


def tree_json(*elements):
    return {"source": "ours", "image_size": [1920, 1080], "elements": list(elements), "timings": {}}


OK = el("e1", "aria:button", "OK", [100, 100, 100, 40])          # centre 150,120 -> view 100,80
HELLO = el("e2", "vax:visibleText", "Hello", [300, 100, 100, 40])  # centre 350,120 -> view 233,80
MENU = el("e3", "aria:menuitem", "Menu", [500, 200, 120, 40])      # centre 560,220 -> view 373,147
TIP = el("e4", "vax:visibleText", "Save the file", [700, 300, 160, 30])
EXTRA = el("e5", "aria:button", "Extra", [900, 500, 100, 40])


class FakeDesk:
    size = (1920, 1080)

    def __init__(self):
        self.calls = []
        self.moves = []

    def click(self, x, y, button=1, double=False):
        self.calls.append(("click", x, y, button, double))

    def type_text(self, text):
        self.calls.append(("type", text))

    def key(self, combo):
        self.calls.append(("key", combo))

    def screenshot(self):
        return np.zeros((1080, 1920, 3), dtype=np.uint8)

    def atspi_nodes(self, process):
        return []


class TreeSeq:
    """Replaces ours_client.build_tree_json: the n-th call returns the n-th tree (the last one repeats)."""

    def __init__(self, *trees):
        self.trees = trees
        self.n = 0

    def __call__(self, png_bytes):
        t = self.trees[min(self.n, len(self.trees) - 1)]
        self.n += 1
        return json.loads(json.dumps(t))


def service(tmp_path, cond, seq, **kw):
    desk = FakeDesk()
    svc = mcp_server.make_service(tmp_path, cond, desk, {}, ":150", build_fn=seq, settle_s=0, hover_wait_s=0,
                                  pointer_fn=lambda d, x, y: d.moves.append((x, y)), **kw)
    return svc, desk


# ---------------------------------------------------------------- to_view
def test_to_view_full_and_changes():
    full = ('screen 1920x1080, 3 elements (full)\n'
            '1 btn "OK" 150,120\n'
            '2 text 350,121\n'
            '3 menuitem "12,34" 560,220')
    assert to_view(full) == ('screen 1280x720, 3 elements (full)\n'
                             '1 btn "OK" 100,80\n'
                             '2 text 233,81\n'
                             '3 menuitem "12,34" 373,147')
    changes = ('changes: +1 -1 ~1, 4 elements\n'
               '+ 7 link "a \\"b\\" 9,9" 3,4\n'
               '- 2\n'
               '~ 5 "x 1,2" 1919,1079')
    assert to_view(changes) == ('changes: +1 -1 ~1, 4 elements\n'
                                '+ 7 link "a \\"b\\" 9,9" 2,3\n'
                                '- 2\n'
                                '~ 5 "x 1,2" 1279,719')
    assert to_view("no change, 12 elements") == "no change, 12 elements"


def test_to_view_names_never_touched_and_rounding():
    # a name that ends in something coordinate-like stays: the line ends with the real coordinates
    assert to_view('+ 1 btn "10,20" 30,60') == '+ 1 btn "10,20" 20,40'
    assert to_view('+ 1 text "a \\"b\\" 9,9" 1,2') == '+ 1 text "a \\"b\\" 9,9" 1,1'    # 1/1.5+0.5 = 1.17 -> 1; 2 -> 1.83 -> 1
    # round half up: 3 / 1.5 + 0.5 = 2.5 -> 2 ; 1 / 1.5 + 0.5 = 1.17 -> 1 ; 0 -> 0 ; 2 -> 1
    assert to_view('4 btn 3,0') == '4 btn 2,0'
    # negative: sign kept, magnitude converted
    assert to_view('4 btn -30,-3') == '4 btn -20,-2'
    # the screen size is replaced only in the header
    assert to_view('screen 1920x1080, 0 elements (full)') == 'screen 1280x720, 0 elements (full)'


# ---------------------------------------------------------------- TreeFirstService
@needs_cv2
def test_x2_sequence(tmp_path):
    seq = TreeSeq(tree_json(OK, HELLO),                   # observe
                  tree_json(OK, HELLO, MENU),             # click
                  tree_json(OK, HELLO, MENU, TIP),        # hover
                  tree_json(OK, HELLO, MENU, TIP, EXTRA)) # click after look
    svc, desk = service(tmp_path, "X2", seq)
    assert svc.scale == 1.5

    text, img = svc.call("observe", {})
    assert img is None
    assert text.splitlines()[0] == "screen 1280x720, 2 elements (full)"
    assert text.splitlines()[1] == '1 btn "OK" 100,80' and text.splitlines()[2] == '2 text "Hello" 233,80'

    text, _ = svc.call("click", {"x": 100, "y": 80})
    assert desk.calls[-1][:3] == ("click", 150, 120)                   # 1280x720 -> screen, x1.5
    assert text == 'changes: +1 -0 ~0, 3 elements\n+ 3 menuitem "Menu" 373,147'

    text, _ = svc.call("hover", {"x": 500, "y": 200})
    assert desk.moves == [(750, 300)]                                  # no click, one pointer move
    assert [c for c in desk.calls if c[0] == "click"] == [desk.calls[0]]
    assert text.startswith("changes: +1 -0 ~0, 4 elements") and '"Save the file"' in text
    rec = json.loads((tmp_path / "steps" / "03" / "action.json").read_text())
    assert rec["tool"] == "hover" and rec["screen_xy"] == [750, 300] and rec["ok"] and rec["t_action_s"] >= 0

    n_before = seq.n
    text, img = svc.call("look", {})
    assert seq.n == n_before                                           # no perception run for look
    assert img and img[:8] == b"\x89PNG\r\n\x1a\n" and text == observation.SHOT_NOTE
    assert (tmp_path / "steps" / "04" / "shot.png").exists()

    text, _ = svc.call("click", {"x": 10, "y": 10})                    # changes are against the list before look
    assert text.splitlines()[0] == "changes: +1 -0 ~0, 5 elements" and text.splitlines()[1].startswith("+ 5 btn")
    assert svc.calls == 5
    for step in (1, 2, 3, 5):                                          # tree-based steps archive the F2 text (screen px)
        f2 = (tmp_path / "steps" / f"{step:02d}" / "f2.txt").read_text()
        assert f2.startswith("screen 1920x1080,")
    assert not (tmp_path / "steps" / "04" / "f2.txt").exists()


def test_x2_hover_outside_and_limit(tmp_path):
    seq = TreeSeq(tree_json(OK, HELLO))
    svc, desk = service(tmp_path, "X2", seq)
    text, _ = svc.call("hover", {"x": 5000, "y": 5})
    assert text == "hover failed: position (5000, 5) is outside the screen" and desk.moves == []
    rec = json.loads((tmp_path / "steps" / "01" / "action.json").read_text())
    assert rec["ok"] is False and rec["tool"] == "hover"
    for _ in range(19):
        svc.call("key", {"name": "Tab"})
    text, img = svc.call("look", {})
    assert text == mcp_server.LIMIT_TEXT and img is None
    assert json.loads((tmp_path / "step_limit.json").read_text()) == {"calls": 21}
    assert not (tmp_path / "steps" / "21").exists()
    assert svc.call("hover", {"x": 1, "y": 1})[0] == mcp_server.LIMIT_TEXT


@needs_cv2
def test_x1_text_is_f2_in_screen_pixels(tmp_path):
    svc, desk = service(tmp_path, "X1", TreeSeq(tree_json(OK, HELLO)))
    assert svc.scale == 1.0
    text, _ = svc.call("observe", {})
    assert text == 'screen 1920x1080, 2 elements\nbtn "OK" 150,120\ntext "Hello" 350,120'
    svc.call("click", {"x": 150, "y": 120})
    assert desk.calls[-1][:3] == ("click", 150, 120)
    assert json.loads((tmp_path / "steps" / "02" / "tree.json").read_text())["image_size"] == [1920, 1080]


@needs_cv2
def test_x2_lean_state_file_makes_first_click_a_change(tmp_path):
    initial = tree_json(OK, HELLO)
    obs = mcp_server.TreeFirstObserver("X2_lean", ":150", build_fn=TreeSeq(initial))
    first = obs.observe(FakeDesk(), "initial")
    assert first.text.splitlines()[0] == "screen 1280x720, 2 elements (full)"
    (tmp_path / "tree_state.json").write_text(json.dumps(obs.state()))
    svc, _ = service(tmp_path, "X2_lean", TreeSeq(tree_json(OK, HELLO, MENU)))
    text, _ = svc.call("click", {"x": 100, "y": 80})
    assert text == 'changes: +1 -0 ~0, 3 elements\n+ 3 menuitem "Menu" 373,147'     # ids continue from the initial list
    # without the state file the first observation of an episode is a full list
    other = tmp_path / "other"
    other.mkdir()
    svc2, _ = service(other, "X2_lean", TreeSeq(tree_json(OK, HELLO, MENU)))
    assert svc2.call("click", {"x": 100, "y": 80})[0].splitlines()[0].endswith("(full)")


@needs_cv2
def test_s_shot_lean_scale_and_observation(tmp_path):
    svc, desk = service(tmp_path, "S_shot_lean", TreeSeq(tree_json()))
    assert svc.scale == 1.5
    text, img = svc.call("click", {"x": 100, "y": 50})
    assert desk.calls[-1][:3] == ("click", 150, 75)
    assert text == observation.SHOT_NOTE and img[:8] == b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------- plugin runner
@pytest.fixture
def plugin():
    run.load_plugin("bench.variants.tree_first.conds")
    yield run
    run.PLUGIN = None


def test_claude_command_plugin(plugin):
    job = {"task": "t", "app": "a", "cond": "X2_lean", "rep": 0, "sentence": "do it"}
    cmd = run.claude_command(job, "claude-haiku-5-5", "/x/mcp.json")
    assert cmd[:6] == ["claude", "-p", "--input-format", "stream-json", "--model", "claude-haiku-5-5"]
    assert "Task: do it" not in cmd
    assert cmd[cmd.index("--allowedTools") + 1].split(",") == [f"mcp__p125__{t}" for t in conds.COND_SPECS["X2_lean"]["tools"]]
    assert "mcp__p125__observe" not in cmd[cmd.index("--allowedTools") + 1]
    assert cmd[cmd.index("--system-prompt") + 1] == conds.COND_SPECS["X2_lean"]["system_prompt"]
    job["cond"] = "X2"
    cmd = run.claude_command(job, "claude-haiku-5-5", "/x/mcp.json")
    assert cmd[:3] == ["claude", "-p", "Task: do it"] and "--input-format" not in cmd
    assert cmd[cmd.index("--allowedTools") + 1].split(",") == [f"mcp__p125__{t}" for t in
                                                                ("observe", "click", "type", "key", "scroll", "done", "hover", "look")]
    assert run.cond_mcp_module("X2") == "bench.variants.tree_first.mcp_server" and run.cond_mcp_module("S_shot") == "bench.agent.mcp_server"
    assert run.cond_model("X1_sonnet") == "claude-sonnet-5-5" and run.cond_model("X1") == "claude-haiku-5-5"
    assert run.all_conds()[-5:] == ["X1", "X1_sonnet", "X2", "S_shot_lean", "X2_lean"]


def _transcript(path, tools, status="connected"):
    init = {"type": "system", "subtype": "init", "cwd": str(run.AGENT_CWD_ROOT / "x"),
            "mcp_servers": [{"name": "p125", "status": status}], "tools": tools}
    path.write_text(json.dumps(init) + "\n" + json.dumps({"type": "system", "subtype": "init", "tools": []}) + "\n")


def test_mcp_ok_per_condition(plugin, tmp_path):
    lean = [f"mcp__p125__{t}" for t in conds.COND_SPECS["X2_lean"]["tools"]]
    six = run.TOOLS.split(",")
    _transcript(tmp_path / "lean.jsonl", lean)
    _transcript(tmp_path / "six.jsonl", six)
    _transcript(tmp_path / "down.jsonl", lean, status="failed")
    assert run.mcp_ok(tmp_path / "lean.jsonl", "X2_lean")
    assert not run.mcp_ok(tmp_path / "lean.jsonl", "X2")            # X2 also needs observe
    assert not run.mcp_ok(tmp_path / "lean.jsonl")                  # the R1 default is the six tools
    assert run.mcp_ok(tmp_path / "six.jsonl") and run.mcp_ok(tmp_path / "six.jsonl", "X1")
    assert not run.mcp_ok(tmp_path / "six.jsonl", "S_shot_lean")    # lean has no observe
    assert not run.mcp_ok(tmp_path / "down.jsonl", "X2_lean")


def test_harness_error(plugin, tmp_path):
    assert conds.harness_error("X1", tmp_path) is None
    (tmp_path / "server_errors.txt").write_text("step 1 observe:\nTraceback...\nbench.variants.tree_first.ours_client.OursServerUnavailable: x")
    assert "unavailable" in conds.harness_error("X1", tmp_path)
    (tmp_path / "server_errors.txt").write_text("step 1 observe:\nValueError: boom")
    assert conds.harness_error("X1", tmp_path) is None
    assert "initial" in conds.harness_error("X2_lean", tmp_path)
    (tmp_path / "initial").mkdir()
    (tmp_path / "initial" / "obs.txt").write_text("x")
    assert conds.harness_error("X2_lean", tmp_path) is None
    (tmp_path / "server_error.txt").write_text("trace")
    assert conds.harness_error("X2_lean", tmp_path)


@needs_cv2
def test_initial_message_blocks(plugin, tmp_path, monkeypatch):
    seq = TreeSeq(tree_json(OK, HELLO))
    monkeypatch.setattr(ours_client, "build_tree_json", lambda png, display, **kw: seq(png))
    ep = type("Ep", (), {"desk": FakeDesk()})()
    job = {"sentence": "press OK"}
    assert conds.initial_message("X2", job, ep, tmp_path, ":150") is None
    blocks = conds.initial_message("X2_lean", job, ep, tmp_path, ":150")
    assert blocks[0] == {"type": "text", "text": "Task: press OK"} and blocks[1]["type"] == "text"
    assert blocks[1]["text"].startswith("screen 1280x720, 2 elements (full)")
    assert (tmp_path / "initial" / "obs.txt").exists() and (tmp_path / "initial" / "tree.json").exists()
    assert json.loads((tmp_path / "initial" / "seconds.json").read_text())["n_elements"] == 2
    assert not (tmp_path / "steps").exists()
    assert json.loads((tmp_path / "tree_state.json").read_text())["next_id"] == 3
    shot = tmp_path / "shot"
    blocks = conds.initial_message("S_shot_lean", job, ep, shot, ":150")
    assert [b["type"] for b in blocks] == ["text", "image", "text"]
    assert blocks[1]["source"]["media_type"] == "image/png" and blocks[2]["text"] == observation.SHOT_NOTE
    assert (shot / "initial" / "shot.png").exists() and not (shot / "tree_state.json").exists()


# ---------------------------------------------------------------- resident ours server
def test_ours_server_roundtrip_and_unavailable(monkeypatch, tmp_path):
    display = ":150"
    path = str(tmp_path / "ours.sock")          # never the live shared socket
    monkeypatch.setattr(ours_client, "SOCKET", path)
    tree = tree_json(OK, HELLO)
    calls = []

    def build(png):
        calls.append(len(png))
        if png == b"boom":
            raise ValueError("bad image")
        return tree

    server = OursServer(path, build_fn=build)
    server.start_thread()
    try:
        assert ours_client.ping(display)
        assert ours_client.build_tree_json(b"\x89PNGxyz", display) == tree
        assert ours_client.build_tree_json(b"abc", display) == tree and calls == [7, 3]
        with pytest.raises(RuntimeError, match="bad image"):
            ours_client.build_tree_json(b"boom", display)
        assert ours_client.build_tree_json(b"abc", display) == tree      # still serving after an error
    finally:
        server.stop()
    with pytest.raises(ours_client.OursServerUnavailable):
        for _ in range(100):                                              # the server thread closes within 0.5 s
            ours_client.build_tree_json(b"abc", display, connect_timeout_s=1)
    with pytest.raises(ours_client.OursServerUnavailable):
        ours_client.build_tree_json(b"abc", ":9999", connect_timeout_s=1)


# ---------------------------------------------------------------- analysis helpers
def test_has_new_text():
    assert analyze.has_new_text('changes: +1 -0 ~0, 3 elements\n+ 4 text "Save" 1,2')
    assert analyze.has_new_text('changes: +0 -0 ~1, 3 elements\n~ 4 "Save" 1,2')
    assert not analyze.has_new_text('changes: +1 -0 ~0, 3 elements\n+ 4 btn 1,2')
    assert not analyze.has_new_text('changes: +0 -0 ~1, 3 elements\n~ 4 "" 1,2\n- 3')
    assert not analyze.has_new_text("no change, 3 elements")


def test_cleared_clicks_counts_emptied_names(tmp_path):
    icon = el("e1", "aria:button", "目", [100, 100, 20, 20])         # icon-sized non-text box: OCR name dropped by cleaning
    btn = el("e2", "aria:button", "Save", [300, 100, 100, 40])
    ep = tmp_path / "ep"
    (ep / "steps" / "01").mkdir(parents=True)
    (ep / "steps" / "02").mkdir(parents=True)
    (ep / "steps" / "01" / "tree.json").write_text(json.dumps(tree_json(icon, btn)))
    (ep / "steps" / "01" / "action.json").write_text(json.dumps({"tool": "observe", "ok": True}))
    (ep / "steps" / "02" / "action.json").write_text(json.dumps({"tool": "click", "ok": True, "screen_xy": [110, 110]}))
    row = {"cond": "X1", "dir": str(ep), "ok": True, "stop_reason": "done", "task": "t", "rep": 0}
    out = analyze.cleared_clicks([row])["X1"]
    assert out["success"] == {"clicks": 1, "name_cleared": 1} and out["top_names"] == [("目", 1)]
    (ep / "steps" / "02" / "action.json").write_text(json.dumps({"tool": "click", "ok": True, "screen_xy": [350, 120]}))
    assert analyze.cleared_clicks([row])["X1"]["success"] == {"clicks": 1}
