#!/usr/bin/env python3
"""Pre-release scrub check: look for things that must not be published.

Scans the working tree (and, with --git-history, the whole commit history) for machine-local paths,
user names, e-mail addresses, internal ticket or run identifiers, secrets and internal tool names.
Standard library only.

    python tools/scrub_check.py                      # scan the working tree
    python tools/scrub_check.py --paths docs tools   # scan only the given files / directories
    python tools/scrub_check.py --git-history        # also scan `git log -p --all`

Output is one line per hit, ``path:line: rule: matched text``. Exit code 1 if there is any hit, else
``scrub_check: 0 hits (N files)`` and exit code 0.

Rules (all of them apply to text files, to file names, and to text members of archives):

  home-path    a machine-local home directory path
  username     the maintainer's account name (case-insensitive); allowed: the project URL on the
               hosting site, and author lines (containing "Copyright") in LICENSE / NOTICE
  email        an e-mail address; allowed: the hosting site's and the assistant vendor's no-reply addresses,
               and addresses on reserved documentation / test domains (example.com, *.example, *.test, ...)
  lifeos       the name of an internal planning tool
  ticket       an internal ticket number ("PROJECT-" followed by digits)
  internal-id  an internal run / task / message identifier (a known prefix, an underscore and hex)
  secret       API keys, tokens, private-key headers, key assignments such as an api-key setting
  claude-dir   a path into a local assistant configuration directory
  tool-name    the name of an internal orchestration tool (whole word, case-insensitive)
  screencast   the name of an internal prototype directory

Binary files (images, pdf, onnx, ...) are checked by file name with every rule; their bytes are only
checked for the literal rules home-path, username, lifeos and claude-dir, so random bytes cannot trigger
the pattern rules. ``.tar.gz`` / ``.tgz`` / ``.zip`` archives are opened and their member names and text
contents are checked.

The patterns below are written with character classes (``[x]``) so that this file does not match its
own rules.
"""

from __future__ import annotations

import argparse
import io
import os
import re
import subprocess
import sys
import tarfile
import zipfile

SKIP_DIRS = {".git", ".venv", "venv", "site", "out", "__pycache__", ".pytest_cache", ".mypy_cache",
             ".ruff_cache"}
SKIP_SUFFIXES = (".pt", ".egg-info")
BINARY_EXTS = {".png", ".webp", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".onnx"}
ARCHIVE_EXTS = (".tar.gz", ".tgz", ".zip")

PROJECT_URL = "github.com/SentimentalK/pixeltree"
EMAIL_ALLOWED_EXACT = {"noreply@github.com", "noreply@anthropic.com"}
EMAIL_ALLOWED_SUFFIX = "users.noreply.github.com"
# Reserved documentation / test domains (RFC 2606, RFC 6761) can never be real addresses.
EMAIL_RESERVED_DOMAINS = ("example.com", "example.org", "example.net")
EMAIL_RESERVED_TLDS = ("example", "test", "invalid", "localhost")
AUTHOR_FILES = {"LICENSE", "NOTICE"}

# name -> pattern. The first element says whether the rule also applies to the raw bytes of binary files.
RULES = [
    ("home-path", True, r"/hom[e]/"),
    ("username", True, r"(?i)sentimenta[l]k"),
    ("email", False, r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    ("lifeos", True, r"Life[O]S"),
    ("ticket", False, r"PROJECT-\d+"),
    ("internal-id", False, r"\b(ctx|term|run|task|msg|wf)_[0-9a-f][0-9a-f-]{7,}"),
    ("secret", False, "|".join([
        r"sk-[A-Za-z0-9_-]{16,}", r"ghp_[A-Za-z0-9]{20,}", r"github_pat_[A-Za-z0-9_]{20,}",
        r"AKIA[0-9A-Z]{16}", r"-{5}BEGIN", r"(?i:api[_-]?key)\s*[:=]"])),
    ("claude-dir", True, r"\.cl[a]ude/"),
    ("tool-name", False, r"(?i)\bor[c]a\b"),
    ("screencast", False, r"screencast_po[c]"),
]
COMPILED = [(n, b, re.compile(p)) for n, b, p in RULES]
BYTE_RULES = [(n, re.compile(p.encode("ascii"))) for n, b, p in RULES if b]


def _mask(rule: str, text: str) -> str:
    text = text.replace("\n", " ")
    if rule == "secret":
        return text[:6] + "..."
    return text if len(text) <= 80 else text[:77] + "..."


def email_allowed(addr: str) -> bool:
    if addr in EMAIL_ALLOWED_EXACT or addr.endswith(EMAIL_ALLOWED_SUFFIX):
        return True
    domain = addr.rsplit("@", 1)[-1].lower()
    return (domain.endswith(EMAIL_RESERVED_TLDS_SUFFIXES)
            or any(domain == d or domain.endswith("." + d) for d in EMAIL_RESERVED_DOMAINS))


EMAIL_RESERVED_TLDS_SUFFIXES = tuple("." + t for t in EMAIL_RESERVED_TLDS)


def scan_line(line: str, in_author_file: bool = False) -> list[tuple[str, str]]:
    """All (rule, matched text) hits in one line of text, whitelists applied."""
    hits = []
    for name, _, rx in COMPILED:
        subject = line
        if name == "username":
            if in_author_file and "Copyright" in line:
                continue
            subject = line.replace(PROJECT_URL, "")
        for m in rx.finditer(subject):
            g = m.group(0)
            if name == "email" and email_allowed(g):
                continue
            hits.append((name, g))
    return hits


def scan_name(name: str) -> list[tuple[str, str]]:
    return scan_line(name)


def scan_bytes(data: bytes) -> list[tuple[str, str]]:
    """Binary content: literal rules only, one hit per rule and kind of match."""
    data = data.replace(PROJECT_URL.encode(), b"")
    hits = []
    for name, rx in BYTE_RULES:
        seen = set()
        for m in rx.finditer(data):
            g = m.group(0).decode("ascii", "replace")
            if g not in seen:
                seen.add(g)
                hits.append((name, g))
    return hits


def _is_binary(name: str, data: bytes) -> bool:
    return os.path.splitext(name)[1].lower() in BINARY_EXTS or b"\0" in data[:8192]


def scan_content(name: str, data: bytes) -> list[tuple[int, str, str]]:
    """Hits (line, rule, text) in the content of a file called ``name``."""
    if _is_binary(name, data):
        return [(0, r, t) for r, t in scan_bytes(data)]
    author_file = os.path.splitext(os.path.basename(name))[0] in AUTHOR_FILES
    out = []
    for i, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
        for r, t in scan_line(line, author_file):
            out.append((i, r, t))
    return out


def _is_archive(name: str) -> bool:
    return name.lower().endswith(ARCHIVE_EXTS)


def scan_archive(path: str, shown: str) -> list[tuple[str, int, str, str]]:
    """Hits (display path, line, rule, text) in an archive: member names and member contents."""
    out = []
    members: list[tuple[str, bytes]] = []
    try:
        if path.lower().endswith(".zip"):
            with zipfile.ZipFile(path) as z:
                for info in z.infolist():
                    members.append((info.filename, b"" if info.is_dir() else z.read(info)))
        else:
            with tarfile.open(path, "r:*") as t:
                for m in t.getmembers():
                    f = t.extractfile(m) if m.isfile() else None
                    members.append((m.name, f.read() if f else b""))
    except (OSError, tarfile.TarError, zipfile.BadZipFile) as e:
        return [(shown, 0, "archive", "cannot read archive: %s" % e)]
    for mname, data in members:
        disp = "%s!%s" % (shown, mname)
        for r, t in scan_name(mname):
            out.append((disp, 0, r, t))
        for i, r, t in scan_content(mname, data):
            out.append((disp, i, r, t))
    return out


def iter_files(root: str):
    """Yield every file below ``root`` (or ``root`` itself if it is a file), skipping build products."""
    if os.path.isfile(root):
        yield root
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.endswith(SKIP_SUFFIXES))
        for f in sorted(filenames):
            if f.endswith(SKIP_SUFFIXES):
                continue
            yield os.path.join(dirpath, f)


def scan_paths(paths: list[str], repo_root: str | None = None) -> tuple[list[tuple[str, int, str, str]], int]:
    """Scan files / directories. Returns (hits, number of files). A hit is (display path, line, rule, text).
    Display paths (and the file-name rule) are relative to ``repo_root`` when the file is inside it,
    otherwise relative to the scanned path."""
    hits = []
    n = 0
    root_abs = os.path.abspath(repo_root) if repo_root else None
    for p in paths:
        p_abs = os.path.abspath(p)
        if root_abs and (p_abs == root_abs or p_abs.startswith(root_abs + os.sep)):
            base = root_abs
        else:
            base = p_abs if os.path.isdir(p_abs) else os.path.dirname(p_abs)
        for f in iter_files(p_abs):
            n += 1
            rel = os.path.relpath(f, base).replace(os.sep, "/")
            for r, t in scan_name(rel):
                hits.append((rel, 0, r, t))
            if _is_archive(f):
                hits.extend(scan_archive(f, rel))
                continue
            with open(f, "rb") as fh:
                data = fh.read()
            for i, r, t in scan_content(rel, data):
                hits.append((rel, i, r, t))
    return hits, n


def scan_git_history(repo_root: str) -> tuple[list[tuple[str, int, str, str]], list[str]]:
    """Patches and commit messages of every commit on every ref (author / committer headers excluded).
    Returns (hits, the set of author / committer e-mail addresses that occur, sorted)."""
    def git(*args):
        return subprocess.run(["git", "-C", repo_root, *args], capture_output=True)

    log = git("log", "-p", "--all", "--format=commit %H%n%B")
    if log.returncode != 0:
        err = log.stderr.decode("utf-8", "replace")
        if "does not have any commits" in err or "bad default revision" in err:
            return [], []
        raise RuntimeError("git log failed: %s" % err.strip())
    hits = []
    commit = "?"
    current_file = ""
    for i, line in enumerate(log.stdout.decode("utf-8", "replace").splitlines(), 1):
        if line.startswith("commit ") and re.fullmatch(r"commit [0-9a-f]{40}", line):
            commit, current_file = line[7:17], ""
            continue
        if line.startswith("diff --git "):
            current_file = line.rsplit(" b/", 1)[-1]
        author_file = os.path.splitext(os.path.basename(current_file))[0] in AUTHOR_FILES
        for r, t in scan_line(line, author_file):
            hits.append(("git:%s" % commit, i, r, t))
    emails = git("log", "--all", "--format=%ae%n%ce")
    addrs = sorted({l.strip() for l in emails.stdout.decode("utf-8", "replace").splitlines() if l.strip()})
    return hits, addrs


def main(argv: list[str] | None = None) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(here)
    ap = argparse.ArgumentParser(description="Check the repository for things that must not be published.")
    ap.add_argument("--paths", nargs="+", metavar="P", help="scan only these files / directories (default: the whole repository)")
    ap.add_argument("--git-history", action="store_true", help="also scan the patches and messages of all commits")
    a = ap.parse_args(argv)

    hits, n = scan_paths(a.paths or [repo_root], repo_root)
    if a.git_history:
        gh, addrs = scan_git_history(repo_root)
        hits.extend(gh)
        for addr in addrs:
            print("INFO: author / committer e-mail in history: %s" % addr)
    for path, line, rule, text in hits:
        print("%s:%d: %s: %s" % (path, line, rule, _mask(rule, text)))
    if hits:
        print("scrub_check: %d hits (%d files)" % (len(hits), n))
        return 1
    print("scrub_check: 0 hits (%d files)" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
