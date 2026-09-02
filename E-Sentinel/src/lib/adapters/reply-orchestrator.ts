// ============================================================================
// Reply Orchestrator — unified pipeline for shadow and real replies.
// Replaces inline LLM generation in platform event routes.
//
// Modes:
//   shadow  — generate + store metrics + audit, NEVER send to platform
//   gradual — generate + compliance check + (if approved) send via adapter
//   full    — generate + compliance check + send (no sampling)
//
// Dual-track: real replies are also stored in shadow_replies for A/B comparison.
// ============================================================================

import { evaluateShadowGate, buildShadowGateConfig, type GateDecision } from "./gatekeeper";
import { applyComplianceGuard, type ComplianceResult } from "./compliance-guard";
import { logAudit } from "../audit";
import { supabaseAdmin } from "../supabase";
import { getCached } from "../llm-provider";

// ── Types ──

export type ReplyMode = "shadow" | "gradual" | "full";

export interface OrchestratorResult {
  reply: string | null;
  knowledgeIds?: string[];
  decision: GateDecision;
  compliance: ComplianceResult | null;
  llmLatencyMs: number;
  wasFallback: boolean;
  cached: boolean;
  sentToPlatform: boolean;
  mode: ReplyMode;
}

// ── Keyword fallback ──

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

// ── Store-level circuit breaker ──

async function isStoreEnabledForRealReply(
  platformCode: string,
  sellerNick: string | undefined,
): Promise<boolean> {
  if (!sellerNick) return false;
  if (!supabaseAdmin) return false;

  try {
    const { getConfigString } = await import("../system-config");
    const raw = await getConfigString(`${platformCode}_real_reply_stores`, "{}");
    const stores: Record<string, boolean> = JSON.parse(raw);
    return stores[sellerNick] === true;
  } catch {
    return false;
  }
}

async function needsHumanApproval(): Promise<boolean> {
  try {
    const { getConfigString } = await import("../system-config");
    return (await getConfigString("tmall_require_human_approval", "true")) === "true";
  } catch {
    return true; // fail-closed: require approval by default
  }
}

export function requiresHumanApprovalForTopic(content: string): boolean {
  return /(退款|退货|赔偿|赔付|投诉|举报|12315|律师|诉讼|法律|银行卡|密码|价格承诺|库存承诺)/i.test(content);
}

async function checkDailyQuota(platformId: string, tenantId?: string): Promise<boolean> {
  if (!supabaseAdmin) return true;
  const scopedTenantId = tenantId?.trim();
  if (!scopedTenantId) return true;

  try {
    const { getConfigNumber } = await import("../system-config");
    const quota = await getConfigNumber("tmall_shadow_daily_quota", 1000);
    if (quota <= 0) return true;

    const today = new Date().toISOString().slice(0, 10);
    const { count, error } = await supabaseAdmin
      .from("shadow_replies")
      .select("id", { count: "exact", head: true })
      .eq("platform_id", platformId)
      .eq("tenant_id", scopedTenantId)
      .gte("created_at", `${today}T00:00:00Z`)
      .lte("created_at", `${today}T23:59:59Z`);

    if (error) return true;
    return (count ?? 0) < quota;
  } catch {
    return true;
  }
}

// ── Main orchestrator ──

export async function orchestrateReply(params: {
  platformCode: string;
  platformId: string;
  sessionId: string;
  messageId: string;
  customerId: string;
  content: string;
  history?: string;
  correlationId: string;
  tenantId?: string;
  sellerNick?: string;
  mode: ReplyMode;
}): Promise<OrchestratorResult> {
  const startTime = Date.now();
  const tenantId = params.tenantId?.trim();

  // 1. Gate check (same as shadow pipeline)
  const gateConfig = buildShadowGateConfig(process.env);
  const decision = evaluateShadowGate(gateConfig, params.sessionId, params.content);

  if (!decision.allowed) {
    return {
      reply: null,
      decision,
      compliance: null,
      llmLatencyMs: 0,
      wasFallback: false,
      cached: false,
      sentToPlatform: false,
      mode: params.mode,
    };
  }

  // 2. Quota check
  const withinQuota = await checkDailyQuota(params.platformId, tenantId);
  if (!withinQuota) {
    return {
      reply: null,
      decision: { allowed: false, reason: "quota_exceeded", tier: decision.tier },
      compliance: null,
      llmLatencyMs: 0,
      wasFallback: false,
      cached: false,
      sentToPlatform: false,
      mode: params.mode,
    };
  }

  // 3. Generate LLM reply
  let reply: string;
  let wasFallback = false;
  let cached = false;
  let knowledgeIds: string[] = [];

  const cacheKey = `${params.platformCode}:reply:${tenantId || "unscoped"}:${simpleHash(`${params.content.slice(0, 300)}\n${(params.history || "").slice(-2400)}`)}`;
  const cachedReply = getCached(cacheKey);

  if (cachedReply) {
    reply = cachedReply;
    cached = true;
  } else {
    try {
      const { generateLLMBotReplyWithMetadata } = await import("../feishu-bot-reply");
      const timeoutPromise = new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error("reply_timeout")), 3000),
      );
      const generated = await Promise.race([
        generateLLMBotReplyWithMetadata(params.content, params.history || "", tenantId),
        timeoutPromise,
      ]);
      reply = generated.reply;
      knowledgeIds = generated.knowledgeIds;
    } catch {
      reply = keywordReply(params.content);
      wasFallback = true;
    }
  }

  const llmLatencyMs = Date.now() - startTime;

  // 4. Store shadow metrics (always — for dual-track comparison)
  storeShadowMetrics({
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
  }).catch(() => {});

  // 5. If shadow mode — stop here, no compliance check, no send
  if (params.mode === "shadow") {
    logAudit({
      action: "tmall_shadow_reply",
      resource_type: "shadow_replies",
      resource_id: params.messageId,
      detail: {
        session_id: params.sessionId,
        llm_latency_ms: llmLatencyMs,
        was_fallback: wasFallback,
        cached,
        gate_reason: decision.reason,
      },
      correlation_id: params.correlationId,
    }).catch(() => {});

    return {
      reply,
      knowledgeIds,
      decision,
      compliance: null,
      llmLatencyMs,
      wasFallback,
      cached,
      sentToPlatform: false,
      mode: "shadow",
    };
  }

  // 6. Compliance guard (hardcoded rules — mandatory for real replies)
  const compliance = applyComplianceGuard(params.content, reply);

  if (!compliance.safe) {
    // Sensitive content → force human handoff, log, NEVER send AI reply
    logAudit({
      action: "tmall_compliance_block",
      resource_type: "actual_replies",
      resource_id: params.messageId,
      detail: {
        session_id: params.sessionId,
        block_reason: compliance.blockReason,
        original_text_preview: params.content.slice(0, 100),
      },
      correlation_id: params.correlationId,
    }).catch(() => {});

    return {
      reply: null,
      knowledgeIds,
      decision,
      compliance,
      llmLatencyMs,
      wasFallback,
      cached,
      sentToPlatform: false,
      mode: params.mode,
    };
  }

  const sanitizedReply: string = compliance.sanitizedReply!; // safe: compliance.safe === true

  // 7. Store-level circuit breaker
  const storeEnabled = await isStoreEnabledForRealReply(params.platformCode, params.sellerNick);
  if (!storeEnabled) {
    return {
      reply: sanitizedReply,
      knowledgeIds,
      decision,
      compliance,
      llmLatencyMs,
      wasFallback,
      cached,
      sentToPlatform: false,
      mode: params.mode,
    };
  }

  // 8. Human approval gate
  const requireApproval = requiresHumanApprovalForTopic(params.content) || await needsHumanApproval();
  if (requireApproval) {
    // Store in actual_replies with pending status (not sent yet)
    await storeActualReply({
      platformId: params.platformId,
      sessionId: params.sessionId,
      messageId: params.messageId,
      customerId: params.customerId,
      originalText: params.content,
      generatedReply: reply,
      sanitizedReply: sanitizedReply,
      llmLatencyMs,
      wasFallback,
      complianceSafe: true,
      sentSuccess: false, // pending human approval
      mode: params.mode,
      tenantId,
    });

    logAudit({
      action: "tmall_real_reply",
      resource_type: "actual_replies",
      resource_id: params.messageId,
      detail: {
        session_id: params.sessionId,
        llm_latency_ms: llmLatencyMs,
        compliance_safe: true,
        status: "pending_approval",
        reply_preview: sanitizedReply.slice(0, 200),
      },
      correlation_id: params.correlationId,
    }).catch(() => {});

    return {
      reply: sanitizedReply,
      knowledgeIds,
      decision,
      compliance,
      llmLatencyMs,
      wasFallback,
      cached,
      sentToPlatform: false, // pending human approval
      mode: params.mode,
    };
  }

  // 9. Send via platform adapter (only if store enabled AND no approval required)
  let sentToPlatform = false;
  try {
    const { getAdapter } = await import("./registry");
    const adapter = getAdapter(params.platformCode);

    if (adapter && !adapter.health.isCircuitOpen) {
      const result = await adapter.sendReply({
        in_reply_to: {
          platform_message_id: params.messageId,
          platform_code: params.platformCode,
          session_id: params.sessionId,
          customer_id: params.customerId,
          content: params.content,
          message_type: "text",
          timestamp: new Date().toISOString(),
          reply_context: { seller_nick: params.sellerNick },
        },
        content: sanitizedReply,
        reply_type: "text",
      });

      sentToPlatform = result.success;
    }
  } catch (err) {
    console.error(`[Orchestrator] Send failed for ${params.platformCode}:`, String(err).slice(0, 100));
  }

  // 10. Store actual reply record
  await storeActualReply({
    platformId: params.platformId,
    sessionId: params.sessionId,
    messageId: params.messageId,
    customerId: params.customerId,
    originalText: params.content,
    generatedReply: reply,
    sanitizedReply: sanitizedReply,
    llmLatencyMs,
    wasFallback,
    complianceSafe: true,
    sentSuccess: sentToPlatform,
    mode: params.mode,
    tenantId,
  });

  logAudit({
    action: "tmall_real_reply",
    resource_type: "actual_replies",
    resource_id: params.messageId,
    detail: {
      session_id: params.sessionId,
      llm_latency_ms: llmLatencyMs,
      compliance_safe: true,
      sent_to_platform: sentToPlatform,
      reply_preview: sanitizedReply.slice(0, 200),
    },
    correlation_id: params.correlationId,
  }).catch(() => {});

  return {
    reply: sanitizedReply,
    knowledgeIds,
    decision,
    compliance,
    llmLatencyMs,
    wasFallback,
    cached,
    sentToPlatform,
    mode: params.mode,
  };
}

// ── Internal helpers ──

async function storeShadowMetrics(params: {
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
    console.warn("[Orchestrator] Shadow metrics insert error:", error.message);
  }
}

async function storeActualReply(params: {
  platformId: string;
  sessionId: string;
  messageId: string;
  customerId: string;
  originalText: string;
  generatedReply: string;
  sanitizedReply: string;
  llmLatencyMs: number;
  wasFallback: boolean;
  complianceSafe: boolean;
  sentSuccess: boolean;
  mode: string;
  tenantId?: string;
}): Promise<void> {
  if (!supabaseAdmin || !params.tenantId) return;

  const { error } = await supabaseAdmin.from("actual_replies").insert({
    tenant_id: params.tenantId,
    platform_id: params.platformId,
    session_id: params.sessionId,
    message_id: params.messageId,
    customer_id: params.customerId,
    original_text: params.originalText,
    generated_reply: params.generatedReply,
    sanitized_reply: params.sanitizedReply,
    reply_mode: params.mode,
    llm_latency_ms: params.llmLatencyMs,
    was_fallback: params.wasFallback,
    compliance_safe: params.complianceSafe,
    sent_success: params.sentSuccess,
    sent_at: params.sentSuccess ? new Date().toISOString() : null,
    metadata: {},
  });

  if (error) {
    console.warn("[Orchestrator] Actual reply insert error:", error.message);
  }
}
