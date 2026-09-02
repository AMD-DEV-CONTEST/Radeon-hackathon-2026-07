/**
 * 质检裁判入口：useAgent 开关选择单次调用或 ReAct agent 循环。
 *
 * 向后兼容：useAgent=false 时行为与现状完全一致（单次 LLM + 返回 content）。
 * ADR-0003 5 层架构：单次语义裁判（adjudicator）+ Agent 调查员（investigator）。
 *   - runJudge(useAgent=false)  → 语义基线（adjudicator，唯一风险裁判）
 *   - runInvestigation()       → 证据收集（investigator，无 finalRisk 写权限）
 */
import type { AgentEvidence, AgentResult } from "./types";
import { runReactLoop } from "./react-loop";
import { executeTool } from "./tools";

export interface RunJudgeOptions {
  conversation: string;
  systemPrompt?: string;
  tenantId?: string;
  useAgent?: boolean;
  /** 跳过 LLM 消息缓存（稳定性评测用，强制真实独立推理）。 */
  useCache?: boolean;
  /** 供单测注入 */
  callLLMSimple?: (opts: { prompt: string; systemPrompt?: string; timeoutMs?: number; tenantId?: string; useCache?: boolean }) => Promise<string | null>;
  callLLMAdvanced?: (req: { messages: Array<{ role: string; content: string }>; tools?: unknown[]; toolChoice?: string; useCache?: boolean; timeoutMs?: number; tenantId?: string }) => Promise<{ content: string; toolCalls?: Array<{ id: string; function: { name: string; arguments: string } }> }>;
}

export interface JudgeOutcome {
  content: string;
  mode: "single-shot" | AgentResult["mode"];
  trace?: AgentResult;
  /** agent 路径的轮数（single-shot 为 0）。 */
  turns: number;
  /** agent 路径使用的工具名（single-shot 为空数组）。 */
  toolsUsed: string[];
}

export async function runJudge(options: RunJudgeOptions): Promise<JudgeOutcome> {
  const { conversation, systemPrompt, tenantId, useAgent, useCache, callLLMSimple, callLLMAdvanced } = options;

  if (!useAgent) {
    // 单次调用（现状）
    if (callLLMSimple) {
      const content = await callLLMSimple({ prompt: conversation, systemPrompt, timeoutMs: 25_000, tenantId, useCache });
      return { content: content || "", mode: "single-shot", turns: 0, toolsUsed: [] };
    }
    const { callLLM } = await import("../llm-provider");
    const content = await callLLM({ prompt: conversation, systemPrompt, timeoutMs: 25_000, tenantId, useCache });
    return { content: content || "", mode: "single-shot", turns: 0, toolsUsed: [] };
  }

  // ReAct agent 循环
  const result = await runReactLoop({
    messages: [{ role: "user", content: conversation }],
    systemPrompt,
    tenantId,
    callLLMAdvanced: callLLMAdvanced as never,
  });

  return { content: result.content, mode: result.mode, trace: result, turns: result.turns, toolsUsed: result.toolsUsed };
}

// ── Agent 调查员（ADR-0003 第 4 层） ────────────────────────────────────────

export interface InvestigationOptions {
  conversation: string;
  /** 不可修改的语义基线摘要（risk + violations），注入为调查员的初始状态。 */
  baselineSummary: string;
  tenantId?: string;
  /** 服务端调查策略要求必调的工具（由服务端确定性执行并注入结果，不依赖模型自选）。 */
  requiredTool?: string;
  /** 必调工具的检索 query（deriveRetrievalQuery 服务端推导）。 */
  requiredQuery?: string;
  /** 必调工具的检索意图（policy_qa / product_qa）。 */
  requiredIntent?: string;
  /** 供单测注入 */
  callLLMAdvanced?: (req: { messages: Array<{ role: string; content: string }>; tools?: unknown[]; toolChoice?: string | Record<string, unknown>; useCache?: boolean; timeoutMs?: number; tenantId?: string }) => Promise<{ content: string; toolCalls?: Array<{ id: string; function: { name: string; arguments: string } }> }>;
}

export interface InvestigationOutcome {
  content: string;
  mode: AgentResult["mode"];
  turns: number;
  toolsUsed: string[];
  trace?: AgentResult;
  /** 解析后的证据（不可解析时为 null，需人工复核）。 */
  parsed: AgentEvidence | null;
}

function buildInvestigatorPrompt(baselineSummary: string): string {
  return `你是客服质检调查助理。裁判官已完成风险判定，基线如下（不可修改）：
${baselineSummary}

你的职责：使用工具（合规扫描/知识检索/纠错先例）收集证据、识别额外违规、核实基线是否遗漏严重违规。
【硬性约束】
1. 不得修改或降级基线风险等级——你没有最终风险判定权，最终风险由确定性解析器决定。
2. 只能提出升级（proposedEscalation 为 "high" 或 "critical"），且必须在 escalationEvidence 中引用对话原文作为证据。
3. 检索不到知识库来源 ≠ 没有违规：knowledgeStatus 置 "insufficient" 并置 requiresHumanReview=true，绝不把空结果当作"没有违规"的负面证据。
4. 若工具证据与基线判定冲突，置 evidenceConflict=true。
5. 不要为了升级而升级；只有找到基线遗漏的具体严重违规证据才升级。
6. 升级证据必须是客服侧违规原句：escalationEvidence 至少 1 条，且必须是对话中客服话术的原文引用。
   - 客户表达不满/投诉/12315/退款/假货/二手等关键词不是违规证据；
   - 客服按流程登记、核实、给出处理时限、原路退回、安抚等合规话术不是违规，不得作为升级证据；
   - 找不到客服侧明确违规原句时，proposedEscalation 必须为 null。
7. 工具证据与基线冲突（evidenceConflict=true）时不得提出升级，应置 requiresHumanReview=true。
【输出 JSON】严格输出纯 JSON 对象，首字符必须是 {，不要包裹 markdown 代码块：
{
  "evidence": [{"type":"compliance|policy|correction|privacy|threat","content":"证据内容","source":"规则ID或来源"}],
  "policyFindings": [{"rule":"政策规则","matched":"命中原文","citation":"知识库来源"}],
  "proposedEscalation": "high 或 critical（可选，仅在发现基线遗漏的严重违规时）",
  "escalationEvidence": ["对话原文引用"],
  "evidenceConflict": false,
  "requiresHumanReview": false,
  "knowledgeStatus": "ok|insufficient|unavailable"
}`;
}

/** 从 agent 最终回答中稳健提取证据 JSON。 */
export function parseAgentEvidence(content: string): AgentEvidence | null {
  const raw = content.replace(/```json\s*/gi, "").replace(/```\s*/gi, "").trim();
  const objStart = raw.indexOf("{");
  const objEnd = raw.lastIndexOf("}");
  if (objStart === -1 || objEnd === -1 || objEnd <= objStart) return null;
  const objStr = raw.substring(objStart, objEnd + 1);
  for (const candidate of [objStr, objStr.replace(/[\x00-\x1f]/g, " ")]) {
    try {
      const parsed = JSON.parse(candidate) as Record<string, unknown>;
      const evidence = Array.isArray(parsed.evidence) ? parsed.evidence : [];
      const policyFindings = Array.isArray(parsed.policyFindings) ? parsed.policyFindings : [];
      const escalationEvidence = Array.isArray(parsed.escalationEvidence) ? parsed.escalationEvidence.map(String) : [];
      // fail-closed：仅当模型显式声明检索成功（"ok"）时视为 ok；
      // 缺失 / 拼写错误 / 未知值一律按 insufficient 处理，触发人工复核而非静默放行。
      const knowledgeStatus =
        parsed.knowledgeStatus === "ok"
          ? "ok"
          : parsed.knowledgeStatus === "unavailable"
            ? "unavailable"
            : "insufficient";
      const esc = parsed.proposedEscalation === "critical" || parsed.proposedEscalation === "high" ? (parsed.proposedEscalation as "high" | "critical") : undefined;
      return {
        evidence: evidence as AgentEvidence["evidence"],
        policyFindings: policyFindings as AgentEvidence["policyFindings"],
        proposedEscalation: esc,
        escalationEvidence,
        evidenceConflict: parsed.evidenceConflict === true,
        requiresHumanReview: parsed.requiresHumanReview === true,
        knowledgeStatus,
      };
    } catch {}
  }
  return null;
}

/**
 * Agent 调查循环：以不可修改的基线为初始状态，用工具收集证据、提出升级提议。
 * 返回的 evidence/proposedEscalation 由确定性 resolver 校验与融合，Agent 不写 finalRisk。
 */
export async function runInvestigation(options: InvestigationOptions): Promise<InvestigationOutcome> {
  const { conversation, baselineSummary, tenantId, requiredTool, requiredQuery, requiredIntent, callLLMAdvanced } = options;
  const systemPrompt = buildInvestigatorPrompt(baselineSummary);

  // 服务端确定性执行必调工具（ADR-0003 第 4 层扩展）：AMD 等端点把 tool_choice 当"偏好"，
  // 模型可能拒绝调用，因此必调工具由代码执行并把结果注入调查上下文，LLM 只做证据总结。
  let preloadedMessages: Array<{ role: string; content: string; tool_call_id?: string; name?: string }> = [];
  let serverExecutedTool: string | null = null;
  if (requiredTool && requiredQuery) {
    const toolResult = await executeTool(requiredTool, JSON.stringify({ query: requiredQuery, intent: requiredIntent || "policy_qa" }));
    serverExecutedTool = requiredTool;
    preloadedMessages = [
      {
        role: "tool",
        content: JSON.stringify(toolResult),
        tool_call_id: `forced_${requiredTool}`,
        name: requiredTool,
      },
    ];
  }

  const result = await runReactLoop({
    messages: [{ role: "user", content: conversation }],
    systemPrompt,
    tenantId,
    preloadedMessages,
    callLLMAdvanced: callLLMAdvanced as never,
  });

  const toolsUsed = serverExecutedTool && !result.toolsUsed.includes(serverExecutedTool)
    ? [serverExecutedTool, ...result.toolsUsed]
    : result.toolsUsed;

  return {
    content: result.content,
    mode: result.mode,
    turns: result.turns,
    toolsUsed,
    trace: result,
    parsed: parseAgentEvidence(result.content),
  };
}
