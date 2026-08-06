// Reasonix (ua-agent) adapter — P3-A2
// Parses ua-agent log output into AgentStreamEvent (P3-0 §3.3).
//
// ua-agent emits lines like:
//   [agent] INFO  turn=3/30
//   [tool]  INFO  read_file path=/workspace/main.py
//   [tool]  OK    lines=123
//   [session] INFO  FINISH turn=4 summary=Created hello.txt
//   <<<FINISH>>>\nsummary: Done\nartifacts: main.py
//   <<<BLOCK>>>\ntype: blocked_auth\nmessage: token expired

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

function parseKV(s: string): Record<string, string> {
  const result: Record<string, string> = {};
  for (const m of s.matchAll(/(\w+)=([^\s]+)/g)) {
    result[m[1]] = m[2];
  }
  return result;
}

function parseColon(lines: string[]): Record<string, string> {
  const result: Record<string, string> = {};
  for (const line of lines) {
    const idx = line.indexOf(": ");
    if (idx !== -1) result[line.slice(0, idx).trim()] = line.slice(idx + 2).trim();
  }
  return result;
}

export function createReasonixAdapter(sessionId: string, agentId: string): AgentAdapter {
  // Multi-line signal accumulation (<<<FINISH>>> / <<<BLOCK>>>)
  let signalType: "FINISH" | "BLOCK" | null = null;
  const signalLines: string[] = [];

  function flushSignal(): AgentStreamEvent[] {
    if (!signalType) return [];
    const kv = parseColon(signalLines);
    const type = signalType;
    signalType = null;
    signalLines.length = 0;

    if (type === "FINISH") {
      const artifacts = (kv["artifacts"] ?? "")
        .split(",").map(s => s.trim()).filter(Boolean);
      return [mkEvent(sessionId, agentId, "finish", {
        summary: kv["summary"] ?? "",
        artifacts,
      })];
    }
    // BLOCK
    return [mkEvent(sessionId, agentId, "block", {
      block_type: kv["type"] ?? "env",
      message: kv["message"] ?? "",
      blocked_until: kv["blocked_until"],
    })];
  }

  return {
    adapt(rawLine: string): AgentStreamEvent[] {
      const line = rawLine.trimEnd();
      if (!line) return [];

      // Signal markers
      if (line === "<<<FINISH>>>") {
        const prev = flushSignal();
        signalType = "FINISH";
        signalLines.length = 0;
        return prev;
      }
      if (line === "<<<BLOCK>>>") {
        const prev = flushSignal();
        signalType = "BLOCK";
        signalLines.length = 0;
        return prev;
      }
      if (signalType !== null) {
        signalLines.push(line);
        return [];
      }

      // Inline single-line FINISH (from deepseek.ts parseFinish format)
      const inlineFinish = line.match(/<<<FINISH>>>\s*(.+)/s);
      if (inlineFinish) {
        const kv = parseColon(inlineFinish[1].split("\n"));
        const artifacts = (kv["artifacts"] ?? "")
          .split(",").map(s => s.trim()).filter(Boolean);
        return [mkEvent(sessionId, agentId, "finish", {
          summary: kv["summary"] ?? inlineFinish[1],
          artifacts,
        })];
      }

      // Structured log: [module] LEVEL rest
      const logMatch = line.match(/^\[(\w+)\]\s+(\S+)\s*(.*)/);
      if (!logMatch) {
        return [mkEvent(sessionId, agentId, "text", { content: line })];
      }

      const [, module, level, rest] = logMatch;
      const kv = parseKV(rest);
      const events: AgentStreamEvent[] = [];

      if (module === "agent") {
        if (kv["turn"]) {
          const [cur] = (kv["turn"] ?? "1/1").split("/").map(Number);
          events.push(mkEvent(sessionId, agentId, "phase", {
            phase: "execute",
            status: cur === 1 ? "start" : "end",
          }));
          if (cur > 1) {
            events.push(mkEvent(sessionId, agentId, "phase", {
              phase: "execute",
              status: "start",
            }));
          }
        } else if (level === "ERROR" || level === "WARN") {
          events.push(mkEvent(sessionId, agentId, level === "ERROR" ? "error" : "warning", {
            message: rest,
            recoverable: level === "WARN",
          }));
        }
      } else if (module === "tool") {
        if (level === "INFO" || level === "START") {
          const toolName = Object.keys(kv)[0] ?? rest.split(" ")[0] ?? "unknown";
          events.push(mkEvent(sessionId, agentId, "tool_use", {
            tool_id: randomUUID(),
            tool_name: toolName,
            input: kv as Record<string, unknown>,
          }));
        } else if (level === "OK" || level === "DONE") {
          events.push(mkEvent(sessionId, agentId, "tool_result", {
            tool_id: "",
            content: rest,
          }));
        } else if (level === "ERROR") {
          events.push(mkEvent(sessionId, agentId, "tool_result", {
            tool_id: "",
            content: "",
            error: rest,
          }));
        }
      } else if (module === "session") {
        if (rest.startsWith("FINISH")) {
          events.push(mkEvent(sessionId, agentId, "finish", {
            summary: kv["summary"] ?? rest.replace(/^FINISH\s*/, ""),
            artifacts: [],
          }));
        } else if (rest.startsWith("INIT")) {
          events.push(mkEvent(sessionId, agentId, "init", {
            agent_name: kv["name"] ?? "reasonix",
            agent_type: "reasonix",
            tools: [],
            model: kv["model"] ?? "deepseek",
          }));
        }
      } else {
        events.push(mkEvent(sessionId, agentId, "text", { content: line }));
      }

      return events;
    },

    flush(): AgentStreamEvent[] {
      return flushSignal();
    },
  };
}
