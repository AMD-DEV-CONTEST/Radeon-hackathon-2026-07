/**
 * Provider-neutral agent abstraction.
 *
 * Any LLM provider (Claude, OpenAI, a local model, etc.) implements the
 * `AgentProvider` interface and is wired in via `lib/agent/index.ts`.
 * The provider owns its own message format and agentic tool-call loop, and
 * invokes the shared `executeTool` callback (injected per call) to actually
 * run tools — so tool definitions and database side effects stay provider-neutral.
 */

/** Provider-neutral tool definition (JSON-schema based input). */
export interface ToolSpec {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
}

/** A simple user/assistant text message. */
export interface AgentMessage {
  role: 'user' | 'assistant';
  content: string;
}

/** Result returned by executing a tool, consumed by both UI and provider. */
export interface ToolExecutionResult {
  /** Text fed back to the model as the tool result. */
  toolResult: string;
  /** Short human label shown in the UI tool chip. */
  clientSummary: string;
  /** Optional long text streamed to the user (contracts / follow-ups). */
  displayText?: string;
}

/** Function that actually runs a tool (DB writes, template generation, etc.). */
export type ToolExecutor = (
  name: string,
  input: Record<string, unknown>
) => Promise<ToolExecutionResult>;

/** Callbacks used to stream output to the UI while the agent runs. */
export interface AgentStreamCallbacks {
  onText: (delta: string) => void;
  onTool?: (name: string, summary: string) => void;
}

export interface RunStreamParams {
  system: string;
  messages: AgentMessage[];
  tools: ToolSpec[];
  executeTool: ToolExecutor;
  callbacks: AgentStreamCallbacks;
}

/** A pluggable agent provider. */
export interface AgentProvider {
  readonly name: string;
  /**
   * Run the agentic streaming loop: stream tokens to `callbacks.onText`,
   * execute any tool calls via `params.executeTool`, feed results back to the
   * model, and repeat until the model stops calling tools. Returns the full
   * text that was shown to the user (for persistence).
   */
  runStream(params: RunStreamParams): Promise<string>;
}

// ─── Subagent & Router types (Phase 3-4, pre-defined to avoid rework) ─────────

/** Subagent identifiers — each maps to a vertical domain. */
export type SubagentId =
  | 'general'           // Default: project management, CRM, contracts
  | 'knowledge_rag'     // Local knowledge base search (TF-IDF)
  | 'data_analysis'     // Pandas/SQL-style data queries
  | 'writing_assistant' // Email, report, document generation
  | 'blockchain'        // Casper blockchain queries
  | 'quick_chat';       // Lightweight chitchat, zero tools

/** Configuration for a vertical Subagent. */
export interface SubagentConfig {
  id: SubagentId;
  /** Human-readable name shown in trace UI */
  label: string;
  /** Keywords that trigger this subagent (used by FunctionRouter Layer 1) */
  routingKeywords: string[];
  /** Example queries for LLM intent classification (used by FunctionRouter Layer 2) */
  routingExamples: string[];
  /** System prompt suffix specific to this subagent's domain */
  systemPrompt: string;
  /** Tool names this subagent can use (empty = no tools, just chat) */
  tools: string[];
  /** Whether this is a lightweight subagent (skip heavy tools, fast response) */
  lightweight?: boolean;
}

/** Result of FunctionRouter routing decision. */
export interface RouteResult {
  subagent: SubagentId;
  /** Confidence score 0-1 */
  confidence: number;
  /** Which layer made the decision: 'keyword' (fast) or 'llm' (fallback) */
  routedBy: 'keyword' | 'llm' | 'default';
  /** Human-readable reason for trace UI */
  reason: string;
}

// ─── Trace types (Phase 5, pre-defined to avoid rework) ────────────────────────

/** A single trace event in the agent execution flow. */
export interface TraceEvent {
  timestamp: number;
  type: 'route' | 'llm_call' | 'tool_call' | 'tool_result' | 'text_stream' | 'error';
  subagent?: SubagentId;
  data: Record<string, unknown>;
}

/** A complete trace for one user turn. */
export interface Trace {
  id: string;
  startTime: number;
  endTime?: number;
  events: TraceEvent[];
  routeResult?: RouteResult;
  /** Total tokens consumed (if available) */
  tokenCount?: number;
  /** True for pre-seeded demo traces (DEMO_MODE only). Removed once real traces exist. */
  isSeedData?: boolean;
}

// ─── Router self-learning types (Phase 6 — feedback-driven weight tuning) ─────

/**
 * A single piece of user feedback on a routing decision.
 *
 * When the router picks the wrong Subagent, the user (or UI) records what the
 * correct Subagent should have been. The learning module uses this to nudge
 * keyword weights so the same mistake is less likely next time.
 */
export interface RouterFeedback {
  /** The original user message that was routed. */
  message: string;
  /** The Subagent the user believes should have handled the message. */
  correctSubagent: SubagentId;
  /** The Subagent the router actually selected. */
  originalSubagent: SubagentId;
  /** When the feedback was recorded (epoch ms). */
  timestamp: number;
}

/**
 * A learned weight adjustment for a single (subagent, keyword) pair.
 *
 * The `weight` is a multiplier applied to that keyword's contribution during
 * routing. It starts at 1.0 (neutral) and drifts within [0.1, 2.0] as the
 * system accumulates feedback.
 */
export interface WeightAdjustment {
  subagentId: SubagentId;
  keyword: string;
  /** Current multiplier weight, clamped to [0.1, 2.0]. */
  weight: number;
  /** How many feedback events touched this keyword. */
  adjustmentCount: number;
}
