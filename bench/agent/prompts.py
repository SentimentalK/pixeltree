"""System prompts of the observation conditions: COMMON + SEE[cond] + RULES, identical except for SEE.

H_ours / H_atspi (added after the first run of the five other conditions) = the S_shot text plus one sentence on the element list.
"""

CONDS = ("T_ours", "T_atspi", "T_omni", "S_shot", "S_shot_strong", "H_ours", "H_atspi")

COMMON = (
    "You operate one application on a Linux desktop (1920x1080) only through the tools of the p125 MCP server. "
    "You have at most 20 tool calls in total, observe included. Every action tool returns what you see after the "
    "action, so you only need observe at the start."
)

_SEE_DETECTED = (
    "You cannot see the screen. You get a list of visible elements that a vision model detected from pixels: each "
    "line is a role, an id in brackets, the text read on the element in quotes (empty when no text was read), its "
    "box @(x,y,w,h) and its centre c=(x,y) in screen pixels. Elements can be missing or have the wrong role. Click "
    "elements by their centre coordinates."
)
_SEE_SHOT = (
    "You see a screenshot of the screen scaled to 1280x720. Give click and scroll positions as pixel coordinates "
    "in that screenshot."
)
SEE = {
    "T_ours": _SEE_DETECTED,
    "T_omni": _SEE_DETECTED,
    "T_atspi": (
        "You cannot see the screen. You get a list of visible elements from the system accessibility tree: each "
        "line is a role, an id in brackets, the accessible name in quotes (empty when the application gives none), "
        "its box @(x,y,w,h) and its centre c=(x,y) in screen pixels. Elements can be missing or have wrong "
        "positions. Click elements by their centre coordinates."
    ),
    "S_shot": _SEE_SHOT,
    "S_shot_strong": _SEE_SHOT,
    "H_ours": _SEE_SHOT + (
        " Below the screenshot note you also get a list of visible elements that a vision model detected from the "
        "pixels (role, id, the text read on the element in quotes, box @(x,y,w,h) and centre c=(x,y) in the same "
        "screenshot coordinates); elements can be missing or have the wrong role."),
    "H_atspi": _SEE_SHOT + (
        " Below the screenshot note you also get a list of visible elements from the system accessibility tree "
        "(role, id, the accessible name in quotes, box @(x,y,w,h) and centre c=(x,y) in the same screenshot "
        "coordinates); elements can be missing or have wrong positions."),
}

RULES = (
    'Use click(x, y) (button="right" for context menus, double=true to open items), type(text) to type into the '
    "focused field, key(name) only for Return, Escape, Tab, shift+Tab, arrow keys, BackSpace, Delete, Home, End, "
    "Page_Up, Page_Down and space (no other shortcuts), and scroll(x, y, dy) to scroll. When the task is complete, "
    "call done with a short answer. If you cannot complete it, call done with an answer starting with FAIL:."
)

MODELS = {"S_shot_strong": "claude-sonnet-5-5"}
DEFAULT_MODEL = "claude-haiku-5-5"


def system_prompt(cond):
    """COMMON, the condition's SEE text and RULES joined by single spaces."""
    if cond not in SEE:
        raise ValueError(f"unknown condition {cond!r}; choose from {CONDS}")
    return " ".join([COMMON, SEE[cond], RULES])


def user_message(sentence):
    return f"Task: {sentence}"


def model_for(cond):
    return MODELS.get(cond, DEFAULT_MODEL)
