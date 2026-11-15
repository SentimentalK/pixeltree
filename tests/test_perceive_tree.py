"""Tree data classes, reading order, text / JSON formats, and the model-free parts of the perception package.

    python -m pytest tests/test_perceive_tree.py -q

The tree tests are pure Python. Tests that need the `perceive` extra (OpenCV, onnxruntime, ...) skip without it;
none of them loads a model.
"""
import json
import re

import pytest

from pixeltree.perceive.tree import MAX_LINES, Element, make_tree, order, to_json, to_text

LINE = re.compile(r'^(?P<role>\S+) \[(?P<id>e\d+)\] "(?P<name>(?:[^"\\]|\\.)*)" '
                  r'@\((?P<x>-?\d+),(?P<y>-?\d+),(?P<w>-?\d+),(?P<h>-?\d+)\) c=\((?P<cx>-?\d+),(?P<cy>-?\d+)\)$')
HEAD = re.compile(r"^screen (?P<w>\d+)x(?P<h>\d+), (?P<n>\d+) elements$")


def parse_text(text):
    """Inverse of to_text for trees with at most MAX_LINES elements: (image_size, [(id, role, name, box, centre)])."""
    lines = text.split("\n")
    head = HEAD.match(lines[0])
    assert head, lines[0]
    rows = []
    for line in lines[1:]:
        m = LINE.match(line)
        assert m, line
        rows.append((m["id"], m["role"], m["name"].replace('\\"', '"'),
                     [int(m[k]) for k in ("x", "y", "w", "h")], [int(m["cx"]), int(m["cy"])]))
    assert len(rows) == int(head["n"])
    return (int(head["w"]), int(head["h"])), rows


def el(role, name, box, conf=0.9):
    return Element(id="", role=role, name=name, box=list(box), conf=conf)


SAMPLE = [
    el("aria:button", "Save", (900, 12, 60, 30)),
    el("aria:textbox", 'say "hi"\nsecond line', (10, 100, 400, 80)),     # quote and newline in the name
    el("vax:visibleText", "File", (10, 10, 40, 20)),
    el("aria:img", "", (200, 400, 33, 33), conf=None),                   # odd size: centre rounds down
    el("vax:visibleText", "Edit", (60, 12, 40, 18)),
    el("aria:listitem", "  spaced \t out  ", (0, 300, 1200, 31)),
]


def test_text_roundtrip_matches_elements():
    tree = make_tree("ours", (1920, 1080), SAMPLE)
    size, rows = parse_text(to_text(tree))
    assert size == (1920, 1080)
    assert [r[0] for r in rows] == [f"e{k}" for k in range(1, len(SAMPLE) + 1)]
    for (eid, role, name, box, centre), e in zip(rows, tree.elements):
        assert (eid, role, box, centre) == (e.id, e.role, [int(v) for v in e.box], e.center)
        assert name == " ".join(e.name.split())  # whitespace collapsed, quotes preserved


def test_centre_is_integer_floor_of_box_middle():
    assert Element("e1", "aria:img", "", [200, 400, 33, 33]).center == [216, 416]
    assert Element("e1", "aria:img", "", [0, 0, 1, 1]).center == [0, 0]


def test_reading_order_rows_then_left_to_right():
    # Two visual rows of height ~20: "File"/"Edit"/"Save" share the top row even though their y differs by a few px.
    items = [el("a", "Save", (900, 14, 60, 20)), el("a", "File", (10, 10, 40, 20)), el("a", "Edit", (60, 12, 40, 18)),
             el("a", "Row2-right", (500, 200, 40, 20)), el("a", "Row2-left", (20, 202, 40, 20))]
    names = [e.name for e in order(items)]
    assert names == ["File", "Edit", "Save", "Row2-left", "Row2-right"]


def test_make_tree_numbers_in_reading_order_and_does_not_mutate_input_order():
    items = [el("a", "b", (100, 100, 10, 10)), el("a", "a", (10, 10, 10, 10))]
    tree = make_tree("ours", (200, 200), items)
    assert [(e.id, e.name) for e in tree.elements] == [("e1", "a"), ("e2", "b")]
    assert [e.name for e in items] == ["b", "a"]  # the input list keeps its order


def test_empty_tree():
    tree = make_tree("ours", (640, 480), [])
    assert to_text(tree) == "screen 640x480, 0 elements"
    assert to_json(tree)["elements"] == []


def test_text_is_truncated_after_max_lines_with_a_count():
    many = [el("aria:button", f"b{k}", (k % 50 * 30, k // 50 * 40, 20, 20)) for k in range(MAX_LINES + 7)]
    lines = to_text(make_tree("ours", (1920, 1080), many)).split("\n")
    assert lines[0] == f"screen 1920x1080, {MAX_LINES + 7} elements"
    assert len(lines) == 1 + MAX_LINES + 1
    assert lines[-1] == "... 7 more elements"


def test_json_has_the_documented_fields_and_is_serialisable():
    tree = make_tree("ours", (1920, 1080), SAMPLE, {"total_s": 1.23456789, "n": 3})
    data = json.loads(json.dumps(to_json(tree)))
    assert set(data) == {"source", "image_size", "elements", "timings"}
    assert data["image_size"] == [1920, 1080]
    assert data["timings"] == {"total_s": 1.2346, "n": 3}
    first = data["elements"][0]
    assert set(first) == {"id", "role", "name", "box", "center", "conf"}
    assert first["conf"] == 0.9
    assert [e["conf"] for e in data["elements"] if e["role"] == "aria:img"] == [None]


# ---------------------------------------------------------------- weights / device resolution (no model loaded)
def test_missing_weights_error_points_to_the_download_script(monkeypatch, tmp_path):
    from pixeltree.perceive import ours

    monkeypatch.delenv("PIXELTREE_WEIGHTS", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))  # default location ~/.cache/pixeltree is empty
    with pytest.raises(FileNotFoundError, match=r"python weights/download\.py"):
        ours.resolve_weights()


def test_weights_resolution_order(monkeypatch, tmp_path):
    from pixeltree.perceive import ours

    arg, env = tmp_path / "arg.pt", tmp_path / "env.pt"
    arg.write_bytes(b"x")
    env.write_bytes(b"x")
    monkeypatch.setenv("PIXELTREE_WEIGHTS", str(env))
    assert ours.resolve_weights(arg) == arg
    assert ours.resolve_weights() == env


def test_device_resolution_order(monkeypatch):
    from pixeltree.perceive import ours

    monkeypatch.delenv("PIXELTREE_DEVICE", raising=False)
    assert ours.resolve_device() == "cpu"
    monkeypatch.setenv("PIXELTREE_DEVICE", "1")
    assert ours.resolve_device() == 1
    assert ours.resolve_device("cpu") == "cpu"
    with pytest.raises(ValueError):
        ours.resolve_device("tpu")


# ---------------------------------------------------------------- OCR line grouping and icon bands (need the extra)
def test_join_lines_reading_order():
    ocr = pytest.importorskip("pixeltree.perceive.ocr")
    boxes = [[100, 50, 160, 66], [10, 52, 90, 68], [10, 10, 80, 26]]   # right word of row 2, left word of row 2, row 1
    assert ocr.join_lines(boxes, ["world", "hello", "first line"]) == "first line\nhello world"
    assert ocr.join_lines(boxes, ["", None, "  "]) == ""


def test_ctc_greedy_collapses_repeats_and_blanks():
    ocr = pytest.importorskip("pixeltree.perceive.ocr")
    chars = ["<blank>", "a", "b"]
    text, score = ocr.ctc_greedy([1, 1, 0, 1, 2, 2], [0.9, 0.8, 1.0, 0.7, 0.6, 0.5], chars)
    assert text == "aab"                            # 1,1 collapse to one 'a'; the blank separates the next 'a'
    assert score == pytest.approx((0.9 + 0.7 + 0.6) / 3)


def test_icon_label_band_covers_the_caption_below_the_glyph():
    observer = pytest.importorskip("pixeltree.perceive.observer")
    x0, y0, x1, y1 = observer.icon_label_band([100, 100, 164, 180], 1920, 1080)
    assert y1 > 180 and y0 < 180 and y0 >= 100          # a band around the bottom edge of the icon box
    assert x0 < 100 and x1 > 164                         # slightly wider than the box (captions overhang the icon)
    assert observer.icon_label_band([100, 100, 120, 130], 1920, 1080) is None   # too small to carry a caption
