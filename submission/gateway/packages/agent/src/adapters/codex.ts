// Codex CLI adapter — P3-A2
// Parses Codex CLI JSON output line-by-line into AgentStreamEvent (P3-0 §3).

import { randomUUID } from "crypto";
import type { AgentAdapter, AgentStreamEvent } from "../stream-events";

function mkEvent(
  sessionId: string,
  agentId: string,
  type: AgentStreamEvent["type"],
  payload: Record<string, unknown>,
): AgentStreamEvent {
  return {
    session_id: sessionId,
    msg_id: randomUUID(),
    agent_id: agentId,
    type,
    payload,
    timestamp: new Date().toISOString(),
  };
}

export function createCodexAdapter(sessionId: string, agentId: string): AgentAdapter {
  let startMs = Date.now();
  let textBuffer = "";

  return {
    adapt(rawLine: string): AgentStreamEvent[] {
      const line = rawLine.trimEnd();
      if (!line) return [];

      let obj: Record<string, unknown>;
      try {
        obj = JSON.parse(line);
      } catch {
        return [mkEvent(sessionId, agentId, "text", { content: line })];
      }

      const events: AgentStreamEvent[] = [];
      const type = obj["type"] as string | undefined;

      if (type === "session_start" || type === "init") {
        startMs = Date.now();
        events.push(mkEvent(sessionId, agentId, "init", {
          agent_name: "codex",
          agent_type: "codex",
          tools: (obj["tools"] as string[]) ?? [],
          model: String(obj["model"] ?? "gpt"),
        }));
      } else if (type === "function_call" || type === "tool_call") {
        if (textBuffer) {
          events.push(mkEvent(sessionId, agentId, "text", { content: textBuffer }));
          textBuffer = "";
        }
        events.push(mkEvent(sessionId, agentId, "tool_use", {
          tool_id: String(obj["id"] ?? obj["call_id"] ?? randomUUID()),
          tool_name: String(obj["name"] ?? obj["function"] ?? ""),
          input: (obj["arguments"] ?? obj["input"] ?? {}) as Record<string, unknown>,
        }));
      } else if (type === "function_call_output" || type === "tool_result") {
        events.push(mkEvent(sessionId, agentId, "tool_result", {
          tool_id: String(obj["call_id"] ?? obj["tool_use_id"] ?? ""),
          content: String(obj["output"] ?? obj["content"] ?? ""),
          error: obj["error"] ? String(obj["error"]) : undefined,
        }));
      } else if (type === "message" || type === "assistant") {
        const content = String(obj["content"] ?? obj["text"] ?? "");
        if (content) events.push(mkEvent(sessionId, agentId, "text", { content }));
      } else if (type === "reasoning" || type === "thinking") {
        events.push(mkEvent(sessionId, agentId, "thinking", {
          content: String(obj["content"] ?? obj["text"] ?? ""),
        }));
      } else if (type === "done" || type === "completed") {
        if (textBuffer) {
          events.push(mkEvent(sessionId, agentId, "text", { content: textBuffer }));
          textBuffer = "";
        }
        const usage = (obj["usage"] ?? {}) as Record<string, unknown>;
        events.push(mkEvent(sessionId, agentId, "done", {
          usage: {
            input_tokens: Number(usage["input_tokens"] ?? usage["prompt_tokens"] ?? 0),
            output_tokens: Number(usage["output_tokens"] ?? usage["completion_tokens"] ?? 0),
          },
          duration_ms: Date.now() - startMs,
        }));
      } else if (type === "error") {
        events.push(mkEvent(sessionId, agentId, "error", {
          message: String(obj["message"] ?? obj["error"] ?? line),
          recoverable: Boolean(obj["recoverable"] ?? false),
        }));
      } else {
        const text = String(obj["text"] ?? obj["content"] ?? "");
        if (text) events.push(mkEvent(sessionId, agentId, "text", { content: text }));
      }

      return events;
    },

    flush(): AgentStreamEvent[] {
      const events: AgentStreamEvent[] = [];
      if (textBuffer) {
        events.push(mkEvent(sessionId, agentId, "text", { content: textBuffer }));
        textBuffer = "";
      }
      return events;
    },
  };
}
