"""Convert the three raw archive layouts into traces. Read-only: nothing in the archive is modified.

The layouts are identified by a source kind: ``w2c`` (experiment R5, agents run through the OMP
shell), ``p125`` (experiment R1, ``claude -p``) and ``w2`` (experiment R3, ``claude -p``). The
``export`` command renames them to ``r5`` / ``r1`` / ``r3``.

Alignment rule: the agent's messages in the transcript are flattened, in order, into a list of
tool calls; call k belongs to ``steps/<k as two digits>/``. The text / thinking that precedes the
first tool call of a message is attached to that call; later calls in the same message get empty
text. ``message_index`` records the message number. If the step directories outnumber or
undercount the tool calls, the step directories win.

Success and grading detail are always taken from the re-graded file ``episodes_v1_1.jsonl``,
never from ``result.json``.
"""

from __future__ import annotations

import json
import os
import re
from typing import Callable, Iterable

from .format import FORMAT, make_step

MODEL_NAMES = {
    "glm": "GLM 5.3 Flash",
    "deepseek": "DeepSeek V4.1 Flash",
    "longcat": "LongCat 2.0 (text only)",
    "haiku": "Claude Haiku 5.5",
    "sonnet": "Claude Sonnet 5.5",
}
# Human-readable condition descriptions.
COND_NOTES = {
    "S_shot": "Screenshot only: the agent sees a 1280×720 screenshot each step.",
    "S_shot_strong": "Screenshot only, with Claude Sonnet as the agent.",
    "S_shot_lean": "Screenshot only, without the redundant observe calls.",
    "T_ours": ("Our tree only: the agent reads a text list of elements produced by our local "
               "detector + OCR from the screenshot; it never sees the image."),
    "T_atspi": ("System accessibility tree only (AT-SPI, flattened to role, name and box); "
                "click by coordinates; no states or element actions."),
    "T_omni": "OmniParser v2 tree only (text).",
    "H_ours": "Screenshot + our tree, both in the 1280×720 frame.",
    "H_atspi": "Screenshot + AT-SPI tree.",
    "X1": "Cleaned compact tree (experimental cleaning rules; they blank the close button '×').",
    "X2": ("Tree first: cleaned list, only changes after actions, plus hover and look "
           "(screenshot on demand)."),
    "X2_lean": "X2 without the redundant observe calls.",
}
SHELLS = {"w2c": "OMP", "p125": "claude -p", "w2": "claude -p"}

# Which jsonl files each R5 model reads, in order (relative to root); later rows override earlier ones
DEFAULT_W2C_RUNS = {
    "glm": ["glm/formal"],
    "deepseek": ["deepseek/formal", "deepseek/formal_seq"],
    "longcat": ["longcat/formal", "longcat/formal_seq"],
    "haiku": ["haiku/formal_seq", "haiku/formal_seq2"],
}
JSONL_NAME = "episodes_v1_1.jsonl"

_TOOL_PREFIX = re.compile(r"^mcp__p125_{1,2}")
_RE_OMP_END = re.compile(r'^\{"type":\s*"message_end"')
_RE_ASSISTANT_ROLE = re.compile(r'"role":\s*"assistant"')
_RE_CC_ASSISTANT = re.compile(r'^\{"type":\s*"assistant"')


def strip_tool_prefix(name: str) -> str:
    return _TOOL_PREFIX.sub("", name or "")


def is_p125_tool(name: str) -> bool:
    return bool(_TOOL_PREFIX.match(name or ""))


def model_key(model_id: str) -> str:
    m = (model_id or "").lower()
    for k in ("glm", "deepseek", "longcat", "haiku", "sonnet"):
        if k in m:
            return k
    return re.sub(r"[^a-z0-9]+", "-", m.split("/")[-1]) or "unknown"


# ---------------------------------------------------------------- transcripts

def _calls_from_messages(messages: list[list[dict]]) -> list[dict]:
    """messages: the content blocks of each agent message (normalised to text / thinking / call).

    Returns the flattened tool calls, in order: {"name","args","text","thinking","message_index"}.
    """
    calls = []
    for mi, blocks in enumerate(messages):
        texts, thinks = [], []
        first = True
        for b in blocks:
            if b["kind"] == "call":
                calls.append({
                    "name": strip_tool_prefix(b["name"]),
                    "raw_name": b["name"],
                    "args": b.get("args") or {},
                    "text": "\n".join(texts) if first else "",
                    "thinking": "\n".join(thinks) if first else "",
                    "message_index": mi,
                })
                first = False
            elif first and b["kind"] == "text":
                texts.append(b["text"])
            elif first and b["kind"] == "thinking":
                thinks.append(b["text"])
    return calls


def parse_omp_transcript(path: str) -> tuple[str, list[dict]]:
    """OMP (R5) transcript -> (task sentence, tool-call list). Only assistant message_end lines are used."""
    task = ""
    messages: list[list[dict]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            head = line[:80]
            if not _RE_OMP_END.match(head):
                continue
            is_assistant = bool(_RE_ASSISTANT_ROLE.search(line[:600]))
            if not is_assistant and task:
                continue  # tool-result lines are large (they carry images); apart from the first user line they are not parsed
            try:
                msg = json.loads(line).get("message") or {}
            except ValueError:
                continue
            role = msg.get("role")
            if role == "user" and not task:
                for b in msg.get("content") or []:
                    if b.get("type") == "text":
                        task = b.get("text", "")
                        break
                if task.startswith("Task: "):
                    task = task[len("Task: "):]
            elif role == "assistant":
                blocks = []
                for b in msg.get("content") or []:
                    t = b.get("type")
                    if t == "text":
                        blocks.append({"kind": "text", "text": b.get("text", "")})
                    elif t == "thinking":
                        blocks.append({"kind": "thinking", "text": b.get("thinking", "")})
                    elif t == "toolCall":
                        blocks.append({"kind": "call", "name": b.get("name", ""),
                                       "args": b.get("arguments") or {}})
                messages.append(blocks)
    calls = [c for c in _calls_from_messages(messages) if is_p125_tool(c["raw_name"])]
    return task, calls


def parse_claude_transcript(path: str) -> list[dict]:
    """claude -p (stream-json) transcript -> tool-call list. Rows with the same message.id are merged into one message."""
    order: list[str] = []
    by_id: dict[str, list[dict]] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not _RE_CC_ASSISTANT.match(line[:60]):
                continue
            try:
                msg = json.loads(line).get("message") or {}
            except ValueError:
                continue
            mid = msg.get("id") or "line%d" % len(order)
            if mid not in by_id:
                by_id[mid] = []
                order.append(mid)
            for b in msg.get("content") or []:
                t = b.get("type")
                if t == "text":
                    by_id[mid].append({"kind": "text", "text": b.get("text", "")})
                elif t == "thinking":
                    by_id[mid].append({"kind": "thinking", "text": b.get("thinking", "")})
                elif t == "tool_use":
                    by_id[mid].append({"kind": "call", "name": b.get("name", ""),
                                       "args": b.get("input") or {}})
    messages = [by_id[m] for m in order]
    return [c for c in _calls_from_messages(messages) if is_p125_tool(c["raw_name"])]


# ------------------------------------------------------------------ one episode

def _read_json(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _step_dirs(ep_dir: str) -> list[tuple[int, str]]:
    root = os.path.join(ep_dir, "steps")
    out = []
    if os.path.isdir(root):
        for n in os.listdir(root):
            if n.isdigit() and os.path.isdir(os.path.join(root, n)):
                out.append((int(n), os.path.join(root, n)))
    return sorted(out)


def cond_observation(cond: str) -> str:
    if cond.startswith("S_"):
        return "image"
    if cond.startswith("H_"):
        return "tree+image"
    return "tree"


def build_steps(ep_dir: str, calls: list[dict]) -> list[dict]:
    steps = []
    for k, d in _step_dirs(ep_dir):
        ap = os.path.join(d, "action.json")
        if not os.path.exists(ap):
            continue
        a = _read_json(ap)
        call = calls[k - 1] if 0 < k <= len(calls) else None

        def rd(name):
            p = os.path.join(d, name)
            return p if os.path.exists(p) else None

        obs_text = ""
        if rd("obs.txt"):
            with open(rd("obs.txt"), encoding="utf-8") as f:
                obs_text = f.read()
        tree = None
        if rd("tree.json"):
            t = _read_json(rd("tree.json"))
            tree = {
                "source": t.get("source"),
                "elements": [
                    {"id": e.get("id"), "role": e.get("role"), "name": e.get("name"),
                     "box": e.get("box"), "conf": e.get("conf")}
                    for e in t.get("elements", [])
                ],
            }
        steps.append(make_step(
            k, tool=a.get("tool", ""), args=a.get("args") or {},
            screen_xy=a.get("screen_xy"), ok=bool(a.get("ok", True)), error=a.get("error"),
            t_start=a.get("t_start"), t_end=a.get("t_end"),
            text=call["text"] if call else "",
            thinking=call["thinking"] if call else "",
            message_index=call["message_index"] if call else None,
            obs_text=obs_text, obs_image=rd("shot.png"), screen=rd("screen.png"),
            tree=tree,
        ))
    return steps


def build_meta(source: str, ep_dir: str, row: dict, sentence: str, difficulty) -> dict:
    mk = model_key(row.get("model", ""))
    cond = row.get("cond", "")
    obs = cond_observation(cond)
    return {
        "format": FORMAT,
        "id": "%s__%s__%s__%s__r%s" % (source, mk, row["task"], cond, row.get("rep", 0)),
        "source": {"kind": source, "path": os.path.abspath(ep_dir)},
        "task": {"id": row["task"], "app": row.get("app", ""), "sentence": sentence,
                 "difficulty": row.get("difficulty", difficulty)},
        "model": {"key": mk, "name": MODEL_NAMES.get(mk, mk), "id": row.get("model", "")},
        "condition": {"key": cond, "note": COND_NOTES.get(cond, "")},
        "shell": SHELLS[source],
        "rep": row.get("rep", 0),
        "started_at": row.get("t_start"),
        "screen_size": [1920, 1080],
        "agent_image_size": [1280, 720] if obs != "tree" else None,
        "observation": obs,
    }


def build_result(row: dict) -> dict:
    return {
        "ok": bool(row.get("ok")),
        "grader": "oracle v1.1",
        "grader_detail": row.get("oracle_detail"),
        "stop_reason": row.get("stop_reason"),
        "answer": row.get("answer"),
        "steps": row.get("steps"),
        "wall_s": row.get("wall_s"),
        "tokens": {"input": row.get("input_tokens"), "output": row.get("output_tokens"),
                   "cache_read": row.get("cache_read_tokens")},
        "cost_usd": row.get("cost_usd"),
    }


def job_id(job: dict) -> str:
    r = job["row"]
    return "%s__%s__%s__%s__r%s" % (job["source"], model_key(r.get("model", "")), r["task"],
                                    r.get("cond", ""), r.get("rep", 0))


def build_trace(job: dict) -> dict:
    """job = {"source","dir","row","tasks"(sentences by id)}; a top-level function so it can be used with multiprocessing."""
    source, ep_dir, row = job["source"], job["dir"], job["row"]
    tasks = job.get("tasks") or {}
    if source == "w2c":
        sentence, calls = parse_omp_transcript(os.path.join(ep_dir, "transcript.jsonl"))
    else:
        calls = parse_claude_transcript(os.path.join(ep_dir, "transcript.jsonl"))
        sentence = (tasks.get(row["task"]) or {}).get("sentence", "")
    difficulty = (tasks.get(row["task"]) or {}).get("difficulty")
    meta = build_meta(source, ep_dir, row, sentence, difficulty)
    steps = build_steps(ep_dir, calls)
    return {"meta": meta, "steps": steps, "result": build_result(row),
            "_align": {"calls": len(calls), "steps": len(steps)}}


# ----------------------------------------------------------------- row selection

def read_jsonl(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def select_w2c_rows(rows: Iterable[dict], tasks: Iterable[str],
                    has_step_limit: Callable[[str], bool] | None = None) -> list[dict]:
    """Pick R5 episodes: rows are given in reading order, and for the same (task, cond, rep) a later
    row overrides an earlier one; rows whose task is not in the task list are dropped; a row with
    stop_reason == "timeout" whose dir contains step_limit.json becomes step_limit. Returns new rows
    sorted by (task-list order, cond, rep); the input is not modified.
    """
    if has_step_limit is None:
        def has_step_limit(d):
            return os.path.exists(os.path.join(d, "step_limit.json"))
    order = {t: i for i, t in enumerate(tasks)}
    chosen: dict[tuple, dict] = {}
    for r in rows:
        if r["task"] not in order:
            continue
        chosen[(r["task"], r["cond"], r.get("rep", 0))] = r
    out = []
    for key in sorted(chosen, key=lambda k: (order[k[0]], k[1], k[2])):
        r = dict(chosen[key])
        if r.get("stop_reason") == "timeout" and r.get("dir") and has_step_limit(r["dir"]):
            r["stop_reason"] = "step_limit"
        out.append(r)
    return out


def read_task_list(path: str) -> list[str]:
    with open(path, encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip()]


def read_tasks_json(path: str) -> dict:
    d = _read_json(path)
    return {t["id"]: t for t in d.get("tasks", [])}


def _ep_name(row: dict) -> str:
    return "%s__%s__r%s" % (row["task"], row["cond"], row.get("rep", 0))


# ---------------------------------------------------------------------- planning

def plan_w2c(archive_root: str, tasks_file: str, runs: dict | None = None,
             root: str = "") -> list[dict]:
    """List the R5 episodes to convert (cheap, transcripts are not read). Each job can be passed to build_trace."""
    runs = runs or DEFAULT_W2C_RUNS
    base = os.path.join(archive_root, root) if root else archive_root
    tasks = read_task_list(tasks_file)
    jobs = []
    for mk in sorted(runs):
        rows = []
        for sub in runs[mk]:
            p = os.path.join(base, sub, JSONL_NAME)
            if os.path.exists(p):
                rows.extend(read_jsonl(p))
        for r in select_w2c_rows(rows, tasks):
            jobs.append({"source": "w2c", "dir": r["dir"], "row": r, "tasks": {}})
    return jobs


def _plan_named(source: str, rows: list[dict], names: list, ep_roots: list[str],
                tasks: dict) -> list[dict]:
    jobs = []
    for entry in names:
        name = entry if isinstance(entry, str) else entry["name"]
        match = [r for r in rows if os.path.basename(r.get("dir", "")) == name]
        if not match:
            match = [r for r in rows if _ep_name(r) == name]
        if not match:
            raise KeyError("episode not found: %s (%s)" % (name, source))
        row = match[-1]
        d = row.get("dir") or ""
        if not os.path.isdir(d):
            d = ""
            for er in ep_roots:
                if os.path.isdir(os.path.join(er, name)):
                    d = os.path.join(er, name)
                    break
        if not d:
            raise FileNotFoundError("episode directory does not exist: %s" % name)
        jobs.append({"source": source, "dir": d, "row": row, "tasks": tasks})
    return jobs


def plan_p125(archive_root: str, names: list, tasks_json: str,
              final: str = "p125/final/" + JSONL_NAME) -> list[dict]:
    rows = read_jsonl(os.path.join(archive_root, final))
    roots = [os.path.join(archive_root, "p125", "formal_v1", "ep"),
             os.path.join(archive_root, "p125", "formal_v1_hybrid", "ep")]
    return _plan_named("p125", rows, names, roots, read_tasks_json(tasks_json))


def plan_w2(archive_root: str, names: list, tasks_json: str,
            jsonl: str = "p127/w2/formal/" + JSONL_NAME) -> list[dict]:
    rows = read_jsonl(os.path.join(archive_root, jsonl))
    roots = [os.path.join(archive_root, "p127", "w2", "formal", "ep")]
    return _plan_named("w2", rows, names, roots, read_tasks_json(tasks_json))


def load_w2c(archive_root: str, tasks_file: str, runs: dict | None = None,
             root: str = "") -> list[dict]:
    return [build_trace(j) for j in plan_w2c(archive_root, tasks_file, runs, root)]


def load_p125(archive_root: str, names: list, tasks_json: str, **kw) -> list[dict]:
    return [build_trace(j) for j in plan_p125(archive_root, names, tasks_json, **kw)]


def load_w2(archive_root: str, names: list, tasks_json: str, **kw) -> list[dict]:
    return [build_trace(j) for j in plan_w2(archive_root, names, tasks_json, **kw)]
