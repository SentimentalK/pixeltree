"""Upload the non-GroundCUA part of the local training mirror to Volume pixeltree-data (real files, not symlinks).

    python upload.py --what labels|weights|images [--limit N]

Resumable: names already on the Volume are skipped. Files go in batches (one commit each).
Layout: /train/{images,labels}, /val/{images,labels}, /weights/yolo11n.pt.
"""
import argparse
import json
import time

import modal

MANIFEST = "out/modal/local_manifest.json"


def remote_path(x):
    if x["kind"] == "weights":
        return f"/weights/{x['name']}"
    return f"/{x['split']}/{'images' if x['kind'] == 'image' else 'labels'}/{x['name']}"


def existing(vol, d):
    try:
        return {e.path.rsplit("/", 1)[-1] for e in vol.listdir(d)}
    except Exception:
        return set()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--what", required=True, choices=["labels", "weights", "images"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--batch", type=int, default=1000)
    a = ap.parse_args()
    kind = {"labels": "label", "weights": "weights", "images": "image"}[a.what]
    items = [x for x in json.load(open(MANIFEST)) if x["kind"] == kind]
    vol = modal.Volume.from_name("pixeltree-data", create_if_missing=True, version=2)
    have = {}
    todo = []
    for x in items:
        d = remote_path(x).rsplit("/", 1)[0] or "/"
        if d not in have:
            have[d] = existing(vol, d)
        if x["name"] not in have[d]:
            todo.append(x)
    if a.limit:
        todo = todo[: a.limit]
    total = sum(x["size"] for x in todo)
    print(f"{a.what}: {len(todo)} to upload of {len(items)} ({total/2**20:.0f} MiB)", flush=True)
    t0 = time.time()
    done = 0
    for i in range(0, len(todo), a.batch):
        chunk = todo[i : i + a.batch]
        with vol.batch_upload(force=True) as up:
            for x in chunk:
                up.put_file(x["src"], remote_path(x))
        done += sum(x["size"] for x in chunk)
        dt = time.time() - t0
        rate = done / 2**20 / dt
        print(f"{min(i + a.batch, len(todo))}/{len(todo)} {done/2**20:.0f} MiB {rate:.1f} MiB/s "
              f"eta {(total - done) / 2**20 / max(rate, 1e-9) / 60:.0f} min", flush=True)
    print(f"done {len(todo)} files in {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
