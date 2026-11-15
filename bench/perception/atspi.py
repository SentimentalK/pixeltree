"""AT-SPI source: the system accessibility tree of one application -> Tree (the "T_atspi" baseline).

Input `nodes` is a flat depth-first list in one of two shapes (both are accepted, also as a JSON string or a path):
  * `XvfbDesktop.atspi_nodes(process)`: {role, name, states, box: [x, y, w, h], depth}
  * a standalone AT-SPI dump file: {role, name, states, scr: [x, y, w, h], depth, app, ...}

Rules:
  * Only the applications whose root node name contains `process` (case-insensitive) are kept; without an
    `application` root node nothing is filtered by name.
  * Only the foreground window subtree: AT-SPI has no z-order, so the foreground window is the LAST showing
    top-level node (depth 1 under the application root) with w*h > 0. AT-SPI lists a toolkit's windows in creation
    order, so a dialog or popup opened after the main window comes last.
  * Inside it only nodes whose states contain `showing` and whose box has w*h > 0 (and is not the "no geometry"
    sentinel INT_MIN of GTK3). Role = AT-SPI role name, name = AT-SPI name (empty stays empty).
  * Coordinates are the node's screen coordinates as reported, nothing is corrected. GTK4 applications report 0,0
    for every node; such boxes are written unchanged.
"""
import json
from pathlib import Path

from pixeltree.perceive.tree import Element, make_tree

EXTENT_LIMIT = 1 << 24  # AT-SPI reports "no geometry" as INT_MIN


def load_nodes(nodes):
    """A node list from a list, a JSON string or a path to a JSON file."""
    if isinstance(nodes, (str, Path)):
        text = str(nodes)
        if text.lstrip().startswith("["):
            return json.loads(text)
        return json.loads(Path(text).read_text(encoding="utf-8"))
    return list(nodes or [])


def _box(node):
    box = node.get("box") if node.get("box") is not None else node.get("scr")
    if not box or len(box) != 4:
        return None
    try:
        return [int(v) for v in box]
    except (TypeError, ValueError):
        return None


def _usable(node):
    """showing, positive area, real geometry -> box; otherwise None."""
    if "showing" not in (node.get("states") or []):
        return None
    box = _box(node)
    if box is None or box[2] <= 0 or box[3] <= 0:   # w*h > 0 with both positive (AT-SPI also reports -1,-1,-1,-1)
        return None
    if max(abs(v) for v in box) >= EXTENT_LIMIT:
        return None
    return box


def _subtree_end(nodes, start):
    """Index after the last descendant of nodes[start] (depth-first order)."""
    depth = nodes[start].get("depth", 0)
    end = start + 1
    while end < len(nodes) and nodes[end].get("depth", 0) > depth:
        end += 1
    return end


def foreground_window(nodes, process=None):
    """(start, end) index range of the foreground window subtree inside `nodes`, or None."""
    needle = (process or "").lower()
    roots = [i for i, n in enumerate(nodes) if n.get("role") == "application"]
    scopes = []
    if roots:
        for i in roots:
            if needle in str(nodes[i].get("name", "")).lower():
                scopes.append((i + 1, _subtree_end(nodes, i), nodes[i].get("depth", 0) + 1))
    else:
        top = min((n.get("depth", 0) for n in nodes), default=0)
        scopes.append((0, len(nodes), top))
    best = None
    for lo, hi, top_depth in scopes:
        i = lo
        while i < hi:
            node = nodes[i]
            end = _subtree_end(nodes, i)
            if node.get("depth", 0) == top_depth and _usable(node) is not None:
                best = (i, end)
            i = end if node.get("depth", 0) == top_depth else i + 1
    return best


def build(nodes, process=None, image_size=(1920, 1080)):
    """Tree of the foreground window of the application `process` (substring of its AT-SPI application name)."""
    nodes = load_nodes(nodes)
    window = foreground_window(nodes, process)
    elements = []
    if window is not None:
        for node in nodes[window[0]:window[1]]:
            box = _usable(node)
            if box is None:
                continue
            elements.append(Element(id="", role=str(node.get("role", "")), name=str(node.get("name", "") or ""),
                                    box=box))
    return make_tree("atspi", image_size, elements, {"n_dump_nodes": len(nodes)})
