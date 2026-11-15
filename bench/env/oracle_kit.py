"""Small read-only helpers for oracles.  Every function returns None when it cannot read (never raises).

An oracle is `oracle(home: Path) -> (ok: bool, detail: str)`; with these helpers most of them are one or two lines:

    def oracle(home):
        rows = sqlite_rows(home, ".local/share/lutris/pga.db", "select name, runner from games where name=?", ("Tide Quest",))
        return (bool(rows), f"games rows={rows!r}")

Nothing here uses an LLM, OCR, screenshots or AT-SPI.  `home` is the sandbox HOME of the episode (`ep.home`).
"""
from __future__ import annotations

import glob
import json
import os
import sqlite3
import subprocess
import xml.etree.ElementTree as ET
from configparser import ConfigParser, Error as ConfigError
from pathlib import Path

CLEAN_PATH = "/usr/local/bin:/usr/bin:/bin:/usr/games"


def _home(home) -> Path:
    return Path(home)


def _glob(home, rel_glob) -> list[Path]:
    try:
        return sorted(Path(p) for p in glob.glob(str(_home(home) / rel_glob), recursive=True))
    except OSError:
        return []


def file_text(home, rel) -> str | None:
    """Text of HOME/rel (utf-8, undecodable bytes replaced); None when missing."""
    try:
        return (_home(home) / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def file_exists(home, rel_glob) -> list[Path] | None:
    """Sorted paths matching the glob under HOME (non-empty list), or None when nothing matches."""
    hits = [p for p in _glob(home, rel_glob) if p.exists()]
    return hits or None


def sqlite_rows(home, rel, sql, params=()) -> list[tuple] | None:
    """Rows of a read-only query on HOME/rel; None when the file or table is missing / locked."""
    path = _home(home) / rel
    if not path.is_file():
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=3)
        try:
            return [tuple(r) for r in con.execute(sql, tuple(params)).fetchall()]
        finally:
            con.close()
    except sqlite3.Error:
        # a WAL database that cannot be opened read-only (no -shm yet): retry on a private copy
        return _sqlite_copy_rows(path, sql, params)


def _sqlite_copy_rows(path: Path, sql, params):
    import shutil
    import tempfile
    try:
        with tempfile.TemporaryDirectory(prefix="oraclekit-") as tmp:
            for suffix in ("", "-wal", "-shm"):
                src = Path(str(path) + suffix)
                if src.exists():
                    shutil.copy(src, Path(tmp) / (path.name + suffix))
            con = sqlite3.connect(str(Path(tmp) / path.name), timeout=3)
            try:
                return [tuple(r) for r in con.execute(sql, tuple(params)).fetchall()]
            finally:
                con.close()
    except (sqlite3.Error, OSError):
        return None


def ini_value(home, rel, section, key) -> str | None:
    """Value of [section] key in an ini / keyfile (case-sensitive keys, no interpolation); None when absent."""
    text = file_text(home, rel)
    if text is None:
        return None
    parser = ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    try:
        parser.read_string(text)
        return parser.get(section, key)
    except (ConfigError, KeyError):
        return None


def xml_find(home, rel_glob, xpath) -> list[ET.Element] | None:
    """Elements matching an ElementTree xpath in every XML file matching the glob; None when no file / no match."""
    found = []
    for path in _glob(home, rel_glob):
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError):
            continue
        found.extend(root.findall(xpath))
    return found or None


def sandbox_env(home) -> dict[str, str]:
    """Environment of the episode (HOME, XDG dirs, the private dbus address when known) for running CLIs."""
    home = _home(home)
    env = {"PATH": CLEAN_PATH, "HOME": str(home), "LANG": "C.UTF-8",
           "XDG_CONFIG_HOME": str(home / ".config"), "XDG_DATA_HOME": str(home / ".local/share"),
           "XDG_CACHE_HOME": str(home / ".cache"), "XDG_STATE_HOME": str(home / ".local/state"),
           "GSETTINGS_BACKEND": "memory", "GIT_CONFIG_NOSYSTEM": "1"}
    recorded = home.parent / "episode_env.json"
    try:
        saved = json.loads(recorded.read_text())
        for key in ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "DBUS_SYSTEM_BUS_ADDRESS", "DISPLAY",
                    "GSETTINGS_BACKEND"):
            if key in saved:
                env[key] = saved[key]
    except (OSError, ValueError):
        pass
    return env


def run_cli(home, argv, timeout=30, stdin: str | None = None) -> str | None:
    """stdout of a command run in the sandbox HOME (+ the episode's dbus session); None on failure / timeout."""
    try:
        res = subprocess.run([str(a) for a in argv], env=sandbox_env(home), cwd=str(_home(home)), input=stdin,
                             stdin=None if stdin is not None else subprocess.DEVNULL,
                             capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return res.stdout if res.returncode == 0 else None


def git(home, repo_rel, *args) -> str | None:
    """stdout of `git -C HOME/repo_rel args` (sandbox identity, no system config); None on failure."""
    repo = _home(home) / repo_rel
    if not repo.exists():
        return None
    return run_cli(home, ["git", "-C", str(repo), "-c", "safe.directory=*", *args])


def keepass_cli(home, kdbx_rel, keyfile_rel, *args) -> str | None:
    """`keepassxc-cli <args>` on a key-file-only database (--no-password -k keyfile); the db path is inserted
    after the sub-command, so pass e.g. keepass_cli(home, db, key, "show", "-s", "Entry")."""
    if not args:
        return None
    home = _home(home)
    cmd, rest = args[0], list(args[1:])
    argv = ["keepassxc-cli", cmd, "--no-password", "-k", str(home / keyfile_rel), str(home / kdbx_rel), *rest]
    return run_cli(home, argv, stdin="")


def ics_events(home, rel_glob) -> list[dict] | None:
    """VEVENTs of every .ics matching the glob as dicts {SUMMARY, DTSTART, DTEND, ...} (raw values, params dropped).
    Unfolds continuation lines; None when no file matches."""
    events, seen = [], False
    for path in _glob(home, rel_glob):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        seen = True
        lines = []
        for raw in text.replace("\r\n", "\n").split("\n"):
            if raw[:1] in (" ", "\t") and lines:
                lines[-1] += raw[1:]
            else:
                lines.append(raw)
        cur = None
        for line in lines:
            if line == "BEGIN:VEVENT":
                cur = {}
            elif line == "END:VEVENT":
                if cur is not None:
                    events.append(cur)
                cur = None
            elif cur is not None and ":" in line:
                head, value = line.split(":", 1)
                cur[head.split(";", 1)[0].upper()] = value
                if ";" in head:
                    cur[head.split(";", 1)[0].upper() + ";PARAMS"] = head.split(";", 1)[1]
    return events if seen else None


def vcards(home, rel_glob) -> list[dict] | None:
    """vCards of every .vcf matching the glob as dicts {FN, N, TEL: [values], EMAIL: [...] ...}; None when no file."""
    cards, seen = [], False
    for path in _glob(home, rel_glob):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        seen = True
        cards.extend(parse_vcards(text))
    return cards if seen else None


def parse_vcards(text: str) -> list[dict]:
    """Parse vCard text (2.1 / 3.0 / 4.0 flavours EDS writes) into dicts; multi-valued properties become lists."""
    lines = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    cards, cur = [], None
    for line in lines:
        up = line.upper()
        if up == "BEGIN:VCARD":
            cur = {}
        elif up == "END:VCARD":
            if cur is not None:
                cards.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            head, value = line.split(":", 1)
            prop = head.split(";", 1)[0].upper()
            if "." in prop:  # group prefix "item1.TEL"
                prop = prop.split(".", 1)[1]
            if prop in ("TEL", "EMAIL", "ADR", "URL", "NOTE", "CATEGORIES"):
                cur.setdefault(prop, []).append(value)
            else:
                cur[prop] = value
    return cards


# ---------------------------------------------------------------------------------------------- PNG (stdlib only)
def png_pixels(home, rel):
    """(width, height, rows) of an 8-bit non-interlaced RGB/RGBA/gray PNG; rows[y] is a bytes object with
    `channels` bytes per pixel (channels = len(row) // width).  None when missing / unsupported."""
    import struct
    import zlib
    try:
        data = (_home(home) / rel).read_bytes()
    except OSError:
        return None
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    pos, idat, ihdr = 8, b"", None
    while pos + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", chunk)
        elif kind == b"IDAT":
            idat += chunk
        elif kind == b"IEND":
            break
        pos += 12 + length
    if ihdr is None:
        return None
    w, h, depth, ctype, _, _, interlace = ihdr
    channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(ctype)
    if depth != 8 or interlace or channels is None:
        return None
    try:
        raw = zlib.decompress(idat)
    except zlib.error:
        return None
    stride, rows, prev = w * channels, [], bytearray(w * channels)
    for y in range(h):
        base = y * (stride + 1)
        ft, line = raw[base], bytearray(raw[base + 1:base + 1 + stride])
        if ft == 1:
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 255
        elif ft == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif ft == 3:
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 255
        elif ft == 4:
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b, c = prev[i], (prev[i - channels] if i >= channels else 0)
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pred) & 255
        elif ft != 0:
            return None
        rows.append(bytes(line))
        prev = line
    return w, h, rows


def png_size(home, rel):
    """(width, height) from the IHDR chunk only (cheap); None when missing / not a PNG."""
    import struct
    try:
        head = (_home(home) / rel).read_bytes()[:24]
    except OSError:
        return None
    if head[:8] != b"\x89PNG\r\n\x1a\n" or len(head) < 24:
        return None
    return struct.unpack(">II", head[16:24])


def png_pixel(home, rel, x, y):
    """(r, g, b) at (x, y); None when unreadable / out of range."""
    img = png_pixels(home, rel)
    if img is None:
        return None
    w, h, rows = img
    if not (0 <= x < w and 0 <= y < h):
        return None
    ch = len(rows[0]) // w
    px = rows[y][x * ch:(x + 1) * ch]
    return (px[0], px[0], px[0]) if ch < 3 else (px[0], px[1], px[2])


def png_count(home, rel, predicate, box=None):
    """Number of pixels (r, g, b) in `box` = (x0, y0, x1, y1) (default: whole image) for which predicate(r, g, b)."""
    img = png_pixels(home, rel)
    if img is None:
        return None
    w, h, rows = img
    x0, y0, x1, y1 = box or (0, 0, w, h)
    ch = len(rows[0]) // w
    n = 0
    for y in range(max(0, y0), min(h, y1)):
        row = rows[y]
        for x in range(max(0, x0), min(w, x1)):
            i = x * ch
            if ch >= 3:
                r, g, b = row[i], row[i + 1], row[i + 2]
            else:
                r = g = b = row[i]
            if predicate(r, g, b):
                n += 1
    return n
