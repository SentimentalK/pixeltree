"""Readers of the `claude -p` stream-json transcript: final answer, cost, tool calls and token totals."""
from __future__ import annotations

import json
from pathlib import Path


def parse_transcript(path):
    """Return (agent_final, cost_usd, num_turns, tool_calls) from a stream-json transcript."""
    agent_final = ""
    cost = None
    turns = None
    calls = []
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return agent_final, cost, turns, calls
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "assistant":
            message = event.get("message") or {}
            for block in message.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    calls.append({"name": block.get("name"), "input": block.get("input")})
        elif event.get("type") == "result":
            agent_final = event.get("result") or agent_final
            cost = event.get("total_cost_usd", cost)
            turns = event.get("num_turns", turns)
    return agent_final, cost, turns, calls


def parse_usage(path):
    """Token totals from the stream-json result event: input / output / cache read / cache write / total."""
    usage = {}
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "result" and isinstance(event.get("usage"), dict):
            usage = event["usage"]
    fields = {
        "input_tokens": int(usage.get("input_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or 0),
        "cache_read_tokens": int(usage.get("cache_read_input_tokens") or 0),
        "cache_write_tokens": int(usage.get("cache_creation_input_tokens") or 0),
    }
    fields["total_tokens"] = sum(fields.values())
    return fields

