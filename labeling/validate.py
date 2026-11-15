#!/usr/bin/env python3
"""Validate ULF v1 label files. Exit 1 if any record has an error."""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from ulf import DATA_ROOT, read_jsonl, validate_record


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate ULF v1 labels.jsonl files")
    parser.add_argument("files", nargs="+", help="labels.jsonl files")
    parser.add_argument("--data-root", type=str, default=str(DATA_ROOT), help="Directory image paths are relative to")
    parser.add_argument("--no-image-check", action="store_true", help="Skip the image existence and size check")
    args = parser.parse_args()

    total_errors = 0
    for path in args.files:
        records = 0
        boxes = 0
        errors: list[str] = []
        warnings: Counter = Counter()
        try:
            for rec in read_jsonl(path):
                records += 1
                boxes += len(rec.get("boxes") or [])
                errs, warns = validate_record(rec, Path(args.data_root), check_image=not args.no_image_check)
                errors.extend(errs)
                for w in warns:
                    warnings[w.split(": ", 1)[1].split(" ", 1)[0]] += 1
        except json.JSONDecodeError as e:
            errors.append(f"{path}: line {records + 1}: invalid JSON ({e})")

        total_errors += len(errors)
        print(f"== {path}")
        print(f"records={records} boxes={boxes} errors={len(errors)}")
        for e in errors[:20]:
            print(f"  ERROR {e}")
        if len(errors) > 20:
            print(f"  ... {len(errors) - 20} more errors")
        warn_text = ", ".join(f"{k}={v}" for k, v in sorted(warnings.items())) or "none"
        print(f"warnings: {warn_text}")

    return 1 if total_errors else 0


if __name__ == "__main__":
    sys.exit(main())
