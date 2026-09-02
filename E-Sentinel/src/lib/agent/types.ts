/**
 * ReAct 质检 Agent 的类型定义。
 */

export interface ToolResult {
  ok: boolean;
  output: unknown;
  error?: string;
}

export interface ToolExecutor {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
  /** 执行工具，参数已由 schema 校验。返回可 JSON 序列化的结果。 */
  execute(args: Record<string, unknown>): Promise<ToolResult> | ToolResult;
}

export interface AgentTurnTrace {
  turn: number;
  thought: string | null;
  toolCalls: Array<{ name: string; arguments: string }>;
  toolResults: Array<{ name: string; ok: boolean; summary: string }>;
}

export type AgentMode = "agent" | "agent-fallback" | "single-shot";

export interface AgentResult {
  /** 最终 LLM 回答文本（含最终质检 JSON）。 */
  content: string;
  mode: AgentMode;
  /** 执行的轮数（agent 路径）。 */
  turns: number;
  toolsUsed: string[];
  traces: AgentTurnTrace[];
}

// ── Agent 调查员输出（ADR-0003 5 层架构：第 4 层） ───────────────
// Agent 是 investigator/orchestrator，无 finalRisk 写权限。
// 只能返回证据、政策发现、升级提议（需证据背书）、冲突标记与人工复核请求。

export interface AgentPolicyFinding {
  rule: string;
  matched: string;
  citation?: string;
}

export interface AgentEvidenceItem {
  type: "compliance" | "policy" | "correction" | "privacy" | "threat";
  content: string;
  source?: string;
}

export interface AgentEvidence {
  /** 工具收集的证据片段（不含最终风险判定）。 */
  evidence: AgentEvidenceItem[];
  /** 检索到的政策规则与命中原文。 */
  policyFindings: AgentPolicyFinding[];
  /** 升级提议：仅在发现基线遗漏的严重违规时提供，需附证据。 */
  proposedEscalation?: "high" | "critical";
  /** 支持升级提议的对话原文证据。 */
  escalationEvidence?: string[];
  /** 工具证据与基线判定冲突。 */
  evidenceConflict?: boolean;
  /** 需要人工复核。 */
  requiresHumanReview?: boolean;
  /** 知识可用性：ok=检索成功 / insufficient=无结果 / unavailable=服务不可用。 */
  knowledgeStatus: "ok" | "insufficient" | "unavailable";
}
