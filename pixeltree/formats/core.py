"""Compact serializations of one element tree, and the change encoding between consecutive trees.

Pure Python, no third-party imports. Input everywhere is a tree dict (the JSON of `pixeltree.perceive.tree.to_json`):
{"image_size": [w, h], "elements": [{"id", "role", "name", "box": [x, y, w, h], "center", "conf"}, ...]}.

    F0  `pixeltree.perceive.tree.to_text`, verbatim.
    F1  compact lines: short role, quoted name (omitted when empty), box centre only.
    F3  elements sent as changes (Delta3 / Decoder3): full first step, then only added / removed / changed elements.
        (F2 = F1 after the optional name cleaning of `pixeltree.formats.clean`, which is off by default.)

F1 text (one line per element, reading order of the input tree):

    screen 1920x1080, <n> elements
    <short role> "<name>" <cx>,<cy>          # name present
    <short role> <cx>,<cy>                   # empty name

F3 text: a full step is the F1 text with a persistent id in front of every element line (`<id> <short role> ...`);
the header says `screen 1920x1080, <n> elements (full)`.  A change step is

    changes: +<a> -<r> ~<c>, <n> elements
    + <id> <short role> "<name>" <cx>,<cy>   # added (name omitted when empty)
    - <id>                                   # removed
    ~ <id> "<name>" <cx>,<cy>                # changed: the new name (always quoted, may be "") and centre

and `no change, <n> elements` when nothing changed.  The ids are plain integers, never reused inside an episode.

All thresholds are module constants.
"""
import difflib
import re

# ---------------------------------------------------------------- roles
SHORT_ROLE = {
    "aria:button": "btn", "aria:link": "link", "aria:menuitem": "menuitem", "aria:tab": "tab",
    "aria:checkbox": "check", "aria:radio": "radio", "aria:textbox": "input", "aria:combobox": "combo",
    "aria:gridcell": "cell", "aria:listitem": "item", "aria:heading": "heading", "aria:img": "img",
    "vax:visibleText": "text", "other:visible": "other",
}

# ---------------------------------------------------------------- thresholds (change encoding)
MATCH_MOVE_PX = 80          # F3: same role + same name, centre moved <= this -> one element that moved
MATCH_RENAME_IOU = 0.3      # F3: same role, different name, box IoU >= this -> one element that was renamed
FULL_IF_CHANGED_FRAC = 0.5  # F3: send full when (added + removed + changed) / (matched + added + removed) > this

_WS = re.compile(r"\s+")


# ---------------------------------------------------------------- small helpers
def box_area(b):
    return max(0, b[2]) * max(0, b[3])


def inter(a, b):
    ix = max(0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    return ix * iy


def iou(a, b):
    i = inter(a, b)
    u = box_area(a) + box_area(b) - i
    return i / u if u > 0 else 0.0


def inside_frac(a, b):
    """Share of box a that lies inside box b."""
    area = box_area(a)
    return inter(a, b) / area if area > 0 else 0.0


def center(box):
    x, y, w, h = box
    return [int(x + w / 2), int(y + h / 2)]


def norm(s):
    """Case-folded letters and digits only (comparison key for names)."""
    return "".join(c for c in str(s or "").casefold() if c.isalnum())


def name_sim(a, b):
    a, b = norm(a), norm(b)
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def one_line(name):
    """One-line name, whitespace collapsed (as `perceive.tree`, without escaping)."""
    return _WS.sub(" ", str(name or "")).strip()


def esc(name):
    """Quote-safe name for F1-F3 lines: backslash and double quote escaped."""
    return one_line(name).replace("\\", "\\\\").replace('"', '\\"')


_UNESC = re.compile(r"\\(.)")


def unesc(s):
    return _UNESC.sub(r"\1", s)


def short_role(role):
    """Short name of a known role; any other role is written in full so that the decoder can map it back."""
    return SHORT_ROLE.get(role, role)


# ---------------------------------------------------------------- F0 / F1
def f0(tree):
    """F0: `pixeltree.perceive.tree.to_text` on the elements of a tree dict."""
    from pixeltree.perceive.tree import Element, Tree, to_text

    elements = [Element(id=e["id"], role=e["role"], name=e.get("name") or "", box=[int(v) for v in e["box"]],
                        conf=e.get("conf")) for e in tree["elements"]]
    return to_text(Tree(source=tree.get("source", "ours"), image_size=tuple(tree["image_size"]), elements=elements))


def f1_line(e):
    cx, cy = center(e["box"])
    name = esc(e.get("name"))
    role = short_role(e["role"])
    return f'{role} "{name}" {cx},{cy}' if name else f"{role} {cx},{cy}"


def f1(tree, elements=None):
    """F1 text of `elements` (default: all elements of the tree, in their reading order)."""
    elements = tree["elements"] if elements is None else elements
    w, h = tree["image_size"]
    return "\n".join([f"screen {w}x{h}, {len(elements)} elements"] + [f1_line(e) for e in elements])


# ---------------------------------------------------------------- F3 changes
def key(e):
    """What an F2 line carries about an element: (role, name, cx, cy)."""
    cx, cy = center(e["box"])
    return (e["role"], one_line(e.get("name")), cx, cy)


def match(prev, cur):
    """Correspondence between two F2 element lists: {cur index: prev index}.
    Pass 1: same role, name and centre.  Pass 2: same role and name, centre moved <= MATCH_MOVE_PX (nearest first).
    Pass 3: same role, box IoU >= MATCH_RENAME_IOU (highest IoU first).  Each element is used at most once."""
    out, used = {}, set()
    by_key = {}
    for p, e in enumerate(prev):
        by_key.setdefault(key(e), []).append(p)
    for c, e in enumerate(cur):
        lst = by_key.get(key(e))
        if lst:
            p = lst.pop(0)
            out[c] = p
            used.add(p)

    def greedy(score_fn, accept):
        cands = []
        for c, e in enumerate(cur):
            if c in out:
                continue
            for p, q in enumerate(prev):
                if p in used or q["role"] != e["role"]:
                    continue
                s = score_fn(q, e)
                if accept(s):
                    cands.append((s, c, p))
        cands.sort(key=lambda t: (t[0], t[1], t[2]))
        for s, c, p in cands:
            if c not in out and p not in used:
                out[c] = p
                used.add(p)

    def dist(q, e):
        if one_line(q.get("name")) != one_line(e.get("name")):
            return float("inf")
        (ax, ay), (bx, by) = center(q["box"]), center(e["box"])
        return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5

    greedy(dist, lambda s: s <= MATCH_MOVE_PX)
    greedy(lambda q, e: -iou(q["box"], e["box"]), lambda s: -s >= MATCH_RENAME_IOU)
    return out


def _q(name):
    return f'"{esc(name)}"'


class Delta3:
    """F3 encoder for one episode: feed the F2 element list of every observation in order.
    `step(els)` returns (text, is_full, n_changes)."""

    def __init__(self, image_size):
        self.image_size = tuple(image_size)
        self.prev = None       # previous F2 elements
        self.prev_ids = None   # their ids
        self.next_id = 1

    def _new_id(self):
        k = self.next_id
        self.next_id += 1
        return k

    def _full(self, els, ids):
        w, h = self.image_size
        lines = [f"screen {w}x{h}, {len(els)} elements (full)"]
        lines += [f"{i} {f1_line(e)}" for i, e in zip(ids, els)]
        return "\n".join(lines)

    def step(self, els):
        if self.prev is None:
            ids = [self._new_id() for _ in els]
            self.prev, self.prev_ids = els, ids
            return self._full(els, ids), True, len(els)
        m = match(self.prev, els)
        ids, added, changed = [], [], []
        for c, e in enumerate(els):
            if c in m:
                i = self.prev_ids[m[c]]
                if key(e) != key(self.prev[m[c]]):
                    changed.append((i, e))
            else:
                i = self._new_id()
                added.append((i, e))
            ids.append(i)
        matched = set(m.values())
        removed = [self.prev_ids[p] for p in range(len(self.prev)) if p not in matched]
        n_ops = len(added) + len(removed) + len(changed)
        union = len(m) + len(added) + len(removed)
        self.prev, self.prev_ids = els, ids
        if union and n_ops / union > FULL_IF_CHANGED_FRAC:
            return self._full(els, ids), True, n_ops
        if n_ops == 0:
            return f"no change, {len(els)} elements", False, 0
        lines = [f"changes: +{len(added)} -{len(removed)} ~{len(changed)}, {len(els)} elements"]
        lines += [f"+ {i} {f1_line(e)}" for i, e in added]
        lines += [f"- {i}" for i in removed]
        lines += [f"~ {i} {_q(e.get('name'))} {center(e['box'])[0]},{center(e['box'])[1]}" for i, e in changed]
        return "\n".join(lines), False, n_ops


# ---------------------------------------------------------------- F3 decoder (for the lossless check)
_LONG_ROLE = {v: k for k, v in SHORT_ROLE.items()}
_LINE = re.compile(r'^(?P<role>\S+)(?: "(?P<name>(?:[^"\\]|\\.)*)")? (?P<cx>-?\d+),(?P<cy>-?\d+)$')
_CHG = re.compile(r'^~ (?P<id>\d+) "(?P<name>(?:[^"\\]|\\.)*)" (?P<cx>-?\d+),(?P<cy>-?\d+)$')


def _parse_el(s):
    m = _LINE.match(s)
    if not m:
        raise ValueError(f"bad element line: {s!r}")
    role = _LONG_ROLE.get(m["role"], m["role"])
    return (role, unesc(m["name"] or ""), int(m["cx"]), int(m["cy"]))


class Decoder3:
    """Rebuilds the current element state {id: (role, name, cx, cy)} from F3 texts (names unescaped)."""

    def __init__(self):
        self.state = {}

    def feed(self, text):
        lines = text.split("\n")
        head = lines[0]
        if head.endswith("(full)"):
            self.state = {}
            for s in lines[1:]:
                i, rest = s.split(" ", 1)
                self.state[int(i)] = _parse_el(rest)
        elif head.startswith("no change"):
            pass
        elif head.startswith("changes:"):
            for s in lines[1:]:
                if s.startswith("+ "):
                    i, rest = s[2:].split(" ", 1)
                    self.state[int(i)] = _parse_el(rest)
                elif s.startswith("- "):
                    del self.state[int(s[2:])]
                elif s.startswith("~ "):
                    m = _CHG.match(s)
                    if not m:
                        raise ValueError(f"bad change line: {s!r}")
                    role = self.state[int(m["id"])][0]
                    self.state[int(m["id"])] = (role, unesc(m["name"]), int(m["cx"]), int(m["cy"]))
                else:
                    raise ValueError(f"bad line: {s!r}")
        else:
            raise ValueError(f"bad header: {head!r}")
        n = int(re.search(r"(\d+) elements", head).group(1))
        if n != len(self.state):
            raise ValueError(f"header says {n} elements, state has {len(self.state)}")
        return sorted(self.state.values())


def f2_keys(els):
    """The multiset (as a sorted list) an F2 full text carries: (role, name, cx, cy) per element."""
    return sorted(key(e) for e in els)
