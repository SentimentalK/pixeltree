from pixeltree.trace.treediff import element_at, tree_diff


def el(i, role, name, x, y, w=60, h=20):
    return {"id": i, "role": role, "name": name, "box": [x, y, w, h]}


def test_added_removed_moved_renamed_each_detected():
    prev = [
        el("e1", "aria:button", "Save", 10, 10),
        el("e2", "aria:button", "Cancel", 100, 10),
        el("e3", "aria:textbox", "Title", 10, 100),
        el("e4", "aria:button", "Gone", 300, 300),
    ]
    cur = [
        el("e1", "aria:button", "Save", 10, 10),          # unchanged
        el("e2", "aria:button", "Cancel", 120, 10),       # moved 20 px to the right -> moved
        el("e3", "aria:textbox", "Heading", 10, 100),     # renamed in place -> renamed
        el("e9", "aria:button", "New", 500, 500),         # added; Gone disappears
    ]
    d = tree_diff(prev, cur)
    assert [e["name"] for e in d["added"]] == ["New"]
    assert [e["name"] for e in d["removed"]] == ["Gone"]
    assert [(p["name"], c["name"], c["box"][0]) for p, c in d["moved"]] == [("Cancel", "Cancel", 120)]
    assert [(p["name"], c["name"]) for p, c in d["renamed"]] == [("Title", "Heading")]
    assert d["same"] == 1


def test_small_shift_is_same_not_moved():
    d = tree_diff([el("a", "r", "X", 10, 10)], [el("a", "r", "X", 13, 12)])
    assert d["same"] == 1 and not d["moved"]


def test_size_change_over_4px_counts_as_moved():
    d = tree_diff([el("a", "r", "X", 10, 10, 60, 20)], [el("a", "r", "X", 10, 10, 70, 20)])
    assert len(d["moved"]) == 1 and d["same"] == 0


def test_two_same_name_buttons_swapping_places_are_not_renamed():
    # two buttons with the same role and name (different sizes) swap places: they must be paired by distance, not mistaken for a rename through IoU
    a = el("e1", "aria:button", "OK", 0, 0, 40, 20)
    b = el("e2", "aria:button", "OK", 30, 0, 40, 20)
    cur_a = el("e1", "aria:button", "OK", 30, 0, 40, 20)
    cur_b = el("e2", "aria:button", "OK", 0, 0, 40, 20)
    d = tree_diff([a, b], [cur_a, cur_b])
    assert d["renamed"] == []
    assert d["added"] == [] and d["removed"] == []
    assert d["same"] == 2 and d["moved"] == []


def test_same_name_beyond_distance_falls_through_to_iou_rename_or_add_remove():
    # same name but > 40 px apart and boxes do not overlap: not paired -> one removed, one added
    d = tree_diff([el("a", "r", "X", 0, 0)], [el("b", "r", "X", 400, 400)])
    assert len(d["added"]) == 1 and len(d["removed"]) == 1 and not d["renamed"]


def test_different_role_is_never_renamed():
    d = tree_diff([el("a", "aria:button", "X", 0, 0)], [el("b", "aria:textbox", "Y", 0, 0)])
    assert not d["renamed"] and len(d["added"]) == 1 and len(d["removed"]) == 1


def test_prev_none_means_everything_added():
    cur = [el("a", "r", "X", 0, 0), el("b", "r", "Y", 50, 50)]
    d = tree_diff(None, cur)
    assert d["added"] == cur
    assert d["removed"] == [] and d["moved"] == [] and d["renamed"] == [] and d["same"] == 0


def test_element_at_picks_smallest_containing_box():
    big = el("big", "pane", "P", 0, 0, 500, 500)
    mid = el("mid", "pane", "M", 100, 100, 200, 200)
    small = el("small", "button", "B", 150, 150, 20, 20)
    assert element_at([big, mid, small], 160, 160)["id"] == "small"
    assert element_at([big, mid, small], 250, 250)["id"] == "mid"
    assert element_at([big, mid, small], 10, 10)["id"] == "big"


def test_element_at_outside_all_boxes_or_empty_is_none():
    assert element_at([el("a", "r", "X", 0, 0, 10, 10)], 50, 50) is None
    assert element_at([], 1, 1) is None
    assert element_at(None, 1, 1) is None
