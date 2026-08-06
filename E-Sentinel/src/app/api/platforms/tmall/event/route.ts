// ============================================================================
// POST /api/platforms/tmall/event — Tmall customer service webhook
//
// Handles: URL verification (handshake), inbound customer messages.
//
// Cold-start optimized: signature verification uses only Node.js built-in
// crypto (zero external deps), responding in <100ms. Heavy imports (Supabase,
// audit) are dynamically loaded only for actual event processing.
// ============================================================================

import { NextResponse } from "next/server";
import { createHash } from "crypto";

/** GET — preliminary URL health check (must return 200) */
export async function GET() {
  return NextResponse.json({ code: 0, message: "ok" });
}

export async function POST(request: Request) {
  // 1. Read raw body and query params
  const body = await request.text();
  const url = new URL(request.url);
  const queryParams: Record<string, string> = {};
  url.searchParams.forEach((v, k) => { queryParams[k] = v; });

  // 2. Signature verification (cold-start safe — only Node.js crypto)
  const appSecret = process.env.TMALL_APP_SECRET || "";
  if (appSecret) {
    const sign = queryParams.sign;
    if (!sign) {
      return NextResponse.json({ error: "Missing signature" }, { status: 401 });
    }

    const sortedStr = Object.keys(queryParams)
      .filter((k) => k !== "sign" && k !== "sign_method")
      .sort()
      .map((k) => `${k}${queryParams[k]}`)
      .join("");

    const computed = createHash("md5")
      .update(`${appSecret}${sortedStr}${body}${appSecret}`, "utf8")
      .digest("hex")
      .toUpperCase();

    if (computed !== sign) {
      console.warn("[Tmall] Signature verification failed");
      return NextResponse.json({ error: "Invalid signature" }, { status: 401 });
    }
  }

  // 3. Parse payload
  let raw: Record<string, unknown>;
  try {
    raw = JSON.parse(body);
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const msgId = raw.msg_id as string;
  const msgType = raw.msg_type as string;
  const sessionId = raw.session_id as string;
  const sendTime = raw.send_time as string;

  if (!msgId || !sessionId) {
    return NextResponse.json({ error: "Missing required fields: msg_id, session_id" }, { status: 400 });
  }

  // 4. URL verification handshake (Tmall may send a verification challenge)
  if (msgType === "url_verification") {
    const challenge = raw.challenge as string;
    if (!challenge) {
      return NextResponse.json({ error: "Missing challenge" }, { status: 400 });
    }
    console.log("[Tmall] URL verification OK");
    return NextResponse.json({ challenge });
  }

  // ── Below: actual event processing ──

  // 5. Dynamic import heavy deps
  const [
    { supabaseAdmin },
    { createCorrelationId },
    { logAudit },
  ] = await Promise.all([
    import("@/lib/supabase"),
    import("@/lib/correlation"),
    import("@/lib/audit"),
  ]);

  const correlationId = createCorrelationId("tmall_evt");

  // 6. Extract message text (platform-normalized)
  const content = extractMessageText(raw);

  // 7. Store raw event (idempotent via msg_id UNIQUE constraint)
  if (supabaseAdmin) {
    const { error: rawErr } = await supabaseAdmin
      .from("feishu_raw_events")
      .upsert(
        {
          event_id: msgId,
          event_type: `tmall_${msgType}`,
          raw_body: safeJson(body),
        },
        { onConflict: "event_id", ignoreDuplicates: true },
      );

    if (rawErr) {
      console.warn("[Tmall] Raw event storage error:", rawErr.message);
    }
  }

  // 8. Resolve Tmall platform ID
  const platformId = await resolveTmallPlatform(supabaseAdmin);
  if (!platformId) {
    console.error("[Tmall] Cannot resolve tmall platform_id");
    return NextResponse.json({ code: 0, message: "platform not found" });
  }

  // 9. Upsert bot_chat_sessions
  if (supabaseAdmin && content) {
    try {
      await processTmallMessage(supabaseAdmin, {
        msgId,
        sessionId,
        msgType,
        content,
        customerId: (raw.sender_user_id || raw.buyer_nick || "unknown") as string,
        sellerNick: raw.seller_nick as string | undefined,
        chatId: raw.chat_id as string | undefined,
        sendTime,
        platformId,
        correlationId,
      });
    } catch (err) {
      console.error("[Tmall] Message processing error:", err);
    }
  }

  // 10. Audit log
  await logAudit({
    action: "tmall_event_receive",
    resource_type: "feishu_raw_events",
    resource_id: msgId,
    detail: {
      event_type: msgType,
      session_id: sessionId,
      platform: "tmall",
    },
    correlation_id: correlationId,
  });

  return NextResponse.json({ code: 0 });
}

// ── Helpers ──

function safeJson(raw: string): unknown {
  try { return JSON.parse(raw); } catch { return raw; }
}

function extractMessageText(raw: Record<string, unknown>): string {
  const content = (raw.content || {}) as Record<string, unknown>;

  switch (raw.msg_type as string) {
    case "text":
      return (content.text as string) || "";
    case "mixed": {
      const items = content.items as Array<{ type: string; text?: string }> | undefined;
      return items
        ?.filter((i) => i.type === "text")
        .map((i) => i.text || "")
        .join(" ") || "[混合消息]";
    }
    case "image":
      return "[图片]";
    case "file":
      return "[文件]";
    case "system":
      return "[系统消息]";
    default:
      return `[不支持的消息类型: ${raw.msg_type}]`;
  }
}

async function resolveTmallPlatform(
  db: NonNullable<Awaited<typeof import("@/lib/supabase")>["supabaseAdmin"]> | null,
): Promise<string | null> {
  if (!db) return null;

  const { data: existing } = await db
    .from("platforms")
    .select("id")
    .eq("code", "tmall")
    .maybeSingle();

  if (existing) return existing.id;

  const { data: created, error } = await db
    .from("platforms")
    .insert({ name: "天猫", code: "tmall", bot_type: "third_party" })
    .select("id")
    .single();

  if (error) {
    console.error("[Tmall] Failed to create platform:", error.message);
    return null;
  }
  return created.id;
}

interface TmallMessageParams {
  msgId: string;
  sessionId: string;
  msgType: string;
  content: string;
  customerId: string;
  sellerNick?: string;
  chatId?: string;
  sendTime: string;
  platformId: string;
  correlationId: string;
}

async function processTmallMessage(
  db: NonNullable<Awaited<typeof import("@/lib/supabase")>["supabaseAdmin"]>,
  params: TmallMessageParams,
) {
  const { createCorrelationId } = await import("@/lib/correlation");
  const tenantId = process.env.TMALL_TENANT_ID?.trim();
  if (!tenantId) {
    console.error("[Tmall] TMALL_TENANT_ID is required; message not processed");
    return;
  }
  const customerLine = `顾客: ${params.content}`;

  // Upsert bot_chat_sessions by external_session_id = session_id
  const { data: existing } = await db
    .from("bot_chat_sessions")
    .select("id, conversation, total_messages")
    .eq("external_session_id", params.sessionId)
    .eq("tenant_id", tenantId)
    .maybeSingle();

  // Generate reply via unified orchestrator (shadow/gradual/full based on env)
  let reply: string;
  const { orchestrateReply } = await import("@/lib/adapters/reply-orchestrator");
  const orchResult = await orchestrateReply({
    platformCode: "tmall",
    platformId: params.platformId,
    sessionId: params.sessionId,
    messageId: params.msgId,
    customerId: params.customerId,
    content: params.content,
    history: existing?.conversation || "",
    correlationId: params.correlationId,
    tenantId,
    sellerNick: params.sellerNick,
    mode: (process.env.TMALL_REPLY_MODE as "shadow" | "gradual" | "full") || "shadow",
  });

  if (orchResult.reply) {
    reply = orchResult.reply;
    const sentTag = orchResult.sentToPlatform ? " [SENT]" : "";
    console.log(
      `[Tmall] ${orchResult.mode} reply — gate:${orchResult.decision.reason} latency:${orchResult.llmLatencyMs}ms fallback:${orchResult.wasFallback} cached:${orchResult.cached}${sentTag}`,
    );
  } else {
    reply = "";
  }

  const botLine = reply ? `机器人: ${reply}` : "系统: 已转人工处理";

  if (existing) {
    await db
      .from("bot_chat_sessions")
      .update({
        conversation: `${existing.conversation}\n${customerLine}\n${botLine}`,
        total_messages: (existing.total_messages as number) + 1,
        knowledge_refs: orchResult.knowledgeIds || [],
      })
      .eq("id", existing.id)
      .eq("tenant_id", tenantId);
  } else {
    await db
      .from("bot_chat_sessions")
      .insert({
        id: crypto.randomUUID(),
        platform_id: params.platformId,
        session_type: "pre_sale",
        external_session_id: params.sessionId,
        customer_id: params.customerId,
        tenant_id: tenantId,
        bot_handled: true,
        is_inquiry: false,
        first_response_ms: 0,
        tags: [],
        conversation: `${customerLine}\n${botLine}`,
        total_messages: 1,
        knowledge_refs: orchResult.knowledgeIds || [],
        correlation_id: createCorrelationId("tmall_sess"),
      });
  }

  console.log(`[Tmall] ${params.sessionId}: ${customerLine.slice(0, 80)}`);

  // The orchestrator owns the send decision. This webhook must not bypass a
  // shadow, compliance, quota, or human-approval gate.
  if (orchResult.sentToPlatform && reply) {
    const { sendReply } = await import("@/lib/reply-router");
    sendReply({
      platform_message_id: params.msgId,
      platform_code: "tmall",
      session_id: params.sessionId,
      customer_id: params.customerId,
      content: params.content,
      message_type: params.msgType,
      timestamp: new Date(params.sendTime).toISOString(),
      reply_context: {
        tmall_session_id: params.sessionId,
        tmall_chat_id: params.chatId,
        seller_nick: params.sellerNick,
      },
    }, reply);
  }

  // Fire-and-forget auto-evaluation (shadow mode)
  if (reply) triggerTmallEvaluation(params.correlationId, params.content, reply);
}

async function triggerTmallEvaluation(correlationId: string, text: string, reply: string) {
  const baseUrl = process.env.VERCEL_URL
    ? `https://${process.env.VERCEL_URL}`
    : process.env.NEXT_PUBLIC_APP_URL || "http://localhost:3000";

  const payload = {
    conversation: `顾客: ${text}\n机器人: ${reply}`,
    ticket_id: `tmall_${correlationId}`,
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
      console.log("[Tmall] Auto-eval OK for", correlationId.slice(-12));
    } else {
      console.warn("[Tmall] Auto-eval failed:", res.status);
    }
  } catch (err) {
    console.warn("[Tmall] Auto-eval error:", String(err).slice(0, 100));
  }
}
