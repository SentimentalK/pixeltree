// R5: OMP extension loaded with `omp -e <this file>` for every R5 episode (never installed globally).
//
// OMP's --system-prompt does not replace the whole system prompt: it appends a <project-context> (OS, arch, model)
// and a <critical> block ("MUST advance the task", "verify ... run the specific test"), and it prefixes the first
// user message with a <system-reminder> (date + cwd).  R1's `claude -p --system-prompt` sent the R1 text alone.
// This hook rewrites the final provider request so that:
//   * the system prompt is exactly $BENCH_OMP_SYSTEM_PROMPT (the R1 text of the condition),
//   * the date / cwd <system-reminder> text block is removed from user messages,
// and appends one JSON line per request to $BENCH_OMP_REQUEST_LOG: sha256 of the system prompt actually sent, the tool
// names offered, the message count and whether a reminder was removed (lockdown + prompt evidence; no headers, no
// credentials, no message bodies).
import { createHash } from "node:crypto";
import { appendFileSync } from "node:fs";

const REMINDER = /^\s*<system-reminder>\s*Today:/;

function stripReminders(content: any): [any, number] {
  if (!Array.isArray(content)) return [content, 0];
  const kept = content.filter((b: any) => !(b && b.type === "text" && typeof b.text === "string" && REMINDER.test(b.text)));
  return [kept, content.length - kept.length];
}

// width x height of every inline PNG / JPEG the request carries (openai image_url data URLs, anthropic base64 sources)
function imageSizes(payload: any): string[] {
  const out: string[] = [];
  const visit = (v: any) => {
    if (!v || typeof v !== "object") return;
    if (Array.isArray(v)) { v.forEach(visit); return; }
    let b64: string | undefined;
    const url = v?.image_url?.url ?? (typeof v?.image_url === "string" ? v.image_url : undefined);
    if (typeof url === "string" && url.startsWith("data:")) b64 = url.slice(url.indexOf(",") + 1);
    if (v?.type === "image" && v?.source?.type === "base64") b64 = v.source.data;
    if (b64) {
      const buf = Buffer.from(b64.slice(0, 64), "base64");
      if (buf[0] === 0x89 && buf[1] === 0x50) out.push(`png ${buf.readUInt32BE(16)}x${buf.readUInt32BE(20)}`);
      else out.push(`other ${b64.length}b64`);
      return;
    }
    for (const k of Object.keys(v)) visit(v[k]);
  };
  visit(payload?.messages);
  return out;
}

function toolNames(payload: any): string[] {
  const tools = Array.isArray(payload?.tools) ? payload.tools : [];
  return tools.map((t: any) => t?.function?.name ?? t?.name ?? "?");
}

export default function (pi: any) {
  // Tool calls of one message: OMP sends them to the MCP server concurrently; this hook runs once per call, in the
  // order the model wrote them, before the call is sent.  It records that order in $BENCH_OMP_CALL_LOG; the R5 MCP server
  // (bench/shells/omp/mcp_server.py) executes calls in this order.  No waiting here (OMP times extension handlers out).
  let seq = 0;
  pi.on("tool_call", async (event: any) => {
    const log = process.env.BENCH_OMP_CALL_LOG;
    seq += 1;
    if (log) {
      try {
        appendFileSync(log, JSON.stringify({ n: seq, id: event?.toolCallId, tool: event?.toolName, input: event?.input ?? {}, t: Date.now() }) + "\n");
      } catch {}
    }
    return undefined;
  });

  pi.on("before_provider_request", async (event: any) => {
    const sp = process.env.BENCH_OMP_SYSTEM_PROMPT;
    const payload = event?.payload;
    if (!sp || !payload || typeof payload !== "object") return undefined;
    let removed = 0;
    let mode = "none";
    if (Array.isArray(payload.messages)) {
      const msgs: any[] = [];
      for (const m of payload.messages) {
        if (m && (m.role === "system" || m.role === "developer")) continue;   // dropped, re-added once below
        if (m && m.role === "user") {
          const [c, n] = stripReminders(m.content);
          removed += n;
          if (n && Array.isArray(c) && c.length === 0) continue;
          msgs.push(n ? { ...m, content: c } : m);
        } else {
          msgs.push(m);
        }
      }
      if (payload.system !== undefined) {           // anthropic-messages shape
        const first = Array.isArray(payload.system) ? payload.system[0] : undefined;
        payload.system = [{ type: "text", text: sp, ...(first?.cache_control ? { cache_control: first.cache_control } : {}) }];
        payload.messages = msgs;
        mode = "anthropic";
      } else {                                      // openai-completions shape
        payload.messages = [{ role: "system", content: sp }, ...msgs];
        mode = "openai";
      }
    } else if (Array.isArray(payload.input)) {      // openai-responses shape
      payload.instructions = sp;
      payload.input = payload.input.filter((m: any) => !(m && (m.role === "system" || m.role === "developer")));
      mode = "responses";
    }
    const log = process.env.BENCH_OMP_REQUEST_LOG;
    if (log) {
      try {
        appendFileSync(log, JSON.stringify({
          t: Date.now(), mode, model: payload.model, system_sha256: createHash("sha256").update(sp).digest("hex"),
          tools: toolNames(payload), n_messages: Array.isArray(payload.messages) ? payload.messages.length : null,
          reminders_removed: removed, images: imageSizes(payload), reasoning_effort: payload.reasoning_effort ?? payload.thinking ?? null,
        }) + "\n");
      } catch {}
    }
    return payload;
  });
}
