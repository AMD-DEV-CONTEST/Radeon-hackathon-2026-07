/**
 * Sprint 5: Lost-deal diagnosis engine.
 *
 * Reason tree categories and layered output:
 *   fact -> inference -> confidence -> counter-evidence -> suggestion
 *
 * The engine is deterministic (rule-based) for v1.0.  It consumes
 * conversation + funnel evidence and produces structured findings that
 * NEVER claim certainty without order/payment proof.
 */

import { TraceContext } from "@/lib/monitoring/tracing";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ReasonCategory =
  | "traffic_quality"
  | "product_mismatch"
  | "price_objection"
  | "trust_deficit"
  | "service_failure"
  | "inventory_fulfillment"
  | "payment_followup"
  | "unknown";

export type ConfidenceLevel = "high" | "medium" | "low" | "insufficient";
export type FunnelStage = "traffic" | "conversation" | "cart" | "order" | "payment";
export type FeedbackTarget = "rule" | "prompt" | "knowledge" | "model" | "none";

export interface EvidenceRef {
  type: "conversation" | "product" | "campaign" | "cart_event" | "order" | "metric" | "rule";
  id: string;
  label: string;
  excerpt?: string;
}

export interface DiagnosisFinding {
  reason_category: ReasonCategory;
  fact_statement: string;
  inference_statement: string | null;
  confidence: ConfidenceLevel;
  confidence_score: number;
  counter_evidence: string | null;
  suggestion: string | null;
  suggestion_actionable: boolean;
  evidence_refs: EvidenceRef[];
  funnel_stage: FunnelStage | null;
  conversation_id: string | null;
  product_id: string | null;
  campaign_id: string | null;
}

export interface DiagnosisInput {
  tenant_id: string;
  conversation_ids: string[];
  campaign_id?: string | null;
  product_id?: string | null;
  time_window_start?: string | null;
  time_window_end?: string | null;
}

export interface ConversationEvidence {
  conversation_id: string;
  campaign_id: string | null;
  product_id: string | null;
  messages: MessageEvidence[];
  had_cart: boolean;
  had_order: boolean;
  had_payment: boolean;
  transferred_to_human: boolean;
  duration_seconds: number;
  customer_sentiment: "positive" | "neutral" | "negative" | "unknown";
}

export interface MessageEvidence {
  role: "customer" | "agent" | "system";
  content: string;
  timestamp: string;
  tags?: string[];
}

export interface FunnelContext {
  traffic_count: number;
  conversation_count: number;
  cart_count: number;
  order_count: number;
  payment_count: number;
}

export interface DiagnosisResult {
  engine_version: string;
  input: DiagnosisInput;
  findings: DiagnosisFinding[];
  summary: DiagnosisSummary;
  trace_context?: TraceContext | null;  // QAE-016: 关联业务 trace
}

export interface DiagnosisSummary {
  total_conversations: number;
  diagnosed_count: number;
  top_reasons: { category: ReasonCategory; count: number }[];
  has_order_evidence: boolean;
  roi_claimable: boolean;
  roi_disclaimer: string | null;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const ENGINE_VERSION = "diagnosis-engine-v1.0";

export const REASON_LABELS: Record<ReasonCategory, string> = {
  traffic_quality: "流量质量",
  product_mismatch: "商品不匹配",
  price_objection: "价格异议",
  trust_deficit: "信任不足",
  service_failure: "客服问题",
  inventory_fulfillment: "库存/履约",
  payment_followup: "支付/跟进",
  unknown: "原因不明",
};

/**
 * Keywords that signal specific reason categories in customer messages.
 * Used for rule-based detection in v1.0.
 */
const CATEGORY_SIGNALS: { category: ReasonCategory; keywords: string[]; stage: FunnelStage }[] = [
  { category: "price_objection", keywords: ["太贵", "价格高", "便宜", "优惠", "折扣", "划算", "性价比", "预算"], stage: "conversation" },
  { category: "product_mismatch", keywords: ["不是我要的", "不合适", "没有这个", "款式", "颜色", "尺寸", "型号", "功能不够"], stage: "conversation" },
  { category: "trust_deficit", keywords: ["正品", "假货", "靠谱", "保修", "退换", "售后", "评价差", "不信"], stage: "conversation" },
  { category: "inventory_fulfillment", keywords: ["发货", "交期", "库存", "缺货", "物流", "快递", "多久到", "什么时候发"], stage: "conversation" },
  { category: "payment_followup", keywords: ["支付", "付款", "下单", "怎么买", "链接", "优惠券", "结算"], stage: "order" },
  { category: "service_failure", keywords: ["态度差", "回复慢", "不专业", "答非所问", "没人理"], stage: "conversation" },
];

// ---------------------------------------------------------------------------
// Core engine
// ---------------------------------------------------------------------------

/**
 * Detect reason categories from a single conversation's messages.
 */
export function detectReasonSignals(
  conversation: ConversationEvidence,
): { category: ReasonCategory; matched_keywords: string[]; stage: FunnelStage }[] {
  const customerMessages = conversation.messages
    .filter((m) => m.role === "customer")
    .map((m) => m.content.toLowerCase());

  const combined = customerMessages.join(" ");
  const results: { category: ReasonCategory; matched_keywords: string[]; stage: FunnelStage }[] = [];

  for (const signal of CATEGORY_SIGNALS) {
    const matched = signal.keywords.filter((kw) => combined.includes(kw));
    if (matched.length > 0) {
      results.push({ category: signal.category, matched_keywords: matched, stage: signal.stage });
    }
  }
  return results;
}

/**
 * Compute confidence based on evidence strength.
 *
 * Rules:
 * - If we have order/payment evidence confirming the loss, confidence can be high.
 * - Keyword match alone = medium at best.
 * - Multiple corroborating signals raise confidence.
 * - No order evidence => NEVER claim high confidence for ROI-related conclusions.
 */
export function computeConfidence(
  signals: { category: ReasonCategory; matched_keywords: string[] }[],
  conversation: ConversationEvidence,
  category: ReasonCategory,
): { level: ConfidenceLevel; score: number } {
  const relevantSignals = signals.filter((s) => s.category === category);
  const keywordCount = relevantSignals.reduce((sum, s) => sum + s.matched_keywords.length, 0);

  let score = 0;

  // Base score from keyword evidence
  if (keywordCount >= 3) score += 0.5;
  else if (keywordCount >= 2) score += 0.4;
  else if (keywordCount >= 1) score += 0.3;

  // Corroboration: negative sentiment supports the finding
  if (conversation.customer_sentiment === "negative") score += 0.15;

  // Corroboration: transfer to human suggests unresolved issue
  if (conversation.transferred_to_human) score += 0.1;

  // Corroboration: short duration + no cart suggests quick bounce
  if (!conversation.had_cart && conversation.duration_seconds < 60) score += 0.1;

  // Cap: without order/payment evidence, max 0.75 (cannot be "high")
  const hasConversionEvidence = conversation.had_order || conversation.had_payment;
  if (!hasConversionEvidence && score > 0.75) score = 0.75;

  // If we DO have evidence that they reached cart/order but didn't pay, higher confidence
  if (conversation.had_cart && !conversation.had_order) score += 0.1;
  if (conversation.had_order && !conversation.had_payment) score += 0.15;

  score = Math.min(score, 1);

  let level: ConfidenceLevel;
  if (score >= 0.75) level = "high";
  else if (score >= 0.5) level = "medium";
  else if (score >= 0.25) level = "low";
  else level = "insufficient";

  return { level, score: Math.round(score * 10000) / 10000 };
}

/**
 * Build a single finding from detected signals and conversation evidence.
 */
export function buildFinding(
  category: ReasonCategory,
  signals: { category: ReasonCategory; matched_keywords: string[]; stage: FunnelStage }[],
  conversation: ConversationEvidence,
): DiagnosisFinding {
  const relevantSignals = signals.filter((s) => s.category === category);
  const allKeywords = relevantSignals.flatMap((s) => s.matched_keywords);
  const stage = relevantSignals[0]?.stage ?? "conversation";
  const { level, score } = computeConfidence(signals, conversation, category);

  // Fact: what objectively happened
  const factParts: string[] = [];
  factParts.push(`客户在会话中提及"${allKeywords.slice(0, 3).join("、")}"相关内容`);
  if (!conversation.had_cart) factParts.push("未产生加购行为");
  if (!conversation.had_order) factParts.push("未产生订单");
  if (conversation.transferred_to_human) factParts.push("会话转接人工");
  const fact_statement = factParts.join("；");

  // Inference: what we think it means (clearly marked as inference)
  const inference_statement =
    level === "insufficient"
      ? null
      : `${REASON_LABELS[category]}可能是该会话未转化的阻力因素`;

  // Counter-evidence
  let counter_evidence: string | null = null;
  if (conversation.customer_sentiment === "positive") {
    counter_evidence = "客户整体情绪正面，可能存在其他未表达的顾虑";
  }
  if (conversation.had_cart && !conversation.had_order) {
    counter_evidence = "客户已加购，可能仍在决策中而非真正流失";
  }

  // Suggestion
  const suggestion = buildSuggestion(category, conversation);

  // Evidence refs
  const evidence_refs: EvidenceRef[] = [
    {
      type: "conversation",
      id: conversation.conversation_id,
      label: `会话 ${conversation.conversation_id}`,
      excerpt: allKeywords.length > 0 ? `关键词: ${allKeywords.join(", ")}` : undefined,
    },
  ];
  if (conversation.product_id) {
    evidence_refs.push({ type: "product", id: conversation.product_id, label: `商品 ${conversation.product_id}` });
  }
  if (conversation.campaign_id) {
    evidence_refs.push({ type: "campaign", id: conversation.campaign_id, label: `广告计划 ${conversation.campaign_id}` });
  }

  return {
    reason_category: category,
    fact_statement,
    inference_statement,
    confidence: level,
    confidence_score: score,
    counter_evidence,
    suggestion: suggestion?.text ?? null,
    suggestion_actionable: suggestion?.actionable ?? false,
    evidence_refs,
    funnel_stage: stage,
    conversation_id: conversation.conversation_id,
    product_id: conversation.product_id,
    campaign_id: conversation.campaign_id,
  };
}

function buildSuggestion(
  category: ReasonCategory,
  conversation: ConversationEvidence,
): { text: string; actionable: boolean } | null {
  switch (category) {
    case "price_objection":
      return { text: "补充优惠活动话术或阶梯报价 FAQ；安排人工跟进报价敏感客户", actionable: true };
    case "product_mismatch":
      return { text: "检查商品详情页与广告投放素材的一致性；补充规格对比知识", actionable: true };
    case "trust_deficit":
      return { text: "在知识库中补充资质证明、退换政策和客户案例", actionable: true };
    case "inventory_fulfillment":
      return { text: "补充交期 FAQ 和物流说明；对履约敏感客户安排人工跟进", actionable: true };
    case "payment_followup":
      return { text: "检查支付引导流程是否完整；对加购未付款客户设置跟进提醒", actionable: true };
    case "service_failure":
      return { text: "复盘客服响应质量；检查是否存在知识缺口或话术不当", actionable: true };
    case "traffic_quality":
      return { text: "复核广告投放人群定向与落地页匹配度", actionable: false };
    default:
      return null;
  }
}

/**
 * Detect traffic quality issues from funnel context.
 */
export function detectTrafficQualityIssue(
  funnel: FunnelContext,
  conversations: ConversationEvidence[],
): DiagnosisFinding | null {
  if (funnel.traffic_count === 0) return null;

  const conversationRate = funnel.conversation_count / funnel.traffic_count;

  // If conversation rate is very low, traffic quality may be the issue
  if (conversationRate > 0.15) return null; // >15% is acceptable

  const shortBounces = conversations.filter((c) => c.duration_seconds < 30 && !c.had_cart);
  const bounceRatio = conversations.length > 0 ? shortBounces.length / conversations.length : 0;

  if (bounceRatio < 0.4) return null;

  const score = Math.min(0.3 + (0.15 - conversationRate) * 2 + bounceRatio * 0.2, 0.75);

  return {
    reason_category: "traffic_quality",
    fact_statement: `广告点击到咨询转化率仅 ${(conversationRate * 100).toFixed(1)}%，${(bounceRatio * 100).toFixed(0)}% 会话在 30 秒内结束且无互动`,
    inference_statement: "流量质量可能不匹配目标客群，或落地页与广告承诺存在落差",
    confidence: score >= 0.5 ? "medium" : "low",
    confidence_score: Math.round(score * 10000) / 10000,
    counter_evidence: "也可能是客服响应速度导致客户提前离开",
    suggestion: "复核广告投放人群定向与落地页匹配度",
    suggestion_actionable: false,
    evidence_refs: [
      { type: "metric", id: "commerce.traffic.clicks", label: "广告点击数" },
      { type: "metric", id: "commerce.conversation.started", label: "有效咨询数" },
    ],
    funnel_stage: "traffic",
    conversation_id: null,
    product_id: null,
    campaign_id: conversations[0]?.campaign_id ?? null,
  };
}

/**
 * Main entry: run diagnosis on a set of conversations.
 */
export function runDiagnosis(
  input: DiagnosisInput,
  conversations: ConversationEvidence[],
  funnel?: FunnelContext | null,
  trace_context?: TraceContext | null,  // QAE-016
): DiagnosisResult {
  const findings: DiagnosisFinding[] = [];

  // Per-conversation analysis
  for (const conversation of conversations) {
    const signals = detectReasonSignals(conversation);

    if (signals.length === 0) {
      // No specific signal detected — if the conversation was lost, mark unknown
      if (!conversation.had_order && !conversation.had_payment) {
        findings.push({
          reason_category: "unknown",
          fact_statement: `会话 ${conversation.conversation_id} 未产生订单，但未检测到明确原因信号`,
          inference_statement: null,
          confidence: "insufficient",
          confidence_score: 0,
          counter_evidence: null,
          suggestion: null,
          suggestion_actionable: false,
          evidence_refs: [
            { type: "conversation", id: conversation.conversation_id, label: `会话 ${conversation.conversation_id}` },
          ],
          funnel_stage: "conversation",
          conversation_id: conversation.conversation_id,
          product_id: conversation.product_id,
          campaign_id: conversation.campaign_id,
        });
      }
      continue;
    }

    // Group by category and build findings
    const categories = [...new Set(signals.map((s) => s.category))];
    for (const category of categories) {
      findings.push(buildFinding(category, signals, conversation));
    }
  }

  // Funnel-level traffic quality check
  if (funnel) {
    const trafficFinding = detectTrafficQualityIssue(funnel, conversations);
    if (trafficFinding) {
      findings.push(trafficFinding);
    }
  }

  // Build summary
  const hasOrderEvidence = conversations.some((c) => c.had_order || c.had_payment);
  const categoryCounts = new Map<ReasonCategory, number>();
  for (const f of findings) {
    categoryCounts.set(f.reason_category, (categoryCounts.get(f.reason_category) ?? 0) + 1);
  }
  const topReasons = [...categoryCounts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([category, count]) => ({ category, count }));

  return {
    engine_version: ENGINE_VERSION,
    input,
    findings,
    summary: {
      total_conversations: input.conversation_ids.length,
      diagnosed_count: findings.length,
      top_reasons: topReasons,
      has_order_evidence: hasOrderEvidence,
      roi_claimable: false,
      roi_disclaimer: hasOrderEvidence
        ? null
        : "缺少订单/支付证据，不能宣称真实 ROI 或确定未成交原因",
    },
    trace_context: trace_context || null,  // QAE-016
  };
}
