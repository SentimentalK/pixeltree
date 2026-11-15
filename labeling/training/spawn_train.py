"""Start / inspect / cancel Modal training runs that survive loss of the local client (deployed app + Function.spawn).

    PIXELTREE_APP_NAME=pixeltree-train modal deploy train_app.py          # once, and again after every train_app.py change
    python spawn_train.py start --run-name S50_s --train-list /vol/lists/train_s.txt --epochs 11 --stage-local --weights yolo11s.pt
    python spawn_train.py status --call-id fc-...
    python spawn_train.py cancel --call-id fc-...

`start` returns as soon as Modal has the call id; the client may exit (or lose the network) afterwards. Calls are appended to
spawned_calls.jsonl next to this file (git-ignored; run name, call id, time, args, no credentials). Credentials come from the
usual Modal config, this file never reads them. Run with a Python environment that has the modal package installed.
"""
import argparse
import csv
import json
import sys
import time
from pathlib import Path

import modal

APP = "pixeltree-train"
LOG = Path(__file__).parent / "spawned_calls.jsonl"
VOL = "pixeltree-data"


def fn_name(gpu: str, stage_local: bool) -> str:
    return f"train_{gpu.lower()}{'_stage' if stage_local else ''}"


def cmd_start(a):
    name = fn_name(a.gpu, a.stage_local)
    fn = modal.Function.from_name(APP, name)
    extra = {}
    if a.val_dir or a.overrides or a.cls_mask:
        if not a.stage_local:
            sys.exit("--val-dir / --overrides / --cls-mask need --stage-local (only the *_stage functions take them)")
        json.loads(a.overrides or "{}")  # fail here, not in the container
        extra = dict(val_dir=a.val_dir, overrides=a.overrides, cls_mask=a.cls_mask)
    call = fn.spawn(a.run_name, a.train_list, a.epochs, a.workers, a.weights, **extra)
    rec = {"run_name": a.run_name, "call_id": call.object_id, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "args": {"app": APP, "function": name, "train_list": a.train_list, "epochs": a.epochs, "workers": a.workers,
                    "weights": a.weights, "stage_local": a.stage_local, "gpu": a.gpu.upper(), **extra}}
    with LOG.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    print(json.dumps(rec, indent=1))


def _run_name_of(call_id: str):
    if LOG.exists():
        for ln in reversed(LOG.read_text().splitlines()):
            r = json.loads(ln)
            if r["call_id"] == call_id:
                return r["run_name"]
    return None


def cmd_status(a):
    call = modal.FunctionCall.from_id(a.call_id)
    try:
        res = call.get(timeout=0)
        state = f"done result={res}"
    except TimeoutError:
        state = "running"  # not finished (queued, staging or training)
    except Exception as e:  # the function raised after all retries, or the call was cancelled
        state = f"failed {type(e).__name__}: {e}"
    run = a.run_name or _run_name_of(a.call_id)
    print(f"call {a.call_id}: {state}")
    if run:
        vol = modal.Volume.from_name(VOL)
        for attempt in range(2):  # a read right when the container commits can fail once (seen: bare "Error" at call completion)
            try:
                rows = list(csv.reader(b"".join(vol.read_file(f"runs/{run}/results.csv")).decode().splitlines()))
                n = max(len(rows) - 1, 0)  # minus header
                print(f"run {run}: results.csv epochs={n}" + (f" last={dict(zip(rows[0], rows[-1]))}" if n and a.verbose else ""))
                break
            except Exception as e:
                if attempt:
                    print(f"run {run}: results.csv not readable ({type(e).__name__}: {e})")
                else:
                    time.sleep(3)
        try:
            b"".join(vol.read_file(f"runs/{run}/DONE"))  # read_file is a lazy generator: consume it to raise when missing
            print(f"run {run}: DONE file present")
        except Exception:
            print(f"run {run}: no DONE file")
    else:
        print("run name unknown (call id not in spawned_calls.jsonl); pass --run-name to read results.csv")


def cmd_cancel(a):
    modal.FunctionCall.from_id(a.call_id).cancel()
    print(f"cancel sent for {a.call_id}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("--run-name", required=True)
    s.add_argument("--train-list", required=True, help="path inside the container, e.g. /vol/lists/train_s.txt")
    s.add_argument("--epochs", type=int, default=11)
    s.add_argument("--workers", type=int, default=8)
    s.add_argument("--stage-local", action="store_true")
    s.add_argument("--weights", default="yolo11n.pt")
    s.add_argument("--gpu", default="A100", choices=["A100", "H100", "a100", "h100"])
    s.add_argument("--val-dir", default="", help="Volume dir with images/ + labels/ as val (default /vol/val)")
    s.add_argument("--overrides", default="", help='JSON merged over RECIPE, e.g. \'{"batch": 8, "close_mosaic": 5}\'')
    s.add_argument("--cls-mask", action="store_true", help="class id 16 rows train box only (cls_mask.py)")
    s.set_defaults(f=cmd_start)
    t = sub.add_parser("status")
    t.add_argument("--call-id", required=True)
    t.add_argument("--run-name", help="default: looked up in spawned_calls.jsonl")
    t.add_argument("--verbose", action="store_true")
    t.set_defaults(f=cmd_status)
    c = sub.add_parser("cancel")
    c.add_argument("--call-id", required=True)
    c.set_defaults(f=cmd_cancel)
    a = p.parse_args()
    a.f(a)


if __name__ == "__main__":
    sys.exit(main())
