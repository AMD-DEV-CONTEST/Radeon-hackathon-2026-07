/**
 * 质检评测核心（消融用）。
 *
 * 把质检的确定性部分抽成可独立调用、可注入开关的 core，供：
 *   1. scripts/evaluate-goldset.mjs 跑消融对比（rule_only/llm_only/dual/...）
 *   2. evaluate/route.ts 复用（逐步接入，避免重复逻辑）
 *
 * 职责边界：只做"评估计算"，不落库、不告警、不建工单——那些是 route 的活。
 * 三个确定性构件：
 *   - QUALITY_STANDARDS（通用质检标准，静态）
 *   - retrieveRules（RAG 规则检索，可注入）
 *   - elevateRiskByKeywords（关键词"只升不降"兜底）
 *   - ruleOnlyClassify（纯关键词基线，供 rule_only 消融档）
 */

// ── 质检标准（静态，与 route 保持一致） ──────────────────────
import type { AgentEvidence } from "../agent/types";

export const QUALITY_STANDARDS = `
【客服质检标准 v1.0】
一、服务态度（20分）
  - 禁止使用负面措辞、反问语气、敷衍话术（如"你自己看""不知道""关我什么事"）
  - 必须使用敬语（您好/请/谢谢），主动报工号或姓名
二、专业性（30分）
  - 严禁提供错误的产品信息、价格、政策
  - 严禁承诺无法兑现的事项（如虚假赔偿承诺）
  - 涉及钱款/合同/法律条款时必须准确引用
三、响应效率（15分）
  - 禁止长时间无响应后直接结束对话
  - 复杂问题需告知预计处理时间并设置跟进提醒
四、解决问题（25分）
  - 必须给出可执行的具体方案，不得仅表达共情而无行动
  - 涉及退款/赔付时必须按照标准流程发起
五、合规与隐私（10分）
  - 严禁索要或泄露客户密码、完整银行卡号
  - 严禁在对话中传播未经确认的内部信息
`;

// ── 关键词兜底（与 route 保持一致） ─────────────────────────
export const RISK_ORDER: Record<string, number> = { low: 0, medium: 1, high: 2, critical: 3 };
export const CRITICAL_KEYWORDS = /12315|工商局|食药监|律师函|起诉|报警|法院|人身安全|生命安全|法律/;
export const HIGH_KEYWORDS = /投诉|举报|消费者协会|消协|差评|曝光|媒体|破损|瑕疵|坏了|烂了|质量|假货|假|二手|退款|退货|退钱|退差价/;
export const MEDIUM_KEYWORDS = /发货|物流|快递|没发|还没发|还没到|没到|订单.*没/;

export type RiskLevel = "low" | "medium" | "high" | "critical";

/**
 * 关键词"只升不降"风险兜底（仅取客户行）。
 * 复制自 route.ts elevateRiskByKeywords，独立出来供消融离线复算。
 */
export function elevateRiskByKeywords(conversation: string, currentRisk: string): RiskLevel {
  const customerLines = conversation
    .split("\n")
    .filter((line) => /^(顾客|客户|买家|用户)[：:]/.test(line))
    .join("\n");

  const currentLevel = RISK_ORDER[currentRisk] ?? 0;
  if (CRITICAL_KEYWORDS.test(customerLines) && currentLevel < 3) return "critical";
  if (HIGH_KEYWORDS.test(customerLines) && currentLevel < 2) return "high";
  if (MEDIUM_KEYWORDS.test(customerLines) && currentLevel < 1) return "medium";
  return (currentRisk as RiskLevel) || "low";
}

// ── rule_only 基线（纯关键词，无需 LLM） ─────────────────────
export interface RuleOnlyViolation {
  category: string;
  rule: string;
  severity: "minor" | "major" | "critical";
  source_quote: string;
}

// 负面/反问/推诿话术 → 服务态度违规
const NEGATIVE_PATTERNS: Array<{ pattern: RegExp; rule: string; severity: "major" | "critical" }> = [
  { pattern: /你(傻|蠢|笨|是不是眼瞎)/i, rule: "禁止辱骂客户", severity: "critical" },
  { pattern: /你自己(看|去|查)/i, rule: "禁止推诿敷衍", severity: "major" },
  { pattern: /我怎么知道|关我什么事|不关我事/i, rule: "禁止消极推诿", severity: "major" },
  { pattern: /这是(公司)?规定我也没办法|我也没办法/i, rule: "禁止冷漠推诿", severity: "major" },
  { pattern: /等通知|到时候再说|行行行/i, rule: "禁止敷衍了事", severity: "major" },
];

/**
 * 纯关键词基线：返回 risk_level + violations（不含 LLM）。
 * 用于 rule_only 消融档，代表"上一代纯规则方案"。
 */
export function ruleOnlyClassify(conversation: string): { riskLevel: RiskLevel; violations: RuleOnlyViolation[] } {
  const violations: RuleOnlyViolation[] = [];
  let risk: RiskLevel = "low";

  for (const { pattern, rule, severity } of NEGATIVE_PATTERNS) {
    const m = conversation.match(pattern);
    if (m) {
      violations.push({ category: "服务态度", rule, severity, source_quote: m[0] });
      if (severity === "critical") risk = "critical";
    }
  }

  // 关键词兜底（只升不降）
  risk = elevateRiskByKeywords(conversation, risk);

  return { riskLevel: risk, violations };
}

// ── 确定性风险解析器（ADR-0003 5 层架构：第 5 层） ─────────────
// finalRisk = max(hardRuleFloor, semanticBaseline, validatedAgentEscalation)
// Agent 无 finalRisk 写权限：它只能升级（需证据背书），不能降级。

const RISK_ORDER_FOR_RESOLVE: Record<RiskLevel, number> = { low: 0, medium: 1, high: 2, critical: 3 };

/**
 * 校验 Agent 升级提议：只有提议本身合法（high/critical）且附证据
 * （原文引用 escalationEvidence）且与基线无冲突时才接受。
 * 检索不到来源 / 无证据的升级一律忽略，避免 Agent 空口升级制造误报。
 *
 * 传入 conversation 时，额外校验 escalationEvidence 必须能对应到对话原文片段
 * （字符级模糊匹配），防止 Agent 幻觉出不存在的"原文"来背书升级。
 * 不传 conversation 时保持向后兼容（仅校验非空数组）。
 */
export function validateAgentEscalation(
  evidence: AgentEvidence | null | undefined,
  conversation?: string,
): RiskLevel | undefined {
  if (!evidence) return undefined;
  // 工具证据与基线冲突时不得自动升级（冲突属于需人工复核场景）
  if (evidence.evidenceConflict === true) return undefined;
  const esc = evidence.proposedEscalation;
  if (!esc || !["high", "critical"].includes(esc)) return undefined;
  // 升级必须附带对话原文证据（客服侧违规原句）；仅 policyFindings 不足以背书升级
  const hasEvidence = Array.isArray(evidence.escalationEvidence) && evidence.escalationEvidence.length > 0;
  if (!hasEvidence) return undefined;
  // 有对话上下文时，校验证据引用确实来自对话原文（至少 8 字符的连续片段命中），
  // 防止模型编造 quote 自证升级。
  if (conversation && conversation.trim().length > 0 && evidence.escalationEvidence) {
    const norm = conversation.replace(/\s+/g, "");
    const grounded = evidence.escalationEvidence.some((q) => {
      const qNorm = String(q || "").replace(/\s+/g, "");
      // 引用必须足够长才有辨识度（<8 字符的单字引用不背书升级）
      if (qNorm.length < 8) return false;
      // 完整引用命中原文，或引用内任意 8 字符连续片段命中（容忍被标点/换行切分）
      return norm.includes(qNorm) || Array.from({ length: qNorm.length - 7 }, (_, i) => qNorm.slice(i, i + 8)).some((sub) => norm.includes(sub));
    });
    if (!grounded) return undefined;
  }
  return esc;
}

/**
 * 人工复核标记（纯函数，可测）：
 * 硬红线命中 / 最终风险 high|critical / 客户诉诸法律监管 / Agent 请求复核 /
 * Agent 证据冲突 / 知识检索不可用或空结果（空检索 ≠ 没有违规）均需人工复核。
 */
export function computeRequiresHumanReview(opts: {
  hardRedlineHit: boolean;
  riskLevel: RiskLevel;
  softRequiresReview: boolean;
  agentRequiresReview?: boolean;
  agentEvidenceConflict?: boolean;
  knowledgeStatus?: "ok" | "insufficient" | "unavailable";
}): boolean {
  if (opts.hardRedlineHit) return true;
  if (opts.riskLevel === "high" || opts.riskLevel === "critical") return true;
  if (opts.softRequiresReview) return true;
  if (opts.agentRequiresReview) return true;
  if (opts.agentEvidenceConflict) return true;
  return opts.knowledgeStatus === "insufficient" || opts.knowledgeStatus === "unavailable";
}

/**
 * 确定性最终风险融合：
 * - hardFloor：硬红线下限（确定性，不可降级）；
 * - semanticBaseline：单次语义裁判基线（adjudicator）；
 * - agentEscalation：经校验的 Agent 升级提议（只能更高）。
 * 取三者最大值。该函数为纯函数，保证"相同输入 → 相同 final risk"。
 */
export function resolveFinalRisk(opts: {
  hardFloor: RiskLevel;
  semanticBaseline: RiskLevel;
  agentEscalation?: RiskLevel;
}): RiskLevel {
  let max = RISK_ORDER_FOR_RESOLVE[opts.semanticBaseline] ?? 0;
  const floor = RISK_ORDER_FOR_RESOLVE[opts.hardFloor] ?? 0;
  if (floor > max) max = floor;
  if (opts.agentEscalation) {
    const esc = RISK_ORDER_FOR_RESOLVE[opts.agentEscalation] ?? 0;
    if (esc > max) max = esc;
  }
  const levels: RiskLevel[] = ["low", "medium", "high", "critical"];
  return levels[max] ?? "low";
}

// ── 关键词陷阱中风险下限（Sprint 3，Kappa 对齐） ──────────────────────────
// gold 方案：客户诉求属于中高风险类型（退款/物流/质量/投诉/12315/假货/二手），
// 即使客服处理得当、无违规，风险也不低于 medium（medium 非 severe，不产生误报）。
// 情绪信号（emotional_intensifier）不在此列：客户情绪强烈≠业务中高风险。
export const MEDIUM_FLOOR_SIGNAL_CODES = new Set([
  "legal_action_threat",
  "complaint_escalation",
  "refund_dispute",
  "product_defect",
  "logistics_delay",
]);

export function applyCustomerIssueMediumFloor(riskLevel: RiskLevel, flagCodes: string[]): RiskLevel {
  if (riskLevel !== "low") return riskLevel;
  return flagCodes.some((code) => MEDIUM_FLOOR_SIGNAL_CODES.has(code)) ? "medium" : riskLevel;
}
