// Claude Code CLI adapter — P3-A2
// Parses `claude --output-format stream-json` line-by-line output
// into unified AgentStreamEvent (P3-0 §3.2).

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

export function createClaudeCodeAdapter(sessionId: string, agentId: string): AgentAdapter {
  let startMs = Date.now();

  return {
    adapt(rawLine: string): AgentStreamEvent[] {
      const line = rawLine.trimEnd();
      if (!line) return [];

      let obj: Record<string, unknown>;
      try {
        obj = JSON.parse(line);
      } catch {
        // Non-JSON line — emit as raw text
        return [mkEvent(sessionId, agentId, "text", { content: line })];
      }

      const events: AgentStreamEvent[] = [];
      const type = obj["type"] as string | undefined;

      if (type === "stream_event") {
        const ev = (obj["event"] ?? {}) as Record<string, unknown>;
        const evType = ev["type"] as string;

        if (evType === "message_start") {
          startMs = Date.now();
          const model = ((ev["message"] as Record<string, unknown>) ?? {})["model"] ?? "claude";
          events.push(mkEvent(sessionId, agentId, "init", {
            agent_name: "cc",
            agent_type: "claude-code",
            tools: [],
            model,
          }));
        } else if (evType === "content_block_delta") {
          const delta = (ev["delta"] ?? {}) as Record<string, unknown>;
          if (delta["type"] === "text_delta") {
            events.push(mkEvent(sessionId, agentId, "text", { content: delta["text"] ?? "" }));
          } else if (delta["type"] === "thinking_delta") {
            events.push(mkEvent(sessionId, agentId, "thinking", { content: delta["thinking"] ?? "" }));
          }
        } else if (evType === "tool_use") {
          events.push(mkEvent(sessionId, agentId, "tool_use", {
            tool_id: ev["id"] ?? "",
            tool_name: ev["name"] ?? "",
            input: (ev["input"] ?? {}) as Record<string, unknown>,
          }));
        } else if (evType === "tool_result") {
          events.push(mkEvent(sessionId, agentId, "tool_result", {
            tool_id: ev["tool_use_id"] ?? "",
            content: String(ev["content"] ?? ""),
          }));
        }
      } else if (type === "result") {
        const usage = (obj["usage"] ?? {}) as Record<string, unknown>;
        events.push(mkEvent(sessionId, agentId, "done", {
          usage: {
            input_tokens: Number(usage["input_tokens"] ?? 0),
            output_tokens: Number(usage["output_tokens"] ?? 0),
          },
          duration_ms: Date.now() - startMs,
        }));
      } else if (type === "error") {
        events.push(mkEvent(sessionId, agentId, "error", {
          message: String(obj["error"] ?? obj["message"] ?? line),
          recoverable: false,
        }));
      }

      return events;
    },

    flush(): AgentStreamEvent[] {
      return [];
    },
  };
}
