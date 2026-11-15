"""Build a Volume image-list txt (one /vol/... path per line) and upload it to /lists/<name>.txt on pixeltree-data.

    python make_list.py NAME SRC [SRC ...] --prefix /vol/train/images [--upload]

SRC = a local directory of images (file names are used as-is, sorted) or a txt list (one local image path
per line; only the basename is used). Every name becomes <prefix>/<basename>. Labels must already sit in
the sibling <prefix-without-images>/labels/ dir on the Volume (ultralytics maps /images/ -> /labels/).
The local list file is written to --out-dir (default out/modal/lists).
"""
import argparse
import os
from pathlib import Path

import modal

EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def names_from(src):
    p = Path(src)
    if p.is_dir():
        return sorted(n for n in os.listdir(p) if Path(n).suffix.lower() in EXT)
    return [Path(l.strip()).name for l in open(p) if l.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("src", nargs="+")
    ap.add_argument("--prefix", required=True, help="Volume dir of the images, e.g. /vol/train/images")
    ap.add_argument("--out-dir", default="out/modal/lists")
    ap.add_argument("--upload", action="store_true")
    a = ap.parse_args()
    names = []
    for s in a.src:
        names += names_from(s)
    if len(set(names)) != len(names):
        raise SystemExit(f"duplicate names: {len(names) - len(set(names))}")
    out = Path(a.out_dir) / f"{a.name}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(f"{a.prefix.rstrip('/')}/{n}\n" for n in names))
    print(f"{out}: {len(names)} lines")
    if a.upload:
        vol = modal.Volume.from_name("pixeltree-data", create_if_missing=True, version=2)
        with vol.batch_upload(force=True) as up:
            up.put_file(str(out), f"/lists/{a.name}.txt")
        print(f"uploaded -> /lists/{a.name}.txt (Volume path /vol/lists/{a.name}.txt)")


if __name__ == "__main__":
    main()
