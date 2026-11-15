"""Name cleaning and de-duplication of a tree ("F2"). EXPERIMENTAL, OFF BY DEFAULT.

Experimental, off by default; known defect: it blanks the name of the title-bar close button '×' (pure-symbol rule),
and agents then click it as a menu and close the app — see PAPER.md.

Nothing in the default path (the `pixeltree-tree` command, `pixeltree.perceive.tree.to_text`) calls this module.
`clean(tree)` returns copies of the tree's elements after

1. per-element name fixes (`fix_name`): an icon-sized non-text box loses its name; odd-script characters are removed;
   a non-text name with no letter or digit left loses its name,
2. de-duplication (`_dup_pair`): two elements with the same name whose boxes overlap or nest, or two empty-named
   elements with a high IoU, keep one,
3. container names: an element that contains several named text elements loses its own OCR name.

"An empty name beats a wrong one" was the design idea; the symbol rule shows where it fails: a lone symbol such as
'×' *is* the correct name of a close button.
"""
import unicodedata

from .core import _WS, box_area, f1, iou, inside_frac, name_sim

# ---------------------------------------------------------------- roles and thresholds
TEXT_ROLES = ("vax:visibleText", "aria:textbox", "aria:heading", "aria:link")  # OCR reads their content
# de-duplication keeps the element with the higher rank (interactive > image > heading > plain text)
ROLE_RANK = {"vax:visibleText": 0, "other:visible": 0, "aria:heading": 1, "aria:img": 2}
DEFAULT_RANK = 3

# frozen thresholds
ICON_MAX_SIDE = 32          # non-text element with max(w, h) < this many px: OCR name dropped (icon glyph)
ODD_MODE = "strip"          # "strip": odd-script characters removed from the name; "blank": any of them -> no name
SYMBOL_ONLY_BLANK = True    # non-text element whose name has no letter or digit left: name dropped
CONTAINER_MIN_TEXTS = 2     # element containing >= this many named text elements: its own OCR name dropped
CONTAIN_FRAC = 0.8          # "A inside B": area(A & B) / area(A) >= this
DUP_NAME_SIM = 0.6          # names "the same" for de-duplication: difflib ratio of normalised names >= this
DUP_IOU = 0.7               # same-name (or both empty) boxes with IoU >= this are one element


def _odd_char(c):
    """Characters outside Latin / Greek / Cyrillic letters, digits, common punctuation: CJK, enclosed alphanumerics,
    box drawing, geometric shapes ... (what OCR reads on icon glyphs in an English UI)."""
    if c.isspace() or c.isascii():
        return False
    cat = unicodedata.category(c)
    if cat.startswith("L"):
        name = unicodedata.name(c, "")
        return not any(s in name for s in ("LATIN", "GREEK", "CYRILLIC"))
    if cat.startswith("N"):
        return not cat == "Nd" or not unicodedata.name(c, "").startswith("DIGIT")
    if cat in ("Pd", "Pi", "Pf", "Ps", "Pe", "Po", "Sc", "Sm"):
        return c not in "…–—‘’“”«»•·×÷±€£¥©®°→←↑↓≤≥"
    return True


def strip_odd(name):
    """Name without odd-script characters, whitespace collapsed."""
    return _WS.sub(" ", "".join(" " if _odd_char(c) else c for c in str(name or ""))).strip()


def fix_name(e):
    """(new name, reason) for one element on its own: reason in {"", "odd", "icon", "symbol"}."""
    name = str(e.get("name") or "")
    if not name:
        return "", ""
    text_role = e["role"] in TEXT_ROLES
    if not text_role and max(e["box"][2], e["box"][3]) < ICON_MAX_SIDE:
        return "", "icon"
    new = strip_odd(name)
    reason = "odd" if new != _WS.sub(" ", name).strip() else ""
    if reason and ODD_MODE == "blank":
        return "", "odd"
    if SYMBOL_ONLY_BLANK and not text_role and new and not any(c.isalnum() for c in new):
        return "", "symbol"
    if not new:
        return "", "odd"
    return new, reason


def _rank(e):
    return ROLE_RANK.get(e["role"], DEFAULT_RANK)


def _dup_pair(a, b):
    """Index (0 = a, 1 = b) of the element to drop when a and b are one element, else None."""
    na, nb = a["name"], b["name"]
    if not na and not nb:
        same = iou(a["box"], b["box"]) >= DUP_IOU
        nested = False
    else:
        if not na or not nb or name_sim(na, nb) < DUP_NAME_SIM:
            return None
        nested = max(inside_frac(a["box"], b["box"]), inside_frac(b["box"], a["box"])) >= CONTAIN_FRAC
        same = nested or iou(a["box"], b["box"]) >= DUP_IOU
    if not same:
        return None
    ka = (_rank(a), box_area(a["box"]), a.get("conf") or 0.0)
    kb = (_rank(b), box_area(b["box"]), b.get("conf") or 0.0)
    return 1 if ka >= kb else 0


def clean(tree, log=None):
    """F2 elements: copies of the tree's elements (reading order kept) after
    1. per-element name fixes (fix_name: icon-sized non-text box -> no name; odd-script characters removed;
       non-text name with no letter / digit left -> no name),
    2. de-duplication: two elements with the same name (DUP_NAME_SIM) whose boxes overlap (IoU >= DUP_IOU) or nest
       (CONTAIN_FRAC), or two empty-named elements with IoU >= DUP_IOU, keep one (higher role rank, then the larger
       box, then the higher confidence),
    3. container names: an element that contains >= CONTAINER_MIN_TEXTS named text elements loses its own OCR name
       (the texts inside carry it; a box spanning several columns reads them as one garbled string).
    `log` (a list) receives (kind, element before, detail) tuples: kind in odd / icon / symbol / dup / container."""
    els = [dict(e) for e in tree["elements"]]
    for e in els:
        new, reason = fix_name(e)
        if reason and log is not None:
            log.append((reason, dict(e), new))
        e["name"] = new
    drop = set()
    for i in range(len(els)):
        if i in drop:
            continue
        for j in range(i + 1, len(els)):
            if j in drop:
                continue
            k = _dup_pair(els[i], els[j])
            if k is None:
                continue
            gone, kept = (i, j) if k == 0 else (j, i)
            drop.add(gone)
            if log is not None:
                log.append(("dup", dict(els[gone]), els[kept]["id"]))
            if gone == i:
                break
    kept = [e for k, e in enumerate(els) if k not in drop]
    texts = [e for e in kept if e["role"] == "vax:visibleText" and e["name"]]
    for e in kept:
        if not e["name"] or e["role"] == "vax:visibleText":
            continue
        n = sum(1 for t in texts if t is not e and inside_frac(t["box"], e["box"]) >= CONTAIN_FRAC
                and box_area(t["box"]) < box_area(e["box"]))
        if n >= CONTAINER_MIN_TEXTS:
            if log is not None:
                log.append(("container", dict(e), n))
            e["name"] = ""
    return kept


def f2(tree):
    return f1(tree, clean(tree))
