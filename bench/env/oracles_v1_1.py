"""Oracle version v1.1: corrections layered on the frozen v1 oracles (the 48 tasks and their oracles as first frozen).

v1 stays untouched in bench/apps/*.py; this module overrides only the oracles listed in OVERRIDES and falls back to
v1 for every other task.  Episodes are re-graded from their archived end state with bench.agent.regrade --oracles v1_1.

v1.1 changes (2026-11-11, found by a review of the failed episodes):
  * okular_popup_note, okular_note_bookmark_facing: v1 `_pdf_notes` read the PDF with a regex that matched only
    generation-0 objects (`N 0 obj`) and also read every revision of an incrementally saved PDF.  Okular writes a
    re-added annotation as `10 1 obj` (generation 1), so v1 missed notes that are in the saved PDF, and it could count
    an annotation the agent had deleted (still present in an older revision).  v1.1 reads the PDF with pypdf (xref /
    incremental updates resolved): the /Text annotations listed in each page's /Annots of the final revision.
    Everything else in these two oracles (exact text, page, bookmark, view mode) is unchanged.
"""
from pathlib import Path

from bench.apps import okular
from bench.env import registry

VERSION = "v1_1"


def _pdf_notes(home):
    """[(page index, text)] of /Subtype /Text annotations on the pages of the final PDF revision (None if unreadable)."""
    from pypdf import PdfReader

    path = Path(home) / okular.PDF
    try:
        reader = PdfReader(str(path))
        notes = []
        for idx, page in enumerate(reader.pages):
            annots = page.get("/Annots")
            annots = annots.get_object() if annots is not None else []
            for ref in annots or []:
                annot = ref.get_object()
                if annot.get("/Subtype") == "/Text":
                    text = annot.get("/Contents")
                    notes.append((idx, None if text is None else str(text)))
        return notes
    except Exception:  # noqa: BLE001  (missing / unreadable PDF = no notes readable, same as v1's None)
        return None


def oracle_note_page2(home):
    notes = _pdf_notes(home)
    ok = notes is not None and (1, "Check Q3 figures") in notes
    return ok, f"[v1.1] PDF text annotations (page index, text)={notes!r}"


def oracle_note_bookmark_facing(home):
    notes, pages, (mode, _, _) = _pdf_notes(home), okular._bookmark_pages(home), okular._view(home)
    ok = notes is not None and (2, "Verify totals") in notes and pages is not None and 2 in pages and mode == "1"
    return ok, (f"[v1.1] annotations={notes!r} bookmarked={sorted(pages) if pages is not None else None!r} "
                f"viewMode={mode!r}")


OVERRIDES = {"okular_popup_note": oracle_note_page2, "okular_note_bookmark_facing": oracle_note_bookmark_facing}


def oracle(task_id, home):
    """v1.1 oracle of `task_id` on a sandbox HOME (v1 for tasks without an override); same contract as registry.oracle."""
    fn = OVERRIDES.get(task_id)
    if fn is None:
        return registry.oracle(task_id, home)
    try:
        ok, detail = fn(Path(home))
        return bool(ok), str(detail)
    except Exception as exc:  # noqa: BLE001
        return False, f"oracle error: {type(exc).__name__}: {exc}"
