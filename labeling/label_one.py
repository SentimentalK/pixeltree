"""Opus look-only labelling through a slim `claude -p` subprocess.

  make  frames.jsonl -> batches/batch_NNN.md (10-15 images each), images symlinked under <work>/img
  run   batch ids    -> one `claude -p` per batch; result JSON in logs/, one ledger.tsv row per batch

frames.jsonl rows: {"stem", "image" (abs path), "w", "h", "hint"}.
Slim = only Read / Write tools, no MCP, no user / project settings (so no hooks), no slash
commands, no session file, a one-line system prompt instead of Claude Code's default one.
Cost is the API list-price equivalent (cache write and uncached input $5, cache read $0.2,
output $20 per MTok), not a bill. A call bills to ANTHROPIC_API_KEY when that variable is set
(billing "api"); otherwise it uses the CLI login (billing "cli").

Example (paths are placeholders):
  python label_one.py make work/frames.jsonl --work work --size 1 --rules prompts/label_rules_v1_1.md
  python label_one.py run batch_000 batch_001 --work work --model claude-opus-5-5 --effort high --jobs 2
"""
import argparse, csv, datetime, json, os, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.join(HERE, "prompts", "label_rules_v1_1.md")
SYSTEM = "You are a GUI screenshot annotator. Use Read to view images and Write to save JSON files."
PRICE = {"input_tokens": 5, "cache_creation_input_tokens": 5, "cache_read_input_tokens": 0.2, "output_tokens": 20}


LEDGER_HEAD = ("batch\timages\tjson_written\tseconds\tinput\tcache_write\tcache_read\toutput\tthinking"
               "\tapi_equiv_usd\tcc_total_cost_usd\tturns\tstatus\tbilling\tts")
# a failed call whose output matches one of these is a billing / auth problem, not a labelling failure
BILLING_ERROR = re.compile(r"credit balance|billing|insufficient|quota|invalid x-api-key|authentication_error"
                           r"|\b(?:401|402|403)\b", re.I)


def call_status(res, stdout, stderr, rc):
    """Ledger status of one `claude -p` call. `claude -p` can report an API error (credit balance too low) as
    subtype "success" with is_error true, so that counts as a failure too."""
    res = res or {}
    status = res.get("subtype", f"rc={rc}")
    if (not res or res.get("subtype") != "success" or res.get("is_error")) and BILLING_ERROR.search(
            "\n".join([stdout or "", stderr or "", str(res.get("result", ""))])):
        status = "billing_error"
    return status


def billing_of(env):
    """"api" when the subprocess environment carries a non-empty ANTHROPIC_API_KEY, else "cli"."""
    return "api" if (env.get("ANTHROPIC_API_KEY") or "").strip() else "cli"


def read_ledger(path):
    """ledger.tsv -> list of dicts. Rows written before the billing / ts columns existed count as "cli", ts ''."""
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    if not rows:
        return []
    head, out = rows[0], []
    for cells in rows[1:]:
        if not cells:
            continue
        d = dict(zip(head, cells))
        extra = cells[len(head):]
        if "billing" not in head:
            d["billing"] = extra[0] if extra else ""
            d["ts"] = extra[1] if len(extra) > 1 else ""
        d["billing"] = d.get("billing") or "cli"
        d["ts"] = d.get("ts") or ""
        out.append(d)
    return out


def ensure_ledger(led):
    """Create the ledger with the current header, or add the billing / ts columns to an old header (rows stay as they are)."""
    if not os.path.exists(led):
        open(led, "w").write(LEDGER_HEAD + "\n")
        return
    lines = open(led).read().split("\n")
    if "billing" not in lines[0].split("\t"):
        lines[0] = LEDGER_HEAD
        open(led, "w").write("\n".join(lines))


def claude_argv(model, effort):
    return ["claude", "-p", "--model", model, "--effort", effort,
            "--tools", "Read,Write", "--allowedTools", "Read,Write",
            "--strict-mcp-config", "--setting-sources", "", "--disable-slash-commands",
            "--no-session-persistence", "--system-prompt", SYSTEM, "--output-format", "json"]


def batch_prompt(rows, work, rules):
    lines = [f"Read the labelling rules in {os.path.abspath(rules)} and follow them.", "",
             "Look-only mode: use only the Read tool to view each image and the Write tool to save each JSON. "
             "Do not run Python or any image processing; estimate coordinates by eye in the stated image size. "
             "Do not open, list or search any other file (no datasets, no other labels). Do not use the web.", "",
             "Images (label each, write its JSON to the path after the arrow):"]
    for r in rows:
        lines.append(f"- {work}/img/{r['stem']}.png  ({r['w']} x {r['h']}; product hint: {r['hint']}) -> {work}/json/{r['stem']}.json")
    lines += ["", "Final reply: one line per image with the element count. Nothing else."]
    return "\n".join(lines) + "\n"


def cmd_make(a):
    rows = [json.loads(l) for l in open(a.frames)]
    for d in ("img", "json", "batches", "logs"):
        os.makedirs(os.path.join(a.work, d), exist_ok=True)
    done = {f[:-5] for f in os.listdir(os.path.join(a.work, "json"))}
    rows = [r for r in rows if r["stem"] not in done]
    n0 = len([f for f in os.listdir(os.path.join(a.work, "batches")) if f.endswith(".md")])
    for i in range(0, len(rows), a.size):
        chunk = rows[i:i + a.size]
        for r in chunk:
            link = os.path.join(a.work, "img", r["stem"] + ".png")
            if not os.path.lexists(link):
                os.symlink(r["image"], link)
        b = f"batch_{n0 + i // a.size:03d}"
        open(os.path.join(a.work, "batches", b + ".md"), "w").write(batch_prompt(chunk, a.work, a.rules))
        json.dump([r["stem"] for r in chunk], open(os.path.join(a.work, "batches", b + ".json"), "w"))
        print(b, len(chunk))


def cost(u):
    return sum(u.get(k, 0) * p for k, p in PRICE.items()) / 1e6


def run_one(a, b):
    stems = json.load(open(os.path.join(a.work, "batches", b + ".json")))
    prompt = open(os.path.join(a.work, "batches", b + ".md")).read()
    env = dict(os.environ)
    t0 = time.time()
    p = subprocess.run(claude_argv(a.model, a.effort), input=prompt, capture_output=True, text=True,
                       cwd=a.work, env=env, timeout=a.timeout)
    dt = time.time() - t0
    open(os.path.join(a.work, "logs", b + ".result.json"), "w").write(p.stdout)
    if p.stderr:
        open(os.path.join(a.work, "logs", b + ".stderr"), "w").write(p.stderr)
    try:
        res = json.loads(p.stdout)
    except json.JSONDecodeError:
        res = {}
    u = res.get("usage", {})
    got = sum(os.path.exists(os.path.join(a.work, "json", s + ".json")) for s in stems)
    think = u.get("output_tokens_details", {}).get("thinking_tokens", 0)
    status = call_status(res, p.stdout, p.stderr, p.returncode)
    row = [b, len(stems), got, f"{dt:.0f}", u.get("input_tokens", 0), u.get("cache_creation_input_tokens", 0),
           u.get("cache_read_input_tokens", 0), u.get("output_tokens", 0), think, f"{cost(u):.4f}",
           f"{res.get('total_cost_usd', 0):.4f}", res.get("num_turns", ""), status, billing_of(env),
           datetime.datetime.now().astimezone().isoformat(timespec="seconds")]
    line = "\t".join(map(str, row))
    with open(os.path.join(a.work, "ledger.tsv"), "a") as f:
        f.write(line + "\n")
    print(line, flush=True)


def cmd_run(a):
    ensure_ledger(os.path.join(a.work, "ledger.tsv"))
    with ThreadPoolExecutor(a.jobs) as ex:
        list(ex.map(lambda b: run_one(a, b), a.batches))


def build_parser():
    ap = argparse.ArgumentParser(description="Look-only Opus/Sonnet labelling through `claude -p` (one call per batch).")
    sp = ap.add_subparsers(dest="cmd", required=True)
    m = sp.add_parser("make", help="split frames into batch prompts")
    m.add_argument("frames", help="frames.jsonl: {stem, image, w, h, hint} per line")
    m.add_argument("--work", required=True, help="working directory (created if missing)")
    m.add_argument("--size", type=int, default=12, help="images per batch (default 12)")
    m.add_argument("--rules", default=RULES, help="labelling rules file (default prompts/label_rules_v1_1.md)")
    r = sp.add_parser("run", help="run one claude -p call per batch")
    r.add_argument("batches", nargs="+", help="batch ids, e.g. batch_000")
    r.add_argument("--work", required=True)
    r.add_argument("--model", default="claude-opus-5-5")
    r.add_argument("--effort", default="high")
    r.add_argument("--jobs", type=int, default=1, help="batches in parallel")
    r.add_argument("--timeout", type=int, default=5400, help="seconds per call")
    return ap


if __name__ == "__main__":
    a = build_parser().parse_args()
    a.work = os.path.abspath(a.work)
    {"make": cmd_make, "run": cmd_run}[a.cmd](a)
