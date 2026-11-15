"""Screenshot -> element tree on the command line.

    python -m bench.perception.cli --image <png | directory> --source ours|omni|atspi \
        [--atspi-json <dump.json> --process <substring>] [--format text|json] [--out <file>]

--image DIR runs every *.png in it (sorted).  For --source atspi each image uses --atspi-json, or <stem>.atspi.json
next to the image.  Per image the stage timings go to stderr; for a directory a per-image table and the median
total follow.  --format json writes one object (one image) or {"<file name>": object, ...} (directory); text
writes the agent text, with a "# <file name>" line before each tree when a directory is given.
"""
import argparse
import json
import statistics
import sys
import time
from pathlib import Path

from .sources import build_tree
from pixeltree.perceive.tree import to_json, to_text


def _images(path):
    path = Path(path)
    if path.is_dir():
        return sorted(path.glob("*.png")), True
    return [path], False


def _one(source, image, atspi_json, process):
    png = image.read_bytes()
    nodes = None
    if source == "atspi":
        dump = Path(atspi_json) if atspi_json else image.with_suffix("").with_suffix(".atspi.json")
        if not dump.is_file():
            raise SystemExit(f"--source atspi needs --atspi-json (or {dump} next to the image)")
        nodes = dump
    t0 = time.perf_counter()
    tree = build_tree(source, png_bytes=png, atspi_nodes=nodes, process=process)
    wall = time.perf_counter() - t0
    return tree, wall


def _fmt_timings(tree, wall):
    parts = [f"{k}={v:.3f}" for k, v in tree.timings.items() if k.endswith("_s") and isinstance(v, float)]
    return f"{len(tree.elements)} elements, wall={wall:.3f}s, " + " ".join(parts)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--image", required=True, help="a PNG screenshot or a directory of PNGs")
    ap.add_argument("--source", required=True, choices=["ours", "omni", "atspi"])
    ap.add_argument("--atspi-json", help="AT-SPI dump (desk.atspi_nodes or real_capture format)")
    ap.add_argument("--process", help="AT-SPI application name substring")
    ap.add_argument("--format", choices=["text", "json"], default="text")
    ap.add_argument("--out", help="write the result here instead of stdout")
    args = ap.parse_args(argv)

    images, many = _images(args.image)
    if not images:
        raise SystemExit(f"no PNG images in {args.image}")
    results, walls, totals = [], [], []
    for image in images:
        tree, wall = _one(args.source, image, args.atspi_json, args.process)
        print(f"{image.name}: {_fmt_timings(tree, wall)}", file=sys.stderr)
        results.append((image, tree))
        walls.append(wall)
        totals.append(tree.timings.get("total_s", wall))
    if many:
        print(f"median over {len(images)} images: wall={statistics.median(walls):.3f}s "
              f"total_s={statistics.median(totals):.3f}s", file=sys.stderr)

    if args.format == "json":
        if many:
            payload = {image.name: to_json(tree) for image, tree in results}
        else:
            payload = to_json(results[0][1])
        text = json.dumps(payload, ensure_ascii=False, indent=1)
    else:
        if many:
            text = "\n\n".join(f"# {image.name}\n{to_text(tree)}" for image, tree in results)
        else:
            text = to_text(results[0][1])
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
