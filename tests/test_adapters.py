import json
import os
import shutil

import pytest

from pixeltree.trace import adapters as A
from pixeltree.trace.format import append_step, make_step, read_trace, write_trace

FX = os.path.join(os.path.dirname(__file__), "fixtures")


def _row(jsonl, rel_dir):
    with open(os.path.join(FX, jsonl), encoding="utf-8") as f:
        r = json.loads(f.readline())
    r["dir"] = os.path.join(FX, rel_dir or r["dir"])
    return r


def _tasks():
    return A.read_tasks_json(os.path.join(FX, "tasks_v1.json"))


def test_w2c_omp_trace():
    row = _row("w2c/episodes_v1_1.jsonl", None)
    t = A.build_trace({"source": "w2c", "dir": row["dir"], "row": row, "tasks": {}})
    m, steps, res = t["meta"], t["steps"], t["result"]
    assert m["id"] == "w2c__deepseek__gitg_stage_readme__H_ours__r0"
    assert m["task"]["sentence"] == ("In gitg, stage the modified file README.md without "
                                     "committing, and leave src/util.py unstaged.")
    assert m["shell"] == "OMP" and m["observation"] == "tree+image"
    assert len(steps) == 3
    s2 = steps[1]
    assert s2["action"]["tool"] == "click"
    assert s2["action"]["screen_xy"] == [28, 27]
    # the agent text is attached to the step that issued the call (OMP visible thinking)
    assert steps[0]["agent"]["thinking"] == "Let me start by observing the screen."
    assert steps[0]["agent"]["message_index"] == 0
    assert s2["agent"]["message_index"] == 1 and s2["agent"]["thinking"].startswith("This is gitg")
    assert s2["tree"]["source"] == "ours" and len(s2["tree"]["elements"]) == 13
    assert s2["observation"]["text"].startswith("Screenshot 1280x720")
    assert s2["observation"]["image"].endswith("steps/02/shot.png")
    # success and grading detail come from the v1_1 row, not from result.json
    assert res["ok"] is False
    assert res["grader_detail"] == "staged=[] commits='5'"
    assert res["stop_reason"] == "fail_answer"
    assert res["tokens"] == {"input": 34575, "output": 2550, "cache_read": 59648}


def test_p125_claude_trace_uses_tasks_json_and_v1_1_row():
    row = _row("p125/episodes_v1_1.jsonl", None)
    t = A.build_trace({"source": "p125", "dir": row["dir"], "row": row, "tasks": _tasks()})
    m, steps, res = t["meta"], t["steps"], t["result"]
    assert m["id"] == "p125__haiku__gitg_commit_readme__T_ours__r0"
    assert m["task"]["sentence"] == _tasks()["gitg_commit_readme"]["sentence"]
    assert m["shell"] == "claude -p" and m["observation"] == "tree" and m["agent_image_size"] is None
    assert [s["action"]["tool"] for s in steps] == ["observe", "scroll", "observe"]
    assert steps[1]["action"]["screen_xy"] == [600, 300]
    # steps 2 and 3 are one message in the transcript (several rows with the same message.id): same message_index
    assert [s["agent"]["message_index"] for s in steps] == [0, 1, 1]
    assert res["ok"] is False and "Use util in main" in res["grader_detail"]
    assert res["stop_reason"] == "no_done"
    # the fake result.json contradicts the v1_1 row and must not be used
    with open(os.path.join(row["dir"], "result.json"), encoding="utf-8") as f:
        assert json.load(f)["ok"] is True


def test_w2_trace_ignores_f2_and_reads_v1_1():
    row = _row("w2/episodes_v1_1.jsonl", None)
    assert os.path.exists(os.path.join(row["dir"], "steps", "01", "f2.txt"))
    t = A.build_trace({"source": "w2", "dir": row["dir"], "row": row, "tasks": _tasks()})
    m, steps, res = t["meta"], t["steps"], t["result"]
    assert m["id"] == "w2__haiku__drawing_no_ctrl_zoom__X1__r2"
    assert m["task"]["sentence"] == _tasks()["drawing_no_ctrl_zoom"]["sentence"]
    assert m["observation"] == "tree" and m["rep"] == 2
    assert len(steps) == 3 and steps[1]["action"]["tool"] == "click"
    assert steps[1]["action"]["screen_xy"] == [1893, 26]
    assert res["ok"] is False and res["stop_reason"] == "fail_answer"
    assert "ctrl-zoom=None" in res["grader_detail"]


def test_plan_p125_picks_row_by_dir_name(tmp_path):
    root = tmp_path / "out"
    (root / "p125" / "final").mkdir(parents=True)
    row = _row("p125/episodes_v1_1.jsonl", None)
    with open(root / "p125" / "final" / "episodes_v1_1.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    jobs = A.plan_p125(str(root), ["gitg_commit_readme__T_ours__r0"], os.path.join(FX, "tasks_v1.json"))
    assert len(jobs) == 1 and jobs[0]["dir"] == row["dir"]
    with pytest.raises(KeyError):
        A.plan_p125(str(root), ["nope__T_ours__r0"], os.path.join(FX, "tasks_v1.json"))


# ---------------------------------------------------------------- R5 episode selection

def _r(task, cond, rep, tag, stop="done", d="/x"):
    return {"task": task, "cond": cond, "rep": rep, "tag": tag, "stop_reason": stop, "dir": d + "/" + tag}


def test_select_w2c_later_row_overrides_earlier_and_off_list_dropped():
    rows = [
        _r("t1", "S_shot", 0, "first"),
        _r("t2", "S_shot", 0, "first"),
        _r("zz", "S_shot", 0, "off-list"),
        _r("t1", "S_shot", 0, "second"),   # a later row overrides an earlier one
    ]
    out = A.select_w2c_rows(rows, ["t1", "t2"], has_step_limit=lambda d: False)
    assert [(r["task"], r["tag"]) for r in out] == [("t1", "second"), ("t2", "first")]
    assert rows[0]["tag"] == "first"  # the input is not modified


def test_select_w2c_timeout_with_step_limit_file_becomes_step_limit():
    rows = [
        _r("t1", "S_shot", 0, "a", stop="timeout"),
        _r("t1", "T_ours", 0, "b", stop="timeout"),
        _r("t1", "H_ours", 0, "c", stop="done"),
    ]
    out = A.select_w2c_rows(rows, ["t1"], has_step_limit=lambda d: d.endswith("/a") or d.endswith("/c"))
    by = {r["cond"]: r["stop_reason"] for r in out}
    assert by == {"S_shot": "step_limit", "T_ours": "timeout", "H_ours": "done"}


def test_select_w2c_step_limit_checks_real_file(tmp_path):
    d = tmp_path / "ep"
    d.mkdir()
    (d / "step_limit.json").write_text('{"calls": 23}')
    out = A.select_w2c_rows([_r("t1", "S_shot", 0, "a", "timeout", str(tmp_path))], ["t1"])
    assert out[0]["stop_reason"] == "timeout"      # no step_limit.json in dir
    out = A.select_w2c_rows([{"task": "t1", "cond": "S_shot", "rep": 0, "stop_reason": "timeout", "dir": str(d)}], ["t1"])
    assert out[0]["stop_reason"] == "step_limit"


def test_plan_w2c_reads_runs_in_order_and_overlays(tmp_path):
    root = tmp_path
    for sub, rows in {
        "haiku/formal_seq": [_r("t1", "S_shot", 0, "seq", "timeout", str(root)), _r("t2", "S_shot", 0, "seq")],
        "haiku/formal_seq2": [_r("t1", "S_shot", 0, "seq2")],
        "haiku/formal": [_r("t1", "S_shot", 0, "NOT-READ")],
    }.items():
        (root / sub).mkdir(parents=True)
        with open(root / sub / A.JSONL_NAME, "w") as f:
            for r in rows:
                r["model"] = "opencode-go/claude-haiku-5-5"
                f.write(json.dumps(r) + "\n")
    tf = root / "tasks.txt"
    tf.write_text("t1\nt2\n")
    jobs = A.plan_w2c(str(root), str(tf), {"haiku": ["haiku/formal_seq", "haiku/formal_seq2"]})
    assert [(j["row"]["task"], j["row"]["tag"]) for j in jobs] == [("t1", "seq2"), ("t2", "seq")]


# --------------------------------------------------- hand-made transcripts: message / call alignment

def _omp_line(role, content):
    return json.dumps({"type": "message_end", "message": {"role": role, "content": content}})


def test_omp_multi_call_message_attaches_text_only_to_first_call(tmp_path):
    p = tmp_path / "t.jsonl"
    lines = [
        json.dumps({"type": "session"}),
        _omp_line("user", [{"type": "text", "text": "Task: Do the thing."}]),
        _omp_line("assistant", [
            {"type": "thinking", "thinking": "hmm"},
            {"type": "text", "text": "I will look."},
            {"type": "toolCall", "name": "mcp__p125_observe", "arguments": {}},
            {"type": "toolCall", "name": "mcp__p125_click", "arguments": {"x": 1, "y": 2}},
        ]),
        _omp_line("toolResult", [{"type": "image", "data": "x"}]),
        _omp_line("assistant", [
            {"type": "text", "text": "Now done."},
            {"type": "toolCall", "name": "mcp__p125_done", "arguments": {"answer": "ok"}},
        ]),
    ]
    p.write_text("\n".join(lines) + "\n")
    task, calls = A.parse_omp_transcript(str(p))
    assert task == "Do the thing."
    assert [c["name"] for c in calls] == ["observe", "click", "done"]
    assert [c["message_index"] for c in calls] == [0, 0, 1]
    assert [c["text"] for c in calls] == ["I will look.", "", "Now done."]
    assert [c["thinking"] for c in calls] == ["hmm", "", ""]


def test_claude_transcript_merges_rows_by_message_id_and_strips_prefix(tmp_path):
    def line(mid, blocks):
        return json.dumps({"type": "assistant", "message": {"id": mid, "content": blocks}})
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join([
        json.dumps({"type": "system"}),
        line("m1", [{"type": "text", "text": "first look"}]),
        line("m1", [{"type": "tool_use", "name": "mcp__p125__observe", "input": {}}]),
        line("m1", [{"type": "tool_use", "name": "mcp__p125__click", "input": {"x": 5, "y": 6}}]),
        json.dumps({"type": "user", "message": {"content": []}}),
        line("m2", [{"type": "thinking", "thinking": "", "signature": "zz"},
                    {"type": "tool_use", "name": "mcp__p125__done", "input": {"answer": "a"}}]),
    ]) + "\n")
    calls = A.parse_claude_transcript(str(p))
    assert [c["name"] for c in calls] == ["observe", "click", "done"]
    assert [c["message_index"] for c in calls] == [0, 0, 1]
    assert [c["text"] for c in calls] == ["first look", "", ""]
    assert calls[1]["args"] == {"x": 5, "y": 6}


def test_step_dirs_are_authoritative_when_transcript_has_more_calls(tmp_path):
    ep = tmp_path / "ep"
    for k in (1, 2):
        d = ep / "steps" / ("%02d" % k)
        d.mkdir(parents=True)
        (d / "action.json").write_text(json.dumps({"step": k, "tool": "observe", "args": {}, "screen_xy": None, "ok": True,
                                                   "error": None, "t_start": 1.0, "t_end": 2.5}))
        (d / "obs.txt").write_text("o%d" % k)
    calls = [{"name": "observe", "args": {}, "text": "t%d" % i, "thinking": "", "message_index": i} for i in range(4)]
    steps = A.build_steps(str(ep), calls)
    assert len(steps) == 2 and steps[1]["agent"]["text"] == "t1" and steps[1]["duration_s"] == 1.5
    steps = A.build_steps(str(ep), calls[:1])   # fewer calls than steps: missing agent fields are empty
    assert steps[1]["agent"] == {"text": "", "thinking": "", "message_index": None}
    assert steps[1]["screen"] is None and steps[1]["tree"] is None


def test_trace_roundtrip_and_running_trace_has_no_result(tmp_path):
    meta = {"format": "pixeltree.trace/1", "id": "x"}
    d = str(tmp_path / "tr")
    write_trace(d, meta, [make_step(1, tool="observe")], None)
    tr = read_trace(d)
    assert tr["result"] is None and len(tr["steps"]) == 1
    append_step(d, make_step(2, tool="click", args={"x": 1, "y": 2}, screen_xy=[3, 4]))
    tr = read_trace(d)
    assert [s["i"] for s in tr["steps"]] == [1, 2] and tr["steps"][1]["action"]["screen_xy"] == [3, 4]
    write_trace(d, meta, tr["steps"], {"ok": True})
    assert read_trace(d)["result"] == {"ok": True}
