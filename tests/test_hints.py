from pixeltree.viewer.hints import merge_ranges, step_hints, summarize

TREE = [
    {"id": "e1", "role": "aria:button", "name": "Save", "box": [0, 0, 100, 40]},
    {"id": "e2", "role": "aria:button", "name": "", "box": [200, 0, 50, 40]},
]


def click(x, y, ok=True):
    return {"tool": "click", "ok": ok, "xy": [x, y]}


def shorts(h):
    return [x["short"] for x in h]


def test_click_on_unnamed_element():
    h = step_hints([click(210, 10)], [TREE], [None])
    assert shorts(h[0]) == ["Clicked an unnamed element"]


def test_click_outside_every_box_when_tree_exists():
    h = step_hints([click(900, 900)], [TREE], [None])
    assert shorts(h[0]) == ["Click landed outside every box"]


def test_click_on_named_element_and_no_tree_are_not_flagged():
    assert step_hints([click(10, 10)], [TREE], [None]) == [[]]
    assert step_hints([click(900, 900)], [None], [None]) == [[]]   # conditions without a tree never get "click landed outside every box"


def test_unchanged_screen_flagged_but_not_first_observe_or_done():
    steps = [{"tool": "observe", "ok": True, "xy": None},
             {"tool": "key", "ok": True, "xy": None},
             {"tool": "observe", "ok": True, "xy": None},
             {"tool": "done", "ok": True, "xy": None}]
    h = step_hints(steps, [None] * 4, [0.0, 0.4, 0.0, 0.0])
    assert [shorts(x) for x in h] == [[], ["Screen unchanged"], [], []]
    # a difference of exactly 1.0 does not count as unchanged
    assert step_hints(steps[1:2] * 2, [None] * 2, [None, 1.0]) == [[], []]


def test_failed_action_flagged():
    h = step_hints([{"tool": "key", "ok": False, "xy": None}], [None], [None])
    assert shorts(h[0]) == ["Action failed"]


def test_merge_consecutive_same_phrase_into_ranges():
    steps = [{"tool": "key", "ok": True, "xy": None}] * 6
    diffs = [None, 0.0, 0.0, 5.0, 0.0, 0.0]
    h = step_hints(steps, [None] * 6, diffs)
    h[2].append({"code": "error", "short": "Action failed", "full": ""})
    assert merge_ranges(h) == [(2, 3, "Screen unchanged"), (3, 3, "Action failed"), (5, 6, "Screen unchanged")]


def test_summary_sentence_parts():
    steps = [{"tool": "key", "ok": True, "xy": None}] * 4
    h = step_hints(steps, [None] * 4, [None, 0.0, 0.0, 9.0])
    s = summarize({"ok": False, "stop_reason": "fail_answer"}, 4, h)
    assert s == "4 steps, failed (agent said it could not do it). Suspicious steps: steps 2\u20133: Screen unchanged. In the end the agent said it could not do the task."
    assert summarize({"ok": True, "stop_reason": "done"}, 3, [[], [], []]) == "3 steps, succeeded (agent said it was done)."
    assert summarize({"ok": False, "stop_reason": "step_limit"}, 20, [[]] * 20).endswith("It used all 20 steps.")
    assert summarize({"ok": False, "stop_reason": "timeout"}, 5, [[]] * 5).endswith("It was stopped by the timeout.")
    assert summarize(None, 2, [[], []]) == "2 steps."


def test_summary_lists_at_most_four_segments():
    steps = [{"tool": "key", "ok": False, "xy": None}] * 1
    hs = [[{"code": "error", "short": "Action failed", "full": ""}] if i % 2 == 0 else [] for i in range(12)]
    s = summarize({"ok": False, "stop_reason": "done"}, 12, hs)
    assert s.count("Action failed") == 4
