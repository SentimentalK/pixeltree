"""OMP (oh-my-pi, `omp` v18.16) side of R5: models, episode workspace, command line, JSON-event scan,
lockdown and quota rules.  Standard library only.

One episode = one `omp -p --mode json` run in a fresh neutral cwd /tmp/pixeltree_agent/<episode>/ that holds only
`.mcp.json` (the bench MCP server of the episode; OMP reads a project `.mcp.json` from the cwd).  Lockdown:
  * `--no-tools` (no built-in tool), `--no-extensions` (no user extension; the R5 hook is passed with -e),
    `--no-skills --no-rules --no-context-files --no-lsp --no-title`, `--no-session` (nothing saved);
  * the overlay `omp_overlay.yml` (`--config`, this run only): no intent argument, no model fallback, no compaction,
    no loop guards / auto-continue, no image description for text-only models, no image resizing;
  * the hook `omp_prompt.ts` sets the system prompt of every provider request to the R1 text (OMP otherwise appends
    its own <project-context> / <critical> blocks), drops OMP's date / cwd reminder, and logs per request the
    system-prompt hash, the offered tool names and the inline image sizes (`requests.jsonl`);
  * OMP sends the tool calls of one model message to the MCP server concurrently (MCP tools are not "exclusive");
    the R5 MCP server (bench.shells.omp.mcp_server) executes them one at a time in request order, as claude -p did;
  * after the episode `scan_events` lists every tool call the model made (assistant toolCall blocks and
    tool_execution events); any call that is not one of the six bench tools makes the episode invalid.
"""
import hashlib
import json
import os
import re
from pathlib import Path

OMP = "omp"
HERE = Path(__file__).resolve().parent
OVERLAY = HERE / "omp_overlay.yml"
HOOK = HERE / "omp_prompt.ts"
SERVER = "p125"
SIX = ("observe", "click", "type", "key", "scroll", "done")
P125_TOOLS = tuple(f"mcp__{SERVER}_{t}" for t in SIX)
IMAGE_CONDS = ("S_shot", "H_ours")

# R5 models: thinking = the lowest level above off / minimal that the model lists in `omp models opencode-go`.
MODELS = {
    "glm": {"id": "opencode-go/glm-5.3-flash", "thinking": "low", "images": True,
            "conds": ("S_shot", "T_ours", "H_ours")},
    "deepseek": {"id": "opencode-go/deepseek-v4.1-flash", "thinking": "low", "images": True,
                 "conds": ("S_shot", "T_ours", "H_ours")},
    "longcat": {"id": "opencode-go/longcat-2.0", "thinking": "low", "images": False,
                "conds": ("T_ours", "T_atspi")},
    "haiku": {"id": "opencode-go/claude-haiku-5-5", "thinking": "low", "images": True,
              "conds": ("S_shot", "T_ours", "H_ours")},
}

_QUOTA_RE = re.compile(r"quota|rate.?limit|\b429\b|too many requests|usage limit|limit (?:reached|exceeded)|"
                       r"insufficient.?(?:balance|credit)|exhausted|subscription|billing|payment required|\b402\b",
                       re.I)


def is_quota_error(text):
    return bool(text) and bool(_QUOTA_RE.search(str(text)))


def classify_call(name):
    """'p125' for one of the six bench tools, else 'foreign' (the episode is invalid)."""
    return "p125" if name in P125_TOOLS else "foreign"


# ---------------------------------------------------------------- workspace and command
def write_workspace(cwd, server_cmd, server_env):
    """<cwd>/.mcp.json with the bench server only."""
    cfg = {"mcpServers": {SERVER: {"command": server_cmd[0], "args": list(server_cmd[1:]), "env": dict(server_env)}}}
    path = Path(cwd) / ".mcp.json"
    path.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    return path


def command(prompt, model_id, thinking):
    return [OMP, "-p", "--mode", "json", "--no-session", "--model", model_id, "--thinking", thinking,
            "--config", str(OVERLAY), "--no-tools", "--no-extensions", "-e", str(HOOK), "--no-skills", "--no-rules",
            "--no-context-files", "--no-lsp", "--no-title",
            "--system-prompt", "(replaced by the R5 hook)", prompt]


def omp_env(system_prompt, request_log):
    """Environment of the omp process: the caller's minus X / Wayland / request-debug variables, plus the two
    R5 hook variables."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("DISPLAY", "WAYLAND_DISPLAY", "WAYLAND_SOCKET", "QT_QPA_PLATFORM_PLUGIN_PATH",
                        "QT_PLUGIN_PATH", "PI_REQ_DEBUG")}
    env["BENCH_OMP_SYSTEM_PROMPT"] = system_prompt
    env["BENCH_OMP_REQUEST_LOG"] = str(request_log)
    env["BENCH_OMP_CALL_LOG"] = str(Path(request_log).with_name("calls.jsonl"))   # read by bench.shells.omp.mcp_server
    return env


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- JSON events
def read_events(path):
    out = []
    try:
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                out.append(event)
    except OSError:
        pass
    return out


def _text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def scan_events(events):
    """Everything the runner needs from one `omp --mode json` stdout.

    Tool calls: every assistant `toolCall` block (what the model asked for, executed or not), matched by id with
    the `tool_execution_end` event (isError).  Calls OMP executed without a matching assistant block (should not
    happen) are added from `tool_execution_start`.  Usage: the sum over assistant `message_end` events."""
    calls = {}
    order = []
    model_calls = 0
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0,
             "reasoning_tokens": 0, "cost_usd": 0.0}
    errors = []
    final_text = ""
    last_stop = None
    session_cwd = ""
    for e in events:
        t = e.get("type")
        if t == "session":
            session_cwd = session_cwd or e.get("cwd") or ""
        elif t == "message_end" and (e.get("message") or {}).get("role") == "assistant":
            m = e["message"]
            model_calls += 1
            u = m.get("usage") or {}
            usage["input_tokens"] += int(u.get("input") or 0)
            usage["output_tokens"] += int(u.get("output") or 0)
            usage["cache_read_tokens"] += int(u.get("cacheRead") or 0)
            usage["cache_write_tokens"] += int(u.get("cacheWrite") or 0)
            usage["reasoning_tokens"] += int(u.get("reasoningTokens") or 0)
            usage["cost_usd"] += float(((u.get("cost") or {}).get("total")) or 0.0)
            last_stop = m.get("stopReason")
            if m.get("stopReason") in ("error", "aborted") or m.get("errorMessage"):
                errors.append(str(m.get("errorMessage") or m.get("stopReason")))
            text = _text_of(m.get("content"))
            if text:
                final_text = text
            for b in m.get("content") or []:
                if isinstance(b, dict) and b.get("type") == "toolCall":
                    cid = b.get("id") or f"anon{len(order)}"
                    if cid not in calls:
                        order.append(cid)
                    calls[cid] = {"name": b.get("name"), "args": b.get("arguments"), "executed": False,
                                  "is_error": None}
        elif t == "tool_execution_start":
            cid = e.get("toolCallId") or f"exec{len(order)}"
            if cid not in calls:
                order.append(cid)
                calls[cid] = {"name": e.get("toolName"), "args": e.get("args"), "executed": False, "is_error": None}
            calls[cid]["executed"] = True
        elif t == "tool_execution_end":
            cid = e.get("toolCallId")
            if cid in calls:
                calls[cid]["executed"] = True
                calls[cid]["is_error"] = bool(e.get("isError"))
        elif t in ("error", "agent_error"):
            errors.append(str(e.get("error") or e.get("message") or e))
    ordered = [dict(calls[c], id=c, kind=classify_call(calls[c]["name"])) for c in order]
    counts = {}
    for c in ordered:
        counts[c["name"]] = counts.get(c["name"], 0) + 1
    usage["cost_usd"] = round(usage["cost_usd"], 6)
    return {
        "calls": ordered,
        "tool_counts": counts,
        "foreign_calls": [{"name": c["name"], "args": c["args"], "executed": c["executed"],
                           "is_error": c["is_error"]} for c in ordered if c["kind"] == "foreign"],
        "n_p125_calls": sum(1 for c in ordered if c["kind"] == "p125"),
        "n_model_calls": model_calls,
        "usage": usage,
        "errors": errors,
        "last_stop": last_stop,
        "final_text": final_text,
        "has_end": any(e.get("type") == "agent_end" for e in events),
        "session_cwd": session_cwd,
    }


def scan_stream(path):
    return scan_events(read_events(path))


def invalid(scan):
    """An episode is invalid when the model called any tool outside the six bench tools."""
    return bool(scan["foreign_calls"])


def read_requests(path):
    """The hook's per-request log (list of dicts)."""
    return read_events(path)


def requests_ok(requests, system_prompt):
    """(ok, reason): every provider request carried exactly the R1 system prompt and only the six bench tools."""
    if not requests:
        return False, "no request logged by the R5 hook"
    want = sha256(system_prompt)
    for r in requests:
        if r.get("system_sha256") != want:
            return False, "system prompt hash differs"
        if sorted(r.get("tools") or []) != sorted(P125_TOOLS):
            return False, f"tools offered: {r.get('tools')}"
    return True, ""
