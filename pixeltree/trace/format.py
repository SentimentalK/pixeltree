"""Reading and writing episode traces.

One episode = one directory:
  meta.json    written once when the episode starts
  steps.jsonl  one line appended per step
  result.json  written when the episode ends; absent = still running

See docs/trace_format.md for the fields. Path fields may be absolute or relative to the trace
directory; large files (screenshots) are referenced, never embedded.
"""

from __future__ import annotations

import json
import os
from typing import Any

FORMAT = "pixeltree.trace/1"

META_KEYS = (
    "format", "id", "source", "task", "model", "condition", "shell", "rep",
    "started_at", "screen_size", "agent_image_size", "observation",
)
STEP_KEYS = (
    "i", "t_start", "t_end", "duration_s", "action", "agent", "observation",
    "screen", "tree",
)
RESULT_KEYS = (
    "ok", "grader", "grader_detail", "stop_reason", "answer", "steps", "wall_s",
    "tokens", "cost_usd",
)

Trace = dict  # {"meta": dict, "steps": list[dict], "result": dict | None}


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def make_step(i: int, *, tool: str, args: dict | None = None, screen_xy=None,
              ok: bool = True, error: str | None = None,
              t_start: float | None = None, t_end: float | None = None,
              text: str = "", thinking: str = "", message_index: int | None = None,
              obs_text: str = "", obs_image: str | None = None,
              screen: str | None = None, tree: dict | None = None) -> dict:
    """Assemble one step in the trace format (used by live recorders and by the adapters)."""
    duration = None
    if t_start is not None and t_end is not None:
        duration = round(t_end - t_start, 3)
    return {
        "i": i,
        "t_start": t_start,
        "t_end": t_end,
        "duration_s": duration,
        "action": {"tool": tool, "args": args or {}, "screen_xy": screen_xy,
                   "ok": ok, "error": error},
        "agent": {"text": text, "thinking": thinking, "message_index": message_index},
        "observation": {"text": obs_text, "image": obs_image},
        "screen": screen,
        "tree": tree,
    }


def write_trace(dir: str, meta: dict, steps: list[dict], result: dict | None) -> None:
    """Write a whole episode at once. With result=None no result.json is written (= still running)."""
    os.makedirs(dir, exist_ok=True)
    with open(os.path.join(dir, "meta.json"), "w", encoding="utf-8") as f:
        f.write(dumps(meta) + "\n")
    with open(os.path.join(dir, "steps.jsonl"), "w", encoding="utf-8") as f:
        for s in steps:
            f.write(dumps(s) + "\n")
    rp = os.path.join(dir, "result.json")
    if result is not None:
        with open(rp, "w", encoding="utf-8") as f:
            f.write(dumps(result) + "\n")
    elif os.path.exists(rp):
        os.remove(rp)


def append_step(dir: str, step: dict) -> None:
    """Live mode: append one step while the episode runs."""
    os.makedirs(dir, exist_ok=True)
    with open(os.path.join(dir, "steps.jsonl"), "a", encoding="utf-8") as f:
        f.write(dumps(step) + "\n")


def read_trace(dir: str) -> Trace:
    with open(os.path.join(dir, "meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    steps = []
    sp = os.path.join(dir, "steps.jsonl")
    if os.path.exists(sp):
        with open(sp, encoding="utf-8") as f:
            steps = [json.loads(line) for line in f if line.strip()]
    result = None
    rp = os.path.join(dir, "result.json")
    if os.path.exists(rp):
        with open(rp, encoding="utf-8") as f:
            result = json.load(f)
    return {"meta": meta, "steps": steps, "result": result}


def resolve_path(trace_dir: str, p: str | None) -> str | None:
    """Path fields: absolute paths are returned as is, relative ones are resolved against the trace directory."""
    if p is None:
        return None
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(trace_dir, p))
