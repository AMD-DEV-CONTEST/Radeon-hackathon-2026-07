// ============================================================================
// POST /api/feishu/event — Feishu Event Subscription webhook
// Handles: url_verification (handshake), im.message.receive_v1 (inbound messages)
//
// Cold-start optimized: URL verification uses only Node.js built-in crypto
// (zero external deps), responding in <100ms. Heavy imports (Supabase, audit)
// are dynamically loaded only for actual event processing.
// ============================================================================

import { NextResponse } from "next/server";
import {
  verifySignature,
  decryptMessage,
  parseMessageText,
  validateToken,
  isWebhookConfigured,
} from "@/lib/feishu-webhook";

/** GET — Feishu preliminary URL health check (must return 200) */
export async function GET() {
  return NextResponse.json({ code: 0, message: "ok" });
}

export async function POST(request: Request) {
  // 1. Read raw body
  const body = await request.text();
  const timestamp = request.headers.get("X-Lark-Request-Timestamp") || "";
  const nonce = request.headers.get("X-Lark-Request-Nonce") || "";
  const signature = request.headers.get("X-Lark-Signature") || "";

  // 2. Decrypt / validate event (only uses Node.js crypto — no external deps)
  let event: Record<string, unknown>;
  let rawStore = body;

  try {
    const bodyJson = JSON.parse(body);

    if (bodyJson.encrypt) {
      if (isWebhookConfigured() && !verifySignature(timestamp, nonce, body, signature)) {
        console.warn("[Feishu] Signature verification failed");
        return NextResponse.json({ error: "Invalid signature" }, { status: 401 });
      }
      const decrypted = decryptMessage(bodyJson.encrypt as string);
      event = JSON.parse(decrypted);
      rawStore = decrypted;
    } else {
      event = bodyJson;
      const token = event.token as string;
      if (isWebhookConfigured() && !validateToken(token)) {
        console.warn("[Feishu] Token validation failed");
        return NextResponse.json({ error: "Invalid token" }, { status: 401 });
      }
    }
  } catch (err) {
    console.error("[Feishu] Failed to parse request body:", err);
    return NextResponse.json({ error: "Invalid request body" }, { status: 400 });
  }

  // 3. Normalize event structure (Feishu v1.0 uses event.type/event_id; v2.0 uses header.event_type/event_id)
  const header = (event.header || event) as Record<string, unknown>;
  const eventType = (header.event_type as string) || (event.type as string) || "unknown";
  const eventId = (header.event_id as string) || (event.event_id as string) || `feishu_${Date.now()}`;
  const eventBody = (event.event || event) as Record<string, unknown>;

  // 4. URL verification handshake — return immediately (cold-start safe, <1s)
  if (eventType === "url_verification" || event.type === "url_verification") {
    const challenge = (eventBody.challenge || event.challenge) as string;
    if (!challenge) {
      return NextResponse.json({ error: "Missing challenge" }, { status: 400 });
    }
    console.log("[Feishu] URL verification OK");
    return NextResponse.json({ challenge });
  }

  // ── Below: actual event processing (only reached for non-verification events) ──

  // 5. Dynamic import heavy deps (Supabase client + audit logger)
  const [
    { supabaseAdmin },
    { createCorrelationId },
    { logAudit },
  ] = await Promise.all([
    import("@/lib/supabase"),
    import("@/lib/correlation"),
    import("@/lib/audit"),
  ]);

  const correlationId = createCorrelationId("feishu_evt");

  // 6. Store raw event (idempotent via event_id UNIQUE constraint)
  if (supabaseAdmin) {
    const { error: rawErr } = await supabaseAdmin
      .from("feishu_raw_events")
      .upsert(
        { event_id: eventId, event_type: eventType, raw_body: safeJson(rawStore) },
        { onConflict: "event_id", ignoreDuplicates: true },
      );

    if (rawErr) {
      console.warn("[Feishu] Raw event storage error:", rawErr.message);
    }
  }

  // 7. Handle im.message.receive_v1
  if (eventType === "im.message.receive_v1" && supabaseAdmin) {
    try {
      await processInboundMessage(supabaseAdmin, eventBody, correlationId);
    } catch (err) {
      console.error("[Feishu] Message processing error:", err);
    }
  }

  // 8. Handle card.action.trigger (supervisor clicks overturn/detail buttons)
  if (eventType === "card.action.trigger" && supabaseAdmin) {
    try {
      await processCardAction(supabaseAdmin, eventBody, correlationId);
    } catch (err) {
      console.error("[Feishu] Card action error:", err);
    }
  }

  // 9. Audit log
  await logAudit({
    action: "feishu_event_receive",
    resource_type: "feishu_raw_events",
    resource_id: eventId,
    detail: {
      event_type: eventType,
      chat_id: extractChatId(event),
      sender_open_id: extractSenderId(event),
    },
    correlation_id: correlationId,
  });

  return NextResponse.json({ code: 0 });
}

// ── Helpers (no supabase dependency — pure functions) ──

function safeJson(raw: string): unknown {
  try { return JSON.parse(raw); } catch { return raw; }
}

function extractChatId(event: Record<string, unknown>): string | null {
  try {
    const evt = event.event || event;
    const message = (evt as Record<string, unknown>)?.message as Record<string, unknown> | undefined;
    return (message?.chat_id as string) || null;
  } catch {
    return null;
  }
}

function extractSenderId(event: Record<string, unknown>): string | null {
  try {
    const evt = event.event || event;
    const sender = (evt as Record<string, unknown>)?.sender as Record<string, unknown> | undefined;
    const senderId = sender?.sender_id as Record<string, string> | undefined;
    return senderId?.open_id || senderId?.user_id || null;
  } catch {
    return null;
  }
}

// ── Inbound message processor (receives supabaseAdmin as parameter) ──

async function processInboundMessage(
  db: NonNullable<Awaited<typeof import("@/lib/supabase")>["supabaseAdmin"]>,
  event: Record<string, unknown>,
  correlationId: string,
) {
  const { createCorrelationId } = await import("@/lib/correlation");

  const evt = (event.event || event) as Record<string, unknown>;
  const message = evt.message as Record<string, unknown>;
  const sender = evt.sender as Record<string, unknown> | undefined;

  const chatId = message?.chat_id as string;
  const msgType = (message?.message_type as string) || "text";
  const contentJson = (message?.content as string) || "{}";
  const senderId = (sender?.sender_id as Record<string, string>)?.open_id || "unknown";
  const tenantId = process.env.FEISHU_TENANT_ID?.trim();

  if (!tenantId) {
    console.error("[Feishu] FEISHU_TENANT_ID is required; message not processed");
    return;
  }

  const text = parseMessageText(msgType, contentJson);

  // Resolve feishu platform UUID
  const platformId = await resolveFeishuPlatform(db);
  if (!platformId) {
    console.error("[Feishu] Cannot resolve feishu platform_id — message not stored");
    return;
  }

  // Upsert bot_chat_sessions by external_session_id = chat_id
  const { data: existing } = await db
    .from("bot_chat_sessions")
    .select("id, conversation, total_messages")
    .eq("external_session_id", chatId)
    .eq("tenant_id", tenantId)
    .maybeSingle();

  // Generate reply: try LLM first (1.5s timeout), fall back to keyword
  let reply: string;
  let knowledgeIds: string[] = [];
  try {
    const { generateLLMBotReplyWithMetadata } = await import("@/lib/feishu-bot-reply");
    const timeoutPromise = new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error("timeout")), 2000),
    );
    const result = await Promise.race([
      generateLLMBotReplyWithMetadata(text, existing?.conversation || "", tenantId),
      timeoutPromise,
    ]);
    reply = result.reply;
    knowledgeIds = result.knowledgeIds;
  } catch {
    reply = generateBotReply(text);
  }

  const customerLine = `顾客: ${text}`;
  const { requiresHumanApprovalForTopic } = await import("@/lib/adapters/reply-orchestrator");
  const requiresApproval = requiresHumanApprovalForTopic(text);
  const botLine = requiresApproval ? "系统: 已转人工处理" : `机器人: ${reply}`;

  if (existing) {
    await db
      .from("bot_chat_sessions")
      .update({
        conversation: `${existing.conversation}\n${customerLine}\n${botLine}`,
        total_messages: (existing.total_messages as number) + 1,
        knowledge_refs: knowledgeIds,
      })
      .eq("id", existing.id)
      .eq("tenant_id", tenantId);
  } else {
    await db
      .from("bot_chat_sessions")
      .insert({
        id: crypto.randomUUID(),
        platform_id: platformId,
        session_type: "pre_sale",
        external_session_id: chatId,
        customer_id: senderId,
        tenant_id: tenantId,
        bot_handled: true,
        is_inquiry: false,
        first_response_ms: 0,
        tags: [],
        conversation: `${customerLine}\n${botLine}`,
        total_messages: 1,
        correlation_id: createCorrelationId("feishu_sess"),
        knowledge_refs: knowledgeIds,
      });
  }

  console.log(`[Feishu] ${chatId}: ${customerLine.slice(0, 80)}`);

  // High-risk topics stay in the human queue; do not let the webhook bypass the gate.
  if (requiresApproval) {
    const { logAudit } = await import("@/lib/audit");
    await logAudit({
      action: "guard_block",
      resource_type: "feishu_replies",
      resource_id: chatId,
      detail: { reason: "high_risk_topic_requires_human", correlation_id: correlationId },
      correlation_id: correlationId,
    });
  } else {
    const { sendFeishuMessage } = await import("@/lib/feishu");
    sendFeishuMessage({
      receive_id: chatId,
      receive_id_type: "chat_id",
      content: reply,
    });
  }

  // Fire-and-forget auto-evaluation (same as Edge Function)
  triggerAutoEvaluation(correlationId, text, reply);
}

function generateBotReply(text: string): string {
  const t = text.toLowerCase();
  if (t.includes("发货") || t.includes("物流") || t.includes("快递") || t.includes("订单")) {
    return "亲亲您好，订单物流问题已收到～仓库正在加急处理，一般48小时内更新物流信息。如需催单，我会为您标记加急，请您耐心等待哦 ❤️";
  }
  if (t.includes("退款") || t.includes("退货") || t.includes("退钱")) {
    return "亲亲您好，退款问题已记录～售后客服会在1个工作日内核实处理，请您保持联系畅通。如需加急，请回复\"加急退款\"～";
  }
  if (t.includes("优惠券") || t.includes("满减") || t.includes("活动")) {
    return "亲亲您好，优惠相关咨询已收到～不同活动优惠券使用规则略有差异，建议您查看商品详情页的优惠说明，或回复具体券码我帮您查询哦～";
  }
  if (t.includes("质量") || t.includes("瑕疵") || t.includes("破损") || t.includes("坏了") || t.includes("烂了")) {
    return "亲亲非常抱歉给您带来不好的体验！商品质量问题我们非常重视，请您拍照上传问题商品照片，售后专员会优先为您处理退换货～";
  }
  return "亲亲您好，您的问题已收到～客服正在马不停蹄赶来，请稍等片刻，感谢您的耐心与理解 ❤️";
}

async function triggerAutoEvaluation(correlationId: string, text: string, reply?: string) {
  const baseUrl = process.env.VERCEL_URL
    ? `https://${process.env.VERCEL_URL}`
    : process.env.NEXT_PUBLIC_APP_URL || "http://localhost:3000";

  const botReply = reply || "亲亲您好，您的问题已收到，客服正在处理中～";
  const payload = {
    conversation: `顾客: ${text}\n机器人: ${botReply}`,
    ticket_id: `feishu_${correlationId}`,
    skip_feishu: true,
    review_mode: "shadow",
  };

  try {
    const res = await fetch(`${baseUrl}/api/qa/evaluate`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...((process.env.ADMIN_API_KEY || process.env.API_SECRET)
          ? { "x-api-key": process.env.ADMIN_API_KEY || process.env.API_SECRET }
          : {}),
      },
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      console.log("[Feishu] Auto-eval OK for", correlationId.slice(-12));
    } else {
      console.warn("[Feishu] Auto-eval failed:", res.status);
    }
  } catch (err) {
    console.warn("[Feishu] Auto-eval error:", String(err).slice(0, 100));
  }
}

// ── Card action processor (supervisor clicks overturn/detail buttons) ──

async function processCardAction(
  db: NonNullable<Awaited<typeof import("@/lib/supabase")>["supabaseAdmin"]>,
  event: Record<string, unknown>,
  correlationId: string,
) {
  const evt = (event.event || event) as Record<string, unknown>;
  const action = evt.action as Record<string, unknown> | undefined;
  if (!action) return;

  const actionValue = action.value as Record<string, string> | undefined;
  const actionType = actionValue?.action;
  const reportId = actionValue?.report_id;
  const chatId = (evt.chat_id as string) || (action.context as Record<string, string>)?.chat_id;

  console.log(`[Feishu] Card action: ${actionType} report=${reportId}`);

  if (actionType === "overturn" && reportId) {
    // Process overturn: update report status and send confirmation
    const { data: report } = await db
      .from("quality_reports")
      .select("id, total_score, risk_level, status")
      .eq("id", reportId)
      .single();

    if (report) {
      const { error: updErr } = await db
        .from("quality_reports")
        .update({
          status: "overturned",
          overturned_reason: "飞书卡片误判驳回 — 主管确认",
        })
        .eq("id", reportId);

      if (updErr) {
        console.error("[Feishu] Overturn update error:", updErr.message);
      } else {
        console.log(`[Feishu] Report ${reportId} overturned`);

        // Log audit
        const { logAudit } = await import("@/lib/audit");
        await logAudit({
          action: "overturn",
          resource_type: "quality_reports",
          resource_id: reportId,
          detail: {
            method: "feishu_card",
            correlation_id: correlationId,
          },
          correlation_id: correlationId,
        });

        // Send confirmation card back to the chat
        if (chatId) {
          const { sendFeishuMessage } = await import("@/lib/feishu");
          await sendFeishuMessage({
            receive_id: chatId,
            receive_id_type: "chat_id",
            msg_type: "interactive",
            content: JSON.stringify({
              header: {
                template: "green",
                title: { tag: "plain_text", content: "✅ 误判驳回已处理" },
              },
              elements: [
                {
                  tag: "div",
                  text: {
                    tag: "lark_md",
                    content: `质检报告 ${reportId.slice(-8)} 已被主管驳回。\n原风险等级: **${(report as Record<string, unknown>).risk_level}**\n原评分: **${(report as Record<string, unknown>).total_score}** 分`,
                  },
                },
              ],
            }),
          });
        }
      }
    }
  }
}

async function resolveFeishuPlatform(
  db: NonNullable<Awaited<typeof import("@/lib/supabase")>["supabaseAdmin"]>,
): Promise<string | null> {
  const { data: existing } = await db
    .from("platforms")
    .select("id")
    .eq("code", "feishu")
    .maybeSingle();

  if (existing) return existing.id as string;

  const { data: created, error } = await db
    .from("platforms")
    .insert({ name: "飞书", code: "feishu" })
    .select("id")
    .single();

  if (error) {
    console.error("[Feishu] Failed to create feishu platform:", error.message);
    return null;
  }
  return created.id as string;
}
