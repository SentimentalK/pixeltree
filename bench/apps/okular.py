"""Okular (Qt6) with ~/Documents/sample.pdf (3 pages, from bench.env.sandbox.prepare_sandbox)."""
from pathlib import Path

from bench.env import oracle_kit as kit

PDF = "Documents/sample.pdf"
def close_prompt(ep):
    """Okular asks "save your changes or discard them?" when annotations were added; answer Save so that the
    annotations the agent made end up in the PDF (the oracle reads them there)."""
    if any(w["title"].startswith("Close Document") for w in ep.windows()):
        ep.click_node(role="button", name="Save", timeout=3)


APP = {
    "name": "okular",
    "argv": lambda home: ["okular", str(home / PDF)],
    "env": {"QT_ACCESSIBILITY": "1", "QT_LINUX_ACCESSIBILITY_ALWAYS_ON": "1"},
    "startup_s": 8,
    "window_title": "sample.pdf",
    "process": "okular",
    "prepare": None,
    "close": "wm_close",
    "state_files": [".local/share/okular/docdata/*.xml", ".config/okularpartrc", ".config/okularrc", ".local/state/okularstaterc"],
    "close_prompt": close_prompt,
    "tier": "good",
    "atspi_recall_05": 0.699,
}


# ---------------------------------------------------------------------------------------------- oracle helpers
def _attr(home, rel_glob, xpath, attr):
    found = kit.xml_find(home, rel_glob, xpath)
    return None if not found else found[-1].get(attr)


def _current_page(home):
    vp = _attr(home, ".local/share/okular/docdata/*.xml", ".//history/current", "viewport")
    return None if vp is None else int(vp.split(";")[0])


def _bookmark_pages(home):
    marks = kit.xml_find(home, ".local/share/okular/bookmarks.xml", ".//bookmark")
    if marks is None:
        return None
    pages = set()
    for m in marks:
        href = m.get("href", "")
        if href.endswith(PDF.split("/")[-1] + "#") or "#" not in href:
            continue
        try:
            pages.add(int(href.split("#", 1)[1].split(";")[0]))
        except ValueError:
            continue
    return pages


def _pdf_notes(home):
    """[(page index, text)] of the /Subtype /Text annotations in the PDF (None when the PDF is unreadable)."""
    import re
    raw = kit.file_text(home, PDF)
    if raw is None:
        return None
    kids = re.findall(r"/Kids\s*\[([^\]]*)\]", raw)
    pages = [int(n) for n in re.findall(r"(\d+)\s+0\s+R", kids[-1])] if kids else []
    notes = []
    for obj in re.finditer(r"(\d+) 0 obj\s*(<<.*?>>)\s*endobj", raw, re.S):
        body = obj.group(2)
        if "/Subtype /Text" not in body and "/Subtype/Text" not in body:
            continue
        hexm = re.search(r"/Contents\s*<([0-9a-fA-F]+)>", body)
        litm = re.search(r"/Contents\s*\(((?:[^()\\]|\\.)*)\)", body)
        text = None
        if hexm:
            data = bytes.fromhex(hexm.group(1))
            text = data.decode("utf-16-be" if data[:2] == b"\xfe\xff" else "latin-1").lstrip("\ufeff")
        elif litm:
            text = litm.group(1)
        page = re.search(r"/P\s+(\d+)\s+0\s+R", body)
        idx = pages.index(int(page.group(1))) if page and int(page.group(1)) in pages else None
        notes.append((idx, text))
    return notes


# ---------------------------------------------------------------------------------------------- oracles
def oracle_goto3(home):
    page = _current_page(home)
    return page == 2, f"docdata current page index={page!r} (page 3 is index 2)"


def oracle_bookmark_current(home):
    pages = _bookmark_pages(home)
    return pages is not None and 0 in pages, f"bookmarked page indexes={sorted(pages) if pages is not None else None!r} (page 1 is index 0)"


def oracle_bookmark_pages(home):
    pages = _bookmark_pages(home)
    return pages is not None and {1, 2} <= pages, f"bookmarked page indexes={sorted(pages) if pages is not None else None!r} (need 1 and 2)"


def _view(home):
    return (_attr(home, ".local/share/okular/docdata/*.xml", ".//view[@name='PageView']/viewMode", "mode"),
            _attr(home, ".local/share/okular/docdata/*.xml", ".//view[@name='PageView']/zoom", "mode"),
            _attr(home, ".local/share/okular/docdata/*.xml", ".//view[@name='PageView']/zoom", "value"))


def oracle_facing_zoom(home):
    mode, zmode, zval = _view(home)
    ok = mode == "1" and zmode == "0" and zval is not None and abs(float(zval) - 2.0) < 0.02
    return ok, f"viewMode={mode!r} (1 = Facing Pages) zoom mode={zmode!r} value={zval!r} (need mode 0, value 2)"


def oracle_note_page2(home):
    notes = _pdf_notes(home)
    ok = notes is not None and (1, "Check Q3 figures") in notes
    return ok, f"PDF text annotations (page index, text)={notes!r}"


def oracle_note_bookmark_facing(home):
    notes, pages, (mode, _, _) = _pdf_notes(home), _bookmark_pages(home), _view(home)
    ok = notes is not None and (2, "Verify totals") in notes and pages is not None and 2 in pages and mode == "1"
    return ok, f"annotations={notes!r} bookmarked={sorted(pages) if pages is not None else None!r} viewMode={mode!r}"


# ---------------------------------------------------------------------------------------------- positive scripts
THUMB = {1: (93, 271), 2: (93, 495), 3: (93, 722)}


def _page(ep, n):
    ep.click(*THUMB[n])
    ep.sleep(1.0)


def _add_bookmark(ep):
    ep.click(193, 11)                       # "Bookmarks" menu
    ep.sleep(0.6)
    ep.click_node(role="menu item", name="Add Bookmark")
    ep.sleep(0.8)


def _facing(ep):
    ep.click(238, 42)                       # "View Mode" toolbar button
    ep.sleep(0.8)
    ep.click(255, 96)                       # "Facing Pages" in the popup (no AT-SPI names for the popup items)
    ep.sleep(1.0)


def _popup_note(ep, page, text):
    _page(ep, page)
    ep.click(1903, 42)                      # drop-down arrow of the annotation tool button
    ep.sleep(0.8)
    ep.click_node(role="menu item", name="Pop-up Note")
    ep.sleep(0.6)
    ep.click(1500, 300)                     # place the note on the page; the note window opens focused
    ep.sleep(1.2)
    ep.type(text)
    ep.sleep(0.6)


def pos_goto3(ep):
    _page(ep, 3)


def pos_bookmark_current(ep):
    _add_bookmark(ep)


def pos_bookmark_pages(ep):
    _page(ep, 2)
    _add_bookmark(ep)
    _page(ep, 3)
    _add_bookmark(ep)


def pos_facing_zoom(ep):
    _facing(ep)
    ep.click(175, 41)                       # zoom combo box
    ep.sleep(0.8)
    ep.click_node(role="list item", name="200%")
    ep.sleep(1.0)


def pos_note_page2(ep):
    _popup_note(ep, 2, "Check Q3 figures")


def pos_note_bookmark_facing(ep):
    _popup_note(ep, 3, "Verify totals")
    _add_bookmark(ep)
    _facing(ep)


TASKS = [
    {"id": "okular_goto_page3", "difficulty": 1,
     "sentence": "In Okular, go to page 3 of the open PDF.",
     "setup": None, "oracle": oracle_goto3, "positive": pos_goto3},
    {"id": "okular_bookmark_current", "difficulty": 1,
     "sentence": "In Okular, add a bookmark to the page that is currently shown.",
     "setup": None, "oracle": oracle_bookmark_current, "positive": pos_bookmark_current},
    {"id": "okular_bookmark_pages", "difficulty": 2,
     "sentence": "Add a bookmark to page 2 and another bookmark to page 3 of the document.",
     "setup": None, "oracle": oracle_bookmark_pages, "positive": pos_bookmark_pages},
    {"id": "okular_facing_zoom", "difficulty": 2,
     "sentence": "Switch Okular's view mode to Facing Pages and set the zoom level to 200%.",
     "setup": None, "oracle": oracle_facing_zoom, "positive": pos_facing_zoom},
    {"id": "okular_popup_note", "difficulty": 2,
     "sentence": "On page 2, add a Pop-up Note whose text is: Check Q3 figures",
     "setup": None, "oracle": oracle_note_page2, "positive": pos_note_page2},
    {"id": "okular_note_bookmark_facing", "difficulty": 3,
     "sentence": "On page 3, add a Pop-up Note with the text Verify totals and bookmark that page; then switch the view mode "
                 "to Facing Pages.",
     "setup": None, "oracle": oracle_note_bookmark_facing, "positive": pos_note_bookmark_facing},
]
