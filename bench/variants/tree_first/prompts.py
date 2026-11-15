"""System prompts of the five R3 conditions (verbatim constants; the wording is part of the design).

COMMON / RULES / SEE["S_shot"] come from bench.agent.prompts unchanged; everything else is defined here.
"""
from bench.agent import prompts as P
from bench.agent.observation import SHOT_NOTE  # noqa: F401  (confirms it exists; conds.py uses it)

ROLES = "btn, link, menuitem, tab, check, radio, input, combo, cell, item, heading, img, text, other"
SEE_X1 = ("You cannot see the screen. You get a list of visible elements that a vision model detected from pixels: "
          "a first line with the screen size and the number of elements, then one line per element with a short role "
          f"({ROLES}), the text read on the element in quotes (left out when no text was read) and its centre x,y in "
          "screen pixels. Elements can be missing or have the wrong role. Click elements by their centre coordinates.")
COMMON_X2 = ("You operate one application on a Linux desktop (1920x1080) only through the tools of the p125 MCP server. "
             "You have at most 20 tool calls in total, observe, hover and look included. Every action tool returns what "
             "you see after the action, so you only need observe at the start.")
SEE_X2 = ("You do not see the screen by default. You get a list of visible elements that a vision model detected from "
          "pixels, in the coordinates of the screen scaled to 1280x720. observe returns the full list: a first line "
          "with the size and the number of elements, then one line per element with an id, a short role "
          f"({ROLES}), the text read on the element in quotes (left out when no text was read) and its centre x,y. "
          "After click, type, key, scroll and hover you get only the changes against the last list you got: "
          '"+ id role \\"text\\" x,y" for a new element, "- id" for one that disappeared, "~ id \\"text\\" x,y" for one '
          'whose text or position changed, or "no change"; when most of the screen changed you get the full list '
          "again. An element keeps its id while it stays on screen. Elements can be missing or have the wrong role. "
          "Read the element list by default. When the list is not enough, an element you need has no text, or you "
          "are unsure, you can call hover(x, y) to move the mouse there without clicking and get the changes (for "
          "example a tooltip), or look() to get a screenshot scaled to 1280x720 in the same coordinates. look costs "
          "more than the list, so use it only when you need it. Give click, scroll and hover positions in these "
          "1280x720 coordinates.")
COMMON_LEAN = ("You operate one application on a Linux desktop (1920x1080) only through the tools of the p125 MCP "
               "server. You have at most 20 tool calls in total{extra}. The current view is given with the task, and "
               "every action tool returns what you see after the action.")
SEE_X2_LEAN = SEE_X2.replace("observe returns the full list:", "The full list is given with the task:")
assert SEE_X2_LEAN != SEE_X2
SYSTEM = {
    "X1": " ".join([P.COMMON, SEE_X1, P.RULES]),
    "X1_sonnet": " ".join([P.COMMON, SEE_X1, P.RULES]),
    "X2": " ".join([COMMON_X2, SEE_X2, P.RULES]),
    "S_shot_lean": " ".join([COMMON_LEAN.format(extra=""), P.SEE["S_shot"], P.RULES]),
    "X2_lean": " ".join([COMMON_LEAN.format(extra=", hover and look included"), SEE_X2_LEAN, P.RULES]),
}
HOVER_DOC = "Move the mouse to (x, y) without clicking, wait, and return what changed (for example a tooltip)."
LOOK_DOC = "Return a screenshot of the screen scaled to 1280x720, in the same coordinates as the element list."
