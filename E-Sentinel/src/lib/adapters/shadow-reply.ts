// ============================================================================
// Shadow Reply Orchestrator — gate → generate → store → audit.
// NEVER calls the real platform adapter. All output stays internal.
// ============================================================================

import { evaluateShadowGate, buildShadowGateConfig, type GateDecision } from "./gatekeeper";
import { logAudit } from "../audit";
import { supabaseAdmin } from "../supabase";
import { getCached } from "../llm-provider";

export interface ShadowReplyResult {
  reply: string | null;
  decision: GateDecision;
  llmLatencyMs: number;
  wasFallback: boolean;
  cached: boolean;
}

/** Keyword fallback when LLM is unavailable or gatekeeper blocks */
function keywordReply(text: string): string {
  const t = text.toLowerCase();
  if (t.includes("发货") || t.includes("物流") || t.includes("快递") || t.includes("订单")) {
    return "亲亲您好，订单物流问题已收到～仓库正在加急处理，一般48小时内更新物流信息。如需催单，我会为您标记加急，请您耐心等待哦 ❤️";
  }
  if (t.includes("退款") || t.includes("退货") || t.includes("退钱")) {
    return "亲亲您好，退款问题已记录～售后客服会在1个工作日内核实处理，请您保持联系畅通。如需加急，请回复「加急退款」～";
  }
  if (t.includes("优惠券") || t.includes("满减") || t.includes("活动")) {
    return "亲亲您好，优惠相关咨询已收到～不同活动优惠券使用规则略有差异，建议您查看商品详情页的优惠说明，或回复具体券码我帮您查询哦～";
  }
  if (t.includes("质量") || t.includes("瑕疵") || t.includes("破损") || t.includes("坏了") || t.includes("烂了")) {
    return "亲亲非常抱歉给您带来不好的体验！商品质量问题我们非常重视，请您拍照上传问题商品照片，售后专员会优先为您处理退换货～";
  }
  return "亲亲您好，您的问题已收到～客服正在马不停蹄赶来，请稍等片刻，感谢您的耐心与理解 ❤️";
}

function simpleHash(input: string): string {
  let hash = 0;
  for (let i = 0; i < input.length; i++) {
    const chr = input.charCodeAt(i);
    hash = ((hash << 5) - hash) + chr;
    hash |= 0;
  }
  return Math.abs(hash).toString(36);
}

/**
 * Generate a shadow reply for a platform message.
 * - Checks gatekeeper first (saves LLM cost when disabled)
 * - Generates LLM reply with 3s timeout + keyword fallback
 * - Stores detailed metrics in shadow_replies table
 * - Logs audit trail
 * - NEVER calls any external platform API
 */
export async function generateShadowReply(params: {
  platformId: string;
  sessionId: string;
  messageId: string;
  customerId: string;
  content: string;
  correlationId: string;
  tenantId?: string;
}): Promise<ShadowReplyResult> {
  const gateConfig = buildShadowGateConfig(process.env);
  const decision = evaluateShadowGate(gateConfig, params.sessionId, params.content);

  if (!decision.allowed) {
    return { reply: null, decision, llmLatencyMs: 0, wasFallback: false, cached: false };
  }

  // Daily quota check (avoids cost explosion)
  const tenantId = params.tenantId?.trim();
  const withinQuota = await checkDailyQuota(params.platformId, tenantId);
  if (!withinQuota) {
    return {
      reply: null,
      decision: { allowed: false, reason: "quota_exceeded", tier: decision.tier },
      llmLatencyMs: 0,
      wasFallback: false,
      cached: false,
    };
  }

  // Generate LLM reply (with cache check + 3s timeout + keyword fallback)
  const startTime = Date.now();
  let reply: string;
  let wasFallback = false;
  let cached = false;

  const cacheKey = `tmall:reply:${tenantId || "unscoped"}:${simpleHash(params.content.slice(0, 300))}`;
  const cachedReply = getCached(cacheKey);

  if (cachedReply) {
    reply = cachedReply;
    cached = true;
  } else {
    try {
      const { generateLLMBotReply } = await import("../feishu-bot-reply");
      const timeoutPromise = new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error("shadow_llm_timeout")), 3000),
      );
      reply = await Promise.race([generateLLMBotReply(params.content, "", params.tenantId), timeoutPromise]);
    } catch {
      reply = keywordReply(params.content);
      wasFallback = true;
    }
  }

  const llmLatencyMs = Date.now() - startTime;

  // Persist shadow reply metrics (fire-and-forget — don't block the webhook ack)
  storeShadowReply({
    platformId: params.platformId,
    sessionId: params.sessionId,
    messageId: params.messageId,
    customerId: params.customerId,
    originalText: params.content,
    generatedReply: reply,
    llmLatencyMs,
    wasFallback,
    cached,
    gateReason: decision.reason,
    gateTier: decision.tier,
    tenantId,
  }).catch((err) => {
    console.warn("[ShadowReply] Failed to store shadow reply:", String(err).slice(0, 100));
  });

  // Audit (fire-and-forget)
  logAudit({
    action: "tmall_shadow_reply",
    resource_type: "shadow_replies",
    resource_id: params.messageId,
    detail: {
      session_id: params.sessionId,
      customer_id: params.customerId,
      llm_latency_ms: llmLatencyMs,
      was_fallback: wasFallback,
      cached,
      gate_reason: decision.reason,
      gate_tier: decision.tier,
      reply_length: reply.length,
    },
    correlation_id: params.correlationId,
  }).catch(() => {});

  return { reply, decision, llmLatencyMs, wasFallback, cached };
}

// ── Internal helpers ──

async function checkDailyQuota(platformId: string, tenantId?: string): Promise<boolean> {
  if (!supabaseAdmin) return true; // dev mode — allow
  const scopedTenantId = tenantId?.trim();
  if (!scopedTenantId) return true;

  try {
    const { getConfigNumber } = await import("../system-config");
    const quota = await getConfigNumber("tmall_shadow_daily_quota", 1000);
    if (quota <= 0) return true; // no limit

    const today = new Date().toISOString().slice(0, 10);
    const { count, error } = await supabaseAdmin
      .from("shadow_replies")
      .select("id", { count: "exact", head: true })
      .eq("platform_id", platformId)
      .eq("tenant_id", scopedTenantId)
      .gte("created_at", `${today}T00:00:00Z`)
      .lte("created_at", `${today}T23:59:59Z`);

    if (error) {
      console.warn("[ShadowReply] Quota check failed:", error.message);
      return true; // fail open — don't block on metric error
    }

    return (count ?? 0) < quota;
  } catch {
    return true; // fail open
  }
}

async function storeShadowReply(params: {
  platformId: string;
  sessionId: string;
  messageId: string;
  customerId: string;
  originalText: string;
  generatedReply: string;
  llmLatencyMs: number;
  wasFallback: boolean;
  cached: boolean;
  gateReason: string;
  gateTier: string;
  tenantId?: string;
}): Promise<void> {
  if (!supabaseAdmin || !params.tenantId) return;

  const { error } = await supabaseAdmin.from("shadow_replies").insert({
    tenant_id: params.tenantId,
    platform_id: params.platformId,
    session_id: params.sessionId,
    message_id: params.messageId,
    customer_id: params.customerId,
    original_text: params.originalText,
    generated_reply: params.generatedReply,
    reply_mode: "shadow",
    llm_latency_ms: params.llmLatencyMs,
    was_fallback: params.wasFallback,
    cached: params.cached,
    gate_reason: params.gateReason,
    gate_tier: params.gateTier,
    metadata: {},
  });

  if (error) {
    console.warn("[ShadowReply] Insert error:", error.message);
  }
}
