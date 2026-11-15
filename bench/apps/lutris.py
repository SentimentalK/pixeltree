"""Lutris (GTK3), empty library, sandbox HOME (no network)."""
from pathlib import Path

from bench.env import oracle_kit as kit

APP = {
    "name": "lutris",
    "argv": lambda home: ["lutris"],
    "env": {"LUTRIS_SKIP_INIT": "1"},   # no runtime / component downloads at start (no network needed)
    "startup_s": 10,
    "window_title": "Lutris",
    "process": "lutris",
    "prepare": None,
    "close": "wm_close",
    "state_files": [".local/share/lutris/pga.db", ".local/share/lutris/lutris.conf", ".config/lutris/**"],
    "tier": "good",
    "atspi_recall_05": 0.776,
}

GAMES_DB = ".local/share/lutris/pga.db"


def seed_games(home: Path, *names: str) -> None:
    """Library rows made with Lutris' own database module (setup only): (name, slug from name, runner linux)."""
    import subprocess
    (home / ".local/share/lutris").mkdir(parents=True, exist_ok=True)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(home), "XDG_DATA_HOME": str(home / ".local/share"),
           "XDG_CONFIG_HOME": str(home / ".config"), "XDG_CACHE_HOME": str(home / ".cache"), "DISPLAY": ""}
    code = ("import sys\nfrom lutris.database import schema, games\nschema.syncdb()\n"
            "for n in sys.argv[1:]:\n    games.add_game(name=n, slug=n.lower().replace(' ', '-'), runner='linux', installed=1)\n")
    subprocess.run(["/usr/bin/python3", "-c", code, *names], env=env, check=True, capture_output=True, timeout=60)


def setup_two_games(home: Path) -> None:
    seed_games(home, "Old Game", "Keep Game")



# ---------------------------------------------------------------------------------------------- oracle helpers
def _games(home):
    return kit.sqlite_rows(home, GAMES_DB, "select name, runner, year from games")


def _favorites(home):
    rows = kit.sqlite_rows(home, GAMES_DB,
                           "select g.name from games g join games_categories gc on gc.game_id = g.id "
                           "join categories c on c.id = gc.category_id where c.name = 'favorite'")
    return None if rows is None else sorted(r[0] for r in rows)


def _conf(home, key):
    return kit.ini_value(home, ".local/share/lutris/lutris.conf", "lutris", key)


# ---------------------------------------------------------------------------------------------- oracles
def oracle_hide_panel(home):
    v = _conf(home, "side_panel_visible")
    return v == "False", f"lutris.conf [lutris] side_panel_visible={v!r}"


def oracle_remove(home):
    games = _games(home)
    names = None if games is None else [g[0] for g in games]
    return names is not None and "Old Game" not in names and "Keep Game" in names, f"games={names!r}"


def oracle_add_game(home):
    games = _games(home) or []
    hit = [g for g in games if g[0] == "Tide Quest"]
    return bool(hit) and hit[0][1] == "linux", f"games (name, runner, year)={games!r}"


def oracle_hide_text(home):
    v = _conf(home, "hide_text_under_icons")
    return v == "True", f"lutris.conf [lutris] hide_text_under_icons={v!r}"


def oracle_favorite(home):
    fav = _favorites(home)
    return fav is not None and "Keep Game" in fav and "Old Game" not in fav, f"favorites={fav!r}"


def oracle_wine_year_fav(home):
    games = _games(home) or []
    hit = [g for g in games if g[0] == "Harbor Run"]
    fav = _favorites(home)
    ok = bool(hit) and hit[0][1] == "wine" and hit[0][2] == 2019 and fav is not None and "Harbor Run" in fav
    return ok, f"games (name, runner, year)={games!r} favorites={fav!r}"


# ---------------------------------------------------------------------------------------------- positive scripts
TILE = {"first": (301, 175), "second": (485, 175)}      # library tiles, alphabetical (Keep Game, Old Game)


def _menu(ep, item=None):
    ep.click(1765, 27)                       # hamburger menu
    ep.sleep(1.0)


def _add_dialog(ep, name, runner, year=None):
    ep.click(27, 27)                         # "+" Add Game
    ep.sleep(1.5)
    ep.click(960, 656)                       # "Add locally installed game"
    ep.sleep(2.5)
    ep.click(1080, 341)                      # Name
    ep.type(name)
    ep.click(1080, 433)                      # Runner combo box
    ep.sleep(0.8)
    ep.click_node(role="menu item", contains=runner + " (Runs")
    ep.sleep(0.8)
    if year:
        ep.click(1080, 479)                  # Release year
        ep.type(str(year))
    ep.click(1339, 239)                      # Save
    ep.sleep(2.5)


def _favorite(ep, tile):
    ep.click(*TILE[tile], button=3)
    ep.sleep(1.0)
    ep.click_node(role="menu item", name="Add to favorites")
    ep.sleep(1.0)


def pos_hide_panel(ep):
    _menu(ep)
    ep.click_node(role="check box", name="Show Side Panel")
    ep.sleep(1.0)


def pos_remove(ep):
    ep.click(*TILE["second"], button=3)
    ep.sleep(1.0)
    ep.click_node(role="menu item", name="Remove")
    ep.sleep(1.5)
    ep.click_node(role="check box", name="Remove from Library")      # the dialog's check box is off by default
    ep.sleep(0.5)
    ep.click_node(role="button", name="Remove")
    ep.sleep(1.5)


def pos_add_game(ep):
    _add_dialog(ep, "Tide Quest", "Linux")


def pos_hide_text(ep):
    _menu(ep)
    ep.click(1724, 174)                      # "Preferences"
    ep.sleep(2.0)
    ep.click_box(ep.wait_node(role="label", name="Hide text under icons"))   # row selects, toggle at the right
    ep.click(1345, 426)
    ep.sleep(1.0)
    ep.key("Escape")
    ep.sleep(1.0)


def pos_favorite(ep):
    _favorite(ep, "first")


def pos_wine_year_fav(ep):
    _add_dialog(ep, "Harbor Run", "Wine", year=2019)
    _favorite(ep, "first")


TASKS = [
    {"id": "lutris_hide_side_panel", "difficulty": 1,
     "sentence": "In Lutris, hide the side panel (the library sidebar on the left).",
     "setup": None, "oracle": oracle_hide_panel, "positive": pos_hide_panel},
    {"id": "lutris_favorite_game", "difficulty": 1,
     "sentence": "Add the game \"Keep Game\" to the favorites (leave \"Old Game\" alone).",
     "setup": setup_two_games, "oracle": oracle_favorite, "positive": pos_favorite},
    {"id": "lutris_remove_game", "difficulty": 2,
     "sentence": "Remove the game \"Old Game\" from the Lutris library and keep \"Keep Game\".",
     "setup": setup_two_games, "oracle": oracle_remove, "positive": pos_remove},
    {"id": "lutris_add_game", "difficulty": 2,
     "sentence": "Add a locally installed game named Tide Quest that uses the Linux runner.",
     "setup": None, "oracle": oracle_add_game, "positive": pos_add_game},
    {"id": "lutris_hide_text", "difficulty": 2,
     "sentence": "Open Lutris Preferences and turn on \"Hide text under icons\".",
     "setup": None, "oracle": oracle_hide_text, "positive": pos_hide_text},
    {"id": "lutris_wine_game_favorite", "difficulty": 3,
     "sentence": "Add a locally installed game named Harbor Run with the Wine runner and the release year 2019, then add it to the favorites.",
     "setup": None, "oracle": oracle_wine_year_fav, "positive": pos_wine_year_fav},
]
