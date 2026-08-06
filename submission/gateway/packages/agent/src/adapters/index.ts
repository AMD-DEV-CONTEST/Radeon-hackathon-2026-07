import type { AgentAdapter, AdapterType } from "../stream-events";
import { createClaudeCodeAdapter } from "./claude-code";
import { createCodexAdapter } from "./codex";
import { createReasonixAdapter } from "./reasonix";

export function createAdapter(
  type: AdapterType,
  sessionId: string,
  agentId: string,
): AgentAdapter {
  switch (type) {
    case "claude-code": return createClaudeCodeAdapter(sessionId, agentId);
    case "codex":       return createCodexAdapter(sessionId, agentId);
    case "reasonix":    return createReasonixAdapter(sessionId, agentId);
  }
}

export type { AgentAdapter, AdapterType } from "../stream-events";
export type { AgentStreamEvent } from "../stream-events";
