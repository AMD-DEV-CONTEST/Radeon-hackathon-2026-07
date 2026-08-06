// P3-0 §3 — AgentStreamEvent unified type definitions
// All CLI adapters produce this format; Streaming Gateway forwards it as SSE.

export type AgentOutputType =
  | "init"
  | "thinking"
  | "tool_use"
  | "tool_result"
  | "text"
  | "warning"
  | "error"
  | "phase"
  | "block"
  | "finish"
  | "done"
  | "heartbeat";

export interface AgentStreamEvent {
  session_id: string;
  msg_id: string;
  agent_id: string;
  type: AgentOutputType;
  payload: Record<string, unknown>;
  timestamp: string; // ISO8601
}

export interface ToolUsePayload {
  tool_id: string;
  tool_name: string;
  input: Record<string, unknown>;
}

export interface ToolResultPayload {
  tool_id: string;
  content: string;
  error?: string;
}

export interface PhasePayload {
  phase: "plan" | "execute" | "review" | "acceptance";
  status: "start" | "end";
}

export interface BlockPayload {
  block_type: "auth" | "rate_limit" | "env" | "permission";
  message: string;
  blocked_until?: string;
}

export interface FinishPayload {
  summary: string;
  artifacts: string[];
}

export interface DonePayload {
  usage: { input_tokens: number; output_tokens: number };
  duration_ms: number;
}

/** Adapter interface — one implementation per CLI type (P3-0 §3.1). */
export interface AgentAdapter {
  /** Process one raw stdout/stderr line; returns 0-N unified events. */
  adapt(rawLine: string): AgentStreamEvent[];
  /** Flush internal buffer on process exit. */
  flush(): AgentStreamEvent[];
}

export type AdapterType = "claude-code" | "codex" | "reasonix";
