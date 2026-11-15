#!/usr/bin/env python3
"""Download the leaf-detector weights and verify them against weights/SHA256SUMS (standard library only).

    python weights/download.py                      # -> ~/.cache/pixeltree/pixeltree-detector-v1.pt
    python weights/download.py --dest PATH          # another destination
    python weights/download.py --check PATH         # only verify a local file (no network)

A download whose SHA-256 does not match is deleted and the exit code is non-zero.
"""
import argparse
import hashlib
import os
import sys
import urllib.request
from pathlib import Path

NAME = "pixeltree-detector-v1.pt"
URL = "https://github.com/SentimentalK/pixeltree/releases/download/v0.1.0/" + NAME
DEFAULT_DEST = Path("~/.cache/pixeltree") / NAME
SUMS = Path(__file__).resolve().with_name("SHA256SUMS")


def expected_sha256():
    """The hash listed for NAME in SHA256SUMS (lines: `<hex>  <file name>`)."""
    for line in SUMS.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == NAME:
            return parts[0].lower()
    raise SystemExit(f"{SUMS} has no entry for {NAME}")


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def check(path):
    """True when `path` exists and matches the listed SHA-256 (prints the result)."""
    path = Path(path).expanduser()
    if not path.is_file():
        print(f"{path}: not found", file=sys.stderr)
        return False
    actual, want = sha256_of(path), expected_sha256()
    if actual != want:
        print(f"{path}: SHA-256 mismatch\n  expected {want}\n  actual   {actual}", file=sys.stderr)
        return False
    print(f"{path}: OK ({actual})")
    return True


def download(dest):
    dest = Path(dest).expanduser()
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    print(f"downloading {URL}")
    try:
        with urllib.request.urlopen(URL) as response, open(part, "wb") as out:
            while True:
                block = response.read(1 << 20)
                if not block:
                    break
                out.write(block)
    except OSError as exc:
        part.unlink(missing_ok=True)
        print(f"download failed: {exc}", file=sys.stderr)
        return False
    if not check(part):
        part.unlink(missing_ok=True)
        return False
    os.replace(part, dest)
    print(f"saved to {dest}")
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dest", default=str(DEFAULT_DEST), help=f"where to save (default {DEFAULT_DEST})")
    ap.add_argument("--check", metavar="PATH", default=None, help="only verify this local file against SHA256SUMS")
    args = ap.parse_args(argv)
    ok = check(args.check) if args.check else download(args.dest)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
