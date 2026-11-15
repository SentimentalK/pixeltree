"""Scan the local training mirror and write the upload manifests.

The mirror root is taken from PIXELTREE_MIRROR (default data/mirror); the base weight from PIXELTREE_BASE_WEIGHTS.

Outputs (default out/modal/):
  local_manifest.json  every image/label that is uploaded from this machine
                       [{kind, split, name, src(real file), size}]
  gc_manifest.json     GroundCUA images the cloud downloads from HF
                       [{name, split, hf(path under raw/), size}]
Symlinks are resolved (os.path.realpath): the real file is what gets uploaded/downloaded.
"""
import json
import os
import sys
from pathlib import Path

R = Path(os.environ.get("PIXELTREE_MIRROR", "data/mirror"))
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "out/modal")
WEIGHTS = os.environ.get("PIXELTREE_BASE_WEIGHTS", "weights/yolo11n.pt")
DEST = {"train": "train", "val": "val"}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    local, gc = [], []
    for split in ("train", "val"):
        for n in sorted(os.listdir(R / split / "images")):
            real = os.path.realpath(R / split / "images" / n)
            size = os.path.getsize(real)
            if n.startswith("groundcua__"):
                gc.append({"name": n, "split": DEST[split], "hf": real.split("/groundcua/raw/")[1], "size": size})
            else:
                local.append({"kind": "image", "split": DEST[split], "name": n, "src": real, "size": size})
        for n in sorted(os.listdir(R / split / "labels")):
            real = os.path.realpath(R / split / "labels" / n)
            local.append({"kind": "label", "split": DEST[split], "name": n, "src": real, "size": os.path.getsize(real)})
    local.append({"kind": "weights", "split": "weights", "name": "yolo11n.pt", "src": WEIGHTS, "size": os.path.getsize(WEIGHTS)})
    json.dump(local, open(OUT / "local_manifest.json", "w"))
    json.dump(gc, open(OUT / "gc_manifest.json", "w"))
    li = [x for x in local if x["kind"] == "image"]
    print(f"local images {len(li)} ({sum(x['size'] for x in li)/2**30:.2f} GiB), "
          f"labels {sum(x['kind']=='label' for x in local)}, groundcua {len(gc)} ({sum(x['size'] for x in gc)/2**30:.2f} GiB)")


if __name__ == "__main__":
    main()
