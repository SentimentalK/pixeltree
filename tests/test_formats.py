"""Formats: F0 = the tree text, F3 rebuilds the full F1/F2 text exactly, cleaning de-duplicates and blanks names.

    python -m pytest tests/test_formats.py -q

Pure Python: no model, no GPU, no display.
"""
import unittest

from pixeltree import formats as F
from pixeltree.perceive.tree import Element, make_tree, to_json, to_text


def el(role, name, box, conf=0.9, id_=""):
    return {"id": id_, "role": role, "name": name, "box": list(box), "conf": conf}


def tree_of(elements, size=(1920, 1080)):
    return {"image_size": list(size), "elements": [dict(e, id=f"e{k}") for k, e in enumerate(elements, 1)]}


def run_f3(trees):
    """Encode a sequence of trees with Delta3, decode with Decoder3; returns (texts, fulls, mismatching steps)."""
    enc, dec = F.Delta3((1920, 1080)), F.Decoder3()
    texts, fulls, bad = [], [], []
    for k, t in enumerate(trees):
        els = F.clean(t)
        text, full, _ = enc.step(els)
        texts.append(text)
        fulls.append(full)
        if dec.feed(text) != F.f2_keys(els):
            bad.append(k)
    return texts, fulls, bad


class TestF0(unittest.TestCase):
    def test_f0_is_the_tree_text(self):
        elements = [Element(id="", role="aria:button", name='Say "hi"', box=[10, 10, 60, 30], conf=0.9),
                    Element(id="", role="vax:visibleText", name="  two\tspaces  ", box=[100, 12, 80, 20]),
                    Element(id="", role="aria:img", name="", box=[300, 400, 24, 24], conf=None),
                    Element(id="", role="aria:listitem", name="Row", box=[0, 500, 1200, 30], conf=0.5)]
        tree = make_tree("ours", (1920, 1080), elements)
        self.assertEqual(F.f0(to_json(tree)), to_text(tree))


class TestF3Lossless(unittest.TestCase):
    base = [el("aria:button", "Open", (10, 10, 60, 30)), el("vax:visibleText", "Title", (800, 10, 200, 20)),
            el("aria:listitem", "Alpha", (0, 100, 300, 30)), el("aria:listitem", "Beta", (0, 140, 300, 30)),
            el("aria:listitem", "Gamma", (0, 180, 300, 30)), el("aria:button", 'Back\\slash "q"', (400, 10, 90, 30)),
            el("aria:slider", "", (900, 500, 200, 20))]  # a role outside SHORT_ROLE

    def test_disappear_rename_move_and_unchanged(self):
        t0 = tree_of(self.base)
        t1 = tree_of(self.base)                                            # no change
        t2 = tree_of([e for e in self.base if e["name"] != "Beta"])        # one element disappears
        t3 = tree_of([dict(e, name="Alpha 2") if e["name"] == "Alpha" else e
                      for e in self.base if e["name"] != "Beta"])          # renamed
        t4 = tree_of([dict(e, box=[e["box"][0] + 30] + e["box"][1:]) if e["name"] == "Open" else e
                      for e in self.base if e["name"] != "Beta"]
                     + [el("aria:menuitem", "New", (20, 50, 100, 25))])    # moved + added
        texts, fulls, bad = run_f3([t0, t1, t2, t3, t4])
        self.assertEqual(bad, [])
        self.assertEqual(fulls, [True, False, False, False, False])
        self.assertTrue(texts[1].startswith("no change"))
        self.assertRegex(texts[2], r"^changes: \+0 -1 ~0")
        self.assertRegex(texts[3], r"^changes: \+0 -0 ~1")
        self.assertRegex(texts[4], r"^changes: \+1 -0 ~2")  # Open moved, "Alpha 2" back to "Alpha"

    def test_full_fallback_when_most_elements_change(self):
        other = [el("aria:button", f"Dialog {k}", (500, 300 + 40 * k, 200, 30)) for k in range(8)]
        t0, t1 = tree_of(self.base), tree_of(other + self.base[:1])
        t2 = tree_of(other[:7] + self.base[:1])
        texts, fulls, bad = run_f3([t0, t1, t2])
        self.assertEqual(bad, [])
        self.assertEqual(fulls, [True, True, False])
        self.assertIn("(full)", texts[1])


class TestClean(unittest.TestCase):
    def test_dedup_nested_same_name_keeps_the_container(self):
        t = tree_of([el("aria:listitem", "Branches", (14, 84, 86, 19)), el("vax:visibleText", "Branches", (34, 85, 65, 16))])
        kept = F.clean(t)
        self.assertEqual([(e["role"], e["name"]) for e in kept], [("aria:listitem", "Branches")])

    def test_no_dedup_same_name_side_by_side(self):
        t = tree_of([el("vax:visibleText", "Test User", (1228, 57, 60, 14)),
                     el("vax:visibleText", "Test User", (1408, 57, 60, 14))])
        self.assertEqual(len(F.clean(t)), 2)

    def test_icon_glyph_name_blanked(self):
        t = tree_of([el("aria:button", "×", (1881, 15, 24, 24)), el("aria:button", "业", (1708, 10, 34, 33))])
        self.assertEqual([e["name"] for e in F.clean(t)], ["", ""])

    def test_real_names_kept(self):
        t = tree_of([el("aria:button", "Open", (11, 10, 66, 33)), el("vax:visibleText", "1", (269, 742, 11, 14)),
                     el("aria:listitem", "☆ Trash", (10, 300, 63, 20))])
        self.assertEqual([e["name"] for e in F.clean(t)], ["Open", "1", "Trash"])

    def test_container_name_blanked_but_texts_kept(self):
        t = tree_of([el("aria:listitem", "Tts t User Tts t User 22da", (408, 52, 1437, 24)),
                     el("vax:visibleText", "Test User", (1228, 57, 60, 14)),
                     el("vax:visibleText", "Jan 4, 10:00", (1767, 57, 84, 15))])
        self.assertEqual([e["name"] for e in F.clean(t)], ["", "Test User", "Jan 4, 10:00"])




class TestThresholdForwarding(unittest.TestCase):
    def test_threshold_set_on_the_package_reaches_the_encoder(self):
        a = [el("aria:button", "Open", (10, 10, 60, 30))]
        b = [el("aria:button", "Open", (110, 10, 60, 30))]  # same name, centre moved 100 px
        old = F.MATCH_MOVE_PX
        try:
            F.MATCH_MOVE_PX = 200
            self.assertEqual(F.match(F.clean(tree_of(a)), F.clean(tree_of(b))), {0: 0})
            F.MATCH_MOVE_PX = 50  # moved 100 px: no longer "the same element"; boxes do not overlap enough to rename
            self.assertEqual(F.match(F.clean(tree_of(a)), F.clean(tree_of(b))), {})
        finally:
            F.MATCH_MOVE_PX = old


if __name__ == "__main__":
    unittest.main()
