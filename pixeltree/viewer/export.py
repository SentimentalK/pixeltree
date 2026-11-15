"""Export episodes from a raw archive as self-contained trace directories.

Each episode becomes ``<out>/<id>/`` with meta.json, steps.jsonl, result.json and ``img/``. Images are
converted to 1280x720 WebP (the same encoding the site uses) and referenced by relative paths. Only the
fields the viewer renders are kept; archive paths, raw transcripts, request logs and stderr captures are
never copied. Episode ids and ``meta.source.kind`` use the public experiment codes (r1 / r3 / r5).
"""

from __future__ import annotations

import json
import os

from PIL import Image

from ..trace import adapters as A
from ..trace.format import META_KEYS, RESULT_KEYS, write_trace

# raw archive kind -> public experiment code
PUBLIC_KIND = {"p125": "r1", "w2": "r3", "w2c": "r5"}

# Where the raw archive keeps each layout (relative to the archive root).
ARCHIVE_DEFAULTS = {
    "w2c": {"root": "p127/w2c", "tasks_file": "p127/w2c/tasks_first24_plus_cal3.txt", "runs": A.DEFAULT_W2C_RUNS},
    "p125": {"tasks_json": "../p125/tasks_v1.json", "final": "p125/final/" + A.JSONL_NAME},
    "w2": {"jsonl": "p127/w2/formal/" + A.JSONL_NAME},
}

IMG_SIZE = (1280, 720)


def public_id(raw_id: str) -> str:
    src, _, rest = raw_id.partition("__")
    if src not in PUBLIC_KIND:
        raise ValueError("unknown source prefix in episode id: %s" % raw_id)
    return "%s__%s" % (PUBLIC_KIND[src], rest)


def read_ids(path: str) -> list[str]:
    with open(path, encoding="utf-8") as f:
        ids = [l.strip() for l in f if l.strip() and not l.lstrip().startswith("#")]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate ids in %s" % path)
    return ids


def plan_ids(archive_root: str, ids: list[str], config: dict | None = None) -> list[dict]:
    """Turn raw episode ids into adapter jobs, in the order of ``ids``."""
    cfg = {k: dict(v) for k, v in ARCHIVE_DEFAULTS.items()}
    for k, v in (config or {}).items():
        if k in cfg:
            cfg[k].update(v)
    by_src: dict[str, list[str]] = {}
    for i in ids:
        parts = i.split("__")
        if len(parts) != 5 or parts[0] not in PUBLIC_KIND:
            raise ValueError("not a raw episode id: %s" % i)
        by_src.setdefault(parts[0], []).append(i)
    jobs: dict[str, dict] = {}
    if "w2c" in by_src:
        c = cfg["w2c"]
        for j in A.plan_w2c(archive_root, os.path.join(archive_root, c["tasks_file"]), c.get("runs"), c.get("root", "")):
            jobs[A.job_id(j)] = j
    for src, plan in (("p125", A.plan_p125), ("w2", A.plan_w2)):
        if src not in by_src:
            continue
        names = ["__".join(i.split("__")[2:]) for i in by_src[src]]
        tj = os.path.normpath(os.path.join(archive_root, cfg["p125"]["tasks_json"]))
        if src == "p125":
            got = plan(archive_root, names, tj, cfg["p125"]["final"])
        else:
            got = plan(archive_root, names, tj, cfg["w2"]["jsonl"])
        for j in got:
            jobs[A.job_id(j)] = j
    out = []
    for i in ids:
        if i not in jobs:
            raise KeyError("episode not found in the archive: %s" % i)
        out.append(jobs[i])
    return out


def _save_webp(src: str, dst: str, quality: int) -> None:
    im = Image.open(src).convert("RGB")
    if im.size != IMG_SIZE:
        im = im.resize(IMG_SIZE, Image.LANCZOS)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    im.save(dst, "WEBP", quality=quality, method=4)


def _clean_meta(meta: dict, new_id: str, kind: str) -> dict:
    m = {k: meta[k] for k in META_KEYS if k in meta}
    m["id"] = new_id
    m["source"] = {"kind": kind}
    m["task"] = {k: meta["task"].get(k) for k in ("id", "app", "sentence", "difficulty")}
    m["model"] = {"key": meta["model"]["key"], "name": meta["model"]["name"]}
    m.pop("started_at", None)
    return m


def export_trace(trace: dict, out_dir: str, quality: int = 80) -> str:
    """Write one episode (as built by the adapters) under ``out_dir``. Returns the new episode id."""
    raw_kind = trace["meta"]["source"]["kind"]
    kind = PUBLIC_KIND[raw_kind]
    new_id = public_id(trace["meta"]["id"])
    d = os.path.join(out_dir, new_id)
    meta = _clean_meta(trace["meta"], new_id, kind)
    steps = []
    for s in trace["steps"]:
        nn = "%02d" % s["i"]
        screen = None
        if s.get("screen") and os.path.exists(s["screen"]):
            _save_webp(s["screen"], os.path.join(d, "img", nn + ".webp"), quality)
            screen = "img/%s.webp" % nn
        a_img = s["observation"].get("image")
        obs_image = None
        if a_img and os.path.exists(a_img):
            _save_webp(a_img, os.path.join(d, "img", nn + "_a.webp"), quality)
            obs_image = "img/%s_a.webp" % nn
        tree = None
        if s.get("tree"):
            tree = {"source": s["tree"].get("source"),
                    "elements": [{k: e.get(k) for k in ("id", "role", "name", "box")} for e in s["tree"]["elements"]]}
        steps.append({
            "i": s["i"], "t_start": None, "t_end": None, "duration_s": s.get("duration_s"),
            "action": s["action"],
            "agent": s["agent"],
            "observation": {"text": s["observation"].get("text") or "", "image": obs_image},
            "screen": screen, "tree": tree,
        })
    result = {k: trace["result"].get(k) for k in RESULT_KEYS}
    write_trace(d, meta, steps, result)
    return new_id


def run_export(archive_root: str, ids_file: str, out: str, config_path: str | None = None,
               quality: int = 80, log=print) -> list[str]:
    cfg = None
    if config_path:
        with open(config_path, encoding="utf-8") as f:
            cfg = json.load(f)
    ids = read_ids(ids_file)
    jobs = plan_ids(archive_root, ids, cfg)
    done = []
    for j in jobs:
        t = A.build_trace(j)
        t.pop("_align", None)
        nid = export_trace(t, out, quality)
        log("exported %s (%d steps)" % (nid, len(t["steps"])))
        done.append(nid)
    return done
