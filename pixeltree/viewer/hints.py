"""Suspicious-step hints and the one-sentence episode summary: pure functions that do not depend on
an image library (thumbnail differences are computed by the caller and passed in).

Four hints:
  unnamed   click-type step, element_at finds an element but its name is empty -> "Clicked an unnamed element"
  empty     click-type step, a tree exists but element_at is None              -> "Click landed outside every box"
  nochange  the 256x144 grayscale thumbnail after step N differs from the one after step N-1 by
            a mean absolute pixel difference < 1.0 (0-255)                      -> "Screen unchanged"
            (not judged for N=1, observe and done steps)
  error     action.ok == false                                                  -> "Action failed"
"""

from __future__ import annotations

from ..trace.treediff import element_at

NO_CHANGE_THRESHOLD = 1.0
MAX_SEGMENTS = 4
CLICK_TOOLS = ("click",)

PHRASES = {
    "unnamed": ("Clicked an unnamed element",
                "The click landed on an element with no name, so the agent could not confirm by name what it clicked."),
    "empty": ("Click landed outside every box",
              "A tree was available for this step, but the click position is not inside any element's box."),
    "nochange": ("Screen unchanged",
                 "The screen after this step is almost identical to the one after the previous step "
                 "(mean thumbnail difference below 1), so this step may have had no effect."),
    "error": ("Action failed", "The action in this step failed to execute."),
}
STOP_TEXT = {
    "done": "agent said it was done",
    "step_limit": "used all 20 steps",
    "timeout": "timed out",
    "no_done": "never said done",
    "fail_answer": "agent said it could not do it",
}
STOP_SENTENCE = {
    "fail_answer": "In the end the agent said it could not do the task.",
    "step_limit": "It used all 20 steps.",
    "timeout": "It was stopped by the timeout.",
}


def _hint(code: str, extra: str = "") -> dict:
    short, full = PHRASES[code]
    return {"code": code, "short": short, "full": full + extra}


def step_hints(steps: list[dict], seen_trees: list, diffs: list) -> list[list[dict]]:
    """steps: per step {"tool","ok","xy"}; seen_trees: the tree (element list or None) the agent had
    when it made this step; diffs: per step, the mean absolute difference between the thumbnail after
    this step and the one after the previous step (None = not computable / first step).
    Returns the hints of every step, [{"code","short","full"}, ...], in a fixed order:
    unnamed/empty, nochange, error."""
    out = []
    for j, s in enumerate(steps):
        hs = []
        tool, xy = s.get("tool"), s.get("xy")
        tree = seen_trees[j] if j < len(seen_trees) else None
        if tool in CLICK_TOOLS and xy is not None and tree is not None:
            e = element_at(tree, xy[0], xy[1])
            if e is None:
                hs.append(_hint("empty"))
            elif not (e.get("name") or "").strip():
                role = (e.get("role") or "").split(":")[-1]
                hs.append(_hint("unnamed", " (element %s, role %s)" % (e.get("id"), role)))
        d = diffs[j] if j < len(diffs) else None
        if j >= 1 and tool not in ("observe", "done") and d is not None and d < NO_CHANGE_THRESHOLD:
            hs.append(_hint("nochange"))
        if s.get("ok") is False:
            hs.append(_hint("error"))
        out.append(hs)
    return out


def merge_ranges(hints: list[list[dict]]) -> list[tuple[int, int, str]]:
    """Merge consecutive steps with the same phrase into ranges: [(first step, last step, phrase)],
    step numbers starting at 1, sorted by first step."""
    runs = []
    open_runs: dict[str, list] = {}
    for j, hs in enumerate(hints):
        now = {h["short"] for h in hs}
        for ph in list(open_runs):
            if ph not in now:
                runs.append(tuple(open_runs.pop(ph)))
        for ph in sorted(now):
            if ph in open_runs:
                open_runs[ph][1] = j + 1
            else:
                open_runs[ph] = [j + 1, j + 1, ph]
    runs.extend(tuple(v) for v in open_runs.values())
    return sorted(runs, key=lambda r: (r[0], r[2]))


def summarize(result: dict | None, n_steps: int, hints: list[list[dict]]) -> str:
    """The one-sentence summary at the top of an episode page; a part that cannot be built is omitted."""
    parts = []
    head = "%d step%s" % (n_steps, "" if n_steps == 1 else "s")
    if result and result.get("ok") is not None:
        head += ", " + ("succeeded" if result["ok"] else "failed")
        sr = result.get("stop_reason")
        if sr:
            head += " (%s)" % STOP_TEXT.get(sr, sr)
    parts.append(head + ". ")
    runs = merge_ranges(hints)
    if runs:
        segs = []
        for a, b, ph in runs[:MAX_SEGMENTS]:
            segs.append("step %d: %s" % (a, ph) if a == b else "steps %d–%d: %s" % (a, b, ph))
        parts.append("Suspicious steps: " + "; ".join(segs) + ". ")
    sr = (result or {}).get("stop_reason")
    if sr in STOP_SENTENCE:
        parts.append(STOP_SENTENCE[sr])
    return "".join(parts).strip()
