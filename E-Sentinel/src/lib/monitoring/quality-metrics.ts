// ============================================================================
// Quality Metrics Engine — computes per-intent quality & risk scores.
// Powers both the dashboard and auto-throttle decisions.
// Data sources: shadow_replies, actual_replies, quality_reports, bot_chat_sessions
// ============================================================================

import { supabaseAdmin } from "../supabase";

// ── Types ──

export interface IntentQualityScore {
  intent: string;
  /** 0-100 composite quality score */
  qualityScore: number;
  /** 0-100 composite risk score (lower is safer) */
  riskScore: number;
  /** Sample count for statistical significance */
  sampleCount: number;
  /** LLM-generated (non-fallback) rate */
  llmRate: number;
  /** Average LLM latency in ms */
  avgLatencyMs: number;
  /** Approval pass rate (for gradual/full modes) */
  approvalRate: number | null;
  /** Compliance block rate (sensitive content) */
  complianceBlockRate: number;
  /** Fallback keyword reply rate */
  fallbackRate: number;
  /** Cache hit rate */
  cacheHitRate: number;
  /** Last N hours of data */
  windowHours: number;
}

export interface GlobalQualitySnapshot {
  overallQuality: number;
  overallRisk: number;
  totalReplies24h: number;
  totalShadow24h: number;
  totalActual24h: number;
  pendingApproval: number;
  complianceBlocked24h: number;
  /** Per-intent breakdown across all stores */
  intents: IntentQualityScore[];
  /** MVP SLO 状态 (QAE-022) */
  sloStatuses?: SloStatus[];
}

// ── Intent classification ──

const INTENT_KEYWORDS: Record<string, string[]> = {
  "发货物流": ["发货", "物流", "快递", "订单", "单号", "运输"],
  "退款退货": ["退款", "退货", "退钱", "退换", "仅退款"],
  "优惠活动": ["优惠券", "满减", "活动", "折扣", "秒杀", "红包"],
  "商品质量": ["质量", "瑕疵", "破损", "坏了", "烂了", "假货", "色差"],
  "尺码规格": ["尺码", "大小", "颜色", "型号", "规格", "尺寸", "码数"],
  "售后投诉": ["投诉", "赔偿", "差评", "举报", "维权", "315", "曝光"],
  "客服咨询": ["怎么", "如何", "能不能", "可以吗", "请问", "咨询"],
};

function classifyIntent(text: string): string {
  const t = text.toLowerCase();
  for (const [intent, keywords] of Object.entries(INTENT_KEYWORDS)) {
    if (keywords.some((kw) => t.includes(kw))) return intent;
  }
  return "其他咨询";
}

// ── Scoring functions ──

function computeQualityScore(metrics: {
  llmRate: number;
  fallbackRate: number;
  avgLatencyMs: number;
  approvalRate: number | null;
}): number {
  // Weighted composite: 40% llmRate + 30% (1-fallbackRate) + 20% latency + 10% approval
  const latencyScore = Math.max(0, 100 - Math.max(0, metrics.avgLatencyMs - 1000) / 30);
  const fallbackPenalty = metrics.fallbackRate * 60;
  const approvalBonus = metrics.approvalRate !== null ? metrics.approvalRate * 10 : 5;
  const raw = metrics.llmRate * 40 + (1 - metrics.fallbackRate) * 30 + latencyScore * 0.2 + approvalBonus - fallbackPenalty;
  return Math.max(0, Math.min(100, Math.round(raw)));
}

function computeRiskScore(metrics: {
  complianceBlockRate: number;
  fallbackRate: number;
}): number {
  // Risk = compliance blocks weighted 70% + fallback rate weighted 30%
  const raw = metrics.complianceBlockRate * 70 + metrics.fallbackRate * 30;
  return Math.max(0, Math.min(100, Math.round(raw)));
}

// ── Main aggregation ──

/**
 * 全局质量快照。
 *
 * 租户隔离说明：本函数依赖的 shadow_replies / actual_replies 两张表当前 schema 中
 * 均无 tenant_id 列（见 migration-012 / migration-013 建表语句），因此暂无法按租户过滤，
 * 属于已知 schema 缺口。补列方案已就绪：supabase/migration-032-tenant-core-tables-columns.sql
 * （含历史行回填与索引）。apply 后需为这两处查询加 .eq("tenant_id", tenantId) 并为本函数
 * 补 tenantId 入参。在此之前不引入无效参数，避免造成"已隔离"的假象。当前单租户回退
 * "default" 下行为正确，缺口仅在未来多租户部署时致命。
 */
export async function getGlobalQualitySnapshot(
  windowHours = 24,
): Promise<GlobalQualitySnapshot> {
  const since = new Date(Date.now() - windowHours * 3600_000).toISOString();

  // Fetch shadow replies in window
  const shadowPromise = supabaseAdmin
    ? supabaseAdmin
        .from("shadow_replies")
        .select("original_text, generated_reply, llm_latency_ms, was_fallback, cached, gate_reason")
        .gte("created_at", since)
        .order("created_at", { ascending: false })
        .limit(2000)
    : Promise.resolve({ data: [], error: null });

  // Fetch actual replies in window
  const actualPromise = supabaseAdmin
    ? supabaseAdmin
        .from("actual_replies")
        .select("original_text, compliance_safe, sent_success, compliance_block_reason, metadata")
        .gte("created_at", since)
        .order("created_at", { ascending: false })
        .limit(2000)
    : Promise.resolve({ data: [], error: null });

  // Fetch pending approvals
  const pendingPromise = supabaseAdmin
    ? supabaseAdmin
        .from("actual_replies")
        .select("id", { count: "exact", head: true })
        .eq("sent_success", false)
        .eq("compliance_safe", true)
    : Promise.resolve({ count: 0, error: null });

  const [shadowRes, actualRes, pendingRes] = await Promise.all([
    shadowPromise,
    actualPromise,
    pendingPromise,
  ]);

  const shadowRows = (shadowRes.data || []) as Array<{
    original_text: string;
    generated_reply: string;
    llm_latency_ms: number | null;
    was_fallback: boolean;
    cached: boolean;
    gate_reason: string;
  }>;

  const actualRows = (actualRes.data || []) as Array<{
    original_text: string;
    compliance_safe: boolean;
    sent_success: boolean;
    compliance_block_reason: string | null;
    metadata: Record<string, unknown> | null;
  }>;

  // Group shadow replies by intent
  const intentBuckets = new Map<string, {
    total: number;
    fallback: number;
    cached: number;
    latencySum: number;
    latencyCount: number;
  }>();

  for (const row of shadowRows) {
    const intent = classifyIntent(row.original_text);
    let bucket = intentBuckets.get(intent);
    if (!bucket) {
      bucket = { total: 0, fallback: 0, cached: 0, latencySum: 0, latencyCount: 0 };
      intentBuckets.set(intent, bucket);
    }
    bucket.total++;
    if (row.was_fallback) bucket.fallback++;
    if (row.cached) bucket.cached++;
    if (row.llm_latency_ms != null) {
      bucket.latencySum += row.llm_latency_ms;
      bucket.latencyCount++;
    }
  }

  // Group actual replies by intent for compliance stats
  const actualIntentBuckets = new Map<string, {
    total: number;
    blocked: number;
    approved: number;
    sent: number;
  }>();

  for (const row of actualRows) {
    const intent = classifyIntent(row.original_text);
    let bucket = actualIntentBuckets.get(intent);
    if (!bucket) {
      bucket = { total: 0, blocked: 0, approved: 0, sent: 0 };
      actualIntentBuckets.set(intent, bucket);
    }
    bucket.total++;
    if (!row.compliance_safe) bucket.blocked++;
    if (row.sent_success) bucket.sent++;
    // Check metadata for approval status
    const meta = row.metadata as Record<string, unknown> | null;
    if (meta?.approved) bucket.approved++;
  }

  // Build per-intent scores
  const intents: IntentQualityScore[] = [];
  const allIntents = new Set([...intentBuckets.keys(), ...actualIntentBuckets.keys()]);

  for (const intent of allIntents) {
    const shadow = intentBuckets.get(intent) || { total: 0, fallback: 0, cached: 0, latencySum: 0, latencyCount: 0 };
    const actual = actualIntentBuckets.get(intent) || { total: 0, blocked: 0, approved: 0, sent: 0 };
    const total = shadow.total + actual.total;

    if (total === 0) continue;

    const llmRate = shadow.total > 0 ? (shadow.total - shadow.fallback) / shadow.total * 100 : 100;
    const fallbackRate = shadow.total > 0 ? shadow.fallback / shadow.total * 100 : 0;
    const cacheHitRate = shadow.total > 0 ? shadow.cached / shadow.total * 100 : 0;
    const avgLatencyMs = shadow.latencyCount > 0 ? Math.round(shadow.latencySum / shadow.latencyCount) : 0;
    const complianceBlockRate = actual.total > 0 ? actual.blocked / actual.total * 100 : 0;
    const approvalRate = actual.total > 0 ? actual.sent / actual.total * 100 : null;

    const qualityScore = computeQualityScore({ llmRate, fallbackRate, avgLatencyMs, approvalRate });
    const riskScore = computeRiskScore({ complianceBlockRate, fallbackRate });

    intents.push({
      intent,
      qualityScore,
      riskScore,
      sampleCount: total,
      llmRate: Math.round(llmRate),
      avgLatencyMs,
      approvalRate: approvalRate !== null ? Math.round(approvalRate) : null,
      complianceBlockRate: Math.round(complianceBlockRate),
      fallbackRate: Math.round(fallbackRate),
      cacheHitRate: Math.round(cacheHitRate),
      windowHours,
    });
  }

  intents.sort((a, b) => b.qualityScore - a.qualityScore);

  // Overall scores (weighted by sample count)
  const totalSamples = intents.reduce((s, i) => s + i.sampleCount, 0);
  const overallQuality = totalSamples > 0
    ? Math.round(intents.reduce((s, i) => s + i.qualityScore * i.sampleCount, 0) / totalSamples)
    : 0;
  const overallRisk = totalSamples > 0
    ? Math.round(intents.reduce((s, i) => s + i.riskScore * i.sampleCount, 0) / totalSamples)
    : 0;

  return {
    overallQuality,
    overallRisk,
    totalReplies24h: shadowRows.length + actualRows.length,
    totalShadow24h: shadowRows.length,
    totalActual24h: actualRows.length,
    pendingApproval: pendingRes.count ?? 0,
    complianceBlocked24h: actualRows.filter((r) => !r.compliance_safe).length,
    intents,
    sloStatuses: computeMvpSloStatuses({ overallQuality, overallRisk, totalReplies24h: shadowRows.length + actualRows.length, totalShadow24h: shadowRows.length, totalActual24h: actualRows.length, pendingApproval: pendingRes.count ?? 0, complianceBlocked24h: actualRows.filter((r) => !r.compliance_safe).length, intents }),
  };
}

// ============================================================================
// MVP SLO & Error Budget (QAE-022 minimal)
// 基于计划 9.3 建议 SLI，引入最小 SLO 定义和错误预算计算
// 用于上线可运营的指标可观测
// ============================================================================

export interface SloDefinition {
  name: string;
  sli: string; // e.g. 'overallQuality' or 'event_success_rate'
  target: number; // e.g. 99.5 for %, or 300000 for ms p95
  unit: string; // '%' | 'ms' | 'count'
  description: string;
}

export const MVP_SLOS: SloDefinition[] = [
  {
    name: "事件接入成功率",
    sli: "event_success_rate",
    target: 99.5,
    unit: "%",
    description: "合法事件成功接收比例（月度）",
  },
  {
    name: "评估时效 p95",
    sli: "evaluation_p95_latency_ms",
    target: 300000, // 5 min
    unit: "ms",
    description: "事件到评估完成 p95 时延",
  },
  {
    name: "数据新鲜度",
    sli: "data_freshness_exceed_ratio",
    target: 1,
    unit: "%",
    description: "关键指标超过刷新窗口比例",
  },
  {
    name: "API 可用性",
    sli: "api_success_rate",
    target: 99.5,
    unit: "%",
    description: "核心读取 API 成功率（月度）",
  },
  {
    name: "可追溯性",
    sli: "traceability_coverage",
    target: 100,
    unit: "%",
    description: "P0/P1 Finding 证据链完整率",
  },
];

export interface SloStatus {
  name: string;
  current: number | null; // null = 无真实数据源，状态未知（绝不编造数字）
  target: number;
  met: boolean; // 仅 status==="met" 时为 true；breached/unknown 均为 false
  status: "met" | "breached" | "unknown";
  errorBudgetRemaining: number | null; // 无数据时为空
  unit: string;
}

/**
 * 最小错误预算计算（MVP）
 * 对于百分比型 SLI： budget = target - current (正为剩余预算)
 * 对于时延型：简化比较
 */
export function computeSloStatus(slo: SloDefinition, currentValue: number | null): SloStatus {
  // 无真实数据来源时明确返回 unknown，绝不编造数字
  if (currentValue == null) {
    return {
      name: slo.name,
      current: null,
      target: slo.target,
      met: false,
      status: "unknown",
      errorBudgetRemaining: null,
      unit: slo.unit,
    };
  }
  let met = false;
  let budget = 0;
  if (slo.unit === "%") {
    met = currentValue >= slo.target;
    budget = slo.target - currentValue;
  } else if (slo.unit === "ms") {
    met = currentValue <= slo.target;
    budget = slo.target - currentValue; // 负为超标
  } else {
    met = currentValue <= slo.target; // e.g. for ratio
    budget = slo.target - currentValue;
  }
  return {
    name: slo.name,
    current: currentValue,
    target: slo.target,
    met,
    status: met ? "met" : "breached",
    errorBudgetRemaining: Math.round(budget * 100) / 100,
    unit: slo.unit,
  };
}

/**
 * 从真实 snapshot 计算 MVP SLO 状态。
 * 仅有真实数据源的 SLO 才计算 current；无数据源的明确返回 unknown，不编造数字。
 * - 事件接入成功率 / 数据新鲜度 / API 可用性 / 可追溯性：当前无对应数据源 → unknown
 * - 评估时效 p95：基于真实意图平均时延（来自 shadow_replies.llm_latency_ms）做近似
 */
export function computeMvpSloStatuses(snapshot: GlobalQualitySnapshot): SloStatus[] {
  const latencyValues = snapshot.intents
    .map((i) => i.avgLatencyMs)
    .filter((v) => v > 0)
    .sort((a, b) => a - b);
  const latencyP95 = latencyValues.length
    ? latencyValues[Math.floor(latencyValues.length * 0.95)]
    : null;

  return [
    computeSloStatus(MVP_SLOS[0], null),
    computeSloStatus(MVP_SLOS[1], latencyP95),
    computeSloStatus(MVP_SLOS[2], null),
    computeSloStatus(MVP_SLOS[3], null),
    computeSloStatus(MVP_SLOS[4], null),
  ];
}
