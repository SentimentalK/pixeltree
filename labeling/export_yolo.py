#!/usr/bin/env python3
"""Export ULF v1 labels to a YOLO dataset (train / exam split from a held-out groups JSON)."""
import argparse
import json
import math
import shutil
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import cv2

from ulf import CLASS_NAMES, DATA_ROOT, KINDS, read_jsonl, yolo_lines

HERE = Path(__file__).parent
SPLITS = ("train", "exam")
OUT_TARGETS = ("train", "exam", "data.yaml", "stats.json")


def load_holdout(path: Path) -> set[tuple[str, str]]:
    if not path.is_file():
        raise SystemExit(f"exam file not found: {path} (pass --exam)")
    data = json.loads(path.read_text(encoding="utf-8"))
    return {(origin, group) for origin, groups in data["holdout"].items() for group in groups}


def parse_exclude(items: list[str]) -> set[tuple[str, str]]:
    excluded = set()
    for item in items:
        origin, sep, group = item.partition("/")
        if not sep or not origin or not group:
            raise SystemExit(f"--exclude expects ORIGIN/GROUP, got {item!r}")
        excluded.add((origin, group))
    return excluded


def load_val_stems(path: Path) -> set[str]:
    if not path.is_file():
        raise SystemExit(f"--val-ids file not found: {path}")
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def prepare_out(out: Path, overwrite: bool, targets: tuple[str, ...] = OUT_TARGETS) -> None:
    present = [name for name in targets if name not in ("stats.json",) and (out / name).exists()]
    if present and not overwrite:
        raise SystemExit(f"{out} already contains {', '.join(present)}; pass --overwrite to replace them")
    for name in targets:
        target = out / name
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        elif target.exists() or target.is_symlink():
            target.unlink()


def export_image(rec: dict, data_root: Path, img_dir: Path, stem: str) -> tuple[int, int, int, int]:
    src = data_root / rec["image"]
    w, h = rec["width"], rec["height"]
    region = rec["window_region"]
    if list(region) == [0, 0, w, h]:
        dst = img_dir / (stem + src.suffix)
        if dst.is_symlink() or dst.exists():
            dst.unlink()
        dst.symlink_to(src.resolve())
        return 0, 0, w, h

    x1 = max(math.floor(region[0]), 0)
    y1 = max(math.floor(region[1]), 0)
    x2 = min(math.ceil(region[2]), w)
    y2 = min(math.ceil(region[3]), h)
    img = cv2.imread(str(src))
    if img is None:
        raise SystemExit(f"{rec['id']}: cannot read image {src}")
    cv2.imwrite(str(img_dir / (stem + ".png")), img[y1:y2, x1:x2])
    return x1, y1, x2, y2


def main() -> None:
    parser = argparse.ArgumentParser(description="Export ULF v1 labels to YOLO format")
    parser.add_argument("--jsonl", nargs="+", action="extend", required=True, help="labels.jsonl files")
    parser.add_argument("--out", type=str, required=True, help="Output dataset directory")
    parser.add_argument("--classes", type=int, choices=[16, 15], default=16, help="16 keeps other:visible, 15 drops it")
    parser.add_argument("--kinds", type=str, default="leaf,content", help="Comma-separated box kinds to export")
    parser.add_argument("--exam", type=str, default="exam.json", help="Held-out groups JSON (see README)")
    parser.add_argument("--data-root", type=str, default=str(DATA_ROOT), help="Directory image paths are relative to")
    parser.add_argument(
        "--exclude", action="append", default=[], metavar="ORIGIN/GROUP",
        help="Skip every record of this source group (repeatable)",
    )
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Replace train/, exam/, data.yaml and stats.json in --out; other files are kept",
    )
    parser.add_argument(
        "--cls-unknown-origins", type=str, default=None, metavar="ORIGIN[,ORIGIN...]",
        help="Train split only: every exported box of these origins gets class id == --classes (unknown)",
    )
    parser.add_argument(
        "--val-ids", type=str, default=None, metavar="FILE",
        help="File of stems (id with '/' -> '__'), one per line; those records go to a third split val/",
    )
    parser.add_argument(
        "--only-split", choices=["train", "val", "exam"], default=None,
        help="Export only the records of this split; the others are skipped silently",
    )
    args = parser.parse_args()

    started = time.time()
    kinds = set(args.kinds.split(","))
    if not kinds <= KINDS:
        raise SystemExit(f"unknown kinds: {sorted(kinds - KINDS)}")
    holdout = load_holdout(Path(args.exam))
    excluded = parse_exclude(args.exclude)
    data_root = Path(args.data_root)
    out = Path(args.out).absolute()
    names = CLASS_NAMES[: args.classes]
    unknown_origins = (
        {o for o in args.cls_unknown_origins.split(",") if o} if args.cls_unknown_origins else set()
    )
    val_stems = load_val_stems(Path(args.val_ids)) if args.val_ids else None
    if args.only_split == "val" and val_stems is None:
        raise SystemExit("--only-split val needs --val-ids")
    splits = ("train", "val", "exam") if val_stems is not None else ("train", "exam")
    targets = OUT_TARGETS + (("val",) if val_stems is not None else ())
    if args.only_split:
        splits = (args.only_split,)
    prepare_out(out, args.overwrite, targets)

    for split in splits:
        (out / split / "images").mkdir(parents=True, exist_ok=True)
        (out / split / "labels").mkdir(parents=True, exist_ok=True)

    seen: set[str] = set()
    images_by_origin = {s: Counter() for s in splits}
    boxes_by_class = {s: [0] * args.classes for s in splits}
    boxes_by_origin_class = {s: defaultdict(lambda: [0] * args.classes) for s in splits}
    box_drops = defaultdict(Counter)
    image_drops = defaultdict(Counter)
    unknown_by_origin = Counter()
    val_matched = 0
    for path in args.jsonl:
        for rec in read_jsonl(path):
            if rec["id"] in seen:
                raise SystemExit(f"duplicate id: {rec['id']}")
            seen.add(rec["id"])

            origin, group = rec["origin"], rec["group"]
            if (origin, group) in excluded:
                image_drops[origin][f"excluded:{origin}/{group}"] += 1
                continue

            stem = rec["id"].replace("/", "__")
            in_holdout = (origin, group) in holdout
            if val_stems is not None and stem in val_stems:
                if in_holdout:
                    raise SystemExit(f"--val-ids stem {stem} belongs to holdout {origin}/{group}")
                split = "val"
                val_matched += 1
            else:
                split = "exam" if in_holdout else "train"
            if args.only_split and split != args.only_split:
                continue
            crop = export_image(rec, data_root, out / split / "images", stem)
            lines = yolo_lines(rec, crop, classes=args.classes, kinds=kinds, drops=box_drops[origin])
            mask_unknown = split == "train" and origin in unknown_origins
            if mask_unknown:
                lines = [f"{args.classes} {line.split(' ', 1)[1]}" for line in lines]
            (out / split / "labels" / (stem + ".txt")).write_text(
                "".join(line + "\n" for line in lines), encoding="utf-8"
            )
            images_by_origin[split][origin] += 1
            per_origin = boxes_by_origin_class[split][origin]
            for line in lines:
                cls = int(line.split()[0])
                if mask_unknown:
                    unknown_by_origin[origin] += 1
                    continue
                boxes_by_class[split][cls] += 1
                per_origin[cls] += 1

    yaml_lines = [
        f"path: {json.dumps(str(out))}",
        "train: train/images",
        "val: val/images" if val_stems is not None else "val: exam/images",
        f"nc: {args.classes}",
        "names:",
        *[f"  - {json.dumps(name)}" for name in names],
    ]
    if unknown_origins:
        yaml_lines.append(f"cls_unknown: {args.classes}")
    (out / "data.yaml").write_text("\n".join(yaml_lines) + "\n", encoding="utf-8")

    stats = {
        "classes": args.classes,
        "kinds": sorted(kinds),
        "exclude": sorted(f"{origin}/{group}" for origin, group in excluded),
        "exam_file": args.exam,
        "splits": {
            s: {
                "images": sum(images_by_origin[s].values()),
                "images_by_origin": dict(images_by_origin[s]),
                "boxes_by_class": boxes_by_class[s],
                "boxes_by_origin_class": {o: list(v) for o, v in boxes_by_origin_class[s].items()},
            }
            for s in splits
        },
        "box_drops_by_origin": {o: dict(c) for o, c in box_drops.items()},
        "image_drops_by_origin": {o: dict(c) for o, c in image_drops.items()},
        "jsonl": list(args.jsonl),
        "seconds": round(time.time() - started, 1),
    }
    if unknown_origins:
        stats["cls_unknown_origins"] = sorted(unknown_origins)
        stats["boxes_cls_unknown_by_origin"] = dict(unknown_by_origin)
    if val_stems is not None:
        stats["val_ids"] = {"file": args.val_ids, "stems": len(val_stems), "matched_records": val_matched}
    if args.only_split:
        stats["only_split"] = args.only_split
    (out / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    for split in splits:
        print(f"{split}: images={sum(images_by_origin[split].values())} boxes={sum(boxes_by_class[split])}")
        for cls, n in enumerate(boxes_by_class[split]):
            print(f"  {cls:2d} {names[cls]}: {n}")
    print("drops by origin:")
    for origin in sorted(set(box_drops) | set(image_drops)):
        print(f"  {origin}: boxes={dict(box_drops.get(origin, {}))} images={dict(image_drops.get(origin, {}))}")


if __name__ == "__main__":
    sys.exit(main())
