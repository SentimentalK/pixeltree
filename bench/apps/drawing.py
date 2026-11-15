"""Drawing (GTK3) with ~/Pictures/sample_0.png (800x600 synthetic picture)."""
from pathlib import Path

from bench.env import oracle_kit as kit

def after_start(ep):
    """Drawing asks on every start (memory gsettings) whether to open the help manual: answer No."""
    try:
        ep.click_node(role="button", name="No", timeout=8)
        ep.sleep(1.0)
    except TimeoutError:
        pass


APP = {
    "name": "drawing",
    "argv": lambda home: ["drawing", str(home / "Pictures" / "sample_0.png")],
    "env": {"GSETTINGS_BACKEND": "keyfile"},   # settings persist in ~/.config/glib-2.0/settings/keyfile (readable by the oracle)
    "startup_s": 6,
    "window_title": "Drawing",
    "process": "drawing",
    "prepare": None,
    "close": "wm_close",
    "state_files": ["Pictures/*", ".config/glib-2.0/settings/keyfile"],
    "after_start": after_start,
    "tier": "good",
    "atspi_recall_05": 0.593,
}

SAMPLE = "Pictures/sample_0.png"
SETTINGS = ".config/glib-2.0/settings/keyfile"
SECTION = "com/github/maoschanz/drawing"


def _red(r, g, b):
    return r >= 150 and g <= 60 and b <= 60 and r - g >= 100   # the default main colour #CC0000 (text / strokes), absent from sample_0.png


def _near(px, rgb, tol=40):
    return px is not None and all(abs(a - b) <= tol for a, b in zip(px, rgb))


# ---------------------------------------------------------------------------------------------- oracles
def oracle_show_names(home):
    v = kit.ini_value(home, SETTINGS, SECTION, "show-labels")
    return v == "true", f"keyfile [{SECTION}] show-labels={v!r}"


def oracle_no_ctrl_zoom(home):
    v = kit.ini_value(home, SETTINGS, SECTION, "ctrl-zoom")
    return v == "false", f"keyfile [{SECTION}] ctrl-zoom={v!r} (default is true, so it is only written once changed)"


def oracle_rotate(home):
    size = kit.png_size(home, SAMPLE)
    cw = kit.png_pixel(home, SAMPLE, 407, 207)         # the orange circle of the original at (207, 192) lands here after a 90 deg clockwise turn
    ccw = kit.png_pixel(home, SAMPLE, 192, 592)        # ... and here after a counter-clockwise turn
    ok = size == (600, 800) and _near(cw, (210, 127, 1)) and not _near(ccw, (210, 127, 1))
    return ok, f"{SAMPLE} size={size!r} pixel(407,207)={cw!r} pixel(192,592)={ccw!r} (orange circle = (210,127,1))"


def oracle_scale(home):
    size = kit.png_size(home, SAMPLE)
    return size == (400, 300), f"{SAMPLE} size={size!r}"


def oracle_text(home):
    size = kit.png_size(home, SAMPLE)
    n = kit.png_count(home, SAMPLE, _red)
    return n is not None and n >= 15, f"{SAMPLE} size={size!r} red text-colour pixels={n!r} (original has 0; text content itself is not checked)"


def oracle_banner(home):
    rel = "Pictures/harbor-banner.png"
    size = kit.png_size(home, rel)
    n = kit.png_count(home, rel, _red)
    return size == (640, 360) and n is not None and n >= 15, f"{rel} size={size!r} red text-colour pixels={n!r}"


# ---------------------------------------------------------------------------------------------- positive scripts
def _menu_item(ep, name, role="button"):
    ep.click(1765, 27)                      # hamburger menu
    ep.sleep(1.0)
    ep.click_node(role=role, name=name)
    ep.sleep(1.2)


def _text(ep, x, y, text):
    ep.click(24, 297)                       # text tool
    ep.sleep(0.6)
    ep.click(x, y)                          # where the text goes; a popover with a text box opens
    ep.sleep(0.8)
    ep.type(text)
    ep.sleep(0.5)
    ep.click_node(role="button", name="Insert here")
    ep.sleep(1.0)


def pos_show_names(ep):
    _menu_item(ep, "Show tools names", role="check box")


def pos_no_ctrl_zoom(ep):
    _menu_item(ep, "Preferences")
    ep.click(260, 497)                      # "Use 'Ctrl' to zoom" switch in the Preferences window
    ep.sleep(1.0)


def pos_rotate(ep):
    ep.click(24, 855)                       # rotate tool
    ep.sleep(0.8)
    ep.click(937, 1052)                     # rotate right (clockwise)
    ep.sleep(0.8)
    ep.click(1891, 1052)                    # apply
    ep.sleep(1.0)
    ep.click(1709, 27)                      # Save
    ep.sleep(2.0)


def pos_scale(ep):
    ep.click(24, 786)                       # scale tool
    ep.sleep(0.8)
    spins = [n for n in ep.atspi() if n["role"] == "spin button" and "showing" in n["states"] and n["box"][1] > 1000]
    spins.sort(key=lambda n: n["box"][0])
    for node, value in zip(spins[:2], ("400", "300")):
        ep.click_box(node, dx=0.12)          # inside the number, not on the "px" label / the - + buttons
        ep.key("ctrl+a")
        ep.type(value)
        ep.key("Tab")
        ep.sleep(0.4)
    ep.click(1891, 1052)                    # apply
    ep.sleep(1.0)
    ep.click(1709, 27)
    ep.sleep(2.0)


def pos_text(ep):
    _text(ep, 300, 500, "Harbor")
    ep.click(1709, 27)
    ep.sleep(2.0)


def pos_banner(ep):
    ep.click(112, 27)                       # "new image" drop-down
    ep.sleep(1.0)
    ep.click_node(role="button", name="New Image With Custom Size")
    ep.sleep(1.5)
    dlg = ep.wait_node(role="dialog", name="New Image With Custom Size")
    spins = sorted(ep.nodes_in(dlg, role="spin button"), key=lambda n: n["box"][1])   # width, height
    for node, value in zip(spins, ("640", "360")):
        ep.click_box(node, dx=0.12)
        ep.key("ctrl+a")
        ep.type(value)
        ep.key("Tab")
    ep.click_node(role="button", name="Create")
    ep.sleep(1.5)
    _text(ep, 300, 200, "Harbor")
    ep.click(1709, 27)                      # Save -> "Save picture as" for an unsaved image
    ep.sleep(2.0)
    ep.key("ctrl+a")
    ep.type("Pictures/harbor-banner.png")
    ep.key("Return")
    ep.sleep(2.5)


TASKS = [
    {"id": "drawing_show_tool_names", "difficulty": 1,
     "sentence": "In Drawing, turn on \"Show tools names\" so the tool list shows text labels.",
     "setup": None, "oracle": oracle_show_names, "positive": pos_show_names},
    {"id": "drawing_no_ctrl_zoom", "difficulty": 1,
     "sentence": "Open Drawing's Preferences and turn off the option \"Use 'Ctrl' to zoom\".",
     "setup": None, "oracle": oracle_no_ctrl_zoom, "positive": pos_no_ctrl_zoom},
    {"id": "drawing_rotate_save", "difficulty": 2,
     "sentence": "Rotate the open picture 90 degrees clockwise (to the right) and save it.",
     "setup": None, "oracle": oracle_rotate, "positive": pos_rotate},
    {"id": "drawing_scale_save", "difficulty": 2,
     "sentence": "Scale the open picture to 400 pixels wide and 300 pixels high and save it.",
     "setup": None, "oracle": oracle_scale, "positive": pos_scale},
    {"id": "drawing_text_save", "difficulty": 2,
     "sentence": "Write the word Harbor on the open picture with the text tool, then save the picture.",
     "setup": None, "oracle": oracle_text, "positive": pos_text},
    {"id": "drawing_banner_save_as", "difficulty": 3,
     "sentence": "Create a new image that is 640 pixels wide and 360 pixels high, write the word Harbor on it, and save it as "
                 "harbor-banner.png in the Pictures folder.",
     "setup": None, "oracle": oracle_banner, "positive": pos_banner},
]
