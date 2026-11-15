#!/usr/bin/env python3
"""Batch review page (labelling-convention review) and batch statistics for a gold-label batch.

Inputs (one batch, read-only):
  --manifest   jsonl, one row per image: gid, pool, application, image, width, height
  --labels     jsonl, one row per image: gid, image, width, height, mode, boxes[{cls, box, kind, name, name_source}]
  --overlay-dir  one overlay PNG per image; the file name starts with "<gid>" (first sorted glob match is used)
  --qa-dir     <gid>.json per image: verdict, reason?, n_missing, n_geometry, n_class, n_forbidden, notes[{type, note, ...}]
               (a missing file or a missing verdict is counted as "no verdict")
  --ledger-opus / --ledger-qa   tsv with an api_equiv_usd column (sum of all rows = cost)

Outputs under --out-dir:
  review_batch1.html   single file, CSS/JS inline, images referenced by relative path
  review_img/<gid>.jpg (long edge <= 1600) and review_img/<gid>_t.jpg (long edge <= 360)
  stats_batch1.json, stats_batch1.md

--check runs structural checks on the generated page (html.parser parse, every relative img exists,
no external references, card count == sample count, source-table total == labels rows counted in stats).

Sampling is done by pick_sample(); see its docstring for the allocation rules.
"""
import argparse
import csv
import datetime
import glob
import html
import json
import os
import random
import statistics
import sys
from collections import OrderedDict
from fractions import Fraction
from html.parser import HTMLParser

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from tile_merge import CLASS_NAMES  # noqa: E402  (AST read of ulf.CLASS_NAMES, no numpy/cv2)

VERDICTS = ("ok", "fix", "reject")
TEXT_CLS = CLASS_NAMES.index("vax:visibleText")
BUTTON_CLS = CLASS_NAMES.index("aria:button")
IMG_CLS = CLASS_NAMES.index("aria:img")
GROUPS = [
    ("text_line", "standalone text line"),
    ("button_text", "button with text"),
    ("icon_button", "icon button"),
    ("img", "image / icon (aria:img)"),
    ("other", "other"),
]
GROUP_LABEL = dict(GROUPS)
JPEG_LONG = 1600
THUMB_LONG = 360
JPEG_QUALITY = 85
NOTES_MAX = 8
TOTAL_KEY = "total"


# ----------------------------------------------------------------------------- inputs

def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def read_tsv(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def ledger_sum(path):
    rows = read_tsv(path)
    if rows and "api_equiv_usd" not in rows[0]:
        raise SystemExit(f"{path}: no api_equiv_usd column (columns: {list(rows[0])})")
    return sum(float(r["api_equiv_usd"] or 0) for r in rows), len(rows)


def load_qa(qa_dir, gid):
    if not qa_dir:
        return None
    path = os.path.join(qa_dir, gid + ".json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def find_overlay(overlay_dir, gid):
    hits = sorted(glob.glob(os.path.join(overlay_dir, gid + "*.png")))
    return hits[0] if hits else None


def box_group(box):
    cls = box.get("cls")
    name = (box.get("name") or "").strip()
    if cls == TEXT_CLS:
        return "text_line"
    if cls == BUTTON_CLS:
        return "button_text" if name else "icon_button"
    if cls == IMG_CLS:
        return "img"
    return "other"


# ----------------------------------------------------------------------------- sampling

def _allocate(counts, k, order):
    """Split integer k over keys of counts (sum(counts) >= k) by largest remainder, proportional to counts.
    If k >= sum(counts) everything is taken."""
    total = sum(counts.values())
    if k >= total:
        return {p: counts[p] for p in order}
    if k <= 0 or total == 0:
        return {p: 0 for p in order}
    exact = {p: Fraction(k * counts[p], total) for p in order}
    base = {p: exact[p].numerator // exact[p].denominator for p in order}
    left = k - sum(base.values())
    ranked = sorted(order, key=lambda p: (-(exact[p] - base[p]), order.index(p)))
    for p in ranked[:left]:
        base[p] += 1
    return base


def _round_robin(cands, k, rng):
    """Shuffle cands with rng, then take k rows cycling over applications so neighbours differ."""
    cands = list(cands)
    rng.shuffle(cands)
    buckets = OrderedDict()
    for r in cands:
        buckets.setdefault(str(r.get("application") or ""), []).append(r)
    out = []
    while len(out) < k and any(buckets.values()):
        for b in buckets.values():
            if b and len(out) < k:
                out.append(b.pop(0))
    return out


def pick_sample(rows, n, n_fix, n_reject, seed):
    """Pick review gids. rows: dicts with gid, pool, application, verdict (ok/fix/reject/None).

    Rules:
      * pool share = n * pool_count / total, largest-remainder rounding (100/150/50, n=50 -> 17/25/8).
      * rejects first: at most n_reject in total (all if fewer), split over pools by largest remainder on
        reject counts; a pool never takes more than its share.
      * then fixes: at most n_fix in total (all if fewer), split by largest remainder on fix counts;
        capped by the pool share left after rejects. Rejects and fixes count toward their pool's share.
      * the rest of each pool's share comes from ok / no-verdict rows, shuffled with
        random.Random(f"{seed}:{pool}") and taken round-robin over application.
      * if a pool has too few ok / no-verdict rows (rare, tiny pools), the remaining slots are filled with
        unpicked fix/reject rows of that pool, so the sample size stays n.
    Same seed and same rows give the same result. Returns a sorted list of gids of length min(n, len(rows)).
    """
    rows = list(rows)
    total = len(rows)
    n = min(n, total)
    if n <= 0:
        return []
    pools = sorted({r["pool"] for r in rows})
    by_pool = {p: sorted((r for r in rows if r["pool"] == p), key=lambda r: r["gid"]) for p in pools}
    share = _allocate({p: len(by_pool[p]) for p in pools}, n, pools)

    fix_rows = {p: [r for r in by_pool[p] if r.get("verdict") == "fix"] for p in pools}
    rej_rows = {p: [r for r in by_pool[p] if r.get("verdict") == "reject"] for p in pools}

    rej_n = _allocate({p: len(rej_rows[p]) for p in pools}, min(n_reject, sum(len(v) for v in rej_rows.values())), pools)
    rej_take = {p: min(rej_n[p], share[p]) for p in pools}
    fix_n = _allocate({p: len(fix_rows[p]) for p in pools}, min(n_fix, sum(len(v) for v in fix_rows.values())), pools)
    fix_take = {p: min(fix_n[p], share[p] - rej_take[p]) for p in pools}

    picked = []
    leftovers = {}
    for p in pools:
        rr = list(rej_rows[p])
        random.Random(f"{seed}:reject:{p}").shuffle(rr)
        ff = list(fix_rows[p])
        random.Random(f"{seed}:fix:{p}").shuffle(ff)
        picked += [r["gid"] for r in rr[:rej_take[p]]] + [r["gid"] for r in ff[:fix_take[p]]]
        leftovers[p] = rr[rej_take[p]:] + ff[fix_take[p]:]

        rest = share[p] - rej_take[p] - fix_take[p]
        plain = [r for r in by_pool[p] if r.get("verdict") not in ("fix", "reject")]
        got = _round_robin(plain, rest, random.Random(f"{seed}:{p}"))
        if len(got) < rest:
            extra = [r for r in leftovers[p] if r["gid"] not in {g["gid"] for g in got}]
            got += extra[: rest - len(got)]
        picked += [r["gid"] for r in got]

    if len(picked) != n or len(set(picked)) != n:
        raise RuntimeError(f"pick_sample: got {len(picked)} unique rows for n={n}")
    return sorted(picked)


# ----------------------------------------------------------------------------- statistics

def _summarise(recs):
    boxes = [len(r["boxes"]) for r in recs]
    groups = {g: 0 for g, _ in GROUPS}
    classes = [0] * len(CLASS_NAMES)
    verdicts = {"ok": 0, "fix": 0, "reject": 0, "none": 0}
    for r in recs:
        for b in r["boxes"]:
            groups[box_group(b)] += 1
            cls = b.get("cls")
            if isinstance(cls, int) and 0 <= cls < len(CLASS_NAMES):
                classes[cls] += 1
        verdicts[r["verdict"] or "none"] += 1
    n_boxes = sum(boxes)
    return {
        "n_images": len(recs),
        "boxes_total": n_boxes,
        "boxes_mean": round(statistics.mean(boxes), 2) if boxes else 0,
        "boxes_median": statistics.median(boxes) if boxes else 0,
        "boxes_min": min(boxes) if boxes else 0,
        "boxes_max": max(boxes) if boxes else 0,
        "groups": groups,
        "classes": classes,
        "verdicts": verdicts,
    }


def compute_stats(recs):
    pools = sorted({r["pool"] for r in recs})
    scopes = OrderedDict((p, _summarise([r for r in recs if r["pool"] == p])) for p in pools)
    scopes[TOTAL_KEY] = _summarise(recs)
    return scopes


def build_stats(recs, scopes, costs, sample, title, labels_rows, skipped):
    return {
        "title": title,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "labels_rows": labels_rows,
        "labels_skipped_not_in_manifest": skipped,
        "n_images": len(recs),
        "group_names": {g: GROUP_LABEL[g] for g, _ in GROUPS},
        "class_names": list(CLASS_NAMES),
        "scopes": scopes,
        "costs_usd": costs,
        "sample": sample,
    }


def _pct(n, d):
    return f"{100.0 * n / d:.1f}%" if d else "–"


def stats_md(st):
    scopes = st["scopes"]
    keys = list(scopes)
    out = [f"# {st['title']} — batch statistics", "",
           f"generated {st['generated_at']} · label rows {st['labels_rows']} · images counted {st['n_images']}"
           f" · skipped (not in manifest) {st['labels_skipped_not_in_manifest']}", ""]

    out += ["## Images and boxes per source", "", "| source | images | boxes mean | boxes median | boxes min | boxes max |", "|---|---|---|---|---|---|"]
    for k in keys:
        s = scopes[k]
        out.append(f"| {k} | {s['n_images']} | {s['boxes_mean']} | {s['boxes_median']} | {s['boxes_min']} | {s['boxes_max']} |")
    out += ["", "## Box group distribution (count / share)", "",
            "| group | " + " | ".join(keys) + " |", "|---|" + "---|" * len(keys)]
    for g, label in GROUPS:
        cells = [f"{scopes[k]['groups'][g]} ({_pct(scopes[k]['groups'][g], scopes[k]['boxes_total'])})" for k in keys]
        out.append(f"| {label} | " + " | ".join(cells) + " |")
    out += ["", "## Per-class counts (16 classes)", "", "| class | " + " | ".join(keys) + " |", "|---|" + "---|" * len(keys)]
    for i, name in enumerate(CLASS_NAMES):
        out.append(f"| {i} {name} | " + " | ".join(str(scopes[k]["classes"][i]) for k in keys) + " |")
    out += ["", "## QA verdict distribution", "", "| source | ok | fix | reject | no verdict | total |", "|---|---|---|---|---|---|"]
    for k in keys:
        v = scopes[k]["verdicts"]
        out.append(f"| {k} | {v['ok']} | {v['fix']} | {v['reject']} | {v['none']} | {scopes[k]['n_images']} |")
    c = st["costs_usd"]
    out += ["", "## Cost (API-equivalent, not a bill)", "",
            f"- Opus, API-equivalent total ${c['opus']:.4f} ({c['opus_rows']} rows)",
            f"- QA, API-equivalent total ${c['qa']:.4f} ({c['qa_rows']} calls)",
            f"- Total ${c['total']:.4f}; average per image ${c['per_image']:.4f} ({st['n_images']} images)", ""]
    smp = st["sample"]
    out += ["## Sample", "", f"Sample of {smp['n']} images (reject {smp['n_reject']} / fix {smp['n_fix']})", "",
            "| source | sample | fix | reject |", "|---|---|---|---|"]
    for p, d in smp["by_pool"].items():
        out.append(f"| {p} | {d['n']} | {d['fix']} | {d['reject']} |")
    return "\n".join(out) + "\n"


# ----------------------------------------------------------------------------- images

def write_images(png_path, gid, img_dir):
    full_path = os.path.join(img_dir, gid + ".jpg")
    thumb_path = os.path.join(img_dir, gid + "_t.jpg")
    with Image.open(png_path) as src:
        if src.mode in ("RGBA", "LA") or "transparency" in src.info:
            rgba = src.convert("RGBA")
            im = Image.new("RGB", rgba.size, (255, 255, 255))
            im.paste(rgba, mask=rgba.split()[-1])
        else:
            im = src.convert("RGB")
    w, h = im.size
    scale = min(1.0, JPEG_LONG / max(w, h))
    if scale < 1.0:
        im = im.resize((round(w * scale), round(h * scale)), Image.Resampling.LANCZOS)
    im.save(full_path, "JPEG", quality=JPEG_QUALITY, optimize=True)
    thumb = im.copy()
    thumb.thumbnail((THUMB_LONG, THUMB_LONG), Image.Resampling.LANCZOS)
    thumb.save(thumb_path, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return im.size


# ----------------------------------------------------------------------------- html

CSS = """
:root{--fg:#1d1d1f;--mut:#6e6e73;--bg:#fff;--line:#e5e5ea;--ok:#1f7a3a;--fix:#b26a00;--rej:#b3261e;--none:#6e6e73;--acc:#0a5bd3}
*{box-sizing:border-box}
body{margin:0;padding:16px;font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Noto Sans CJK SC",sans-serif;color:var(--fg);background:var(--bg)}
[hidden]{display:none !important}
h1{font-size:20px;margin:0 0 4px}
h2{font-size:15px;margin:22px 0 8px}
.sub{color:var(--mut);margin:0 0 12px}
.cost{background:#f5f5f7;border-radius:8px;padding:8px 10px;margin:10px 0}
table{border-collapse:collapse;width:100%;font-size:13px;margin-bottom:6px}
th,td{border-bottom:1px solid var(--line);padding:5px 8px;text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left}
tr.total td{font-weight:600;border-top:2px solid var(--line)}
.tables{display:grid;gap:14px}
.wrap{overflow-x:auto}
details{margin-top:8px}
summary{cursor:pointer;color:var(--acc)}
.filters{display:flex;flex-wrap:wrap;gap:6px;margin:14px 0 6px;position:sticky;top:0;background:var(--bg);padding:6px 0;z-index:2}
.filters button{font:inherit;border:1px solid var(--line);background:#fff;border-radius:16px;padding:4px 12px;cursor:pointer}
.filters button[aria-pressed="true"]{background:var(--acc);border-color:var(--acc);color:#fff}
#count{align-self:center;color:var(--mut);margin-left:4px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}
.card{border:1px solid var(--line);border-radius:10px;padding:8px;display:flex;gap:10px;align-items:flex-start;min-width:0}
.thumb{border:0;padding:0;background:#f5f5f7;border-radius:6px;cursor:zoom-in;flex:0 0 120px;overflow:hidden}
.thumb img{display:block;width:120px;height:auto}
.info{min-width:0;flex:1}
.gid{font-weight:600;font-size:12px;word-break:break-all}
.meta{color:var(--mut);font-size:12px;margin:2px 0 4px}
.badge{display:inline-block;font-size:11px;font-weight:600;color:#fff;border-radius:4px;padding:1px 6px}
.b-ok{background:var(--ok)}.b-fix{background:var(--fix)}.b-reject{background:var(--rej)}.b-none{background:var(--none)}
.reason{font-size:12px;margin-top:4px;word-break:break-word}
.lb{position:fixed;inset:0;background:rgba(0,0,0,.85);z-index:10;display:flex;flex-direction:column}
.lb-bar{display:flex;gap:8px;align-items:center;justify-content:flex-end;padding:8px}
.lb-bar button{font:inherit;color:#fff;background:transparent;border:1px solid #888;border-radius:6px;padding:4px 10px;cursor:pointer}
.lb-main{flex:1;display:flex;min-height:0;gap:12px;padding:0 12px 12px;align-items:stretch}
.lb-imgwrap{flex:1 1 auto;min-width:0;overflow:auto;display:flex;align-items:flex-start;justify-content:center;background:#111;border-radius:8px}
.lb-imgwrap img{max-width:100%;height:auto;display:block}
.lb-side{flex:0 0 300px;background:#fff;border-radius:8px;padding:10px 12px;overflow:auto;font-size:13px}
.lb-side p{margin:4px 0}
.lb-side ul{padding-left:18px;margin:4px 0}
.lb-side li{margin-bottom:4px;word-break:break-word}
@media (max-width:760px){
  .lb-main{flex-direction:column}
  .lb-side{flex:0 0 auto;max-height:40vh}
  .grid{grid-template-columns:1fr}
}
"""

JS = r"""
(function(){
  var DATA = __DATA__;
  var cards = Array.prototype.slice.call(document.querySelectorAll('[data-card]'));
  var buttons = Array.prototype.slice.call(document.querySelectorAll('[data-filter-kind]'));
  var counter = document.getElementById('count');
  var lb = document.getElementById('lb');
  var lbImg = document.getElementById('lb-img');
  var lbSide = document.getElementById('lb-side');
  var lbPos = document.getElementById('lb-pos');
  var vis = [];
  var cur = -1;

  function matches(card, kind, value){
    if (kind === 'all') return true;
    if (kind === 'pool') return card.getAttribute('data-pool') === value;
    return card.getAttribute('data-verdict') === value;
  }
  function setFilter(kind, value){
    cards.forEach(function(c){ c.hidden = !matches(c, kind, value); });
    buttons.forEach(function(b){
      b.setAttribute('aria-pressed', String(b.getAttribute('data-filter-kind') === kind && b.getAttribute('data-filter-value') === value));
    });
    vis = cards.filter(function(c){ return !c.hidden; });
    counter.textContent = vis.length + ' / ' + cards.length;
  }
  function el(tag, text){
    var e = document.createElement(tag);
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  }
  function row(label, value){
    var p = el('p');
    p.appendChild(el('strong', label + ': '));
    p.appendChild(document.createTextNode(value));
    return p;
  }
  function show(i){
    if (i < 0 || i >= vis.length) return;
    cur = i;
    var gid = vis[i].getAttribute('data-gid');
    var d = DATA[gid];
    lbImg.src = '__IMGDIR__/' + gid + '.jpg';
    lbImg.alt = gid;
    lbPos.textContent = (i + 1) + ' / ' + vis.length;
    lbSide.textContent = '';
    lbSide.appendChild(row('gid', d.gid));
    lbSide.appendChild(row('pool', d.pool));
    lbSide.appendChild(row('application', d.application));
    lbSide.appendChild(row('boxes', String(d.n_boxes)));
    lbSide.appendChild(row('boxes per group', d.groups.map(function(g){ return g[0] + ' ' + g[1]; }).join(' · ')));
    lbSide.appendChild(row('verdict', d.verdict_label));
    lbSide.appendChild(row('reason', d.reason_display));
    if (d.notes.length) {
      lbSide.appendChild(el('p', 'QA notes:'));
      var ul = el('ul');
      d.notes.forEach(function(n){ ul.appendChild(el('li', '[' + n.type + '] ' + n.note)); });
      lbSide.appendChild(ul);
      if (d.more_notes) lbSide.appendChild(el('p', '… ' + d.more_notes + ' more notes'));
    }
    lb.hidden = false;
    document.getElementById('lb-close').focus();
  }
  function close(){ lb.hidden = true; cur = -1; }
  function step(delta){ if (cur >= 0) show((cur + delta + vis.length) % vis.length); }

  buttons.forEach(function(b){
    b.addEventListener('click', function(){
      setFilter(b.getAttribute('data-filter-kind'), b.getAttribute('data-filter-value'));
    });
  });
  Array.prototype.slice.call(document.querySelectorAll('[data-open]')).forEach(function(b){
    b.addEventListener('click', function(){
      var card = b.closest('[data-card]');
      show(vis.indexOf(card));
    });
  });
  document.getElementById('lb-close').addEventListener('click', close);
  document.getElementById('lb-prev').addEventListener('click', function(){ step(-1); });
  document.getElementById('lb-next').addEventListener('click', function(){ step(1); });
  document.addEventListener('keydown', function(e){
    if (lb.hidden) return;
    if (e.key === 'ArrowLeft') { e.preventDefault(); step(-1); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); step(1); }
    else if (e.key === 'Escape') { close(); }
  });
  setFilter('all', '');
})();
"""


def esc(s):
    return html.escape("" if s is None else str(s), quote=True)


def html_table(headers, rows, total_row=None, total_cell_attr=None, total_cell_index=1):
    """rows: list of lists of already-rendered cell strings (escaped by caller where needed).
    total_cell_attr is put on the cell at total_cell_index of total_row (default: the second cell)."""
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    if total_row is not None:
        cells = []
        for i, c in enumerate(total_row):
            attr = f' data-role="{total_cell_attr}"' if (total_cell_attr and i == total_cell_index) else ""
            cells.append(f"<td{attr}>{c}</td>")
        body += '<tr class="total">' + "".join(cells) + "</tr>"
    return f'<div class="wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def render_html(title, generated_at, st, cards, lb_data, sample_info, cost_line, img_dir="review_img"):
    scopes = st["scopes"]
    keys = list(scopes)
    pools = [k for k in keys if k != TOTAL_KEY]

    src_rows = [[esc(k), str(scopes[k]["n_images"]), str(scopes[k]["boxes_mean"]), str(scopes[k]["boxes_median"]),
                 str(scopes[k]["boxes_min"]), str(scopes[k]["boxes_max"])] for k in pools]
    src_total = [esc(TOTAL_KEY), str(scopes[TOTAL_KEY]["n_images"]), str(scopes[TOTAL_KEY]["boxes_mean"]),
                 str(scopes[TOTAL_KEY]["boxes_median"]), str(scopes[TOTAL_KEY]["boxes_min"]),
                 str(scopes[TOTAL_KEY]["boxes_max"])]
    t_src = html_table(["source", "images", "boxes mean", "boxes median", "boxes min", "boxes max"], src_rows, src_total,
                       total_cell_attr="total-count")

    grp_rows = []
    for g, label in GROUPS:
        cells = [esc(label)]
        for k in keys:
            n = scopes[k]["groups"][g]
            cells.append(f"{n} ({_pct(n, scopes[k]['boxes_total'])})")
        grp_rows.append(cells)
    t_grp = html_table(["group"] + keys, grp_rows)

    v_rows = []
    for k in keys:
        v = scopes[k]["verdicts"]
        v_rows.append([esc(k), str(v["ok"]), str(v["fix"]), str(v["reject"]), str(v["none"]),
                       str(scopes[k]["n_images"])])
    t_ver = html_table(["source", "ok", "fix", "reject", "no verdict", "total"], v_rows)

    cls_rows = []
    for i, name in enumerate(CLASS_NAMES):
        cls_rows.append([esc(f"{i} {name}")] + [str(scopes[k]["classes"][i]) for k in keys])
    t_cls = html_table(["class"] + keys, cls_rows)

    sub_html = (f"generated {esc(generated_at)} · label rows {st['labels_rows']} · images counted {st['n_images']} · "
                f"{smp_line_html(sample_info)}")
    tables_html = (
        '<div class="tables">\n'
        f'<section><h2>Images and mean boxes per source</h2>{t_src}</section>\n'
        f'<section><h2>Box group distribution (count / share)</h2>{t_grp}</section>\n'
        f'<section><h2>QA verdict distribution</h2>{t_ver}</section>\n'
        f'<details><summary>Per-class counts (16 classes)</summary>{t_cls}</details>\n'
        '</div>'
    )
    body_html = ('<h2>Sample cards</h2>\n' + filter_bar_html(pools) + '\n<div class="grid">\n'
                 + ''.join(cards) + '\n</div>')
    return html_page(title, sub_html, cost_line, tables_html, body_html, lb_data, img_dir)


def smp_line_html(smp):
    return (f"Sample of {smp['n']} images: reject {smp['n_reject']} · fix {smp['n_fix']} · "
            + " · ".join(f"{esc(p)} {d['n']}" for p, d in smp["by_pool"].items()))


def filter_bar_html(pools):
    """Filter buttons (all / per pool / per verdict) plus the visible-count span used by JS."""
    filters = ['<button type="button" data-filter-kind="all" data-filter-value="" aria-pressed="true">all</button>']
    for p in pools:
        filters.append(f'<button type="button" data-filter-kind="pool" data-filter-value="{esc(p)}" '
                       f'aria-pressed="false">{esc(p)}</button>')
    for v, label in (("ok", "ok"), ("fix", "fix"), ("reject", "reject")):
        filters.append(f'<button type="button" data-filter-kind="verdict" data-filter-value="{v}" '
                       f'aria-pressed="false">{label}</button>')
    return ('<div class="filters" role="group" aria-label="filter">\n' + ''.join(filters)
            + '\n<span id="count"></span>\n</div>')


def html_page(title, sub_html, cost_html, tables_html, body_html, lb_data, img_dir="review_img"):
    """Page shell shared by review_<name> and review-all: head, summary, tables, cards, lightbox, script.
    sub_html / cost_html are inserted as-is (caller escapes); tables_html and body_html are HTML fragments."""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} — review</title>
<style>{CSS}</style>
</head>
<body>
<h1>{esc(title)}</h1>
<p class="sub">{sub_html}</p>
<p class="cost">{cost_html}</p>

{tables_html}

{body_html}

<div id="lb" class="lb" hidden role="dialog" aria-modal="true" aria-label="enlarged image">
  <div class="lb-bar">
    <span id="lb-pos" style="color:#fff;margin-right:auto"></span>
    <button type="button" id="lb-prev" aria-label="previous">‹ previous</button>
    <button type="button" id="lb-next" aria-label="next">next ›</button>
    <button type="button" id="lb-close" aria-label="close">close (Esc)</button>
  </div>
  <div class="lb-main">
    <div class="lb-imgwrap"><img id="lb-img" alt=""></div>
    <aside class="lb-side" id="lb-side"></aside>
  </div>
</div>
<script>{JS.replace('__DATA__', lb_data).replace('__IMGDIR__', img_dir)}</script>
</body>
</html>
"""


def card_html(i, r, img_dir="review_img"):
    vtag = r["verdict"] or "none"
    vlabel = r["verdict"] or "no verdict"
    app = r["application"] or "–"
    return (
        f'<article class="card" data-card data-gid="{esc(r["gid"])}" data-pool="{esc(r["pool"])}" '
        f'data-verdict="{vtag}">'
        f'<button type="button" class="thumb" data-open="{i}" aria-label="open enlarged image {esc(r["gid"])}">'
        f'<img src="{img_dir}/{esc(r["gid"])}_t.jpg" alt="{esc(r["gid"])}" loading="lazy"></button>'
        f'<div class="info"><div class="gid">{esc(r["gid"])}</div>'
        f'<div class="meta">{esc(r["pool"])} · {esc(app)} · {len(r["boxes"])} boxes</div>'
        f'<span class="badge b-{vtag}">{esc(vlabel)}</span>'
        f'<div class="reason">{esc(r["reason_display"])}</div></div></article>'
    )


def lb_entry(r):
    groups = {g: 0 for g, _ in GROUPS}
    for b in r["boxes"]:
        groups[box_group(b)] += 1
    notes = [{"type": str(n.get("type") or ""), "note": str(n.get("note") or "")} for n in r["notes"]]
    return {
        "gid": r["gid"], "pool": r["pool"], "application": r["application"] or "–",
        "n_boxes": len(r["boxes"]),
        "groups": [[GROUP_LABEL[g], groups[g]] for g, _ in GROUPS],
        "verdict_label": r["verdict"] or "no verdict",
        "reason_display": r["reason_display"],
        "notes": notes[:NOTES_MAX],
        "more_notes": max(0, len(notes) - NOTES_MAX),
    }


def json_for_script(obj):
    return json.dumps(obj, ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


# ----------------------------------------------------------------------------- check

class _Scan(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.refs = []          # src / href values
        self.imgs = []          # static <img src>
        self.cards = 0
        self.total_text = None
        self._in_total = False
        self._buf = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for key in ("src", "href"):
            if a.get(key):
                self.refs.append(a[key])
        if tag == "img" and a.get("src"):
            self.imgs.append(a["src"])
        if tag == "article" and "data-card" in a:
            self.cards += 1
        if a.get("data-role") == "total-count":
            self._in_total = True
            self._buf = []

    def handle_endtag(self, tag):
        if self._in_total and tag == "td":
            self._in_total = False
            self.total_text = "".join(self._buf).strip()

    def handle_data(self, data):
        if self._in_total:
            self._buf.append(data)


def run_check(out_dir, sample_gids, labels_included, page_name="review_batch1.html", img_dir="review_img",
              n_cards=None):
    """Structural checks on one review page. sample_gids: gids whose jpg/_t.jpg must exist under img_dir.
    n_cards defaults to len(sample_gids) (one card per sampled image)."""
    problems = []
    page = os.path.join(out_dir, page_name)
    if n_cards is None:
        n_cards = len(sample_gids)
    try:
        with open(page, encoding="utf-8") as f:
            text = f.read()
        scan = _Scan()
        scan.feed(text)
        scan.close()
    except Exception as e:  # html.parser is lenient; any exception here is a failure
        return [f"html parse failed: {e}"]

    for src in scan.imgs:
        if src.startswith(("http://", "https://", "//", "data:")):
            problems.append(f"img src not relative: {src}")
        elif not os.path.isfile(os.path.join(out_dir, src)):
            problems.append(f"img src missing: {src}")
    for ref in scan.refs:
        if ref.startswith(("http://", "https://", "//")):
            problems.append(f"external reference: {ref}")
    for gid in sample_gids:
        for name in (gid + ".jpg", gid + "_t.jpg"):
            if not os.path.isfile(os.path.join(out_dir, img_dir, name)):
                problems.append(f"sample image missing: {img_dir}/{name}")
    if scan.cards != n_cards:
        problems.append(f"card count {scan.cards} != expected {n_cards}")
    if scan.total_text is None:
        problems.append("source table total-count cell not found")
    elif scan.total_text != str(labels_included):
        problems.append(f"source table total {scan.total_text} != labels rows counted {labels_included}")
    return problems


# ----------------------------------------------------------------------------- main

def qa_fields(qa):
    """(verdict or None, reason_display, notes list) from one QA json (or None when there is no QA file)."""
    verdict = qa.get("verdict") if qa else None
    if verdict not in VERDICTS:
        verdict = None
    reason = qa.get("reason") if qa else None
    notes = list(qa.get("notes") or []) if qa else []
    first_note = next((str(n.get("note")) for n in notes if str(n.get("note") or "").strip()), None)
    reason_display = (reason or "").strip() or first_note or "–"
    return verdict, reason_display, notes


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--overlay-dir", required=True)
    ap.add_argument("--qa-dir", required=True)
    ap.add_argument("--ledger-opus", required=True)
    ap.add_argument("--ledger-qa", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--n-fix", type=int, default=10)
    ap.add_argument("--n-reject", type=int, default=3)
    ap.add_argument("--seed", type=int, default=123)
    ap.add_argument("--title", default="batch review")
    ap.add_argument("--check", action="store_true", help="run structural checks on the page after writing it")
    ap.add_argument("--name", default="batch1",
                    help="output name: review_<name>.html, stats_<name>.json, stats_<name>.md (default batch1)")
    a = ap.parse_args(argv)
    html_name = f"review_{a.name}.html"
    json_name = f"stats_{a.name}.json"
    md_name = f"stats_{a.name}.md"

    manifest = {}
    for r in read_jsonl(a.manifest):
        manifest[r["gid"]] = r

    labels = read_jsonl(a.labels)
    recs, skipped = [], []
    for lab in labels:
        gid = lab["gid"]
        m = manifest.get(gid)
        if m is None:
            skipped.append(gid)
            continue
        verdict, reason_display, notes = qa_fields(load_qa(a.qa_dir, gid))
        recs.append({
            "gid": gid,
            "pool": m["pool"],
            "application": m.get("application") or None,
            "boxes": lab.get("boxes") or [],
            "verdict": verdict,
            "reason_display": reason_display,
            "notes": notes,
        })
    if skipped:
        print(f"skipped {len(skipped)} labels rows whose gid is not in the manifest: {skipped[:10]}")

    opus_usd, opus_rows = ledger_sum(a.ledger_opus)
    qa_usd, qa_rows = ledger_sum(a.ledger_qa)
    total_usd = opus_usd + qa_usd
    per_image = total_usd / len(recs) if recs else 0.0
    costs = {"opus": opus_usd, "opus_rows": opus_rows, "qa": qa_usd, "qa_rows": qa_rows,
             "total": total_usd, "per_image": per_image}
    cost_line = (f"Cost (API-equivalent, not a bill): Opus ${opus_usd:.2f} + QA ${qa_usd:.2f} = ${total_usd:.2f}; "
                 f"average per image ${per_image:.3f} ({len(recs)} images)")

    rows = [{"gid": r["gid"], "pool": r["pool"], "application": r["application"], "verdict": r["verdict"]}
            for r in recs]
    sample_gids = pick_sample(rows, a.n, a.n_fix, a.n_reject, a.seed)
    by_gid = {r["gid"]: r for r in recs}
    sample_recs = [by_gid[g] for g in sample_gids]
    smp_pools = OrderedDict()
    for r in sample_recs:
        d = smp_pools.setdefault(r["pool"], {"n": 0, "fix": 0, "reject": 0})
        d["n"] += 1
        if r["verdict"] in ("fix", "reject"):
            d[r["verdict"]] += 1
    sample_info = {
        "n": len(sample_recs),
        "n_fix": sum(1 for r in sample_recs if r["verdict"] == "fix"),
        "n_reject": sum(1 for r in sample_recs if r["verdict"] == "reject"),
        "by_pool": smp_pools,
    }

    scopes = compute_stats(recs)
    st = build_stats(recs, scopes, costs, sample_info, a.title, len(labels), len(skipped))

    out_dir = a.out_dir
    img_dir = os.path.join(out_dir, "review_img")
    os.makedirs(img_dir, exist_ok=True)
    wanted = set()
    for r in sample_recs:
        png = find_overlay(a.overlay_dir, r["gid"])
        if png is None:
            raise SystemExit(f"no overlay PNG for sampled gid {r['gid']} in {a.overlay_dir}")
        write_images(png, r["gid"], img_dir)
        wanted.update({r["gid"] + ".jpg", r["gid"] + "_t.jpg"})
    for name in os.listdir(img_dir):  # drop images of earlier samples so the folder matches this run
        if name.endswith(".jpg") and name not in wanted:
            os.remove(os.path.join(img_dir, name))

    cards = []
    order = sorted(sample_recs, key=lambda r: (r["pool"], {"reject": 0, "fix": 1}.get(r["verdict"], 2), r["gid"]))
    for i, r in enumerate(order):
        cards.append(card_html(i, r))
    lb_data = json_for_script({r["gid"]: lb_entry(r) for r in order})

    generated_at = st["generated_at"]
    page = render_html(a.title, generated_at, st, cards, lb_data, sample_info, cost_line)
    with open(os.path.join(out_dir, html_name), "w", encoding="utf-8") as f:
        f.write(page)
    with open(os.path.join(out_dir, json_name), "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
    with open(os.path.join(out_dir, md_name), "w", encoding="utf-8") as f:
        f.write(stats_md(st))

    print(f"labels rows {len(labels)} · counted {len(recs)} · skipped {len(skipped)}")
    print(f"sample {sample_info['n']} (reject {sample_info['n_reject']}, fix {sample_info['n_fix']})")
    for p, d in smp_pools.items():
        print(f"  {p}: sample {d['n']} · fix {d['fix']} · reject {d['reject']}")
    print(cost_line)
    print(f"wrote {os.path.join(out_dir, html_name)}")

    if a.check:
        problems = run_check(out_dir, sample_gids, len(recs), page_name=html_name)
        if problems:
            print("CHECK FAILED:")
            for p in problems:
                print("  - " + p)
            return 1
        print(f"CHECK OK: html parses; {len(sample_gids)} cards; all img refs exist; no external refs; "
              f"source total {len(recs)} == counted labels rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
