"""Command line: `python -m pixeltree.perceive SHOT.png` (also installed as `pixeltree-tree`).

Prints the tree text of one screenshot to stdout. `--text OUT.txt` / `--json OUT.json` write files instead (the JSON
has the structure of `pixeltree.perceive.tree.to_json`). Nothing in this command cleans or reformats the tree.
"""
import argparse
import json
import sys
from pathlib import Path

from .tree import to_json, to_text


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pixeltree-tree", description="Screenshot (PNG) -> element tree")
    ap.add_argument("screenshot", help="path of the PNG screenshot")
    ap.add_argument("--weights", default=None,
                    help="detector weights (default $PIXELTREE_WEIGHTS, else ~/.cache/pixeltree/pixeltree-detector-v1.pt)")
    ap.add_argument("--device", default=None,
                    help="cpu or a CUDA index (default $PIXELTREE_DEVICE, else cpu)")
    ap.add_argument("--json", metavar="OUT.json", default=None, help="write the tree as JSON")
    ap.add_argument("--text", metavar="OUT.txt", default=None, help="write the tree text to a file")
    args = ap.parse_args(argv)

    from .ours import build

    png = Path(args.screenshot).read_bytes()
    try:
        tree = build(png, weights=args.weights, device=args.device)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"pixeltree-tree: {exc}", file=sys.stderr)
        return 2

    text = to_text(tree)
    if args.text:
        Path(args.text).write_text(text + "\n", encoding="utf-8")
    if args.json:
        Path(args.json).write_text(json.dumps(to_json(tree), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    if not args.text and not args.json:
        print(text)
    else:
        print(f"{len(tree.elements)} elements in {tree.timings['total_s']:.2f} s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
