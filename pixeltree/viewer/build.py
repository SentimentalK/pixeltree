"""Generate the offline static replay site. Building the same input twice gives byte-identical output.

Two input modes:
  * a directory of traces (``build --traces DIR``): every subdirectory is one ``pixeltree.trace/1`` episode;
  * a raw archive plus a runs config (``build --config C --archive-root R``), read through the adapters.
"""

from __future__ import annotations

import html
import json
import os
import shutil
import sys
import time
from multiprocessing import Pool

from PIL import Image, ImageChops

from ..trace import adapters as A
from ..trace.format import FORMAT, read_trace, resolve_path, write_trace
from ..trace.treediff import element_at, tree_diff
from . import hints as H
from . import markdown

ASSETS = os.path.join(os.path.dirname(__file__), "assets")

CONCEPTS = [
    ("Tree", "The text list of \u201cwhat is on screen\u201d that the agent reads: one element per line with its role (button, text box, \u2026), name and position."),
    ("Episode", "One model doing one task in one app, from start to finish (at most 20 steps)."),
    ("Step", "One tool call by the agent (observe / click / type / key / scroll / done; some experiments also hover / look)."),
    ("Grading", "After the task ends and the app is closed, a program reads the state the app actually saved to disk and decides success or failure. No human or AI judge is involved."),
]
STOP_TEXT = H.STOP_TEXT
STOP_SHORT = {"done": "done", "step_limit": "20 steps", "timeout": "timeout", "no_done": "no done",
              "fail_answer": "gave up"}
COND_ORDER = ["S_shot", "S_shot_strong", "S_shot_lean", "T_ours", "H_ours", "T_atspi", "H_atspi",
              "T_omni", "X1", "X2", "X2_lean"]
MODEL_ORDER = ["glm", "deepseek", "longcat", "haiku", "sonnet"]
# Public experiment codes for the source kinds (raw-archive kinds and exported kinds).
SOURCE_LABEL = {"w2c": "R5", "p125": "R1", "w2": "R3", "r5": "R5", "r1": "R1", "r3": "R3"}


def esc(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def embed(obj) -> str:
    return dumps(obj).replace("</", "<\\/")



# ------------------------------------------------------------------ images

def _encode(job):
    src, outs = job
    try:
        smt = os.path.getmtime(src)
    except OSError:
        return 0
    todo = [o for o in outs if not (os.path.exists(o[0]) and os.path.getmtime(o[0]) >= smt)]
    if not todo:
        return 0
    im = Image.open(src)
    for dst, size, q in todo:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if im.format == "WEBP" and im.size == size:
            # already in the site encoding (e.g. an exported trace): copy instead of re-compressing
            tmp = dst + ".tmp.webp"
            shutil.copyfile(src, tmp)
            os.replace(tmp, dst)
            continue
        r = im.convert("RGB")
        r = r if r.size == size else r.resize(size, Image.LANCZOS)
        tmp = dst + ".tmp.webp"
        r.save(tmp, "WEBP", quality=q, method=4)
        os.replace(tmp, dst)
    return len(todo)


def image_jobs(traces: list[dict], out: str) -> list[tuple]:
    jobs = []
    for t in traces:
        tid = t["meta"]["id"]
        d = os.path.join(out, "img", tid)
        for s in t["steps"]:
            nn = "%02d" % s["i"]
            if s.get("screen") and os.path.exists(s["screen"]):
                jobs.append((s["screen"], [(os.path.join(d, nn + ".webp"), (1280, 720), 80),
                                           (os.path.join(d, nn + "_t.webp"), (256, 144), 60)]))
            a = s["observation"].get("image")
            if a and os.path.exists(a):
                jobs.append((a, [(os.path.join(d, nn + "_a.webp"), (1280, 720), 80)]))
    return jobs


def thumb_changes(t: dict, out: str) -> list:
    """Mean absolute per-pixel difference (0-255) between the 256x144 grayscale thumbnail after step N
    and the one after step N-1. It is computed from the already generated _t.webp files (so the result
    is stable whether or not they came from the cache); None for step 1 or a missing image."""
    d = os.path.join(out, "img", t["meta"]["id"])
    res = []
    prev = None
    for k, s in enumerate(t["steps"]):
        p = os.path.join(d, "%02d_t.webp" % s["i"])
        cur = None
        if os.path.exists(p):
            with Image.open(p) as im:
                cur = im.convert("L")
                cur.load()
        if k == 0 or cur is None or prev is None:
            res.append(None)
        else:
            hist = ImageChops.difference(cur, prev).histogram()
            res.append(sum(i * c for i, c in enumerate(hist)) / float(sum(hist)))
        prev = cur
    return res


# -------------------------------------------------------------- step labels

def _trunc(s: str, n: int) -> str:
    s = (s or "").replace("\n", " ")
    return s if len(s) <= n else s[:n] + "…"


def _quote(s: str) -> str:
    return "“%s”" % s


def step_label(step: dict, seen_tree: list[dict] | None) -> str:
    a = step["action"]
    tool, args, xy = a["tool"], a.get("args") or {}, a.get("screen_xy")

    def target():
        if xy is None:
            return "(?)"
        e = element_at(seen_tree, xy[0], xy[1]) if seen_tree else None
        if e and (e.get("name") or "").strip():
            return _quote(_trunc(e["name"], 14))
        if e:  # an element was found but it has no name: show its role so the reader sees what was clicked
            return "(%d,%d) · unnamed %s" % (xy[0], xy[1], _role_key(e.get("role")))
        return "(%d,%d)" % (xy[0], xy[1])

    if tool == "click":
        return ("Double-click " if args.get("double") else "Click ") + target()
    if tool == "hover":
        return "Hover " + target()
    if tool == "type":
        return "Type " + _quote(_trunc(args.get("text", ""), 20))
    if tool == "key":
        return "Key %s" % (args.get("name") or args.get("keys") or "")
    if tool == "observe":
        return "Observe"
    if tool == "scroll":
        dy = args.get("dy")
        return "Scroll" + ("" if dy is None else " dy=%s" % dy)
    if tool == "done":
        return "Done"
    if tool == "look":
        return "Look"
    return tool


def _trim(e: dict) -> dict:
    return {"id": e.get("id"), "role": e.get("role"), "name": e.get("name"), "box": e.get("box")}


def _diff_out(d: dict) -> dict:
    return {
        "added": [_trim(e) for e in d["added"]],
        "removed": [_trim(e) for e in d["removed"]],
        "moved": [[_trim(p), _trim(c)] for p, c in d["moved"]],
        "renamed": [[_trim(p), _trim(c)] for p, c in d["renamed"]],
        "same": d["same"],
    }


def _role_key(role: str) -> str:
    for p in ("aria:", "vax:"):
        if (role or "").startswith(p):
            return role[len(p):]
    return role or ""


def view_steps(t: dict, changes: list | None = None) -> list[dict]:
    """Per-step data for the pages (including which step's state the agent was looking at, the label,
    the tree diff and the suspicious-step hints)."""
    steps = t["steps"]
    changes = changes or [None] * len(steps)
    out = []
    seen_prev = -1
    seen_trees = []
    for j, s in enumerate(steps):
        mi = s["agent"].get("message_index")
        first = j == 0 or mi is None or mi != steps[j - 1]["agent"].get("message_index")
        seen = j - 1 if first else seen_prev
        seen_prev = seen
        seen_tree = steps[seen]["tree"]["elements"] if seen >= 0 and steps[seen]["tree"] else None
        seen_trees.append(seen_tree)
        diff = None
        diff_note = None
        if seen >= 0 and seen_tree is not None:
            if not first:
                diff_note = "batched"
            else:
                prev_tree = steps[seen - 1]["tree"]["elements"] if seen >= 1 and steps[seen - 1]["tree"] else None
                if prev_tree is None:
                    diff_note = "first"
                else:
                    diff = _diff_out(tree_diff(prev_tree, seen_tree))
        elif seen >= 0 and not first:
            diff_note = "batched"
        nn = "%02d" % s["i"]
        a = s["action"]
        out.append({
            "i": s["i"], "tool": a["tool"], "args": a.get("args"), "xy": a.get("screen_xy"),
            "ok": a.get("ok"), "error": a.get("error"), "dur": s.get("duration_s"),
            "text": s["agent"].get("text") or "", "thinking": s["agent"].get("thinking") or "",
            "mi": mi, "first": first, "seen": seen,
            "label": step_label(s, seen_tree),
            "obs": s["observation"].get("text") or "",
            "has_a": bool(s["observation"].get("image") and os.path.exists(s["observation"]["image"])),
            "has_screen": bool(s.get("screen") and os.path.exists(s["screen"])),
            "tree": ([_trim(e) for e in s["tree"]["elements"]] if s["tree"] else None),
            "diff": diff, "diff_note": diff_note, "nn": nn,
        })
    hs = H.step_hints(out, seen_trees, changes)
    for v, h in zip(out, hs):
        v["hints"] = h
    return out


# ------------------------------------------------------------------- pages

def page(title: str, body: str, depth: int, nav: dict, data: dict | None = None,
         body_class: str = "") -> str:
    p = "../" * depth
    links = ['<a href="%sindex.html">Home</a>' % p]
    if nav.get("report"):
        links.append('<a href="%sreport.html">Report</a>' % p)
    head = ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>%s</title>" % esc(title)
            + '<link rel="stylesheet" href="%sassets/app.css"></head>' % p)
    top = '<nav class="topnav"><span class="brand">pixeltree replay</span>%s</nav>' % " ".join(links)
    tail = ""
    if data is not None:
        tail = '<script>window.PT = %s;</script>' % embed(data)
    tail += '<script src="%sassets/app.js"></script>' % p
    return "%s<body class=\"%s\">%s<main>%s</main>%s</body></html>\n" % (head, body_class, top, body, tail)


def badge(ok: bool, text: str | None = None) -> str:
    return '<span class="badge %s">%s</span>' % ("ok" if ok else "bad", text or ("✓ Success" if ok else "✗ Failure"))


def concept_html() -> str:
    return "<dl class=\"concepts\">%s</dl>" % "".join(
        "<dt>%s</dt><dd>%s</dd>" % (esc(k), esc(v)) for k, v in CONCEPTS)


def cond_title(c: str) -> str:
    return A.COND_NOTES.get(c, "")


def source_label(kind: str) -> str:
    return SOURCE_LABEL.get(kind, kind)


# ------------------------------------------------------------ matrix layout

def model_group_fn(traces: list[dict]):
    """A model normally is one matrix column group. If the same model was run under more than one
    shell (e.g. Claude Haiku through both ``claude -p`` and OMP), each shell gets its own group."""
    shells: dict[str, set] = {}
    for t in traces:
        shells.setdefault(t["meta"]["model"]["key"], set()).add(t["meta"]["shell"])

    def group(meta: dict) -> tuple[str, str]:
        k = meta["model"]["key"]
        if len(shells[k]) == 1:
            return k, meta["model"]["name"]
        return "%s|%s" % (k, meta["shell"]), "%s · %s" % (meta["model"]["name"], meta["shell"])
    return group


def _cond_pos(c: str) -> int:
    return COND_ORDER.index(c) if c in COND_ORDER else len(COND_ORDER)


def _model_pos(gk: str) -> tuple:
    base = gk.split("|")[0]
    return (MODEL_ORDER.index(base) if base in MODEL_ORDER else len(MODEL_ORDER), gk)


def matrix_layout(traces: list[dict]) -> dict:
    """The index matrix, derived from the traces present: model groups x conditions x tasks.
    A cell shows the lowest-rep episode for (task, model group, condition); any further episodes
    for the same cell go to the "other episodes" list."""
    group = model_group_fn(traces)
    names: dict[str, str] = {}
    conds: dict[str, set] = {}
    cells: dict[tuple, list] = {}
    for t in traces:
        m = t["meta"]
        gk, gname = group(m)
        names[gk] = gname
        conds.setdefault(gk, set()).add(m["condition"]["key"])
        cells.setdefault((m["task"]["id"], gk, m["condition"]["key"]), []).append(t)
    for k in cells:
        cells[k].sort(key=lambda t: (t["meta"]["rep"], t["meta"]["id"]))
    models = sorted(names, key=_model_pos)
    return {
        "group": group, "names": names, "models": models,
        "conds": {g: sorted(conds[g], key=lambda c: (_cond_pos(c), c)) for g in models},
        "cells": cells,
    }


def build_index(layout, traces_by_id, order, task_info, nav) -> str:
    models, names, conds, cells = layout["models"], layout["names"], layout["conds"], layout["cells"]
    cols = [(m, c) for m in models for c in conds[m]]
    shown = {id(v[0]) for v in cells.values()}
    tasks = sorted({k[0] for k in cells}, key=lambda tid: (task_info[tid]["app"], tid))
    apps = sorted({task_info[t]["app"] for t in tasks})
    n_eps = len(traces_by_id)

    intro = ('<section class="intro"><h1>What this is and how to read it</h1>'
             "<p>These are <strong>replays of recorded episodes</strong>. Each cell of the matrix below is one episode "
             "(one model doing one task in one app). "
             "<span class=\"okc\">Green ✓</span> = success, <span class=\"badc\">red ✗</span> = failure; "
             "the small text in a cell is the stop reason: "
             "done = the agent said it was done, 20 steps = it used all 20 steps, timeout = it timed out, "
             "no done = it never said done, gave up = the agent said it could not do the task. "
             "Click a cell to replay the episode; click a task name for the comparison page "
             "(all episodes of that task side by side).</p>"
             + concept_html()
             + '<p class="caveat">Scope: %d episodes over %d tasks, one run per cell. Compare conditions within '
               "the same model; do not compare absolute numbers across models.</p></section>" % (n_eps, len(tasks)))

    # filters
    f = ['<section class="filters"><label>App <select id="f-app"><option value="">All</option>%s</select></label>'
         % "".join('<option value="%s">%s</option>' % (esc(a), esc(a)) for a in apps)]
    f.append('<fieldset><legend>Model</legend>%s</fieldset>' % "".join(
        '<label><input type="checkbox" class="f-model" value="%s" checked> %s</label>'
        % (esc(m), esc(names[m])) for m in models))
    all_conds = []
    for m in models:
        for c in conds[m]:
            if c not in all_conds:
                all_conds.append(c)
    f.append('<fieldset><legend>Condition</legend>%s</fieldset>' % "".join(
        '<label title="%s"><input type="checkbox" class="f-cond" value="%s" checked> %s</label>'
        % (esc(cond_title(c)), esc(c), esc(c)) for c in all_conds))
    f.append('<fieldset><legend>Outcome</legend><label><input type="radio" name="f-ok" value="" checked> All</label>'
             '<label><input type="radio" name="f-ok" value="1"> Successes only</label>'
             '<label><input type="radio" name="f-ok" value="0"> Failures only</label></fieldset></section>')

    # matrix
    h1 = ["<th rowspan=\"2\" class=\"taskcol\">Task</th>"]
    for m in models:
        h1.append('<th colspan="%d" class="mh" data-model="%s">%s</th>' % (len(conds[m]), esc(m), esc(names[m])))
    h2 = []
    for m, c in cols:
        h2.append('<th class="ch" data-model="%s" data-cond="%s" title="%s">%s</th>' % (esc(m), esc(c), esc(cond_title(c)), esc(c)))
    rows = []
    last_app = None
    for tid in tasks:
        app = task_info[tid]["app"]
        if app != last_app:
            rows.append('<tr class="grp" data-app="%s"><th colspan="%d">%s</th></tr>' % (esc(app), len(cols) + 1, esc(app)))
            last_app = app
        tcells = ['<th class="task"><a href="task/%s.html" title="%s">%s</a></th>' % (esc(tid), esc(task_info[tid]["sentence"]), esc(tid))]
        for m, c in cols:
            lst = cells.get((tid, m, c))
            if not lst:
                tcells.append('<td class="cell none" data-model="%s" data-cond="%s">—</td>' % (esc(m), esc(c)))
                continue
            t = lst[0]
            r = t["result"]
            sr = r.get("stop_reason") or ""
            tcells.append(
                '<td class="cell %s" data-model="%s" data-cond="%s" data-ok="%d"><a href="ep/%s.html">'
                '<span class="mark">%s</span><small>%s</small></a></td>'
                % ("ok" if r["ok"] else "bad", esc(m), esc(c), 1 if r["ok"] else 0, esc(t["meta"]["id"]),
                   "✓" if r["ok"] else "✗", esc(STOP_SHORT.get(sr, sr))))
        rows.append('<tr class="trow" data-app="%s">%s</tr>' % (esc(app), "".join(tcells)))
    # count row (initial values; the page script recomputes them when filters change)
    cnt = ['<th class="task">Successes / episodes</th>']
    for m, c in cols:
        ts = [cells[(tid, m, c)][0] for tid in tasks if (tid, m, c) in cells]
        cnt.append('<td class="count" data-model="%s" data-cond="%s">%d/%d</td>'
                   % (esc(m), esc(c), sum(1 for t in ts if t["result"]["ok"]), len(ts)))
    rows.append('<tr class="counts">%s</tr>' % "".join(cnt))
    matrix_html = ('<div class="tablewrap"><table class="matrix" id="matrix"><thead><tr>%s</tr><tr>%s</tr></thead><tbody>%s</tbody></table></div>'
                   % ("".join(h1), "".join(h2), "".join(rows)))

    # episodes that did not get a cell of their own
    others = [traces_by_id[i] for i in order if id(traces_by_id[i]) not in shown]
    orows = []
    for t in others:
        m = t["meta"]
        orows.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>r%s</td><td>%s</td><td><a href=\"ep/%s.html\">Replay</a></td></tr>"
                     % (esc(source_label(m["source"]["kind"])), esc(m["model"]["name"]),
                        esc(m["task"]["id"]), esc(m["condition"]["key"]), esc(m["rep"]),
                        badge(t["result"]["ok"]), esc(m["id"])))
    other_html = ""
    if orows:
        other_html = ('<section><h2>Other episodes</h2><p class="muted">Repeats of a cell already shown above.</p>'
                      '<div class="tablewrap"><table class="list"><thead><tr><th>Source</th><th>Model</th><th>Task</th><th>Condition</th><th>rep</th><th>Result</th><th></th></tr></thead><tbody>%s</tbody></table></div></section>'
                      % "".join(orows))
    return page("pixeltree replay · Home", intro + f[0] + "".join(f[1:]) + matrix_html + other_html, 0, nav,
                {"kind": "index"}, "index")


def build_task_page(tid, tlist, info, nav, views) -> str:
    cols = []
    maxn = max(len(t["steps"]) for t in tlist)
    for t in tlist:
        m = t["meta"]
        cols.append('<th class="tcol"><a href="../ep/%s.html">%s</a><div class="muted">%s · %s · r%s · %s</div>%s</th>'
                    % (esc(m["id"]), esc(m["model"]["name"]), esc(m["condition"]["key"]),
                       esc(source_label(m["source"]["kind"])), esc(m["rep"]), esc(m["shell"]),
                       badge(t["result"]["ok"])))
    body_rows = []
    for k in range(maxn + 1):
        cells = ['<th class="rowh">%s</th>' % ("Result" if k == maxn else "Step %d" % (k + 1))]
        for t in tlist:
            m = t["meta"]
            n = len(t["steps"])
            v = views[m["id"]]
            if k < n:
                s = v[k]
                cls = "tcell fail" if s["ok"] is False else "tcell"
                img = ('<img loading="lazy" width="256" height="144" alt="" src="../img/%s/%s_t.webp">' % (esc(m["id"]), s["nn"])
                       if s["has_screen"] else '<div class="noimg">no screenshot</div>')
                warn = ""
                if s["hints"]:
                    warn = ' <b class="warn" title="%s">⚠</b>' % esc(" ".join("%s: %s" % (h["short"], h["full"]) for h in s["hints"]))
                cells.append('<td class="%s"><a href="../ep/%s.html#s=%d">%s<span>%s%s</span></a></td>'
                             % (cls, esc(m["id"]), s["i"], img, esc(s["label"]), warn))
            elif k == n:
                r = t["result"]
                sr = r.get("stop_reason") or ""
                cells.append('<td class="tcell res %s"><a href="../ep/%s.html#s=%d">%s<br><small>%s</small></a></td>'
                             % ("ok" if r["ok"] else "bad", esc(m["id"]), n,
                                "✓ Success" if r["ok"] else "✗ Failure", esc(STOP_TEXT.get(sr, sr))))
            else:
                cells.append("<td></td>")
        body_rows.append("<tr>%s</tr>" % "".join(cells))
    body = ('<header class="pagehead"><h1>%s</h1><p class="sentence">%s</p><p class="muted">App: %s</p></header>'
            '<p class="hint">Each column is one episode, read top to bottom step by step. Compare the cells of one row across columns to see who took a different path at which step. Click any cell to jump to that step on the episode page.</p>'
            '<div class="tablewrap wide"><table class="cmp"><thead><tr><th></th>%s</tr></thead><tbody>%s</tbody></table></div>'
            % (esc(tid), esc(info["sentence"]), esc(info["app"]), "".join(cols), "".join(body_rows)))
    return page("Comparison · " + tid, body, 1, nav, None, "task")


def build_episode_page(t, nav_ids, task_info, nav, v) -> str:
    m, r = t["meta"], t["result"]
    roles = sorted({_role_key(e["role"]) for s in v if s["tree"] for e in s["tree"]})
    data = {
        "kind": "episode", "id": m["id"],
        "task": m["task"], "model": m["model"], "cond": m["condition"], "shell": m["shell"], "rep": m["rep"],
        "observation": m["observation"], "result": r, "steps": v, "roles": roles,
        "summary": H.summarize(r, len(v), [x["hints"] for x in v]),
        "stop_text": STOP_TEXT.get(r.get("stop_reason") or "", ""),
        "nav": {"task": "../task/%s.html" % m["task"]["id"],
                "prev": nav_ids[0], "next": nav_ids[1]},
        "concepts": CONCEPTS, "img": "../img/%s/" % m["id"],
    }
    return page("Replay · " + m["id"], '<div id="app">Loading…</div>', 1, nav, data, "episode")


# --------------------------------------------------------------------- inputs

def load_trace_dir(root: str, log=print) -> list[dict]:
    """Read every ``<root>/<name>/`` that holds a ``pixeltree.trace/1`` episode. Image paths are resolved
    against the episode directory. Subdirectories without meta.json are ignored; an episode without
    result.json (still running) is skipped with a warning."""
    traces = []
    seen = set()
    for name in sorted(os.listdir(root)):
        d = os.path.join(root, name)
        if not os.path.isfile(os.path.join(d, "meta.json")):
            continue
        t = read_trace(d)
        if t["meta"].get("format") != FORMAT:
            raise ValueError("%s: unsupported trace format %r (expected %s)" % (d, t["meta"].get("format"), FORMAT))
        if t["result"] is None:
            log("warning: %s has no result.json (still running?); skipped" % name)
            continue
        tid = t["meta"]["id"]
        if tid in seen:
            raise ValueError("duplicate episode id: %s" % tid)
        seen.add(tid)
        for s in t["steps"]:
            s["screen"] = resolve_path(d, s.get("screen"))
            s["observation"]["image"] = resolve_path(d, s["observation"].get("image"))
        traces.append(t)
    return traces


def load_archive(config_path: str, archive_root: str, only: str | None = None, jobs: int = 8,
                 log=print) -> list[dict]:
    """Read raw archive episodes through the adapters; ``config_path`` lists which runs to read."""
    with open(config_path, encoding="utf-8") as f:
        cfg = json.load(f)
    plans = []
    if "w2c" in cfg:
        c = cfg["w2c"]
        plans += A.plan_w2c(archive_root, os.path.join(archive_root, c["tasks_file"]),
                            c.get("runs"), c.get("root", ""))
    if "p125" in cfg:
        c = cfg["p125"]
        plans += A.plan_p125(archive_root, c["episodes"], os.path.normpath(os.path.join(archive_root, c["tasks_json"])),
                             c.get("final", "p125/final/" + A.JSONL_NAME))
    if "w2" in cfg:
        c = cfg["w2"]
        tj = c.get("tasks_json") or cfg.get("p125", {}).get("tasks_json")
        plans += A.plan_w2(archive_root, c["episodes"], os.path.normpath(os.path.join(archive_root, tj)),
                           c.get("jsonl", "p127/w2/formal/" + A.JSONL_NAME))
    if only:
        plans = [p for p in plans if A.job_id(p).startswith(only)]
    log("episodes: %d" % len(plans))
    with Pool(jobs) as pool:
        traces = pool.map(A.build_trace, plans, chunksize=4)
    for t in traces:
        t.pop("_align", None)
    return traces


# --------------------------------------------------------------------- driver

def _site_trace(t: dict) -> tuple[dict, list[dict]]:
    """The trace as written under ``<site>/traces/<id>/``: image paths point to the site's own image
    files (relative), and the archive path of the source is dropped."""
    tid = t["meta"]["id"]
    meta = json.loads(json.dumps(t["meta"]))
    meta.get("source", {}).pop("path", None)
    steps = []
    for s in t["steps"]:
        c = json.loads(json.dumps(s))
        nn = "%02d" % s["i"]
        c["screen"] = "../../img/%s/%s.webp" % (tid, nn) if s.get("screen") and os.path.exists(s["screen"]) else None
        a = s["observation"].get("image")
        c["observation"]["image"] = "../../img/%s/%s_a.webp" % (tid, nn) if a and os.path.exists(a) else None
        steps.append(c)
    return meta, steps


def _ordered_ids(traces: list[dict], layout, task_info) -> list[str]:
    group = layout["group"]
    mpos = {g: i for i, g in enumerate(layout["models"])}

    def key(t):
        m = t["meta"]
        return (task_info[m["task"]["id"]]["app"], m["task"]["id"], mpos[group(m)[0]],
                _cond_pos(m["condition"]["key"]), m["condition"]["key"], m["rep"], m["id"])
    return [t["meta"]["id"] for t in sorted(traces, key=key)]


def render_site(traces: list[dict], out: str, report: str | None = None, jobs: int = 8, log=print) -> dict:
    t0 = time.time()
    if not traces:
        raise ValueError("no episodes to build")
    traces_by_id = {t["meta"]["id"]: t for t in traces}

    task_info: dict = {}
    for t in traces:
        tk = t["meta"]["task"]
        task_info.setdefault(tk["id"], {"app": tk.get("app") or "", "sentence": tk.get("sentence") or ""})
        if not task_info[tk["id"]]["sentence"] and tk.get("sentence"):
            task_info[tk["id"]]["sentence"] = tk["sentence"]
    layout = matrix_layout(traces)
    order = _ordered_ids(traces, layout, task_info)

    os.makedirs(out, exist_ok=True)
    os.makedirs(os.path.join(out, "assets"), exist_ok=True)
    for name in ("app.css", "app.js"):
        shutil.copyfile(os.path.join(ASSETS, name), os.path.join(out, "assets", name))

    ij = image_jobs(traces, out)
    log("image jobs: %d" % len(ij))
    with Pool(jobs) as pool:
        done = sum(pool.imap_unordered(_encode, ij, chunksize=16))
    log("newly encoded images: %d (%.0fs)" % (done, time.time() - t0))

    for t in traces:
        meta, steps = _site_trace(t)
        write_trace(os.path.join(out, "traces", t["meta"]["id"]), meta, steps, t["result"])

    have_report = bool(report and os.path.exists(report))
    nav = {"report": have_report}
    if report and not have_report:
        log("note: report file does not exist, skipping report.html: %s" % report)

    def w(path, text):
        p = os.path.join(out, path)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    views = {i_: view_steps(traces_by_id[i_], thumb_changes(traces_by_id[i_], out)) for i_ in order}
    w("index.html", build_index(layout, traces_by_id, order, task_info, nav))
    for i, i_ in enumerate(order):
        prev_id = order[i - 1] if i > 0 else None
        next_id = order[i + 1] if i + 1 < len(order) else None
        w("ep/%s.html" % i_, build_episode_page(traces_by_id[i_], (prev_id, next_id), task_info, nav, views[i_]))
    by_task: dict[str, list] = {}
    for i_ in order:
        by_task.setdefault(traces_by_id[i_]["meta"]["task"]["id"], []).append(traces_by_id[i_])
    for tk, tl in sorted(by_task.items()):
        w("task/%s.html" % tk, build_task_page(tk, tl, task_info[tk], nav, views))
    if have_report:
        with open(report, encoding="utf-8") as f:
            md = f.read()
        w("report.html", page("Report", '<article class="report">%s</article>' % markdown.render(md), 0, nav, None, "report"))
    log("done: %d episodes, %d tasks, %.0fs" % (len(traces), len(by_task), time.time() - t0))
    return {"traces": len(traces), "tasks": len(by_task)}


def run_build_traces(traces_dir: str, out: str, report: str | None = None, jobs: int = 8, log=print) -> dict:
    """Build a site from a directory of ``pixeltree.trace/1`` episodes."""
    return render_site(load_trace_dir(traces_dir, log), out, report, jobs, log)


def run_build(config_path: str, archive_root: str, out: str, report: str | None = None,
              only: str | None = None, jobs: int = 8, log=print) -> dict:
    """Build a site from a raw archive (through the adapters) and a runs config."""
    return render_site(load_archive(config_path, archive_root, only, jobs, log), out, report, jobs, log)
