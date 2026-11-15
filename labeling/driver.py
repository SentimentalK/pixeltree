#!/usr/bin/env python3
"""Batch driver: label -> QA sample -> QA gate -> ULF export -> review page, for a list of batches.

  run     --plan PLAN.json [--dry-run]
            Drives every batch of the plan in order. A batch directory must already contain frames.jsonl
            (made with `tile_merge.py frames`). Steps per batch: label (label_one.py make / run, in chunks)
            -> merge (tile_merge.py merge) -> QA on a per-application sample (tile_merge.py qa-make, then
            label_one.py run with the QA model) -> QA gate -> ULF export (batch.py ulf) -> review page
            (review_page.py). Events go to <plan dir>/driver_events.log; a failed gate or repeated failure
            writes <plan dir>/STOP and exits 10 (delete the file to resume). Finished batches are skipped.
  ledger  --root DIR [--json]
            Sums the claude -p ledgers (<...>/work/ledger.tsv) under DIR by role (label / qa / fix) and by
            billing path (api / cli), in API-equivalent US dollars. Not a bill.

Plan file (JSON; relative paths are resolved against the plan file's directory):
  {
    "rules": "prompts/label_rules_v1_1.md",
    "qa_rules": "qa_rules_v1_1.md",
    "label_model": "claude-opus-5-5", "qa_model": "claude-sonnet-5-5", "effort": "high",
    "jobs": 2, "chunk": 8,
    "batches": [{"name": "batch1", "dir": "work/batch1", "manifest": "data/manifest_batch1.jsonl"}]
  }
"""
import argparse
import csv
import datetime
import glob
import json
import math
import os
import random
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from label_one import read_ledger  # noqa: E402

ROLES = ("label", "qa", "fix")
BILLINGS = ("api", "cli")

QA_FRAC = 0.20           # share of each batch that goes to QA
QA_FIX_MAX = 0.15        # QA gate: fix share of the sample must not exceed this
QA_REJECT_MAX = 0.05     # QA gate: reject share of the sample must not exceed this
RETRY_WAIT_S = 900
RETRY_MAX = 3
NO_PROGRESS_MAX = 3


class Stop(Exception):
    """The driver stops (writes STOP, exit 10)."""


def role_of(ledger_path):
    p = ledger_path.replace(os.sep, "/")
    if "/qa/work/" in p:
        return "qa"
    if "/fix/work/" in p:
        return "fix"
    return "label"


def find_ledgers(root):
    out = []
    for dirpath, _, files in os.walk(root):
        if "ledger.tsv" in files and os.path.basename(dirpath) == "work":
            out.append(os.path.join(dirpath, "ledger.tsv"))
    return sorted(out)


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def ledger_summary(root):
    by_role = {r: {b: {"calls": 0, "usd": 0.0} for b in BILLINGS} for r in ROLES}
    for led in find_ledgers(root):
        role = role_of(led)
        for row in read_ledger(led):
            b = row["billing"] if row["billing"] in BILLINGS else "cli"
            cell = by_role[role][b]
            cell["calls"] += 1
            cell["usd"] += _num(row.get("cc_total_cost_usd"))
    total = sum(by_role[r][b]["usd"] for r in ROLES for b in BILLINGS)
    return {"total_usd": round(total, 4),
            "by_role": {r: {b: {"calls": c["calls"], "usd": round(c["usd"], 4)} for b, c in v.items()}
                        for r, v in by_role.items()}}


def format_ledger(res, root):
    lines = [f"ledger {root} (API-equivalent cost; not a bill)", "  role   billing  calls  usd"]
    for r in ROLES:
        for b in BILLINGS:
            c = res["by_role"][r][b]
            lines.append(f"  {r:<6} {b:<8} {c['calls']:>6}  {c['usd']:>8.2f}")
    lines.append(f"  total                   {res['total_usd']:.2f}")
    return "\n".join(lines)


# ---------------------------------------------------------------- QA sampling and gate

def qa_sample(name, apps_to_gids):
    """QA sample of a batch: total K = ceil(n * QA_FRAC) (more only when there are more applications than K).

    Every application gets one image, the remaining K - applications slots go by largest remainder of
    n_app * QA_FRAC - 1 (ties by application name, never more than the application has). Drawing is seeded
    by batch and application name, so a re-run draws the same sample."""
    sizes = {app: len(set(g)) for app, g in apps_to_gids.items()}
    target = math.ceil(sum(sizes.values()) * QA_FRAC - 1e-9)
    k = {a: min(1, n) for a, n in sizes.items()}
    for _ in range(max(0, target - sum(k.values()))):
        cand = [a for a in sizes if k[a] < sizes[a]]
        if not cand:
            break
        best = min(cand, key=lambda a: (-(sizes[a] * QA_FRAC - k[a]), a))
        k[best] += 1
    out = []
    for app in sorted(apps_to_gids):
        gids = sorted(set(apps_to_gids[app]))
        first = min(k[app], max(1, round(len(gids) * QA_FRAC)))
        pick = random.Random(f"qa:{name}:{app}").sample(gids, first)
        if k[app] > first:
            rest = [g for g in gids if g not in pick]
            pick += random.Random(f"qa:{name}:{app}:extra").sample(rest, k[app] - first)
        out += pick
    return sorted(out)


def qa_gate(verdicts):
    """verdicts: {gid: "ok"|"fix"|"reject"} of the sampled gids -> (passed, fix_rate, counts)."""
    cnt = {"ok": 0, "fix": 0, "reject": 0}
    for v in verdicts.values():
        if v in cnt:
            cnt[v] += 1
    n = sum(cnt.values())
    rate = cnt["fix"] / n if n else 0.0
    passed = not (cnt["fix"] > QA_FIX_MAX * n + 1e-9 or cnt["reject"] > QA_REJECT_MAX * n + 1e-9)
    return passed, rate, cnt


def _read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def count_billing_errors(batch_dir):
    n = 0
    for led in find_ledgers(batch_dir):
        n += sum(1 for r in read_ledger(led) if r.get("status") == "billing_error" and r.get("billing") == "api")
    return n


# ---------------------------------------------------------------- driver

class Driver:
    def __init__(self, plan_path, dry_run=False):
        self.plan_path = os.path.abspath(plan_path)
        self.root = os.path.dirname(self.plan_path)
        with open(self.plan_path, encoding="utf-8") as f:
            self.cfg = json.load(f)
        self.dry = dry_run
        self.events = os.path.join(self.root, "driver_events.log")
        self.stop_file = os.path.join(self.root, "STOP")

    def p(self, rel):
        """Resolve a plan-relative path."""
        return rel if os.path.isabs(rel) else os.path.join(self.root, rel)

    # -- events
    def event(self, event, batch="", **detail):
        line = json.dumps({"ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
                           "event": event, "batch": batch, "detail": detail}, ensure_ascii=False)
        if not self.dry:
            with open(self.events, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        print(line, flush=True)

    def stop(self, reason, batch="", **detail):
        self.event("STOP", batch, reason=reason, **detail)
        with open(self.stop_file, "w", encoding="utf-8") as f:
            f.write(reason + "\n")
        raise Stop(reason)

    def sleep(self, seconds, batch, why):
        self.event("sleep", batch, seconds=seconds, why=why)
        time.sleep(seconds)

    # -- process
    def tool(self, script, args, log_dir):
        """Run one script of this directory; output is appended to <log_dir>/driver_run.log. Returns the exit code."""
        os.makedirs(log_dir, exist_ok=True)
        argv = [sys.executable, os.path.join(HERE, script)] + [str(a) for a in args]
        with open(os.path.join(log_dir, "driver_run.log"), "ab") as log:
            return subprocess.run(argv, stdout=log, stderr=subprocess.STDOUT, cwd=self.root).returncode

    def claude(self, cmd_args, model, log_dir):
        """label_one.py run for the given batch ids."""
        return self.tool("label_one.py", ["run", *cmd_args, "--model", model,
                                          "--effort", self.cfg.get("effort", "high"),
                                          "--jobs", self.cfg.get("jobs", 2)], log_dir)

    # -- label
    def pending_batches(self, work):
        """Batch ids whose batch JSON lists a stem without an output JSON yet."""
        bdir, jdir = os.path.join(work, "batches"), os.path.join(work, "json")
        out = []
        for f in sorted(os.listdir(bdir)):
            if not f.endswith(".json"):
                continue
            stems = json.load(open(os.path.join(bdir, f), encoding="utf-8"))
            if not all(os.path.exists(os.path.join(jdir, s + ".json")) for s in stems):
                out.append(f[:-5])
        return out

    def label_loop(self, b, d):
        name, work = b["name"], os.path.join(d, "work")
        if not os.path.isdir(os.path.join(work, "batches")):
            self.tool("label_one.py", ["make", os.path.join(d, "frames.jsonl"), "--work", work, "--size", 1,
                                       "--rules", self.p(self.cfg["rules"])], d)
        chunk_n = int(self.cfg.get("chunk", 8))
        stalled = 0
        while True:
            units = self.pending_batches(work)
            if not units:
                break
            done_before = len(units)
            for i in range(0, len(units), chunk_n):
                self.claude(units[i:i + chunk_n], self.cfg["label_model"], d)
            left = len(self.pending_batches(work))
            if left >= done_before:
                stalled += 1
                if stalled > NO_PROGRESS_MAX:
                    self.stop("label_no_progress", name, pending=left)
                self.sleep(RETRY_WAIT_S, name, f"label no progress {stalled}/{NO_PROGRESS_MAX}")
            else:
                stalled = 0
        return len(self.pending_batches(work))

    # -- QA
    def verdicts(self, d, ids):
        out = {}
        for g in ids:
            p = os.path.join(d, "qa", "work", "json", g + ".json")
            if os.path.exists(p):
                out[g] = json.load(open(p, encoding="utf-8")).get("verdict")
        return out

    def qa_loop(self, b, d, ids):
        name, qa_work = b["name"], os.path.join(d, "qa", "work")
        qa_file = os.path.join(d, "qa_only.txt")
        open(qa_file, "w").write("\n".join(ids) + "\n")
        retries = 0
        while len(self.verdicts(d, ids)) < len(ids):
            self.tool("tile_merge.py", ["qa-make", "--labels", os.path.join(d, "labels_round1.jsonl"),
                                        "--overlay-dir", os.path.join(d, "overlay_round1"), "--work", qa_work,
                                        "--manifest", self.p(b["manifest"]), "--rules", self.cfg["qa_rules"],
                                        "--only", qa_file], d)
            units = self.pending_batches(qa_work)
            if units:
                rc = self.claude(units, self.cfg["qa_model"], d)
            else:
                rc = 0
            if len(self.verdicts(d, ids)) >= len(ids):
                break
            retries += 1
            if retries > RETRY_MAX:
                self.stop("qa_incomplete", name, missing=len(ids) - len(self.verdicts(d, ids)), rc=rc)
            self.sleep(RETRY_WAIT_S, name, f"qa incomplete, retry {retries}/{RETRY_MAX}")
        self.tool("tile_merge.py", ["qa-summary", "--work", qa_work, "--out", os.path.join(d, "qa", "summary.md")], d)

    def overlay(self, d, gid):
        hits = sorted(glob.glob(os.path.join(d, "overlay_round1", glob.escape(gid) + "__*.png")))
        return hits[0] if hits else ""

    # -- one batch
    def run_batch(self, b):
        name, d = b["name"], self.p(b["dir"])
        os.makedirs(d, exist_ok=True)
        self.event("batch_start", name, dir=d)
        left = self.label_loop(b, d)
        if left:
            self.stop("label_incomplete", name, pending=left)
        manifest = self.p(b["manifest"])
        self.tool("tile_merge.py", ["merge", "--dir", d, "--manifest", manifest], d)
        labels = os.path.join(d, "labels_round1.jsonl")
        os.replace(os.path.join(d, "labels.jsonl"), labels)
        self.tool("tile_merge.py", ["overlay", "--labels", labels, "--out", os.path.join(d, "overlay_round1")], d)

        man = {m["gid"]: m for m in _read_jsonl(manifest)}
        by_app = {}
        for lab in _read_jsonl(labels):
            g = lab["gid"]
            by_app.setdefault(man[g].get("application") or man[g]["pool"], []).append(g)
        ids = qa_sample(name, by_app)
        self.event("qa_sample", name, n=len(ids))
        self.qa_loop(b, d, ids)
        verdicts = self.verdicts(d, ids)
        passed, rate, cnt = qa_gate(verdicts)
        reject_rate = round(cnt["reject"] / max(1, sum(cnt.values())), 3)
        if not passed:
            order = sorted(ids, key=lambda g: {"reject": 0, "fix": 1}.get(verdicts.get(g), 2))[:10]
            self.stop("qa_gate", name, fix_rate=round(rate, 3), reject_rate=reject_rate, counts=cnt,
                      overlays=[self.overlay(d, g) for g in order])
        self.event("qa_gate_pass", name, counts=cnt, fix_rate=round(rate, 3), reject_rate=reject_rate,
                   rejects=sorted(g for g, v in verdicts.items() if v == "reject"))

        rc = self.tool("batch.py", ["ulf", "--labels", labels, "--manifest", manifest,
                                    "--qa", os.path.join(d, "qa", "work", "json"),
                                    "--out", os.path.join(d, f"labels_{name}.jsonl")], d)
        if rc != 0:
            self.stop("ulf", name, rc=rc)
        rc = self.tool("review_page.py", ["--name", name, "--n", 20, "--n-fix", 10, "--n-reject", 3,
                                          "--manifest", manifest, "--labels", labels,
                                          "--overlay-dir", os.path.join(d, "overlay_round1"),
                                          "--qa-dir", os.path.join(d, "qa", "work", "json"),
                                          "--ledger-opus", os.path.join(d, "work", "ledger.tsv"),
                                          "--ledger-qa", os.path.join(d, "qa", "work", "ledger.tsv"),
                                          "--out-dir", d, "--check"], d)
        if rc != 0:
            self.stop("review", name, rc=rc)
        n_box = sum(len(r["boxes"]) for r in _read_jsonl(labels))
        self.event("batch_done", name, boxes=n_box, qa={"sampled": len(ids), **cnt},
                   review=os.path.join(d, f"review_{name}.html"), stats=os.path.join(d, f"stats_{name}.json"))

    def finished(self, b):
        d = self.p(b["dir"])
        return (os.path.exists(os.path.join(d, f"labels_{b['name']}.jsonl"))
                and os.path.exists(os.path.join(d, f"review_{b['name']}.html")))

    def dry_run(self):
        for b in self.cfg["batches"]:
            d = self.p(b["dir"])
            if self.finished(b):
                print(f"{b['name']}: finished")
                continue
            work = os.path.join(d, "work")
            if os.path.isdir(os.path.join(work, "batches")):
                print(f"{b['name']}: {len(self.pending_batches(work))} label batch(es) pending")
            else:
                print(f"{b['name']}: no label batches yet (frames: {os.path.join(d, 'frames.jsonl')})")

    def run(self):
        if os.path.exists(self.stop_file):
            print("STOP exists:", open(self.stop_file).read().strip(), "(delete it to resume)")
            return 10
        if self.dry:
            self.dry_run()
            return 0
        try:
            for b in self.cfg["batches"]:
                if not self.finished(b):
                    self.run_batch(b)
        except Stop:
            return 10
        self.event("all_done")
        return 0


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("run", help="drive the batches of a plan file (resumable)")
    r.add_argument("--plan", required=True)
    r.add_argument("--dry-run", action="store_true", help="print the state of each batch; run nothing")
    lg = sp.add_parser("ledger", help="sum the claude -p ledgers under a directory")
    lg.add_argument("--root", required=True)
    lg.add_argument("--json", action="store_true")
    return ap


def main():
    a = build_parser().parse_args()
    if a.cmd == "run":
        sys.exit(Driver(a.plan, a.dry_run).run())
    res = ledger_summary(a.root)
    print(json.dumps(res, indent=1) if a.json else format_ledger(res, a.root))


if __name__ == "__main__":
    main()
