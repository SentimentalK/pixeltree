"""Modal GPU training app (training recipe: recipe.RECIPE).

    modal run --detach train_app.py --run-name probe_a100 --train-list /vol/lists/probe.txt --epochs 1
    modal run --detach train_app.py --run-name exp_a100 --train-list /vol/lists/train.txt --epochs 11 --gpu H100
    modal run train_app.py --run-name exp_base --train-list /vol/lists/train.txt --prewarm-only   # CPU label-cache prewarm
    modal run --detach train_app.py --run-name probe_stage --train-list /vol/lists/probe.txt --epochs 1 --stage-local
    modal run train_app.py --run-name stage_test --train-list /vol/lists/train_b.txt --stage-only --limit 20000   # copy timing only
    modal run --detach train_app.py --run-name exp_s --train-list /vol/lists/train_s.txt --epochs 11 --stage-local --weights yolo11s.pt

--weights NAME (default yolo11n.pt = behaviour unchanged): pretrained checkpoint /vol/weights/NAME for a fresh start (resume
uses last.pt). The file must be on the Volume beforehand (`modal volume put pixeltree-data <local>.pt /weights/NAME`; yolo11s.pt was
uploaded once from the COCO weight yolo11s.pt). Nothing is downloaded in the container. Only the model changes, RECIPE does not.

--stage-local (default off, behaviour unchanged without it): at GPU function start copy every train image + its label
(images/X -> labels/X.txt) and /vol/val/{images,labels} with 64 threads to the container disk /tmp/stage/<path after /vol/>,
write a local list /tmp/stage/lists/<run>.txt + data.yaml (val local) and train from those (RECIPE untouched). No Volume
reads during training; outputs still go to /vol/runs/<run_name>. Resume stages again and passes the local yaml via
model.train(resume=True, data=...) (ultralytics overwrites ckpt_args["data"] with it). labels.cache is scanned on local disk.

Only workers (default 8, recipe has 6) and device differ from RECIPE; imgsz 1280 / batch 4 / AdamW /
augmentation etc. come from recipe.py unchanged. Data: Volume pixeltree-data (v2, mounted at /vol),
val = /vol/val/images. Output: /vol/runs/<run_name> (save_period=1, Volume committed after every
epoch save). Restartable: with weights/last.pt and no DONE file the run resumes; DONE -> no-op.
Besides the ultralytics files the run dir gets timing.json (epoch train/val seconds, it/s) and
gpu_util.csv (nvidia-smi every 5 s). Fetch results from the Volume with `modal volume get`.
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import modal

HERE = Path(__file__).parent.resolve()
ULTRALYTICS = "8.4.182"  # pinned version of the ultralytics package used for training
TORCH_INDEX = "https://download.pytorch.org/whl/cu128"

app = modal.App(os.environ.get("PIXELTREE_APP_NAME", "pixeltree-train"))  # deployed copy: PIXELTREE_APP_NAME=pixeltree-train (see README)
vol = modal.Volume.from_name("pixeltree-data", create_if_missing=True, version=2)

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("libgl1", "libglib2.0-0")
    .pip_install("torch==2.14.1", "torchvision==0.29.1", extra_index_url=TORCH_INDEX)
    .pip_install(f"ultralytics=={ULTRALYTICS}")
    .add_local_file(str(HERE / "recipe.py"), "/app/recipe.py")
    .add_local_file(str(HERE.parent / "cls_mask.py"), "/app/cls_mask.py")
)

# names / nc copied from runs/114_data/base_v16.yaml
NAMES = ["aria:button", "aria:link", "aria:menuitem", "aria:tab", "aria:checkbox", "aria:radio",
         "aria:textbox", "aria:combobox", "aria:slider", "aria:progressbar", "aria:gridcell",
         "aria:listitem", "aria:heading", "aria:img", "vax:visibleText", "other:visible"]


def _gpu_logger(path, stop):
    with open(path, "a") as f:
        while not stop.is_set():
            try:
                out = subprocess.run(
                    ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=10).stdout.strip()
                f.write(f"{time.time():.0f},{out}\n")
                f.flush()
            except Exception:
                pass
            stop.wait(5)


def _ensure_yaml(run_name: str, train_list: str) -> Path:
    data_yaml = Path("/vol/yaml") / f"{run_name}.yaml"
    data_yaml.parent.mkdir(parents=True, exist_ok=True)
    if not data_yaml.exists():
        lines = [f"train: {train_list}", "val: /vol/val/images", "nc: 16", "names:"]
        lines += [f'  - "{n}"' for n in NAMES]
        data_yaml.write_text("\n".join(lines) + "\n")
    return data_yaml


STAGE = Path("/tmp/stage")
STAGE_THREADS = 64


def _label_of(img: str) -> str:
    head, _, tail = img.rpartition("/images/")
    return f"{head}/labels/{tail.rsplit('.', 1)[0]}.txt"


def _copy_one(src: str, dst: str, must_exist: bool):
    """Copy via temp name + rename; 3 tries. Returns (bytes, 'ok'|'missing'); raises after the last failed try."""
    if os.path.exists(dst):
        return os.path.getsize(dst), "ok"
    err = None
    for attempt in range(3):
        try:
            tmp = dst + ".part"
            shutil.copyfile(src, tmp)
            os.replace(tmp, dst)
            return os.path.getsize(dst), "ok"
        except FileNotFoundError as e:
            if not must_exist and not os.path.exists(src):  # label without file = background image (ultralytics does the same)
                return 0, "missing"
            err = e
        except Exception as e:
            err = e
        time.sleep(1 + attempt)
    raise RuntimeError(f"copy failed after 3 tries: {src}: {err!r}")


def _copy_all(pairs, tag: str):
    """pairs: [(src, dst, must_exist)]. Parallel copy with progress; any file failing 3 tries aborts the run."""
    for d in {os.path.dirname(dst) for _, dst, _ in pairs}:
        os.makedirs(d, exist_ok=True)
    t0 = time.time()
    done = nbytes = missing = 0
    failed = []
    with ThreadPoolExecutor(STAGE_THREADS) as ex:
        futs = [ex.submit(_copy_one, *p) for p in pairs]
        last = t0
        for f, p in zip(futs, pairs):
            try:
                b, st = f.result()
                nbytes += b
                missing += st == "missing"
            except Exception as e:
                failed.append((p[0], repr(e)))
            done += 1
            if time.time() - last > 15:
                last = time.time()
                print(f"stage {tag}: {done}/{len(pairs)} files {nbytes / 1e9:.2f} GB {done / (last - t0):.0f} files/s", flush=True)
    secs = time.time() - t0
    out = {"files": len(pairs), "seconds": round(secs, 1), "bytes": nbytes, "gb": round(nbytes / 1e9, 2),
           "files_per_s": round(len(pairs) / max(secs, 1e-9), 1), "mb_per_s": round(nbytes / 1e6 / max(secs, 1e-9), 1),
           "no_label": missing, "failed": len(failed)}
    print(f"stage {tag}: {out}", flush=True)
    if failed:
        print("stage failures (first 10):", failed[:10], flush=True)
        raise RuntimeError(f"stage {tag}: {len(failed)} files failed after 3 tries")
    return out


def _stage(run_name: str, train_list: str, limit: int = 0, with_val: bool = True, val_dir: str = "/vol/val"):
    """Copy train images/labels (+ val) to /tmp/stage; returns (local yaml path, stats)."""
    lines = [ln.strip() for ln in Path(train_list).read_text().splitlines() if ln.strip()]
    if limit:
        lines = lines[:limit]
    imgs = list(dict.fromkeys(lines))  # copy each file once; the local list keeps repeats (ft104 is listed 8x on purpose)
    rel = lambda p: STAGE / p.removeprefix("/vol/")
    pairs = []
    for im in imgs:
        assert im.startswith("/vol/") and "/images/" in im, im
        pairs.append((im, str(rel(im)), True))
        lb = _label_of(im)
        pairs.append((lb, str(rel(lb)), False))
    stats = {"train_lines": len(lines), "train_unique": len(imgs), "train": _copy_all(pairs, "train")}
    local_list = STAGE / "lists" / f"{run_name}.txt"
    local_list.parent.mkdir(parents=True, exist_ok=True)
    local_list.write_text("\n".join(str(rel(i)) for i in lines) + "\n")
    if with_val:
        vp = []
        for sub in ("images", "labels"):
            for e in os.scandir(f"{val_dir}/{sub}"):
                if e.is_file():
                    vp.append((e.path, str(rel(e.path)), sub == "images"))
        stats["val"] = _copy_all(vp, "val")
    yaml_path = STAGE / "yaml" / f"{run_name}.yaml"
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"train: {local_list}", f"val: {rel(val_dir + '/images')}", "nc: 16", "names:"]
    lines += [f'  - "{n}"' for n in NAMES]
    yaml_path.write_text("\n".join(lines) + "\n")
    du = shutil.disk_usage(str(STAGE))
    stats["disk_free_gb"] = round(du.free / 1e9, 1)
    print(f"stage done: {stats}", flush=True)
    return yaml_path, stats


def _train(run_name: str, train_list: str, epochs: int, workers: int, stage_local: bool = False,
           weights: str = "yolo11n.pt", val_dir: str = "", overrides: str = "", cls_mask: bool = False):
    """val_dir (stage_local only): Volume dir with images/ + labels/ used as val instead of /vol/val.
    overrides: JSON object merged over recipe.RECIPE for a fresh start (e.g. batch, close_mosaic).
    cls_mask: label rows with class id == 16 train box/DFL only (cls_mask.py)."""
    sys.path.insert(0, "/app")
    from recipe import RECIPE
    from ultralytics import YOLO

    vol.reload()
    run_dir = Path("/vol/runs") / run_name
    if (run_dir / "DONE").exists():
        print(f"{run_name}: DONE exists, nothing to do", flush=True)
        return {"run": run_name, "done": True}
    run_dir.mkdir(parents=True, exist_ok=True)
    last = run_dir / "weights" / "last.pt"

    stage_stats = None
    if stage_local:
        data_yaml, stage_stats = _stage(run_name, train_list, val_dir=val_dir or "/vol/val")
        (run_dir / "stage.json").write_text(json.dumps(stage_stats, indent=1))
    else:
        data_yaml = _ensure_yaml(run_name, train_list)

    timing = {"epochs": [], "overrides": json.loads(overrides) if overrides else {}, "cls_mask": bool(cls_mask),
              "val_dir": val_dir or "/vol/val"}
    if cls_mask:
        import cls_mask as _cm
        _cm.patch_dataset()
    if stage_stats:
        timing["stage"] = stage_stats
    cur = {}

    def on_epoch_start(tr):
        cur["t0"] = time.time()

    def on_train_epoch_end(tr):
        cur["train_s"] = time.time() - cur["t0"]
        cur["images"] = len(tr.train_loader.dataset)
        cur["iters"] = len(tr.train_loader)
        cur["t1"] = time.time()

    def on_fit_epoch_end(tr):
        timing["epochs"].append({
            "epoch": tr.epoch + 1, "train_s": round(cur["train_s"], 1), "val_s": round(time.time() - cur["t1"], 1),
            "images": cur["images"], "iters": cur["iters"],
            "it_per_s": round(cur["iters"] / cur["train_s"], 3), "img_per_s": round(cur["images"] / cur["train_s"], 2),
            "epoch_time_s": round(float(tr.epoch_time), 1) if tr.epoch_time is not None else None,
            "metrics": {k: float(v) for k, v in tr.metrics.items() if "mAP" in k}})
        (run_dir / "timing.json").write_text(json.dumps(timing, indent=1))

    def on_model_save(tr):
        vol.commit()

    stop = threading.Event()
    logger = threading.Thread(target=_gpu_logger, args=(str(run_dir / "gpu_util.csv"), stop), daemon=True)
    logger.start()
    t0 = time.time()
    try:
        print("cpu_count", os.cpu_count(), flush=True)
        if last.exists():
            print(f"{run_name}: resume {last}", flush=True)
            model = YOLO(str(last))
            for ev, fn in (("on_train_epoch_start", on_epoch_start), ("on_train_epoch_end", on_train_epoch_end),
                           ("on_fit_epoch_end", on_fit_epoch_end), ("on_model_save", on_model_save)):
                model.add_callback(ev, fn)
            if cls_mask:
                model.add_callback("on_train_start", _cm.make_callback())
            if stage_local:  # last.pt stores the Volume yaml; train(resume=True, data=...) makes ultralytics overwrite it
                model.train(resume=True, data=str(data_yaml))
            else:
                model.train(resume=True)
        else:
            model = YOLO(f"/vol/weights/{weights}")
            for ev, fn in (("on_train_epoch_start", on_epoch_start), ("on_train_epoch_end", on_train_epoch_end),
                           ("on_fit_epoch_end", on_fit_epoch_end), ("on_model_save", on_model_save)):
                model.add_callback(ev, fn)
            if cls_mask:
                model.add_callback("on_train_start", _cm.make_callback())
            kw = dict(RECIPE)
            if overrides:
                kw.update(json.loads(overrides))
            kw.update(data=str(data_yaml), epochs=int(epochs), project="/vol/runs", name=run_name,
                      save_period=1, exist_ok=True, workers=int(workers), device=0)
            model.train(**kw)
    finally:  # a failed attempt must close gpu_util.csv, else the retry's vol.reload() raises "open files"
        stop.set()
        logger.join(timeout=10)
    secs = time.time() - t0
    (run_dir / "DONE").write_text(f"seconds: {secs:.1f}\n")
    vol.commit()
    return {"run": run_name, "done": True, "seconds": round(secs, 1)}


# per-attempt timeout; deploys with PIXELTREE_TIMEOUT_S=14400 (4 h cap per function)
_FN = dict(image=image, volumes={"/vol": vol}, timeout=int(os.environ.get("PIXELTREE_TIMEOUT_S", "86400")),
           retries=modal.Retries(max_retries=5, initial_delay=10.0, backoff_coefficient=1.0))


@app.function(gpu="A100-40GB", **_FN)
def train_a100(run_name: str, train_list: str, epochs: int, workers: int = 8, weights: str = "yolo11n.pt"):
    return _train(run_name, train_list, epochs, workers, weights=weights)


@app.function(gpu="H100", **_FN)
def train_h100(run_name: str, train_list: str, epochs: int, workers: int = 8, weights: str = "yolo11n.pt"):
    return _train(run_name, train_list, epochs, workers, weights=weights)


_STAGE_FN = dict(_FN, ephemeral_disk=512 * 1024)  # MiB; Modal minimum is 512 GiB (100 is rejected), data needs about 20-25 GB


@app.function(gpu="A100-40GB", **_STAGE_FN)
def train_a100_stage(run_name: str, train_list: str, epochs: int, workers: int = 8, weights: str = "yolo11n.pt",
                     val_dir: str = "", overrides: str = "", cls_mask: bool = False):
    return _train(run_name, train_list, epochs, workers, stage_local=True, weights=weights, val_dir=val_dir,
                  overrides=overrides, cls_mask=cls_mask)


@app.function(gpu="H100", **_STAGE_FN)
def train_h100_stage(run_name: str, train_list: str, epochs: int, workers: int = 8, weights: str = "yolo11n.pt",
                     val_dir: str = "", overrides: str = "", cls_mask: bool = False):
    return _train(run_name, train_list, epochs, workers, stage_local=True, weights=weights, val_dir=val_dir,
                  overrides=overrides, cls_mask=cls_mask)


@app.function(cpu=4, memory=8192, timeout=3600, image=image, volumes={"/vol": vol})
def vol_copy(pairs_json: str):
    """Copy files inside the Volume. pairs_json is the Volume path of a JSON list [[src, dst], ...] (both under /vol/).

    Images that are already on the Volume are copied server side, not uploaded again."""
    vol.reload()
    pairs = json.loads(Path(pairs_json).read_text())
    t0 = time.time()
    out = _copy_all([(src, dst, True) for src, dst in pairs], "vol_copy")
    vol.commit()
    out["pairs"] = len(pairs)
    out["seconds_total"] = round(time.time() - t0, 1)
    return out


@app.function(cpu=4, memory=8192, timeout=3600, image=image, volumes={"/vol": vol})
def untar(tar_path: str, dest: str):
    """Extract a tar already on the Volume (e.g. /vol/tars/data.tar) into dest (e.g. /vol/new/data), then commit.

    Many-file uploads can stall from a laptop; one large tar file does not."""
    import tarfile
    vol.reload()
    t0 = time.time()
    os.makedirs(dest, exist_ok=True)
    with tarfile.open(tar_path) as tf:
        names = tf.getnames()
        tf.extractall(dest, filter="data")
    vol.commit()
    counts = {}
    for d, _, files in os.walk(dest):
        counts[d.removeprefix(dest).lstrip("/") or "."] = len(files)
    return {"tar": tar_path, "dest": dest, "members": len(names), "seconds": round(time.time() - t0, 1), "files_per_dir": counts}


@app.function(cpu=8, memory=16384, timeout=4 * 3600, image=image, volumes={"/vol": vol},
              ephemeral_disk=512 * 1024)
def stage_copy(run_name: str, train_list: str, limit: int, with_val: bool):
    """Copy-timing only: stage the first `limit` list lines (+ val) to the container disk, no training."""
    vol.reload()
    t0 = time.time()
    _, stats = _stage(run_name, train_list, limit, with_val)
    stats["total_s"] = round(time.time() - t0, 1)
    return stats


@app.function(cpu=8, memory=16384, timeout=4 * 3600, image=image, volumes={"/vol": vol})
def prewarm(run_name: str, train_list: str):
    """CPU only: build the train and val datasets once so labels.cache lands on the Volume before the GPU run.

    Same ultralytics version, same yaml and same dataset builder as the trainer, so the cache hash (label and image
    file sizes) matches and the training log shows "Scanning <cache>... N images" instead of a fresh scan.
    Cache location = parent dir of the first sorted label file + ".cache" (train: /vol/train/labels.cache,
    val: /vol/val/labels.cache).
    """
    sys.path.insert(0, "/app")
    from recipe import RECIPE
    from ultralytics.cfg import get_cfg
    from ultralytics.data.build import build_yolo_dataset
    from ultralytics.data.utils import check_det_dataset

    vol.reload()
    data_yaml = _ensure_yaml(run_name, train_list)
    vol.commit()
    cfg = get_cfg(overrides=dict(RECIPE, data=str(data_yaml), model="yolo11n.pt"))
    data = check_det_dataset(str(data_yaml))
    out = {}
    for mode, key in (("train", "train"), ("val", "val")):
        t0 = time.time()
        ds = build_yolo_dataset(cfg, data[key], 4 if mode == "train" else 8, data, mode=mode, rect=mode == "val", stride=32)
        out[mode] = {"images": len(ds), "seconds": round(time.time() - t0, 1),
                     "cache": str(Path(ds.label_files[0]).parent.with_suffix(".cache"))}
        print(mode, out[mode], flush=True)
        vol.commit()
    return out


@app.local_entrypoint()
def main(run_name: str, train_list: str, epochs: int = 11, workers: int = 8, gpu: str = "A100", prewarm_only: bool = False,
         stage_local: bool = False, stage_only: bool = False, limit: int = 0, stage_val: bool = True, weights: str = "yolo11n.pt"):
    if stage_only:  # CPU: copy timing, no training
        print(stage_copy.remote(run_name, train_list, limit, stage_val), flush=True)
        return
    if prewarm_only:  # CPU: build labels.cache on the Volume, no GPU
        print(prewarm.remote(run_name, train_list), flush=True)
        return
    fns = {"A100": train_a100, "H100": train_h100}
    if stage_local:
        fns = {"A100": train_a100_stage, "H100": train_h100_stage}
    fn = fns[gpu.upper()]
    print(f"{run_name}: {gpu} train_list={train_list} epochs={epochs} workers={workers} stage_local={stage_local} weights={weights}", flush=True)
    print(fn.remote(run_name, train_list, epochs, workers, weights), flush=True)

