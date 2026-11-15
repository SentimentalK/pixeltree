"""Element tree: data classes, reading order, text and JSON.

Pure Python, no third-party imports, so it loads (and is unit-tested) without cv2, torch or a display.

Reading order: rows by centre y, a new row starts when the centre y differs by more than 0.5 x the median element
height from the first element of the current row; inside a row, left to right. The ids `e1, e2, ...` follow that
order.

Text format (one line per element):

    screen 1920x1080, <n> elements
    <role> [e<k>] "<name>" @(x,y,w,h) c=(cx,cy)

`name` is empty -> `""`; coordinates are integer screen pixels; `c` is the box centre `int(x + w/2)`, `int(y + h/2)`.
At most MAX_LINES element lines are written; the rest is replaced by a last line `... <n> more elements`.
"""
import re
import statistics
from dataclasses import dataclass, field

MAX_LINES = 400
_WS = re.compile(r"\s+")


@dataclass
class Element:
    """One visible element: `box` is [x, y, w, h] in screen pixels, `conf` the detector confidence (None if unknown)."""
    id: str
    role: str
    name: str
    box: list
    conf: float = None

    @property
    def center(self):
        x, y, w, h = self.box
        return [int(x + w / 2), int(y + h / 2)]


@dataclass
class Tree:
    """Elements of one observation. `image_size` = (width, height) of the screen; `timings` = seconds per stage."""
    source: str
    image_size: tuple
    elements: list = field(default_factory=list)
    timings: dict = field(default_factory=dict)


def order(elements):
    """Elements in reading order (rows by centre y, left to right inside a row); returns a new list."""
    elements = list(elements)
    if not elements:
        return []
    tol = 0.5 * statistics.median(float(e.box[3]) for e in elements)
    items = sorted(enumerate(elements), key=lambda p: (p[1].center[1], p[1].center[0], p[0]))
    rows = []
    for item in items:
        cy = item[1].center[1]
        if rows and abs(cy - rows[-1][0][1].center[1]) <= tol:
            rows[-1].append(item)
        else:
            rows.append([item])
    out = []
    for row in rows:
        out.extend(e for _, e in sorted(row, key=lambda p: (p[1].center[0], p[0])))
    return out


def make_tree(source, image_size, elements, timings=None):
    """Tree with `elements` put in reading order and numbered e1..eN (the input elements' ids are overwritten)."""
    ordered = order(elements)
    for k, element in enumerate(ordered, 1):
        element.id = f"e{k}"
    return Tree(source=source, image_size=(int(image_size[0]), int(image_size[1])),
                elements=ordered, timings=dict(timings or {}))


def _clean(name):
    """One-line, quote-safe name for the text format."""
    return _WS.sub(" ", str(name or "")).strip().replace('"', '\\"')


def to_text(tree, max_lines=MAX_LINES):
    """The agent-facing text of a tree (format in the module docstring)."""
    n = len(tree.elements)
    lines = [f"screen {tree.image_size[0]}x{tree.image_size[1]}, {n} elements"]
    for e in tree.elements[:max_lines]:
        x, y, w, h = (int(v) for v in e.box)
        cx, cy = e.center
        lines.append(f'{e.role} [{e.id}] "{_clean(e.name)}" @({x},{y},{w},{h}) c=({cx},{cy})')
    if n > max_lines:
        lines.append(f"... {n - max_lines} more elements")
    return "\n".join(lines)


def to_json(tree):
    """JSON-serialisable dict: {"source", "image_size": [w, h], "elements": [...], "timings": {...}}."""
    return {
        "source": tree.source,
        "image_size": [int(tree.image_size[0]), int(tree.image_size[1])],
        "elements": [{"id": e.id, "role": e.role, "name": e.name or "", "box": [int(v) for v in e.box],
                      "center": e.center, "conf": None if e.conf is None else round(float(e.conf), 4)}
                     for e in tree.elements],
        "timings": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in tree.timings.items()},
    }
