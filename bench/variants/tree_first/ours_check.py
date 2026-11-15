"""Check that the resident server returns the same tree as a direct build:

    python -m bench.variants.tree_first.ours_check --display :150 --png <screenshot.png>

Builds the tree of the PNG through the client (the server for --display must be running) and directly with
bench.perception.sources.build_tree("ours"), then compares (role, name, box) element by element (conf rounded to 4
decimals; timings ignored).  Prints `identical <n> elements` (exit 0) or the first difference (exit 1).
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def compare(a, b):
    """None when the two tree json dicts carry the same elements, else a description of the first difference."""
    ea, eb = a["elements"], b["elements"]
    if len(ea) != len(eb):
        return f"element count differs: {len(ea)} vs {len(eb)}"
    for k, (x, y) in enumerate(zip(ea, eb)):
        for field in ("role", "name", "box"):
            if x[field] != y[field]:
                return f"element {k} ({x['id']}): {field} {x[field]!r} vs {y[field]!r}"
        cx = None if x.get("conf") is None else round(x["conf"], 4)
        cy = None if y.get("conf") is None else round(y["conf"], 4)
        if cx != cy:
            return f"element {k} ({x['id']}): conf {cx} vs {cy}"
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--display", required=True)
    ap.add_argument("--png", required=True)
    args = ap.parse_args(argv)
    png = Path(args.png).read_bytes()
    from bench.perception import sources
    from pixeltree.perceive.tree import to_json
    from bench.variants.tree_first import ours_client

    via_server = ours_client.build_tree_json(png, args.display)
    direct = to_json(sources.build_tree("ours", png_bytes=png))
    diff = compare(via_server, direct)
    if diff:
        print(f"DIFFERENT: {diff}")
        return 1
    print(f"identical {len(direct['elements'])} elements")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
