// ============================================================================
// Supabase Edge Function — Feishu Event Subscription Webhook
// URL: https://<project>.supabase.co/functions/v1/feishu-event
//
// Deno runtime, global edge deployment, <100ms cold start.
// Handles: GET health check, POST url_verification + im.message.receive_v1
// ============================================================================

import { serve } from "https://deno.land/std@0.224.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

// ── Crypto helpers (Web Crypto API — built into Deno) ──

const encoder = new TextEncoder();
const decoder = new TextDecoder();

async function sha256Hex(input: string): Promise<string> {
  const hash = await crypto.subtle.digest("SHA-256", encoder.encode(input));
  return Array.from(new Uint8Array(hash))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

async function aesDecrypt(encryptedBase64: string, encryptKey: string): Promise<string> {
  const keyHash = await crypto.subtle.digest("SHA-256", encoder.encode(encryptKey));
  const key = await crypto.subtle.importKey("raw", keyHash, { name: "AES-CBC" }, false, ["decrypt"]);

  const raw = Uint8Array.from(atob(encryptedBase64), (c) => c.charCodeAt(0));
  const iv = raw.slice(0, 16);
  const ciphertext = raw.slice(16);

  const decrypted = await crypto.subtle.decrypt({ name: "AES-CBC", iv }, key, ciphertext);
  return decoder.decode(decrypted);
}

// ── Feishu-specific helpers ──

function parseMessageText(msgType: string, contentJson: string): string {
  if (!contentJson) return "[空消息]";

  let parsed: Record<string, unknown>;
  try {
    parsed = JSON.parse(contentJson);
  } catch {
    return contentJson;
  }

  switch (msgType) {
    case "text":
      return (parsed.text as string) || "[空文本]";
    case "post": {
      const post = parsed.content;
      if (!post) return "[富文本]";
      try {
        const blocks = post as Record<string, unknown[][]>;
        return Object.values(blocks)
          .flat(2)
          .map((el) => (el as { text?: string })?.text || "")
          .join("");
      } catch {
        return "[富文本]";
      }
    }
    case "image":
      return "[图片]";
    case "audio":
    case "media":
      return "[语音]";
    case "file":
      return `[文件: ${(parsed.file_name as string) || ""}]`;
    case "sticker":
      return "[表情]";
    default:
      return `[不支持: ${msgType}]`;
  }
}

function extractChatId(event: Record<string, unknown>): string | null {
  try {
    const evt = (event.event || event) as Record<string, unknown>;
    const msg = evt.message as Record<string, unknown> | undefined;
    return (msg?.chat_id as string) || null;
  } catch {
    return null;
  }
}

function extractSenderId(event: Record<string, unknown>): string | null {
  try {
    const evt = (event.event || event) as Record<string, unknown>;
    const sender = evt.sender as Record<string, unknown> | undefined;
    const sid = sender?.sender_id as Record<string, string> | undefined;
    return sid?.open_id || sid?.user_id || null;
  } catch {
    return null;
  }
}

// ── UUID v4 generator (no external deps) ──

function uuidv4(): string {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

// ── LLM Circuit Breaker & Health Monitoring ──

const INTENT_CLASSIFY_TIMEOUT_MS = 1500;
const GENERATE_REPLY_TIMEOUT_MS = 4000;
const EMBEDDING_TIMEOUT_MS = 2000;
const LLM_REPORT_TIMEOUT_MS = 4000;

const VALID_INTENTS = new Set([
  "help", "quality_report", "compliance_check", "generate_report",
  "payment_reminder", "work_orders", "knowledge_gaps", "bot_suggest",
  "chat_stats", "qa_evaluate", "meeting_pipeline", "daily_brief",
  "general_chat", "system_health",
  "batch_hitl_confirm", "hitl_pending_count", "pipeline_status", "pipeline_detail",
  "quick_reply", "emotion_detect",
  "export_quality_reports", "export_chat_sessions", "export_work_orders",
  "export_pipeline_jobs",
  "pipeline_retry", "pipeline_history",
  "personality_switch",
  "quality_improvement",
  "transfer_human",
]);

const llmFailures = new Map<string, { count: number; lastFail: number }>();
const llmRecentCallLog: Array<{ service: string; ok: boolean; latencyMs: number }> = [];
const LLM_RECENT_LOG_MAX = 100;

function isCircuitOpen(service: string): boolean {
  const f = llmFailures.get(service);
  if (!f) return false;
  // Open circuit if 3+ failures in 60 seconds; auto-recover after 60s
  return f.count >= 3 && (Date.now() - f.lastFail) < 60000;
}

function recordFailure(service: string): void {
  const f = llmFailures.get(service);
  if (f) {
    f.count++;
    f.lastFail = Date.now();
  } else {
    llmFailures.set(service, { count: 1, lastFail: Date.now() });
  }
}

function recordSuccess(service: string): void {
  llmFailures.delete(service);
}

function logLLMHealth(service: string, type: string, ok: boolean, latencyMs: number): void {
  console.log(`[LLM-Health] service=${service} type=${type} ok=${ok} latency=${latencyMs}ms`);
  llmRecentCallLog.push({ service: `${service}-${type}`, ok, latencyMs });
  if (llmRecentCallLog.length > LLM_RECENT_LOG_MAX) {
    llmRecentCallLog.shift();
  }
}

function getCircuitBreakerState(): {
  deepseek: "ok" | "open" | "degraded";
  embedding: "ok" | "open" | "degraded";
  recentLog: Array<{ service: string; ok: boolean; latencyMs: number }>;
} {
  const dsRecent = llmRecentCallLog.filter(e => e.service.startsWith("deepseek-")).slice(-10);
  const embRecent = llmRecentCallLog.filter(e => e.service.startsWith("embedding-")).slice(-10);

  return {
    deepseek: isCircuitOpen("deepseek")
      ? "open"
      : dsRecent.length > 0 && dsRecent.some(e => !e.ok)
        ? "degraded"
        : "ok",
    embedding: isCircuitOpen("embedding")
      ? "open"
      : embRecent.length > 0 && embRecent.some(e => !e.ok)
        ? "degraded"
        : "ok",
    recentLog: llmRecentCallLog.slice(-10),
  };
}

// ── LLM-Powered Report Generation ──

function generateFallbackReport(reportType: string, stats: { total?: number; critical?: number; avgScore?: number }): string {
  const total = stats.total || 0;
  const critical = stats.critical || 0;
  const avg = stats.avgScore ?? "N/A";
  const rate = total > 0 ? Math.round((1 - critical / total) * 100) : 100;

  return [
    `**${reportType}质检概况**`,
    ``,
    `- 会话总数: **${total}**`,
    `- 平均分: **${avg}**`,
    `- 致命风险: **${critical}** 条`,
    `- 合格率: **${rate}%**`,
    ``,
    `> 建议定期关注高风险会话，针对性优化客服话术。`,
  ].join("\n");
}

async function getReportStats(reportType: string, periodRaw: string) {
  const tStr = new Date().toISOString().slice(0, 10);
  const tmrStr = new Date(Date.now() + 86400000).toISOString().slice(0, 10);
  const yStr = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
  const targetDate = periodRaw === "昨天" ? yStr : tStr;

  const { data: qStats } = await supabase.from("quality_reports")
    .select("risk_level, total_score").gte("created_at", targetDate).lt("created_at", tmrStr).limit(500);
  const total = qStats?.length || 0;
  const critical = qStats?.filter((r: any) => r.risk_level === "critical").length || 0;
  const avgScore = total > 0 ? Math.round((qStats?.reduce((s: number, r: any) => s + (r.total_score || 0), 0) || 0) / total) : 0;
  return { total, critical, avgScore, riskDist: `${critical} critical`, topViolations: "" };
}

async function generateLLMReport(
  reportType: string,
  stats: {
    total?: number;
    critical?: number;
    avgScore?: number;
    riskDistribution?: Record<string, number>;
    topViolations?: string[];
  },
): Promise<string> {
  const apiKey = Deno.env.get("DEEPSEEK_API_KEY") || "";
  const apiUrl = Deno.env.get("DEEPSEEK_API_URL") || "";

  if (!apiKey || !apiUrl) {
    console.warn("[LLM-Report] No API key configured, using fallback");
    return generateFallbackReport(reportType, stats);
  }

  if (isCircuitOpen("deepseek")) {
    console.warn("[LLM-Report] Circuit breaker open, using fallback");
    return generateFallbackReport(reportType, stats);
  }

  const total = stats.total || 0;
  const avg = stats.avgScore ?? "N/A";
  const critical = stats.critical || 0;
  const distribution = stats.riskDistribution
    ? Object.entries(stats.riskDistribution)
        .map(([k, v]) => `${k === "critical" ? "致命" : k === "high" ? "高危" : k === "medium" ? "中危" : "低危"}: ${v}条`)
        .join(", ")
    : "无";
  const violations = stats.topViolations && stats.topViolations.length > 0
    ? stats.topViolations.join(", ")
    : "无";

  const prompt = `你是一个数据分析师。根据以下**精确数据**生成一份${reportType}报告（Markdown格式）：

**数据（必须原样引用，不得修改数字）：**
- 会话总数: ${total}
- 质检平均分: ${avg}
- 致命风险: ${critical}条
- 风险分布: ${distribution}
- 高频违规: ${violations}

**要求：**
1. 所有数字必须与上面给出的数据完全一致，不得四舍五入、不得估算、不得推测
2. 300字以内
3. 核心数据用加粗展示
4. 给出1-2条具体改进建议`;

  const startTime = Date.now();
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), LLM_REPORT_TIMEOUT_MS);

  try {
    const res = await fetch(apiUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
      body: JSON.stringify({
        model: "deepseek-chat",
        messages: [{ role: "user", content: prompt }],
        temperature: 0.1,
        max_tokens: 600,
      }),
      signal: controller.signal,
    });
    clearTimeout(timeoutId);
    const latencyMs = Date.now() - startTime;

    if (res.ok) {
      const data = await res.json() as { choices?: [{ message?: { content?: string } }] };
      const content = data.choices?.[0]?.message?.content?.trim();
      if (content) {
        recordSuccess("deepseek");
        logLLMHealth("deepseek", "report_gen", true, latencyMs);
        console.log("[LLM-Report] Generated report for:", reportType, `(${content.length} chars)`);
        return content;
      }
    }
    recordFailure("deepseek");
    logLLMHealth("deepseek", "report_gen", false, latencyMs);
    console.warn("[LLM-Report] API non-ok or empty response, using fallback");
  } catch (e) {
    clearTimeout(timeoutId);
    const latencyMs = Date.now() - startTime;
    recordFailure("deepseek");
    logLLMHealth("deepseek", "report_gen", false, latencyMs);
    console.warn("[LLM-Report] Exception, using fallback:", String(e).slice(0, 80));
  }

  return generateFallbackReport(reportType, stats);
}

// ── User Engagement Tracking ──

function trackUsage(
  supabase: ReturnType<typeof createClient>,
  userOpenId: string,
  intent: { action: string; method: string; confidence: number },
  text: string,
) {
  try {
    supabase.from("audit_logs").insert({
      id: uuidv4(),
      action: "bot_command_usage",
      resource_type: "feishu_bot",
      resource_id: userOpenId,
      detail: { intent: intent.action, method: intent.method, text_snippet: text.slice(0, 100), confidence: intent.confidence },
      created_at: new Date().toISOString(),
    }).then(
      () => {},
      (err) => { console.warn("[Engagement] trackUsage DB write failed:", String(err).slice(0, 80)); },
    );
  } catch (e) {
    console.warn("[Engagement] trackUsage error:", String(e).slice(0, 80));
  }
}

interface UserProfile {
  profileStr: string;
  topIntents: string[];
  useCount: number;
}

async function getUserProfile(
  supabase: ReturnType<typeof createClient>,
  userOpenId: string,
): Promise<UserProfile> {
  const empty: UserProfile = { profileStr: "", topIntents: [], useCount: 0 };
  try {
    const { data: recentUses } = await supabase.from("audit_logs")
      .select("detail")
      .eq("action", "bot_command_usage")
      .eq("resource_id", userOpenId)
      .order("created_at", { ascending: false })
      .limit(20);

    if (!recentUses || recentUses.length === 0) return empty;

    const intentCounts: Record<string, number> = {};
    for (const row of recentUses) {
      let detail: Record<string, unknown> | undefined;
      if (typeof row.detail === "string") { try { detail = JSON.parse(row.detail); } catch { detail = undefined; } }
      else { detail = row.detail as Record<string, unknown> | undefined; }
      const intentName = (detail?.intent as string) || "unknown";
      intentCounts[intentName] = (intentCounts[intentName] || 0) + 1;
    }

    const intentLabels: Record<string, string> = {
      quality_report: "质检报告", compliance_check: "合规检查", generate_report: "生成报表",
      payment_reminder: "催单提醒", work_orders: "工单查询", knowledge_gaps: "知识缺口",
      bot_suggest: "话术建议", chat_stats: "会话统计", qa_evaluate: "质检评测",
      meeting_pipeline: "会议测试", help: "帮助", general_chat: "通用对话",
      daily_brief: "今日简报", system_health: "系统健康",
      batch_hitl_confirm: "全部确认", hitl_pending_count: "待处理", command_usage: "指令帮助",
      pipeline_status: "管线状态", pipeline_retry: "重试管线", pipeline_history: "管线历史",
      feedback_helpful: "反馈", feedback_unhelpful: "反馈",
      export_quality_reports: "导出质检", export_chat_sessions: "导出会话", export_work_orders: "导出工单",
      export_pipeline_jobs: "导出管线", recall: "撤回", share_report: "分享",
      emotion_detect: "情绪检测", quick_reply: "快捷回复", personality_switch: "风格切换",
      quality_improvement: "质检改进",
    };

    // Filter out non-business intents (help, general_chat, command_usage, etc.)
    const businessOnly = Object.entries(intentCounts)
      .filter(([intent]) => intentLabels[intent] &&
        !["help","general_chat","command_usage","feedback_helpful","feedback_unhelpful","share_report","recall"].includes(intent));
    const sorted = businessOnly.sort((a, b) => b[1] - a[1]);
    const top3 = sorted.slice(0, 3);

    const profileStr = top3.length > 0
      ? "常用功能: " + top3.map(([intent, count]) => `${intentLabels[intent] || intent}(${count}次)`).join(", ")
      : "";

    return {
      profileStr,
      topIntents: top3.map(([intent]) => intent),
      useCount: recentUses.length,
    };
  } catch (e) {
    console.warn("[Engagement] getUserProfile error:", String(e).slice(0, 80));
    return empty;
  }
}

async function getPersonalizedGreeting(
  supabase: ReturnType<typeof createClient>,
  userOpenId: string,
  tone?: string,
  botWelcomeMessage?: string,
): Promise<string> {
  try {
    // Fetch style-specific greeting from system_configs if a tone is specified
    let styleGreeting = "";
    const effectiveTone = tone || "professional";
    try {
      const { data } = await supabase
        .from("system_configs")
        .select("value")
        .eq("key", `style_${effectiveTone}`)
        .maybeSingle();
      if (data?.value && typeof data.value === "object") {
        const val = data.value as Record<string, unknown>;
        styleGreeting = (val.greeting as string) || "";
      }
    } catch { /* fall back to default greeting */ }

    const { data: recentUses } = await supabase.from("audit_logs")
      .select("detail")
      .eq("action", "bot_command_usage")
      .eq("resource_id", userOpenId)
      .order("created_at", { ascending: false })
      .limit(30);

    if (!recentUses || recentUses.length === 0) {
      // Bot welcome_message overrides all other greetings for first-time users
      if (botWelcomeMessage) return botWelcomeMessage;
      if (styleGreeting) return styleGreeting;
      return "👋 初次使用，发送「帮助」查看可用指令";
    }

    const intentCounts: Record<string, number> = {};
    for (const row of recentUses) {
      let detail: Record<string, unknown> | undefined;
      if (typeof row.detail === "string") { try { detail = JSON.parse(row.detail); } catch { detail = undefined; } }
      else { detail = row.detail as Record<string, unknown> | undefined; }
      const intentName = (detail?.intent as string) || "unknown";
      intentCounts[intentName] = (intentCounts[intentName] || 0) + 1;
    }

    const qaRelated = (intentCounts["quality_report"] || 0) + (intentCounts["qa_evaluate"] || 0) + (intentCounts["chat_stats"] || 0);
    const woRelated = (intentCounts["work_orders"] || 0) + (intentCounts["payment_reminder"] || 0);

    if (qaRelated >= 3) {
      return "📊 今日质检已就绪，发送「质检报告」查看";
    }
    if (woRelated >= 3) {
      return "📝 工单系统已待命";
    }

    if (styleGreeting) return styleGreeting;
    return "👋 欢迎回来，发送「帮助」查看可用指令";
  } catch (e) {
    console.warn("[Engagement] getPersonalizedGreeting error:", String(e).slice(0, 80));
    return "👋 初次使用，发送「帮助」查看可用指令";
  }
}

// ── Agent name resolution ──

async function findAgentName(
  supabase: ReturnType<typeof createClient>,
  senderId: string,
  chatId: string,
): Promise<string | null> {
  // Helper: resolve raw ID to display name via mapping
  const resolveName = async (rawId: string): Promise<string> => {
    try {
      const { data: mappingConfig } = await supabase
        .from("system_configs")
        .select("value")
        .eq("key", "agent_name_mapping")
        .maybeSingle();
      if (mappingConfig?.value) {
        const val = typeof mappingConfig.value === "string"
          ? JSON.parse(mappingConfig.value)
          : mappingConfig.value;
        if (val && typeof val === "object" && (val as Record<string, unknown>)[rawId]) {
          return (val as Record<string, string>)[rawId];
        }
      }
    } catch { /* ignore */ }
    return rawId; // fallback: return raw ID if no mapping
  };

  // Strategy 1: Check mapping for sender_id directly
  const nameFromSender = await resolveName(senderId);
  if (nameFromSender !== senderId) return nameFromSender;

  // Strategy 2: Look up customer_id from session, then resolve to name
  try {
    const { data: session } = await supabase
      .from("bot_chat_sessions")
      .select("customer_id")
      .eq("external_session_id", chatId)
      .maybeSingle();

    if (session?.customer_id) {
      return await resolveName(session.customer_id);
    }
  } catch { /* ignore */ }

  // Strategy 3: Fallback — use sender_id (already resolved in Strategy 1)
  return nameFromSender;
}

// ── Session context cache (in-memory, per-Edge-Function instance) ──

const sessionContextCache = new Map<string, string>();
const SESSION_CACHE_MAX = 100;

// ── Session style cache (in-memory, per-chat tone preference) ──
const sessionStyleCache = new Map<string, string>(); // chatId -> tone

async function getSessionContext(
  supabase: ReturnType<typeof createClient>,
  chatId: string,
  senderId: string,
): Promise<{ context: string; prevCustomerMsg: string }> {
  const sessionKey = `${chatId}:${senderId}`;
  try {
    const cached = sessionContextCache.get(sessionKey);
    if (cached !== undefined) {
      const lines = cached.split("\n");
      const customerLines = lines.filter((l) => l.startsWith("顾客:"));
      const prevCustomerMsg = customerLines.length > 0
        ? customerLines[customerLines.length - 1].replace(/^顾客:\s*/, "")
        : "";
      return { context: cached, prevCustomerMsg };
    }

    const { data } = await supabase
      .from("bot_chat_sessions")
      .select("conversation")
      .eq("external_session_id", chatId)
      .maybeSingle();

    if (!data?.conversation || typeof data.conversation !== "string") {
      return { context: "", prevCustomerMsg: "" };
    }

    const lines = data.conversation.split("\n");
    // Take last 10 lines (5 pairs of customer + bot)
    const recentLines = lines.slice(-10);
    const context = `[对话历史]\n${recentLines.join("\n")}`;
    const trimmed = context.length > 500 ? context.slice(0, 500) + "..." : context;

    // Extract last customer message for follow-up detection
    const customerLines = recentLines.filter((l: string) => l.startsWith("顾客:"));
    const prevCustomerMsg = customerLines.length > 0
      ? customerLines[customerLines.length - 1].replace(/^顾客:\s*/, "")
      : "";

    // Cache it
    if (sessionContextCache.size >= SESSION_CACHE_MAX) {
      const firstKey = sessionContextCache.keys().next().value;
      if (firstKey !== undefined) sessionContextCache.delete(firstKey);
    }
    sessionContextCache.set(sessionKey, trimmed);

    return { context: trimmed, prevCustomerMsg };
  } catch (e) {
    console.warn("[Session] getSessionContext error:", String(e).slice(0, 80));
    return { context: "", prevCustomerMsg: "" };
  }
}

function saveSessionContext(chatId: string, senderId: string, customerMsg: string, botReply: string): void {
  const sessionKey = `${chatId}:${senderId}`;
  try {
    const existing = sessionContextCache.get(sessionKey) || "";
    const emotion = detectEmotion(customerMsg);
    const emotionTag = emotion.level !== "neutral" ? `[客户情绪: ${emotion.level}] ` : "";
    const newLine = `${emotionTag}顾客: ${customerMsg}\n机器人: ${botReply}`;
    let updated = existing
      ? `${existing}\n${newLine}`
      : `[对话历史]\n${newLine}`;
    // Keep last 10 lines (5 pairs)
    const lines = updated.split("\n");
    if (lines.length > 11) {
      updated = lines[0] + "\n" + lines.slice(-10).join("\n");
    }
    if (updated.length > 500) {
      updated = updated.slice(0, 500) + "...";
    }
    // Evict oldest if at capacity
    if (sessionContextCache.size >= SESSION_CACHE_MAX) {
      const firstKey = sessionContextCache.keys().next().value;
      if (firstKey !== undefined) sessionContextCache.delete(firstKey);
    }
    sessionContextCache.set(sessionKey, updated);
  } catch (_) {
    // Best-effort cache update; failure is non-critical
  }
}

function detectFollowUp(text: string, prevCustomerMsg: string): string | null {
  if (!prevCustomerMsg) return null;
  const trimmed = text.trim();
  const shortMsg = trimmed.length < 10;
  const followUpWords = /里面|其中|刚才|那个|这个|之前|上次|刚说|上面|那些|哪/;
  if (shortMsg || followUpWords.test(trimmed)) {
    return prevCustomerMsg;
  }
  return null;
}

// ── Personality Engine ──

const personalityCache = new Map<string, { inject: string; cachedAt: number }>();
const PERSONALITY_CACHE_TTL_MS = 5 * 60 * 1000; // 5 minutes

async function getPersonalityInjection(
  supabase: ReturnType<typeof createClient>,
  tone?: string | null,
): Promise<string> {
  const effectiveTone = tone || "professional";

  // Check in-memory cache
  const cached = personalityCache.get(effectiveTone);
  if (cached && (Date.now() - cached.cachedAt) < PERSONALITY_CACHE_TTL_MS) {
    return cached.inject;
  }

  // Query system_configs for the style template prompt_inject text
  try {
    const { data } = await supabase
      .from("system_configs")
      .select("value")
      .eq("key", `style_${effectiveTone}`)
      .maybeSingle();

    if (data?.value && typeof data.value === "object") {
      const val = data.value as Record<string, unknown>;
      const promptInject = (val.prompt_inject as string) || "";
      personalityCache.set(effectiveTone, { inject: promptInject, cachedAt: Date.now() });
      return promptInject;
    }
  } catch (e) {
    console.warn("[Personality] lookup error:", String(e).slice(0, 80));
  }

  return "";
}

// ── Real-time Emotion Detection (keyword + heuristic, no LLM) ──

function detectEmotion(text: string): { level: string; keywords: string[]; suggestion: string } {
  const t = text.toLowerCase();
  if (/很?生气|投诉|举报|12315|消协|律师|太过分|忍无可忍/.test(t))
    return { level: "angry", keywords: ["投诉倾向","法律威胁"], suggestion: "警告：高怒客户：优先安抚情绪，避免争论，立即升级主管" };
  if (/失望|太慢|等.*天|还没|怎么.*还|忽悠|骗/.test(t))
    return { level: "frustrated", keywords: ["不满","等待焦虑"], suggestion: "注意：不满客户：主动道歉+给出明确时间承诺+补偿方案" };
  if (/谢谢|感谢|太好了|满意|不错/.test(t))
    return { level: "happy", keywords: ["满意"], suggestion: "满意客户：感谢认可，邀请好评或推荐" };
  if (/着急|快点|赶紧|催|急/.test(t))
    return { level: "urgent", keywords: ["紧急"], suggestion: "注意：紧急客户：优先处理，缩短响应时间，主动告知进度" };
  return { level: "neutral", keywords: [], suggestion: "" };
}

// ── Quick Reply Suggestions by Category ──

function getQuickReplies(category: string): string[] {
  const c = category.toLowerCase();
  if (/物流|发货|快递|运输|查物流/.test(c)) {
    return ["查物流: 请提供订单号我帮您查", "催发货: 已为您标记加急", "改地址: 请提供新地址我帮您修改"];
  }
  if (/退款|退钱|退货|退/.test(c)) {
    return ["申请退款: 请提供订单号+退款原因", "查询进度: 退款处理中一般1-3个工作日", "投诉: 已记录您的问题专员会联系您"];
  }
  if (/质量|瑕疵|破损|坏|品控/.test(c)) {
    return ["拍照上传: 请拍照商品问题处发给我", "换货: 可以为您安排换货", "补偿: 已申请补偿方案"];
  }
  if (/投诉|举报/.test(c)) {
    return ["情绪安抚: 非常抱歉给您带来不好的体验", "升级处理: 已为您转接高级专员", "问题记录: 已详细记录您反馈的问题"];
  }
  return ["查订单: 请提供订单号", "常见问题: 请查看帮助中心", "投诉建议: 已记录您的反馈，客服主管将跟进"];
}

// ── Feishu API helpers ──

async function getFeishuToken(): Promise<string> {
  const appId = Deno.env.get("FEISHU_APP_ID") || "";
  const appSecret = Deno.env.get("FEISHU_APP_SECRET") || "";
  let lastError = "";
  for (let attempt = 0; attempt < 2; attempt++) {
    if (attempt > 0) {
      console.warn("[Feishu] Token fetch retry after:", lastError);
      await new Promise((r) => setTimeout(r, 1000));
    }
    try {
      const res = await fetch("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ app_id: appId, app_secret: appSecret }),
      });
      const data = await res.json() as { code?: number; tenant_access_token?: string; msg?: string };
      if (res.ok && data.code === 0 && data.tenant_access_token) {
        return data.tenant_access_token;
      }
      lastError = data.msg || `HTTP ${res.status}`;
    } catch (e) {
      lastError = String(e).slice(0, 100);
    }
  }
  console.error("[Feishu] Token fetch FAILED after retry:", lastError);
  handleSystemAlert("飞书 Token 获取失败", { error: lastError, attempts: 2 });
  throw new Error(lastError || "Failed to get tenant_access_token");
}

async function sendFeishuReply(chatId: string, text: string, replyToMsgId?: string): Promise<string | null> {
  try {
    const token = await getFeishuToken();
    const body: Record<string, unknown> = {
      receive_id: chatId,
      msg_type: "text",
      content: JSON.stringify({ text }),
    };
    const res = await fetch(
      `https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id`,
      {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    );
    const data = await res.json() as { code?: number; msg?: string; data?: { message_id?: string } };
    if (!res.ok || (data.code !== undefined && data.code !== 0)) {
      console.error("[Feishu] Reply send failed:", data.msg);
      return null;
    } else {
      const msgId = data.data?.message_id || null;
      console.log(`[Feishu] Reply sent to ${chatId.slice(-12)}:`, text.slice(0, 50));
      if (msgId) {
        trackFeishuMessage(msgId, chatId, "bot_reply", text.slice(0, 200)).catch(() => {});
      }
      return msgId;
    }
  } catch (e) {
    console.error(`[Feishu] Reply send error (chatId=${chatId.slice(-12)}, msgLen=${text.length}):`, String(e).slice(0, 200));
    return null;
  }
}

async function sendFeishuCard(chatId: string, card: Record<string, unknown>, receiveIdType: "chat_id" | "open_id" = "chat_id") {
  const body = {
    receive_id: chatId,
    msg_type: "interactive",
    content: JSON.stringify({ config: { wide_screen_mode: true }, ...card }),
  };

  // Try Bot token first, fall back to user token on permission errors
  for (const tokenType of ["bot", "user"] as const) {
    let token: string;
    if (tokenType === "bot") {
      token = await getFeishuToken();
    } else {
      token = Deno.env.get("FEISHU_USER_ACCESS_TOKEN") || "";
      if (!token) continue; // No user token configured, skip
    }

    try {
      const res = await fetch(`https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=${receiveIdType}`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json() as { code?: number; msg?: string; data?: { message_id?: string } };

      if (res.ok && (data.code === undefined || data.code === 0)) {
        const msgId = data.data?.message_id || null;
        console.log(`[Feishu] Card sent via ${tokenType} to ${chatId.slice(-12)}, msg_id=${msgId}`);
        if (msgId) {
          const title = (card as { header?: { title?: { content?: string } } }).header?.title?.content || "";
          trackFeishuMessage(msgId, chatId, "bot_card", title).catch(() => {});
        }
        return msgId;
      }

      // 200341 = permission denied for bot → try user token
      if (data.code === 200341 && tokenType === "bot") {
        console.warn(`[Feishu] Bot permission denied (200341), trying user token...`);
        continue;
      }

      // Other errors or user token also failed
      console.error(`[Feishu] Card send failed via ${tokenType}:`, data.msg, "code:", data.code);
      if (tokenType === "user") return null; // Both tokens failed
    } catch (e) {
      console.error(`[Feishu] Card send error via ${tokenType} (chatId=${chatId.slice(-12)}):`, String(e).slice(0, 200));
      if (tokenType === "user") return null;
    }
  }

  return null;
}

async function sendFeishuReplyWithFeedback(chatId: string, reply: string) {
  const card = {
    config: { wide_screen_mode: true },
    header: {
      title: { tag: "plain_text", content: "🤖 机器人回复" },
    },
    elements: [
      {
        tag: "div",
        text: { tag: "lark_md", content: reply },
      },
      { tag: "hr" },
      {
        tag: "action",
        actions: [
          {
            tag: "button",
            text: { tag: "plain_text", content: "有帮助" },
            type: "primary",
            value: JSON.stringify({ action: "feedback_helpful", session_id: chatId, reply_text: reply }),
          },
          {
            tag: "button",
            text: { tag: "plain_text", content: "无帮助" },
            type: "danger",
            value: JSON.stringify({ action: "feedback_unhelpful", session_id: chatId, reply_text: reply }),
          },
        ],
      },
    ],
  };
  return sendFeishuCard(chatId, card);
}

// ── Message Tracking & Recall ──

async function trackFeishuMessage(messageId: string, chatId: string, messageType: string, contentSnippet: string): Promise<void> {
  try {
    const supabase = createClient(
      Deno.env.get("SUPABASE_URL") || "",
      Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "",
    );
    await supabase.from("feishu_messages").insert({
      message_id: messageId,
      chat_id: chatId,
      message_type: messageType,
      content: { snippet: contentSnippet },
      status: "sent",
      sent_at: new Date().toISOString(),
    });
  } catch (e) {
    console.warn("[Recall] trackFeishuMessage error:", String(e).slice(0, 80));
  }
}

async function updateFeishuCard(messageId: string, card: Record<string, unknown>): Promise<boolean> {
  try {
    const token = await getFeishuToken();
    const res = await fetch(
      `https://open.feishu.cn/open-apis/im/v1/messages/${messageId}`,
      {
        method: "PATCH",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({
          content: JSON.stringify({ config: { wide_screen_mode: true }, ...card }),
        }),
      },
    );
    const data = await res.json() as { code?: number; msg?: string };
    if (res.ok && (data.code === undefined || data.code === 0)) {
      console.log("[Recall] Card updated:", messageId.slice(-12));
      return true;
    }
    console.error("[Recall] Card update failed:", data.msg);
    return false;
  } catch (e) {
    console.error(`[Recall] Card update error (messageId=${messageId.slice(-12)}):`, String(e).slice(0, 200));
    return false;
  }
}

async function findRecentBotMessage(chatId: string, withinMinutes = 5): Promise<string | null> {
  try {
    const supabase = createClient(
      Deno.env.get("SUPABASE_URL") || "",
      Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "",
    );
    const cutoff = new Date(Date.now() - withinMinutes * 60 * 1000).toISOString();
    const { data } = await supabase
      .from("feishu_messages")
      .select("message_id")
      .eq("chat_id", chatId)
      .in("message_type", ["bot_reply", "bot_card"])
      .gte("sent_at", cutoff)
      .order("sent_at", { ascending: false })
      .limit(1);
    return (data?.[0]?.message_id as string) || null;
  } catch (e) {
    console.warn("[Recall] findRecentBotMessage error:", String(e).slice(0, 80));
    return null;
  }
}

async function recallLastBotMessage(chatId: string): Promise<string> {
  const messageId = await findRecentBotMessage(chatId, 5);
  if (!messageId) {
    return "没有可撤回的消息（仅支持撤回5分钟内的消息）";
  }
  const ok = await updateFeishuCard(messageId, {
    header: { title: { tag: "plain_text", content: "消息已撤回" }, template: "yellow" },
    elements: [{ tag: "div", text: { tag: "lark_md", content: "此消息已被撤回" } }],
  });
  if (ok) {
    try {
      const supabase = createClient(
        Deno.env.get("SUPABASE_URL") || "",
        Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "",
      );
      await supabase.from("feishu_messages")
        .update({ status: "updated", updated_at: new Date().toISOString() })
        .eq("message_id", messageId);
    } catch { /* non-critical */ }
    console.log("[Recall] Recalled message:", messageId.slice(-12));
    return "已撤回上一条消息";
  }
  return "撤回失败，请稍后重试";
}

// ── Auto-evaluation trigger (fire-and-forget -> Vercel evaluate API) ──
// VERCEL_APP_URL: Vercel deployment URL. Update via Supabase Dashboard when
// the domain changes (e.g. custom domain) -- no code change needed.
// Retries up to 3 times (2s apart); on final failure writes to audit_logs.

// ── RAG Knowledge Retrieval ──

async function getEmbedding(text: string): Promise<number[] | null> {
  const apiKey = Deno.env.get("EMBEDDING_API_KEY");
  if (!apiKey) return null;

  const apiUrl = Deno.env.get("EMBEDDING_API_URL") || "https://api.siliconflow.cn/v1/embeddings";
  const model = Deno.env.get("EMBEDDING_MODEL") || "Qwen/Qwen3-Embedding-0.6B";

  const startTime = Date.now();
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), EMBEDDING_TIMEOUT_MS);

  try {
    const res = await fetch(apiUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
      body: JSON.stringify({ model, input: text }),
      signal: controller.signal,
    });
    clearTimeout(timeoutId);
    const latencyMs = Date.now() - startTime;

    if (!res.ok) {
      console.warn("[RAG] Embedding API error:", res.status);
      recordFailure("embedding");
      logLLMHealth("embedding", "get_embedding", false, latencyMs);
      return null;
    }
    const data = await res.json() as { data?: Array<{ embedding: number[] }> };
    const embedding = data.data?.[0]?.embedding || null;
    if (embedding) {
      recordSuccess("embedding");
      logLLMHealth("embedding", "get_embedding", true, latencyMs);
    } else {
      logLLMHealth("embedding", "get_embedding", false, latencyMs);
    }
    return embedding;
  } catch (e) {
    clearTimeout(timeoutId);
    const latencyMs = Date.now() - startTime;
    recordFailure("embedding");
    logLLMHealth("embedding", "get_embedding", false, latencyMs);
    console.warn("[RAG] Embedding fetch error:", String(e).slice(0, 80));
    return null;
  }
}

async function searchKnowledge(
  supabase: ReturnType<typeof createClient>,
  embedding: number[],
  query: string,
  limit = 3,
): Promise<{ context: string; tone: string | null }> {
  // Try pgvector similarity via existing match_knowledge_entries RPC
  try {
    const { data, error } = await supabase.rpc("match_knowledge_entries", {
      query_embedding: embedding,
      match_count: limit,
    });
    if (!error && data && Array.isArray(data) && data.length > 0) {
      const entries = data as Array<{ title?: string; content?: string; similarity?: number; tone?: string }>;
      console.log("[RAG] Vector search hit", entries.length, "entries, top similarity:", entries[0]?.similarity);
      const tone = entries.find((e) => e.tone)?.tone || null;
      return {
        context: entries
          .map((e) => `- ${e.title || "未命名"}: ${(e.content || "").slice(0, 250)}`)
          .join("\n"),
        tone,
      };
    }
    if (error) console.warn("[RAG] Vector search RPC error:", error.message);
  } catch (e) {
    console.warn("[RAG] Vector search unavailable, falling back to text:", String(e).slice(0, 80));
  }

  // Fallback: text search via ilike
  try {
    const keyword = query.slice(0, 40).replace(/[%_]/g, "");
    if (!keyword) return { context: "", tone: null };
    const { data } = await supabase
      .from("knowledge_entries")
      .select("title,content,category,tone")
      .or(`title.ilike.%${keyword}%,content.ilike.%${keyword}%`)
      .limit(limit);
    if (data && data.length > 0) {
      console.log("[RAG] Text search hit", data.length, "entries");
      const entries = data as Array<{ title?: string; content?: string; tone?: string }>;
      const tone = entries.find((e) => e.tone)?.tone || null;
      return {
        context: entries
          .map((e) => `- ${e.title || "未命名"}: ${(e.content || "").slice(0, 250)}`)
          .join("\n"),
        tone,
      };
    }
  } catch (e) {
    console.warn("[RAG] Text search error:", String(e).slice(0, 80));
  }

  return { context: "", tone: null };
}

// Scene-to-cost-tier mapping: simple questions → budget models, complex → premium
const SCENE_MODEL_TIERS: Record<string, "budget" | "standard" | "premium"> = {
  general_chat: "budget", help: "budget", quick_reply: "budget", command_usage: "budget",
  emotion_detect: "budget", chat_stats: "budget", system_health: "budget",
  quality_report: "standard", generate_report: "standard", daily_brief: "standard",
  knowledge_gaps: "standard", bot_suggest: "standard", work_orders: "standard",
  pipeline_status: "standard", pipeline_detail: "standard", pipeline_history: "standard",
  hitl_pending_count: "standard", batch_hitl_confirm: "standard",
  compliance_check: "premium", qa_evaluate: "premium", meeting_pipeline: "premium",
  payment_reminder: "premium", export_quality_reports: "premium",
  export_chat_sessions: "premium", export_work_orders: "premium", export_pipeline_jobs: "premium",
  quality_improvement: "premium",
};

function sortModelChainByTier(
  chain: Array<{ apiKey: string; apiUrl: string; modelName: string; provider: string; temperature: number; maxTokens: number }>,
  intentAction?: string,
): Array<{ apiKey: string; apiUrl: string; modelName: string; provider: string; temperature: number; maxTokens: number }> {
  if (!intentAction || chain.length <= 1) return chain;
  const targetTier = SCENE_MODEL_TIERS[intentAction] || "standard";
  // Priority ranges: premium=1-5, standard=6-20, budget=21+
  const tierMatches = chain.filter((m, i) => {
    const priority = i + 1;
    if (targetTier === "premium") return priority <= 5;
    if (targetTier === "standard") return priority <= 20;
    return true; // budget: all models
  });
  return tierMatches.length > 0 ? tierMatches : chain; // fallback to full chain
}

async function generateBotReplyWithRAG(
  supabase: ReturnType<typeof createClient>,
  text: string,
  sessionContext?: string,
  personalityInjection?: string,
  intentAction?: string,
): Promise<string> {
  // Try to fetch active prompt + model fallback chain from DB
  let activePrompt: string | undefined;
  const rawChain = await getModelFallbackChain(supabase).catch(() => [] as Array<{ apiKey: string; apiUrl: string; modelName: string; provider: string; temperature: number; maxTokens: number }>);
  const modelChain = sortModelChainByTier(rawChain, intentAction);
  try {
    const { data: promptData } = await supabase
      .from("prompts")
      .select("system_prompt")
      .eq("is_active", true)
      .eq("status", "published")
      .order("updated_at", { ascending: false })
      .limit(1)
      .maybeSingle();
    if (promptData?.system_prompt) activePrompt = promptData.system_prompt as string;
  } catch { /* ignore */ }

  // Skip RAG entirely if no embedding API key configured
  if (!Deno.env.get("EMBEDDING_API_KEY")) {
    return generateBotReply(text, undefined, undefined, sessionContext, personalityInjection, activePrompt, modelChain);
  }

  // If primary model's circuit is open, skip expensive embedding
  const primaryProvider = modelChain[0]?.provider || "deepseek";
  if (isCircuitOpen(primaryProvider)) {
    console.warn(`[RAG] Circuit breaker open for ${primaryProvider}, skipping RAG`);
    return generateBotReply(text, undefined, undefined, sessionContext, personalityInjection, activePrompt, modelChain);
  }

  try {
    const result = await Promise.race([
      (async () => {
        const embedding = await getEmbedding(text);
        if (!embedding) return { ctx: "", sources: [] as string[], articleTone: null as string | null };
        const { context: ctx, tone: articleTone } = await searchKnowledge(supabase, embedding, text);
        const sources = ctx
          .split("\n")
          .filter(line => line.match(/^-\s*[^:]+:/))
          .map(line => line.replace(/^-\s*/, "").split(":")[0].trim())
          .filter(Boolean);
        return { ctx, sources, articleTone };
      })(),
      new Promise<{ ctx: string; sources: string[]; articleTone: string | null }>((resolve) =>
        setTimeout(() => resolve({ ctx: "", sources: [], articleTone: null }), 2000)
      ),
    ]);

    // Resolve personality injection: user preference > article tone > default (none)
    let finalInjection = personalityInjection || "";
    if (!finalInjection && result.articleTone && result.articleTone !== "professional") {
      finalInjection = await getPersonalityInjection(supabase, result.articleTone);
    }

    return generateBotReply(text, result.ctx || undefined, result.sources.length > 0 ? result.sources : undefined, sessionContext, finalInjection, activePrompt, activeModel);
  } catch (e) {
    console.warn("[RAG] Error, falling back to standard reply:", String(e).slice(0, 80));
    return generateBotReply(text, undefined, undefined, sessionContext, personalityInjection, activePrompt, activeModel);
  }
}

// Fetch model fallback chain from DB (sorted by priority ASC), with env var fallback
async function getModelFallbackChain(supabase: ReturnType<typeof createClient>): Promise<Array<{ apiKey: string; apiUrl: string; modelName: string; provider: string; temperature: number; maxTokens: number }>> {
  try {
    const { data } = await supabase
      .from("model_configs")
      .select("provider, model_name, api_key, api_url, temperature, max_tokens")
      .eq("is_active", true)
      .order("priority", { ascending: true });
    if (data && Array.isArray(data) && data.length > 0) {
      const chain: Array<{ apiKey: string; apiUrl: string; modelName: string; provider: string; temperature: number; maxTokens: number }> = [];
      for (const row of data) {
        const config = row as Record<string, unknown>;
        const provider = (config.provider as string) || "deepseek";
        const envKey = provider === "kimi" || provider === "moonshot" ? "MOONSHOT" : (provider === "openai" ? "OPENAI" : "DEEPSEEK");
        const apiKey = (config.api_key as string) || Deno.env.get(`${envKey}_API_KEY`) || "";
        const apiUrl = (config.api_url as string) || Deno.env.get(`${envKey}_API_URL`) || "";
        if (apiKey && apiUrl) {
          chain.push({
            apiKey, apiUrl, provider,
            modelName: (config.model_name as string) || "deepseek-chat",
            temperature: (config.temperature as number) ?? 0.7,
            maxTokens: (config.max_tokens as number) ?? 2048,
          });
        }
      }
      if (chain.length > 0) return chain;
    }
  } catch { /* fall through to env vars */ }
  // Fallback to env vars as a single-entry chain
  return [{
    apiKey: Deno.env.get("DEEPSEEK_API_KEY") || Deno.env.get("MOONSHOT_API_KEY") || "",
    apiUrl: Deno.env.get("DEEPSEEK_API_URL") || Deno.env.get("MOONSHOT_API_URL") || "",
    modelName: "deepseek-chat",
    provider: "deepseek",
    temperature: 0.3,
    maxTokens: 256,
  }];
}

async function generateBotReply(text: string, knowledgeContext?: string, knowledgeSources?: string[], sessionContext?: string, personalityInjection?: string, customSystemPrompt?: string, modelChain?: Array<{ apiKey: string; apiUrl: string; modelName: string; provider: string; temperature: number; maxTokens: number }>): Promise<string> {
  const chain = (modelChain && modelChain.length > 0) ? modelChain : [{
    apiKey: Deno.env.get("DEEPSEEK_API_KEY") || "", apiUrl: Deno.env.get("DEEPSEEK_API_URL") || "",
    modelName: "deepseek-chat", provider: "deepseek", temperature: 0.3, maxTokens: 256,
  }];

  // Try each model in the fallback chain
  for (let i = 0; i < chain.length; i++) {
    const mc = chain[i];
    const provider = mc.provider || "deepseek";
    const apiKey = mc.apiKey || "";
    const apiUrl = mc.apiUrl || "";
    if (!apiKey || !apiUrl) continue;

    // Circuit breaker: skip this model if circuit is open
    if (isCircuitOpen(provider)) {
      console.warn(`[LLM] Circuit breaker open for ${provider} (priority ${i+1}/${chain.length}), trying next...`);
      continue; // try next model in chain
    }

    const startTime = Date.now();
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), GENERATE_REPLY_TIMEOUT_MS);

    try {
      let systemPrompt: string;
      if (customSystemPrompt) {
        systemPrompt = customSystemPrompt;
        if (knowledgeContext) {
          systemPrompt += `\n\n## 可用的知识库条目（仅供参考）：\n${knowledgeContext.slice(0, 800)}`;
        }
      } else if (knowledgeContext) {
        systemPrompt = `你是电商客服助手。回复要求：1. 简洁专业，2-4句话 2. 语气亲切但不油腻 3. 针对客户问题给出具体解决方案或下一步指引 4. 不要使用「亲」「亲亲」等过度亲昵称呼 5. 不要编造订单号或物流单号 6. 如果涉及退款/投诉，引导客户提供订单号 7. 当客户表述模糊时（如「送妈妈合适吗」「这个怎么样」），主动追问1-2个关键问题（如使用场景、年龄段、预算）后再给出建议\n\n## 可用的知识库条目（仅供参考，不要编造）：\n${knowledgeContext.slice(0, 800)}`;
      } else {
        systemPrompt = "你是电商客服助手。回复要求：1. 简洁专业，2-4句话 2. 语气亲切但不油腻 3. 针对客户问题给出具体解决方案或下一步指引 4. 不要使用「亲」「亲亲」等过度亲昵称呼 5. 不要编造订单号或物流单号 6. 如果涉及退款/投诉，引导客户提供订单号 7. 当客户表述模糊时（如「送妈妈合适吗」「这个怎么样」），主动追问1-2个关键问题（如使用场景、年龄段、预算）后再给出建议";
      }

      if (personalityInjection) {
        systemPrompt = `## 回复风格要求：\n${personalityInjection}\n\n---\n\n${systemPrompt}`;
      }

      if (sessionContext) {
        systemPrompt = `## 对话历史（最近消息）：\n${sessionContext}\n\n## 当前用户问题：\n${text}\n\n---\n\n${systemPrompt}`;
      }

      const res = await fetch(apiUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
        body: JSON.stringify({
          model: mc.modelName,
          messages: [
            { role: "system", content: systemPrompt },
            { role: "user", content: text },
          ],
          temperature: mc.temperature,
          max_tokens: mc.maxTokens,
        }),
        signal: controller.signal,
      });
      clearTimeout(timeoutId);
      const latencyMs = Date.now() - startTime;

        if (res.ok) {
          const data = await res.json() as { choices?: [{ message?: { content?: string } }] };
          let reply = data.choices?.[0]?.message?.content?.trim();
          if (reply) {
            if (reply.length > 1000) {
              reply = reply.slice(0, 1000);
              console.warn("[LLM] Reply trimmed to 1000 chars");
            }
            recordSuccess(provider);
            logLLMHealth(provider, "reply_gen", true, latencyMs);
            console.log(`[LLM] Reply by ${provider}/${mc.modelName} in ${latencyMs}ms`);
            if (i > 0) console.log(`[LLM] ⚠️ Used fallback model (priority ${i+1})`);
            if (knowledgeSources && knowledgeSources.length > 0) {
              const uniqueSources = [...new Set(knowledgeSources)].slice(0, 3);
              return reply + `\n\n${uniqueSources.map(s => `📎 ${s}`).join("  ")}`;
            }
            return reply;
          }
        }
        // This model failed — record failure and try next in chain
        recordFailure(provider);
        logLLMHealth(provider, "reply_gen", false, latencyMs);
        console.warn(`[LLM] ${provider}/${mc.modelName} failed (priority ${i+1}), trying next...`);
      } catch (e) {
        clearTimeout(timeoutId);
        recordFailure(provider);
        logLLMHealth(provider, "reply_gen", false, Date.now() - startTime);
        console.error(`[LLM] ${provider}/${mc.modelName} error:`, String(e).slice(0, 80));
    }
  }

  // Fallback: keyword matching
  const t = text.toLowerCase();
  if (t.includes("发货") || t.includes("物流") || t.includes("快递") || t.includes("订单")) return "您好，订单物流问题已收到。仓库正常处理时效为48小时内更新物流信息，如需加急处理请提供订单号，我为您标记优先。";
  if (t.includes("退款") || t.includes("退货") || t.includes("退钱")) return "您好，退款申请已记录。售后会在1个工作日内核实处理，请提供订单号以便加快处理进度。";
  if (t.includes("优惠券") || t.includes("满减") || t.includes("活动")) return "您好，优惠活动咨询已收到。不同活动规则有差异，建议查看商品详情页说明，或提供具体券码我帮您核实使用条件。";
  if (t.includes("质量") || t.includes("瑕疵") || t.includes("破损")) return "非常抱歉给您带来不便！商品质量问题我们高度重视，请拍照上传问题商品，售后专员将优先为您处理退换货。";
  return "您好，已收到您的消息。客服正在处理中，请稍等片刻。如需紧急处理请直接说明问题类型（物流/退款/质量等），感谢您的耐心。";
}

// ── Quality Improvement Feedback Loop ──

async function generateImprovementSuggestions(
  violations: Array<{ category: string; rule: string; deduction: number; source_quote?: string }>,
): Promise<Array<{ category: string; quote: string; improvement: string }>> {
  const apiKey = Deno.env.get("DEEPSEEK_API_KEY") || "";
  const apiUrl = Deno.env.get("DEEPSEEK_API_URL") || "";

  if (!apiKey || !apiUrl) return [];

  if (isCircuitOpen("deepseek")) {
    console.warn("[Improvement] Circuit breaker open, skipping LLM suggestions");
    return [];
  }

  const startTime = Date.now();
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), LLM_REPORT_TIMEOUT_MS);

  try {
    const violationsJson = JSON.stringify(violations, null, 2);
    const res = await fetch(apiUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
      body: JSON.stringify({
        model: Deno.env.get("DEEPSEEK_API_KEY") ? "deepseek-chat" : (Deno.env.get("MOONSHOT_API_KEY") ? "moonshot-v1-8k" : "deepseek-chat"),
        messages: [
          {
            role: "system",
            content: `你是客服质检改进顾问。根据以下质检违规记录，为客服生成具体、可操作的改进建议。

要求：
1. 每条建议必须引用原文片段（source_quote）
2. 给出具体的改进话术示例
3. 语气是帮助成长，不是批评
4. 每条建议不超过2行

违规记录：
${violationsJson}

请以JSON格式返回：{"suggestions": [{"category": "...", "quote": "...", "improvement": "..."}]}`,
          },
        ],
        temperature: 0.3,
        max_tokens: 800,
      }),
      signal: controller.signal,
    });
    clearTimeout(timeoutId);
    const latencyMs = Date.now() - startTime;

    if (res.ok) {
      const data = await res.json() as { choices?: [{ message?: { content?: string } }] };
      const raw = data.choices?.[0]?.message?.content?.trim();
      if (raw) {
        const jsonMatch = raw.match(/\{[\s\S]*\}/);
        if (jsonMatch) {
          const parsed = JSON.parse(jsonMatch[0]);
          if (parsed.suggestions && Array.isArray(parsed.suggestions)) {
            recordSuccess("deepseek");
            logLLMHealth("deepseek", "improvement_suggest", true, latencyMs);
            return parsed.suggestions;
          }
        }
      }
    }
    logLLMHealth("deepseek", "improvement_suggest", false, latencyMs);
  } catch (e) {
    clearTimeout(timeoutId);
    const latencyMs = Date.now() - startTime;
    if (String(e).includes("abort")) {
      logLLMHealth("deepseek", "improvement_suggest", false, latencyMs);
    } else {
      recordFailure("deepseek");
      logLLMHealth("deepseek", "improvement_suggest", false, latencyMs);
    }
    console.warn("[Improvement] LLM error:", String(e).slice(0, 80));
  }

  return [];
}

async function sendImprovementCard(
  chatId: string,
  agentName: string,
  reportId: string,
  violations: Array<{ category: string; rule: string; deduction: number; source_quote?: string }>,
  suggestions: Array<{ category: string; quote: string; improvement: string }>,
) {
  const elements: Array<Record<string, unknown>> = [];

  // Show improvement suggestions (or fallback to violations)
  if (suggestions.length > 0) {
    for (const s of suggestions) {
      elements.push({
        tag: "div",
        text: {
          tag: "lark_md",
          content: `**${s.category}**\n引用: "${s.quote}"\n💡 ${s.improvement}`,
        },
      });
      elements.push({ tag: "hr" });
    }
  } else {
    // Fallback: show violations without LLM suggestions
    for (const v of violations) {
      elements.push({
        tag: "div",
        text: {
          tag: "lark_md",
          content: `**${v.category}** — ${v.rule}\n原文: "${v.source_quote || "（无原文片段）"}"\n扣分: ${v.deduction}分`,
        },
      });
      elements.push({ tag: "hr" });
    }
  }

  // Acknowledge button
  elements.push({
    tag: "action",
    actions: [
      {
        tag: "button",
        text: { tag: "plain_text", content: "✅ 已理解" },
        type: "primary",
        value: JSON.stringify({
          action: "improvement_acknowledged",
          report_id: reportId,
          agent_name: agentName,
        }),
      },
    ],
  });

  // Privacy footer
  elements.push({
    tag: "note",
    elements: [
      { tag: "plain_text", content: "此建议仅对你可见，旨在帮助你提升服务质量" },
    ],
  });

  return sendFeishuCard(chatId, {
    header: {
      title: { tag: "plain_text", content: `📝 质检改进建议 | ${agentName}` },
      template: "green",
    },
    elements,
  });
}

// ── Auto-evaluation follow-up: fire-and-forget improvement check ──

async function autoSendImprovementAfterEval(
  supabase: ReturnType<typeof createClient>,
  chatId: string,
  senderId: string,
  ticketId: string,
) {
  try {
    // Delay to allow async evaluation to complete (fire-and-forget, already async)
    await new Promise((r) => setTimeout(r, 8000));

    // Query for the quality report created by this evaluation
    const { data: reports } = await supabase
      .from("quality_reports")
      .select("*")
      .eq("ticket_id", ticketId)
      .order("created_at", { ascending: false })
      .limit(1);

    if (!reports || reports.length === 0) {
      console.log("[Improvement] No report found for ticket:", ticketId.slice(-20));
      return;
    }

    const report = reports[0] as Record<string, unknown>;
    const totalScore = (report.total_score as number) || 0;
    const violations = Array.isArray(report.violations) ? report.violations as Array<{ category: string; rule: string; deduction: number; source_quote?: string }> : [];
    const agentName = (report.agent_name as string) || "";

    // Only send improvement card if score < 80 or violations exist
    if (totalScore >= 80 && violations.length === 0) {
      console.log("[Improvement] Score OK, skipping improvement card");
      return;
    }

    if (!agentName) {
      console.log("[Improvement] No agent_name on report, skipping");
      return;
    }

    // Find agent's chat_id from agent_name_mapping (reverse lookup)
    let agentChatId = chatId; // default: same chat
    try {
      const { data: mappingConfig } = await supabase
        .from("system_configs")
        .select("value")
        .eq("key", "agent_name_mapping")
        .maybeSingle();
      if (mappingConfig?.value) {
        const val = typeof mappingConfig.value === "string"
          ? JSON.parse(mappingConfig.value)
          : mappingConfig.value;
        if (val && typeof val === "object") {
          // Reverse lookup: agent_name -> open_id
          for (const [openId, name] of Object.entries(val as Record<string, string>)) {
            if (name === agentName) {
              agentChatId = openId;
              break;
            }
          }
        }
      }
    } catch { /* use default chatId */ }

    // Generate suggestions
    const suggestions = await generateImprovementSuggestions(violations);

    // Send improvement card
    await sendImprovementCard(agentChatId, agentName, (report.id as string) || "", violations, suggestions);
    console.log("[Improvement] Auto-sent improvement card to agent:", agentName);
  } catch (e) {
    console.error("[Improvement] autoSendImprovementAfterEval error:", String(e).slice(0, 200));
  }
}

async function triggerAutoEvaluation(
  supabase: ReturnType<typeof createClient>,
  chatId: string,
  senderId: string,
  text: string,
  eventId: string,
  reply?: string,
): Promise<string> {
  const vercelUrl = Deno.env.get("VERCEL_APP_URL") || "https://qa-system-ain2k9x2x-yyy99045s-projects.vercel.app";
  const botReply = reply || "亲亲您好，您的问题已收到，客服正在处理中～";
  const conversation = `顾客: ${text}\n机器人: ${botReply}`;
  const ticketId = `feishu_${chatId}_${Date.now()}_${uuidv4().slice(0, 8)}`;

  const payload = {
    conversation,
    ticket_id: ticketId,
    skip_feishu: true,
    review_mode: "shadow",
  };

  let lastError = "";

  for (let attempt = 0; attempt < 3; attempt++) {
    if (attempt > 0) {
      await new Promise((r) => setTimeout(r, 2000));
    }
    try {
      const res = await fetch(`${vercelUrl}/api/qa/evaluate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        console.log(`[Feishu] Auto-eval OK (attempt ${attempt + 1}) for`, chatId.slice(-12));
        return ticketId;
      }
      lastError = `HTTP ${res.status}`;
      console.warn(`[Feishu] Auto-eval attempt ${attempt + 1}/3 failed:`, lastError);
    } catch (err) {
      lastError = String(err).slice(0, 200);
      console.warn(`[Feishu] Auto-eval attempt ${attempt + 1}/3 error:`, lastError);
    }
  }

  // All retries exhausted — persist failure for diagnosis
  console.error(`[Feishu] Auto-eval FAILED after 3 attempts:`, lastError);
  try {
    await supabase
      .from("audit_logs")
      .insert({
        id: uuidv4(),
        action: "auto_evaluate_failed",
        resource_type: "feishu_raw_events",
        resource_id: eventId,
        detail: {
          chat_id: chatId,
          ticket_id: ticketId,
          error: lastError,
          conversation_preview: text.slice(0, 100),
        },
        correlation_id: `feishu_evt_${uuidv4().slice(0, 12)}`,
        created_at: new Date().toISOString(),
      });
  } catch (auditErr) {
    console.error("[Feishu] Failed to write auto_evaluate_failed audit:", auditErr);
  }

  // Alert with debounce (once per N minutes per chatId)
  try {
    const debounceMinutes = parseInt(Deno.env.get("ALERT_DEBOUNCE_MINUTES") || "5", 10);
    const cutoff = new Date(Date.now() - debounceMinutes * 60 * 1000).toISOString();
    const { data: recentAlerts } = await supabase
      .from("audit_logs")
      .select("id")
      .eq("action", "system_error")
      .eq("resource_type", "auto_evaluation_exhausted")
      .eq("detail->>chat_id", chatId)
      .gt("created_at", cutoff)
      .limit(1);
    if (!recentAlerts || recentAlerts.length === 0) {
      console.log("[Feishu] Sending evaluation exhausted alert for chatId:", chatId.slice(-12));
      await supabase.from("audit_logs").insert({
        id: uuidv4(),
        action: "system_error",
        resource_type: "auto_evaluation_exhausted",
        resource_id: eventId,
        detail: { chat_id: chatId, ticket_id: ticketId, error: lastError },
        created_at: new Date().toISOString(),
      });
      handleSystemAlert("自动评估重试耗尽", {
        chat_id: chatId,
        ticket_id: ticketId,
        error: lastError,
      }).catch(e => console.error("[Feishu] Alert send failed:", String(e)));
    } else {
      console.log("[Feishu] Evaluation alert suppressed (debounce active for chatId:", chatId.slice(-12) + ")");
    }
  } catch (alertErr) {
    console.error("[Feishu] Evaluation alert debounce check error:", String(alertErr));
  }
}

// ── System Alert ──

async function handleSystemAlert(message: string, context: Record<string, unknown>): Promise<void> {
  const groupChatId = Deno.env.get("FEISHU_GROUP_CHAT_ID") || "";
  if (!groupChatId) {
    console.error("[Feishu] handleSystemAlert: FEISHU_GROUP_CHAT_ID not configured, cannot send alert");
    return;
  }
  let token = "";
  try {
    const appId = Deno.env.get("FEISHU_APP_ID") || "";
    const appSecret = Deno.env.get("FEISHU_APP_SECRET") || "";
    const res = await fetch("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ app_id: appId, app_secret: appSecret }),
    });
    const data = await res.json() as { code?: number; tenant_access_token?: string; msg?: string };
    if (res.ok && data.code === 0 && data.tenant_access_token) {
      token = data.tenant_access_token;
    }
  } catch (_) { /* best-effort */ }
  if (!token) {
    console.error("[Feishu] handleSystemAlert: could not get Feishu token for alerting");
    return;
  }
  try {
    const contextStr = Object.entries(context)
      .map(([k, v]) => `- **${k}:** ${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
      .join("\n");
    const cardContent = JSON.stringify({
      config: { wide_screen_mode: true },
      header: {
        title: { tag: "plain_text", content: "⚠️ 系统异常告警" },
        template: "yellow",
      },
      elements: [{
        tag: "div",
        text: {
          tag: "lark_md",
          content: `**告警信息:** ${message}\n\n**上下文详情:**\n${contextStr}`,
        },
      }],
    });
    const res = await fetch(
      `https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id`,
      {
        method: "POST",
        headers: { "Authorization": `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({
          receive_id: groupChatId,
          msg_type: "interactive",
          content: cardContent,
        }),
      },
    );
    if (res.ok) {
      console.log("[Feishu] System alert card sent OK");
    } else {
      const errText = await res.text().catch(() => "");
      console.error(`[Feishu] System alert card FAILED: HTTP ${res.status} ${errText.slice(0, 200)}`);
    }
  } catch (e) {
    console.error(`[Feishu] System alert card send error (alert=${message.slice(0, 50)}):`, String(e).slice(0, 200));
  }
}
// ── Alert aggregation & quiet hours helpers ──

function isQuietHours(): boolean {
  const start = Deno.env.get("ALERT_QUIET_START") || "22:00";
  const end = Deno.env.get("ALERT_QUIET_END") || "08:00";
  const now = new Date();
  const nowMinutes = now.getHours() * 60 + now.getMinutes();
  const [startH, startM] = start.split(":").map(Number);
  const [endH, endM] = end.split(":").map(Number);
  const startMinutes = startH * 60 + startM;
  const endMinutes = endH * 60 + endM;

  if (startMinutes > endMinutes) {
    // Overnight: e.g. 22:00 - 08:00
    return nowMinutes >= startMinutes || nowMinutes < endMinutes;
  }
  return nowMinutes >= startMinutes && nowMinutes < endMinutes;
}

function getAlertTargets(): { type: "group"; chatId: string } | { type: "users"; openIds: string[] } {
  const subscribed = Deno.env.get("ALERT_SUBSCRIBED_USERS") || "";
  if (subscribed.trim()) {
    const openIds = subscribed.split(",").map(s => s.trim()).filter(Boolean);
    if (openIds.length > 0) return { type: "users", openIds };
  }
  return { type: "group", chatId: Deno.env.get("FEISHU_GROUP_CHAT_ID") || "" };
}

async function sendAlertToTargets(
  targets: ReturnType<typeof getAlertTargets>,
  card: Record<string, unknown>,
) {
  let token = "";
  try {
    token = await getFeishuToken();
  } catch {
    console.error("[Alert] Cannot get Feishu token for alert card");
    return;
  }
  const content = JSON.stringify({ config: { wide_screen_mode: true }, ...card });

  if (targets.type === "group") {
    if (!targets.chatId) { console.error("[Alert] No group chat ID"); return; }
    try {
      await fetch(`https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ receive_id: targets.chatId, msg_type: "interactive", content }),
      });
      console.log("[Alert] Card sent to group");
    } catch (e) {
      console.error("[Alert] Group card send error:", String(e));
    }
  } else {
    for (const openId of targets.openIds) {
      try {
        await fetch(`https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id`, {
          method: "POST",
          headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
          body: JSON.stringify({ receive_id: openId, msg_type: "interactive", content }),
        });
        console.log("[Alert] Card sent to user:", openId.slice(-8));
      } catch (e) {
        console.error("[Alert] User card send error:", openId.slice(-8), String(e));
      }
    }
  }
}

// ── Proactive Alerts ──

async function checkProactiveAlerts(supabase: ReturnType<typeof createClient>) {
  const now = Date.now();
  const fourHoursAgo = new Date(now - 4 * 60 * 60 * 1000).toISOString();
  const thirtyMinAgo = new Date(now - 30 * 60 * 1000).toISOString();

  const targets = getAlertTargets();
  if (targets.type === "group" && !targets.chatId) {
    console.log("[Proactive] No FEISHU_GROUP_CHAT_ID, skipping");
    return;
  }
  if (targets.type === "users" && targets.openIds.length === 0) {
    console.log("[Proactive] No subscribed users, skipping");
    return;
  }

  const quiet = isQuietHours();
  if (quiet) console.log("[Proactive] Currently in quiet hours");

  try {
    const triggeredAlerts: Array<{
      type: string;
      resourceType: string;
      count: number;
      detail: Record<string, unknown>;
    }> = [];

    // a) Stale work orders (>24h, status open/pending) — NON-CRITICAL
    const staleSince = new Date(now - 24 * 60 * 60 * 1000).toISOString();

    const { data: staleDebounce } = await supabase
      .from("audit_logs")
      .select("id")
      .eq("action", "aggregated_alert")
      .eq("resource_type", "stale_work_orders_alert")
      .gt("created_at", fourHoursAgo)
      .limit(1);

    if (!staleDebounce || staleDebounce.length === 0) {
      const { count: staleCount, error: staleErr } = await supabase
        .from("work_orders")
        .select("*", { count: "exact", head: true })
        .in("status", ["open", "pending"])
        .lt("created_at", staleSince);

      if (!staleErr && staleCount && staleCount > 0) {
        const detail = { count: staleCount, threshold_hours: 24 };
        const recordId = targets.type === "group" ? targets.chatId : targets.openIds.join(",");

        if (quiet) {
          // Suppress non-critical alert during quiet hours
          console.log("[Proactive] Stale work orders alert suppressed (quiet hours)");
          await supabase.from("audit_logs").insert({
            id: uuidv4(), action: "suppressed_alert", resource_type: "stale_work_orders_alert",
            resource_id: recordId, detail,
            created_at: new Date().toISOString(),
          });
        } else {
          await supabase.from("audit_logs").insert({
            id: uuidv4(), action: "aggregated_alert", resource_type: "stale_work_orders_alert",
            resource_id: recordId, detail,
            created_at: new Date().toISOString(),
          });
          triggeredAlerts.push({
            type: "工单超时", resourceType: "stale_work_orders_alert",
            count: staleCount, detail,
          });
        }
      }
    }

    // b) Quality spike (last hour, critical > 5) — CRITICAL, always fires
    const oneHourAgo = new Date(now - 60 * 60 * 1000).toISOString();

    const { data: spikeDebounce } = await supabase
      .from("audit_logs")
      .select("id")
      .eq("action", "aggregated_alert")
      .eq("resource_type", "quality_spike_alert")
      .gt("created_at", fourHoursAgo)
      .limit(1);

    if (!spikeDebounce || spikeDebounce.length === 0) {
      const { count: criticalCount, error: qErr } = await supabase
        .from("quality_reports")
        .select("*", { count: "exact", head: true })
        .eq("risk_level", "critical")
        .gt("created_at", oneHourAgo);

      if (!qErr && criticalCount !== null && criticalCount > 5) {
        const detail = { count: criticalCount, window_hours: 1 };
        const recordId = targets.type === "group" ? targets.chatId : targets.openIds.join(",");

        await supabase.from("audit_logs").insert({
          id: uuidv4(), action: "aggregated_alert", resource_type: "quality_spike_alert",
          resource_id: recordId, detail,
          created_at: new Date().toISOString(),
        });
        triggeredAlerts.push({
          type: "质检飙升", resourceType: "quality_spike_alert",
          count: criticalCount, detail,
        });
      }
    }

    // c) Send suppressed alerts if quiet hours just ended
    if (!quiet) {
      const { data: suppressed } = await supabase
        .from("audit_logs")
        .select("resource_type, detail")
        .eq("action", "suppressed_alert")
        .order("created_at", { ascending: false })
        .limit(20);

      if (suppressed && suppressed.length > 0) {
        const summaryLines: string[] = [];
        const seen = new Set<string>();
        for (const s of suppressed as Array<{ resource_type: string; detail: Record<string, unknown> }>) {
          const d = s.detail || {};
          if (s.resource_type === "stale_work_orders_alert" && !seen.has("wo")) {
            seen.add("wo");
            summaryLines.push(`- 工单超时: ${d.count || "?"}个`);
          } else if (!seen.has(s.resource_type)) {
            seen.add(s.resource_type);
            summaryLines.push(`- 其他: ${d.count || "?"}条`);
          }
        }
        if (summaryLines.length > 0) {
          const card = {
            header: { title: { tag: "plain_text", content: "🔔 静默时段积压告警" }, template: "yellow" },
            elements: [{ tag: "div", text: { tag: "lark_md", content: `**安静时段积压的告警:**\n${summaryLines.join("\n")}` } }],
          };
          await sendAlertToTargets(targets, card);
        }
        // Clean up suppressed entries so they only fire once
        await supabase.from("audit_logs").delete().eq("action", "suppressed_alert");
      }
    }

    // d) Check for aggregation: if multiple alert entries exist in the 30-min window
    //    (including from prior invocations), send one aggregated card
    const { data: recentAggregated } = await supabase
      .from("audit_logs")
      .select("resource_type, detail")
      .eq("action", "aggregated_alert")
      .gt("created_at", thirtyMinAgo)
      .order("created_at", { ascending: false })
      .limit(20);

    const totalAggregated = (recentAggregated || []).length;

    if (triggeredAlerts.length > 0 && totalAggregated > 1) {
      // Multiple alerts in 30-min window — send aggregated card
      const summaryLines: string[] = [];
      const seen = new Set<string>();
      for (const entry of (recentAggregated || [])) {
        const d = (entry.detail || {}) as Record<string, unknown>;
        if (entry.resource_type === "stale_work_orders_alert" && !seen.has("wo")) {
          seen.add("wo");
          summaryLines.push(`- 工单超时: ${d.count || "?"}个`);
        } else if (entry.resource_type === "quality_spike_alert" && !seen.has("qa")) {
          seen.add("qa");
          summaryLines.push(`- 质检飙升: ${d.count || "?"}条致命风险`);
        } else if (!seen.has(entry.resource_type)) {
          seen.add(entry.resource_type);
          summaryLines.push(`- 其他: ${d.count || "?"}条`);
        }
      }

      const vercelUrl = Deno.env.get("VERCEL_APP_URL") || "";
      const card = {
        header: { title: { tag: "plain_text", content: "⚠️ 聚合告警 (过去30分钟)" }, template: "yellow" },
        elements: [
          { tag: "div", text: { tag: "lark_md", content: summaryLines.join("\n") } },
          { tag: "action", actions: [{ tag: "button", text: { tag: "plain_text", content: "查看详情" }, type: "primary", url: vercelUrl }] },
        ],
      };
      await sendAlertToTargets(targets, card);
      console.log("[Proactive] Sent aggregated alert card with", summaryLines.length, "items");
    } else if (triggeredAlerts.length === 1) {
      // Single alert — send individual card
      const alert = triggeredAlerts[0];
      const vercelUrl = Deno.env.get("VERCEL_APP_URL") || "";

      if (alert.resourceType === "stale_work_orders_alert") {
        const card = {
          header: { title: { tag: "plain_text", content: "⚠️ 工单超时提醒" }, template: "yellow" },
          elements: [
            { tag: "div", text: { tag: "lark_md", content: `${alert.count} 个工单超过24小时未处理` } },
            { tag: "action", actions: [{ tag: "button", text: { tag: "plain_text", content: "查看详情" }, type: "primary", url: `${vercelUrl}/dashboard?tab=work-orders` }] },
          ],
        };
        await sendAlertToTargets(targets, card);
      } else if (alert.resourceType === "quality_spike_alert") {
        const card = {
          header: { title: { tag: "plain_text", content: "🚨 质检告警激增" }, template: "red" },
          elements: [
            { tag: "div", text: { tag: "lark_md", content: `过去1小时 ${alert.count} 条致命风险` } },
            { tag: "action", actions: [{ tag: "button", text: { tag: "plain_text", content: "查看质检面板" }, type: "primary", url: `${vercelUrl}/quality` }] },
          ],
        };
        await sendAlertToTargets(targets, card);
      }
      console.log("[Proactive] Sent individual alert:", alert.type);
    }
  } catch (e) {
    console.error("[Proactive] Alert check error:", String(e).slice(0, 200));
  }
}

// ── HITL Confirmation ──

async function handleHitlConfirmAll(
  supabase: ReturnType<typeof createClient>,
  pipelineJobId: string,
  stepId: string,
  resolution: string,
): Promise<boolean> {
  try {
    // Fetch the step's resume_token before updating (stores the HITL card message_id)
    const { data: stepData } = await supabase
      .from("execution_steps")
      .select("resume_token")
      .eq("id", stepId)
      .maybeSingle();

    const { error: stepErr } = await supabase.from("execution_steps")
      .update({ status: "SUCCEEDED", completed_at: new Date().toISOString() })
      .eq("id", stepId);
    if (stepErr) {
      console.error("[HITL] Step update error:", stepErr.message);
      return false;
    }

    const { error: jobErr } = await supabase.from("pipeline_jobs")
      .update({ status: "PROCESSING", suspend_reason: null, timeout_at: null })
      .eq("id", pipelineJobId);
    if (jobErr) {
      console.error("[HITL] Job update error:", jobErr.message);
      return false;
    }

    await supabase.from("audit_logs").insert({
      id: uuidv4(),
      action: "hitl_confirm",
      resource_type: "execution_steps",
      resource_id: stepId,
      detail: { pipeline_job_id: pipelineJobId, resolution: resolution || "confirmed" },
      created_at: new Date().toISOString(),
    });

    // Auto-update the original HITL card to show confirmed status
    const cardMsgId = (stepData as { resume_token?: string } | null)?.resume_token;
    if (cardMsgId) {
      updateFeishuCard(cardMsgId, {
        header: { title: { tag: "plain_text", content: "HITL 审核已确认" }, template: "green" },
        elements: [
          { tag: "div", text: { tag: "lark_md", content: `审核结果: ${resolution || "已确认"}\n步骤: ${stepId.slice(0, 8)}` } },
        ],
      }).catch((e) => console.warn("[HITL] Card auto-update failed:", String(e).slice(0, 80)));
    }

    console.log(`[HITL] Confirmed step ${stepId.slice(0, 8)} for job ${pipelineJobId.slice(0, 8)}`);
    return true;
  } catch (e) {
    console.error("[HITL] handleHitlConfirmAll error:", String(e).slice(0, 80));
    return false;
  }
}

async function handleBatchHitlConfirm(supabase: ReturnType<typeof createClient>): Promise<number> {
  const { data: steps, error } = await supabase.from("execution_steps")
    .select("id, pipeline_job_id")
    .eq("status", "SUSPENDED_HITL")
    .limit(20);

  if (error) {
    console.error("[HITL] Batch query error:", error.message);
    return 0;
  }

  let confirmed = 0;
  for (const step of (steps || [])) {
    const ok = await handleHitlConfirmAll(supabase, step.pipeline_job_id, step.id, "batch_confirmed");
    if (ok) confirmed++;
  }

  console.log(`[HITL] Batch confirmed ${confirmed}/${(steps || []).length} steps`);
  return confirmed;
}

// ── HITL Card Auto-Update on Timeout ──

async function checkHitlTimeouts(
  supabase: ReturnType<typeof createClient>,
): Promise<number> {
  const now = new Date().toISOString();
  let updated = 0;

  try {
    const { data: expiredSteps } = await supabase
      .from("execution_steps")
      .select("id, resume_token, pipeline_job_id")
      .eq("status", "SUSPENDED_HITL")
      .lte("timeout_at", now)
      .not("resume_token", "is", null)
      .limit(20);

    if (!expiredSteps || expiredSteps.length === 0) return 0;

    for (const step of expiredSteps as Array<{ id: string; resume_token: string; pipeline_job_id: string }>) {
      const cardUpdated = await updateFeishuCard(step.resume_token, {
        header: { title: { tag: "plain_text", content: "HITL 审核已超时" }, template: "red" },
        elements: [
          { tag: "div", text: { tag: "lark_md", content: "此审核请求已超时升级至管理员" } },
        ],
      });
      if (cardUpdated) {
        updated++;
        console.log("[HITL] Timeout card updated for step:", step.id.slice(0, 8));
      }
    }
  } catch (e) {
    console.error("[HITL] checkHitlTimeouts error:", String(e).slice(0, 80));
  }

  return updated;
}

// ── Silent Session Monitoring (silent alarm) ──

async function checkSilentSessions(supabase: ReturnType<typeof createClient>) {
  try {
    const now = Date.now();
    const fiveMinAgo = new Date(now - 5 * 60 * 1000).toISOString();
    const tenMinAgo = new Date(now - 10 * 60 * 1000).toISOString();
    const thirtyMinAgo = new Date(now - 30 * 60 * 1000).toISOString();

    const groupChatId = Deno.env.get("FEISHU_GROUP_CHAT_ID") || "";
    if (!groupChatId) {
      console.log("[SilentSession] No FEISHU_GROUP_CHAT_ID, skipping");
      return;
    }

    // Query active sessions with stale updated_at (last update >5 min ago)
    const { data: sessions, error } = await supabase
      .from("bot_chat_sessions")
      .select("id, external_session_id, customer_id, conversation, updated_at")
      .eq("status", "active")
      .lt("updated_at", fiveMinAgo)
      .order("updated_at", { ascending: true })
      .limit(50);

    if (error) {
      console.error("[SilentSession] Query error:", error.message);
      return;
    }
    if (!sessions || sessions.length === 0) return;

    const vercelUrl = Deno.env.get("VERCEL_APP_URL") || "";

    for (const session of sessions) {
      try {
        const conversation = (session.conversation as string) || "";
        const lines = conversation.split("\n").filter(l => l.trim());
        if (lines.length === 0) continue;

        // Check if last message is from customer (not bot reply).
        // The conversation format is always: "顾客: ..." or "机器人: ..." per line.
        const lastLine = lines[lines.length - 1].trim();
        const isCustomerLast = lastLine.includes("顾客:") && !lastLine.includes("机器人:");
        if (!isCustomerLast) continue;

        const sessionUpdatedAt = new Date(session.updated_at as string);
        const minutesSinceUpdate = Math.round((now - sessionUpdatedAt.getTime()) / 60000);
        const isTier2 = sessionUpdatedAt.getTime() < new Date(tenMinAgo).getTime();

        // Deduplication: don't re-alert the same tier for the same session within 30 min.
        // Tier-2 (escalated) uses a separate dedup key so escalation can still fire.
        const resourceType = isTier2 ? "silent_session_alert_tier2" : "silent_session_alert_tier1";
        const { data: recentAlerts } = await supabase
          .from("audit_logs")
          .select("id")
          .eq("action", "silent_session_alert")
          .eq("resource_type", resourceType)
          .eq("resource_id", session.external_session_id)
          .gt("created_at", thirtyMinAgo)
          .limit(1);

        if (recentAlerts && recentAlerts.length > 0) {
          console.log("[SilentSession] Alert suppressed (dedup) for:", String(session.external_session_id || "").slice(-12));
          continue;
        }

        // Record alert in audit_logs for dedup
        await supabase.from("audit_logs").insert({
          id: uuidv4(),
          action: "silent_session_alert",
          resource_type: resourceType,
          resource_id: session.external_session_id,
          detail: {
            session_id: session.id,
            customer_id: session.customer_id,
            minutes_silent: minutesSinceUpdate,
            tier: isTier2 ? "escalated" : "initial",
          },
          created_at: new Date().toISOString(),
        });

        // Build and send Feishu alert card
        const prefix = isTier2 ? "🔴 升级·" : "";
        const card = {
          header: {
            title: { tag: "plain_text", content: `${prefix}⚠️ 会话静默告警` },
            template: isTier2 ? "red" : "yellow",
          },
          elements: [
            {
              tag: "div",
              text: {
                tag: "lark_md",
                content: [
                  `**会话ID:** ${String(session.external_session_id || "").slice(-12)}`,
                  `**客户ID:** ${session.customer_id || "未知"}`,
                  `**最后活跃:** ${minutesSinceUpdate}分钟前`,
                  isTier2
                    ? "🔴 **已静默超过10分钟，需要立即处理**"
                    : "⚠️ 会话已静默超过5分钟，请关注",
                ].join("\n"),
              },
            },
            {
              tag: "action",
              actions: [
                {
                  tag: "button",
                  text: { tag: "plain_text", content: "查看会话" },
                  type: "primary",
                  url: `${vercelUrl}/dashboard?tab=sessions`,
                },
              ],
            },
          ],
        };

        await sendFeishuCard(groupChatId, card);
        console.log(
          `[SilentSession] ${isTier2 ? "Escalated" : "Initial"} alert sent for:`,
          String(session.external_session_id || "").slice(-12),
        );
      } catch (sessionErr) {
        console.error("[SilentSession] Session processing error:", String(sessionErr).slice(0, 200));
      }
    }
  } catch (e) {
    console.error("[SilentSession] Check error:", String(e).slice(0, 200));
  }
}

// ── User Daily Brief (triggered by @bot 今日简报) ──

async function checkUserDailyBrief(
  supabase: ReturnType<typeof createClient>,
  targetOpenId: string,
  chatId: string,
) {
  const todayStr = new Date().toISOString().slice(0, 10);
  const tomorrowStr = new Date(Date.now() + 86400000).toISOString().slice(0, 10);

  try {
    // Pending work orders for this user
    const { data: pendingOrders, error: woErr } = await supabase
      .from("work_orders")
      .select("id,title,status,priority,created_at")
      .eq("assignee_id", targetOpenId)
      .in("status", ["pending", "open"])
      .order("created_at", { ascending: false })
      .limit(10);

    // Quality reports for today (team-wide)
    const { data: qualityReports, error: qrErr } = await supabase
      .from("quality_reports")
      .select("risk_level,total_score")
      .gte("created_at", todayStr)
      .lt("created_at", tomorrowStr)
      .limit(100);

    const woCount = (pendingOrders && !woErr ? pendingOrders.length : 0);
    const qrTotal = (qualityReports && !qrErr ? qualityReports.length : 0);
    const qrCritical = (qualityReports && !qrErr
      ? qualityReports.filter((r: { risk_level?: string }) => r.risk_level === "critical").length
      : 0);
    const avgScore = qrTotal > 0
      ? Math.round((qualityReports as Array<{ total_score?: number }>).reduce((s, r) => s + (r.total_score || 0), 0) / qrTotal)
      : 0;

    const woList = woCount > 0
      ? (pendingOrders as Array<{ title?: string; status?: string }>).map((wo) => `- ${wo.title || "未命名"} [${wo.status}]`).join("\n")
      : "暂无待处理工单";

    const brief = [
      `📋 **今日简报** (${todayStr})`,
      ``,
      `**待处理工单:** ${woCount} 个`,
      woList,
      ``,
      `**质检概况:**`,
      `- 今日报告: ${qrTotal} 条`,
      `- 致命风险: ${qrCritical} 条`,
      `- 平均分: ${avgScore}`,
    ].join("\n");

    const card = {
      header: { title: { tag: "plain_text", content: "📋 今日简报" }, template: "blue" },
      elements: [{ tag: "div", text: { tag: "lark_md", content: brief } }],
    };
    await sendFeishuCard(chatId, card);
  } catch (e) {
    console.error("[DailyBrief] Error:", String(e).slice(0, 200));
  }
}

// ── Decision Transparency Helper ──
// Appends a lightweight rationale line to replies so users understand why
// the system made a particular judgment.

function addTransparency(reply: string, type: string, meta: Record<string, string>): string {
  switch (type) {
    case "compliance":
      return `${reply}\n\n📎 判断依据: ${meta.matchedRules} | 共扫描${meta.totalRules}条规则`;
    case "data_query":
      return `${reply}\n\n📎 数据来源: ${meta.source} 表 | 时间范围: ${meta.timeRange} | 共扫描${meta.recordCount}条记录`;
    case "intent_classification":
      return `${reply}\n\n🤖 理解: ${meta.intentLabel} (置信度${meta.confidence}·${meta.method})`;
    default:
      return reply;
  }
}

// ── Natural Language Time Parsing ──

function parseNaturalPeriod(text: string): { from: string; to: string } | null {
  // "5.1-5.15" or "5/1-5/15" -> explicit date range
  const rangeMatch = text.match(/(\d{1,2})[.\/](\d{1,2})\s*[-~到]\s*(\d{1,2})[.\/](\d{1,2})/);
  if (rangeMatch) {
    const y = new Date().getFullYear();
    return {
      from: `${y}-${rangeMatch[1].padStart(2, "0")}-${rangeMatch[2].padStart(2, "0")}`,
      to: `${y}-${rangeMatch[3].padStart(2, "0")}-${rangeMatch[4].padStart(2, "0")}`,
    };
  }
  // "最近N天" / "最近一周" / "近一周"
  const recentDaysMatch = text.match(/最近\s*(\d+)\s*天/);
  if (recentDaysMatch) {
    const days = parseInt(recentDaysMatch[1]);
    const now = new Date();
    const from = new Date(now.getTime() - days * 86400000);
    return { from: from.toISOString().slice(0, 10), to: now.toISOString().slice(0, 10) };
  }
  if (/最近一周|近一周/.test(text)) {
    const now = new Date();
    const from = new Date(now.getTime() - 7 * 86400000);
    return { from: from.toISOString().slice(0, 10), to: now.toISOString().slice(0, 10) };
  }
  // "这个月" / "本月"
  if (/这个月|本月/.test(text)) {
    const now = new Date();
    const firstDay = new Date(now.getFullYear(), now.getMonth(), 1);
    return { from: firstDay.toISOString().slice(0, 10), to: now.toISOString().slice(0, 10) };
  }
  // "上月" / "上个月"
  if (/上月|上个月/.test(text)) {
    const now = new Date();
    const firstDay = new Date(now.getFullYear(), now.getMonth() - 1, 1);
    const lastDay = new Date(now.getFullYear(), now.getMonth(), 0);
    return { from: firstDay.toISOString().slice(0, 10), to: lastDay.toISOString().slice(0, 10) };
  }
  // "5月中旬" -> May 10-20
  const midMonthMatch = text.match(/(\d{1,2})\s*月\s*中旬/);
  if (midMonthMatch) {
    const m = parseInt(midMonthMatch[1]);
    const y = new Date().getFullYear();
    return {
      from: `${y}-${String(m).padStart(2, "0")}-10`,
      to: `${y}-${String(m).padStart(2, "0")}-20`,
    };
  }
  // "上周Y到周X" -> compute last Monday + offset
  const lastWeekRangeMatch = text.match(/上周\s*(\S)\s*[到~至]\s*周(\S)/);
  if (lastWeekRangeMatch) {
    const dayMap: Record<string, number> = { "一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6 };
    const startDay = dayMap[lastWeekRangeMatch[1]];
    const endDay = dayMap[lastWeekRangeMatch[2]];
    if (startDay !== undefined && endDay !== undefined) {
      const now = new Date();
      const dayOfWeek = now.getDay();
      const mondayOffset = dayOfWeek === 0 ? -13 : -6 - dayOfWeek;
      const lastMonday = new Date(now.getFullYear(), now.getMonth(), now.getDate() + mondayOffset);
      const from = new Date(lastMonday.getTime() + startDay * 86400000);
      const to = new Date(lastMonday.getTime() + endDay * 86400000);
      return { from: from.toISOString().slice(0, 10), to: to.toISOString().slice(0, 10) };
    }
  }
  return null;
}

// ── Custom Command Registry ──

interface CustomCommand {
  command_name: string;
  regex_pattern: string;
  action_type: string;
  reply_template?: string;
  api_endpoint?: string;
  api_method?: string;
}

async function loadCustomCommands(
  supabase: ReturnType<typeof createClient>,
): Promise<CustomCommand[]> {
  try {
    const { data, error } = await supabase
      .from("bot_commands")
      .select("command_name, regex_pattern, action_type, reply_template, api_endpoint, api_method")
      .eq("is_active", true);
    if (error || !data) return [];
    return data as CustomCommand[];
  } catch {
    return [];
  }
}

// ── Hybrid Intent Router ──
// L0: Fast regex path (<1ms) for high-frequency deterministic commands
// L1: DeepSeek LLM fallback for ambiguous/natural-language intents

// ── Typo correction for common Chinese input errors ──
const TYPO_MAP: Record<string, string> = {
  "生城": "生成",
  "申城": "生成",
  "质捡": "质检",
  "质简": "质检",
  "催单提腥": "催单提醒",
  "华术建议": "话术建议",
  "会花": "会话",
  "慧花": "会话",
  "倒出": "导出",
  "报标": "报表",
};

function correctTypos(text: string): string {
  let corrected = text;
  for (const [typo, correct] of Object.entries(TYPO_MAP)) {
    if (corrected.includes(typo)) {
      corrected = corrected.replace(typo, correct);
      console.log(`[Typo] Corrected "${typo}" → "${correct}" in: ${text.slice(0, 50)}`);
    }
  }
  return corrected;
}

async function classifyIntent(text: string, customCommands: CustomCommand[], sessionContext?: string): Promise<{
  action: string;
  params: Record<string, string>;
  confidence: number;
  method: "regex" | "llm" | "fallback";
}> {
  // Pre-process: correct common typos
  const correctedText = correctTypos(text);

  // L0 custom commands first
  for (const cmd of customCommands) {
    try {
      const m = text.match(new RegExp(cmd.regex_pattern));
      if (m) {
        return { action: cmd.action_type, params: {}, confidence: 1.0, method: "regex" };
      }
    } catch { /* skip invalid regex */ }
  }

  // L0: Fast-path regex matching
  const l0Patterns: Array<{
    regex: RegExp;
    action: string;
    paramExtractor: (m: RegExpMatchArray) => Record<string, string>;
  }> = [
    { regex: /^系统健康/, action: "system_health", paramExtractor: () => ({}) },
    { regex: /^周报$/, action: "generate_report", paramExtractor: () => ({ type: "周报" }) },
    { regex: /^月报$/, action: "generate_report", paramExtractor: () => ({ type: "月报" }) },
    { regex: /^待办$/, action: "hitl_pending_count", paramExtractor: () => ({}) },
    { regex: /^健康$/, action: "system_health", paramExtractor: () => ({}) },
    { regex: /^(帮助|help|菜单|指令)$/i, action: "help", paramExtractor: () => ({}) },
    { regex: /^怎么用\s+(.+)/i, action: "command_usage", paramExtractor: (m) => ({ command: (m[1] || "").trim() }) },
    { regex: /^质检报告\s*(昨天|今日|本周|上周)?/, action: "quality_report", paramExtractor: (m) => ({ period: m[1] || "今日" }) },
    { regex: /^合规(检查|检测|扫描)\s*(.*)/, action: "compliance_check", paramExtractor: (m) => ({ content: (m[2] || "").trim() }) },
    { regex: /^生成(周报|月报|日报)/, action: "generate_report", paramExtractor: (m) => ({ type: m[1] }) },
    { regex: /^(催单|催付|催款)/, action: "payment_reminder", paramExtractor: () => ({}) },
    { regex: /^工单|work.?order/i, action: "work_orders", paramExtractor: () => ({}) },
    { regex: /^知识缺口|话术缺口/, action: "knowledge_gaps", paramExtractor: () => ({}) },
    { regex: /^话术建议\s*(.+)?/, action: "bot_suggest", paramExtractor: (m) => ({ keyword: (m[1] || "通用").trim() }) },
    { regex: /^会话统计|聊天统计/, action: "chat_stats", paramExtractor: () => ({}) },
    { regex: /^质检分析|质检评测/, action: "qa_evaluate", paramExtractor: () => ({}) },
    { regex: /^会议测试|触发会议|pipeline\s*(.*)/i, action: "meeting_pipeline", paramExtractor: (m) => ({ topic: (m[1] || "Bot触发的会议测试").trim() }) },
    { regex: /^今日简报/, action: "daily_brief", paramExtractor: () => ({}) },
    { regex: /^全部确认/, action: "batch_hitl_confirm", paramExtractor: () => ({}) },
    { regex: /^待处理/, action: "hitl_pending_count", paramExtractor: () => ({}) },
    { regex: /^管线状态/, action: "pipeline_status", paramExtractor: () => ({}) },
    { regex: /^管线详情\s*(.+)?/, action: "pipeline_detail", paramExtractor: (m) => ({ job_id: (m[1] || "").trim() }) },
    { regex: /^管线历史/, action: "pipeline_history", paramExtractor: () => ({}) },
    { regex: /^重试管线\s*(.+)?/, action: "pipeline_retry", paramExtractor: (m) => ({ job_id: (m[1] || "").trim() }) },
    { regex: /^(转人工|人工客服|转接人工)/, action: "transfer_human", paramExtractor: () => ({}) },
    { regex: /^快捷回复\s*(.+)?/, action: "quick_reply", paramExtractor: (m) => ({ category: (m[1] || "general").trim() }) },
    { regex: /^情绪检测/, action: "emotion_detect", paramExtractor: () => ({}) },
    { regex: /^风格\s*(专业|正式|严谨|亲切|活泼|简洁|高效|professional|friendly|concise)?/i, action: "personality_switch", paramExtractor: (m) => ({ tone: (m[1] || "").trim() }) },
    { regex: /^style\s*(professional|friendly|concise)?/i, action: "personality_switch", paramExtractor: (m) => ({ tone: (m[1] || "").trim() }) },
    { regex: /导出质检报告/, action: "export_quality_reports", paramExtractor: () => ({}) },
    { regex: /导出会话/, action: "export_chat_sessions", paramExtractor: () => ({}) },
    { regex: /导出工单/, action: "export_work_orders", paramExtractor: () => ({}) },
    { regex: /导出管线/, action: "export_pipeline_jobs", paramExtractor: () => ({}) },
    { regex: /^(改进建议|我的质检|质检改进)/, action: "quality_improvement", paramExtractor: () => ({}) },
  ];

  for (const pattern of l0Patterns) {
    const match = correctedText.match(pattern.regex);
    if (match) {
      return { action: pattern.action, params: pattern.paramExtractor(match), confidence: 1.0, method: "regex" };
    }
  }

  // L1: LLM fallback
  const apiKey = Deno.env.get("DEEPSEEK_API_KEY") || "";
  const apiUrl = Deno.env.get("DEEPSEEK_API_URL") || "";

  if (apiKey && apiUrl) {
    // Circuit breaker: skip L1 if DeepSeek is failing
    if (isCircuitOpen("deepseek")) {
      console.warn("[Intent] Circuit breaker open for deepseek, skipping L1, falling back to general_chat");
      return { action: "general_chat", params: {}, confidence: 0, method: "fallback" };
    }

    const startTime = Date.now();
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), INTENT_CLASSIFY_TIMEOUT_MS);

    try {
      const res = await fetch(apiUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
        body: JSON.stringify({
          model: "deepseek-chat",
          messages: [
            {
              role: "system",
              content: `将用户输入分类为以下意图之一。只返回JSON：{"action":"<intent>","params":{},"confidence":<0-1>}

可用意图：help, quality_report, compliance_check, generate_report, payment_reminder, work_orders, knowledge_gaps, bot_suggest, chat_stats, qa_evaluate, meeting_pipeline, daily_brief, general_chat`,
            },
            { role: "user", content: sessionContext ? `对话历史: ${sessionContext}\n当前输入: ${text}` : text },
          ],
          temperature: 0,
          max_tokens: 150,
        }),
        signal: controller.signal,
      });
      clearTimeout(timeoutId);
      const latencyMs = Date.now() - startTime;

      if (res.ok) {
        const data = await res.json() as { choices?: [{ message?: { content?: string } }] };
        const raw = data.choices?.[0]?.message?.content?.trim();
        if (raw) {
          // Extract JSON from response (may be wrapped in markdown code blocks)
          const jsonMatch = raw.match(/\{[\s\S]*\}/);
          if (jsonMatch) {
            const parsed = JSON.parse(jsonMatch[0]);
            if (parsed.action && typeof parsed.confidence === "number" && parsed.confidence >= 0.7) {
              const action = String(parsed.action);
              // Output validation: reject unknown intents
              if (VALID_INTENTS.has(action)) {
                recordSuccess("deepseek");
                logLLMHealth("deepseek", "intent_classify", true, latencyMs);
                return {
                  action,
                  params: parsed.params && typeof parsed.params === "object" ? parsed.params as Record<string, string> : {},
                  confidence: parsed.confidence,
                  method: "llm",
                };
              } else {
                console.warn("[Intent] Unknown intent from LLM:", action, ", falling back to general_chat");
              }
            }
          }
        }
      }
      // Parse/validation failure or non-ok response — log but don't trip circuit breaker
      logLLMHealth("deepseek", "intent_classify", false, latencyMs);
    } catch (e) {
      clearTimeout(timeoutId);
      const latencyMs = Date.now() - startTime;
      recordFailure("deepseek");
      logLLMHealth("deepseek", "intent_classify", false, latencyMs);
      console.warn("[Intent] LLM classification error:", String(e).slice(0, 80));
    }
  }

  // Fallback
  return { action: "general_chat", params: {}, confidence: 0, method: "fallback" };
}

// ── Main handler ──

serve(async (req: Request) => {
  // GET — health check with Supabase connectivity verification
  if (req.method === "GET") {
    let dbStatus = "unknown";
    try {
      const healthSupabase = createClient(
        Deno.env.get("SUPABASE_URL") || "",
        Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "",
      );
      const { error } = await healthSupabase.from("audit_logs").select("id").limit(1);
      dbStatus = error ? `error: ${error.message}` : "connected";
    } catch (e) {
      dbStatus = `error: ${String(e).slice(0, 100)}`;
    }
    console.log(`[Feishu] Health check: database=${dbStatus}`);
    return new Response(JSON.stringify({ code: 0, message: "ok", database: dbStatus }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }

  if (req.method !== "POST") {
    return new Response(JSON.stringify({ error: "Method not allowed" }), {
      status: 405,
      headers: { "Content-Type": "application/json" },
    });
  }

  try {

  const encryptKey = Deno.env.get("FEISHU_EVENT_ENCRYPT_KEY") || "";
  const verifyToken = Deno.env.get("FEISHU_VERIFY_TOKEN") || "";

  const body = await req.text();
  const timestamp = req.headers.get("X-Lark-Request-Timestamp") || "";
  const nonce = req.headers.get("X-Lark-Request-Nonce") || "";
  const signature = req.headers.get("X-Lark-Signature") || "";

  // ── 1. Parse body ──

  console.log("[Feishu] Incoming:", {
    hasEncrypt: String(body.includes('"encrypt"')),
    hasSignature: String(!!signature),
    bodyLen: body.length,
    bodyPreview: body.slice(0, 120),
  });

  let event: Record<string, unknown>;
  let rawStore = body;
  let isEncrypted = false;

  try {
    const bodyJson = JSON.parse(body);

    if (bodyJson.encrypt) {
      // Encrypted mode — decrypt first to check for URL verification
      isEncrypted = true;
      if (!encryptKey) {
        console.error("[Feishu] Encrypt key not set");
        return new Response(JSON.stringify({ error: "encrypt_key_not_set" }), {
          status: 400, headers: { "Content-Type": "application/json" },
        });
      }
      try {
        const decrypted = await aesDecrypt(bodyJson.encrypt as string, encryptKey);
        event = JSON.parse(decrypted);
        rawStore = decrypted;
        console.log("[Feishu] Decrypted OK, type:", event.type);
      } catch (err) {
        console.error("[Feishu] Decrypt failed:", err);
        return new Response(JSON.stringify({ error: "decrypt_failed" }), {
          status: 400, headers: { "Content-Type": "application/json" },
        });
      }
    } else {
      event = bodyJson;
      console.log("[Feishu] Plaintext OK, type:", event.type);
    }
  } catch (err) {
    console.error("[Feishu] Parse error:", err);
    return new Response(JSON.stringify({ error: "Invalid request body" }), {
      status: 400, headers: { "Content-Type": "application/json" },
    });
  }

  // ── 2. URL verification — respond BEFORE signature/token check ──

  if (event.type === "url_verification") {
    const challenge = event.challenge as string;
    if (!challenge) {
      return new Response(JSON.stringify({ error: "Missing challenge" }), {
        status: 400, headers: { "Content-Type": "application/json" },
      });
    }
    console.log("[Feishu] URL verification OK");
    return new Response(JSON.stringify({ challenge }), {
      status: 200, headers: { "Content-Type": "application/json" },
    });
  }

  // ── 3. Validate signature/token (after URL verification) ──

  if (isEncrypted) {
    if (encryptKey && signature) {
      const signStr = `${timestamp}${nonce}${encryptKey}${body}`;
      const expected = await sha256Hex(signStr);
      if (expected !== signature) {
        console.error("[Feishu] Signature mismatch");
        return new Response(JSON.stringify({ code: 0 }), {
          status: 200, headers: { "Content-Type": "application/json" },
        });
      }
      console.log("[Feishu] Signature verified");
    }
  } else {
    // Card callbacks use their own token (c-xxx), skip verifyToken check
    const isCardCallback = (event.type as string) === "card.action.trigger";
    if (!isCardCallback) {
      const token = event.token as string;
      if (verifyToken && token && token !== verifyToken) {
        console.error("[Feishu] Token mismatch");
        return new Response(JSON.stringify({ code: 0 }), {
          status: 200, headers: { "Content-Type": "application/json" },
        });
      }
    }
  }

  // ── 3. Process event ──

  const supabase = createClient(
    Deno.env.get("SUPABASE_URL") || "",
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "",
  );

  // Feishu v2.0: header.event_type, header.event_id; v1.0: type, event_id
  const header = (event.header || event) as Record<string, unknown>;
  const eventType = (header.event_type as string) || (event.type as string) || "unknown";
  const eventId = (header.event_id as string) || (event.event_id as string) || `feishu_${Date.now()}`;
  const eventBody = (event.event || event) as Record<string, unknown>;
  const correlationId = `feishu_evt_${uuidv4().slice(0, 12)}`;

  // 3a. Store raw event (idempotent — INSERT fails on duplicate → skip)
  const { error: rawErr } = await supabase
    .from("feishu_raw_events")
    .insert({ event_id: eventId, event_type: eventType, raw_body: JSON.parse(rawStore), created_at: new Date().toISOString() });

  if (rawErr) {
    // 23505 = unique_violation — Feishu redelivered this event, skip processing
    if ((rawErr as Record<string,unknown>).code === "23505") {
      console.log("[Feishu] Duplicate event, skipping:", eventId.slice(0, 20));
      return new Response(JSON.stringify({ code: 0 }), {
        status: 200, headers: { "Content-Type": "application/json" },
      });
    }
    console.warn("[Feishu] Raw event storage error:", rawErr.message);
  }

  // 3b. Handle card.action.trigger (feedback buttons + other card actions)
  if (eventType === "card.action.trigger") {
    try {
      const cardEvent = eventBody;
      console.log("[Feishu] Card action received:", JSON.stringify(cardEvent).slice(0, 300));
      const action = (cardEvent.action as Record<string, unknown>) || {};
      const actionValue = (action.value as string) || (cardEvent.value as string) || undefined;
      console.log("[Feishu] Card actionValue:", String(actionValue).slice(0, 200));

      if (actionValue) {
        let parsed: { action?: string; session_id?: string; reply_text?: string };
        try {
          // Card callback double-encodes the value: "\"{\\"action\\":...}\""
          const firstPass = JSON.parse(actionValue);
          parsed = typeof firstPass === "string" ? JSON.parse(firstPass) : firstPass;
        } catch {
          parsed = {};
        }

        if (parsed.action === "feedback_helpful" || parsed.action === "feedback_unhelpful") {
          const feedbackType = parsed.action === "feedback_helpful" ? "helpful" : "unhelpful";
          const operatorOpenId = ((cardEvent.operator as Record<string, unknown>)?.open_id) as string | undefined;

          // Store feedback in audit_logs (fire-and-forget — card callback must respond <1s)
          supabase.from("audit_logs").insert({
            id: uuidv4(),
            action: "reply_feedback",
            resource_type: "bot_chat_sessions",
            resource_id: parsed.session_id || null,
            detail: {
              feedback_type: feedbackType,
              reply_text: parsed.reply_text || "",
              operator_open_id: operatorOpenId || null,
            },
            correlation_id: `feishu_fb_${uuidv4().slice(0, 12)}`,
            created_at: new Date().toISOString(),
          }).catch(e => console.error("[Feishu] Feedback log error:", String(e).slice(0, 100)));

          console.log(`[Feishu] Feedback: ${feedbackType} on session ${parsed.session_id}`);

          // Return toast + updated card (buttons replaced with thank-you note)
          const updatedCard = {
            header: {
              title: { tag: "plain_text", content: parsed.reply_text || "" },
              template: feedbackType === "helpful" ? "green" : "red",
            },
            elements: [
              {
                tag: "note",
                elements: [
                  {
                    tag: "plain_text",
                    content: feedbackType === "helpful"
                      ? "感谢您的反馈！已标记为有帮助 ✓"
                      : "感谢您的反馈！我们会努力改进 ✗",
                  },
                ],
              },
            ],
          };

          return new Response(JSON.stringify({
            toast: {
              type: "success",
              content: feedbackType === "helpful" ? "已标记为有帮助" : "已记录，我们会改进",
            },
            card: updatedCard,
          }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }

        if (parsed.action === "compliance_overturn") {
          const checkId = (parsed as Record<string, string>).check_id || "";
          const reason = (parsed as Record<string, string>).reason || "人工复核误判";
          console.log(`[Compliance] Overturn: checkId=${checkId}, reason=${reason}`);

          await supabase.from("audit_logs").insert({
            id: uuidv4(),
            action: "compliance_overturn_card",
            resource_type: "compliance_check",
            resource_id: checkId,
            detail: { reason, operator: ((cardEvent.operator as Record<string, unknown>)?.open_id) as string || "unknown" },
            created_at: new Date().toISOString(),
          });

          // Return updated card showing overturn confirmation
          return new Response(JSON.stringify({
            toast: {
              type: "success",
              content: "已标记为误判，该规则将不再触发",
            },
            card: {
              config: { wide_screen_mode: true },
              header: { title: { tag: "plain_text", content: "已驳回" }, template: "green" },
              elements: [{
                tag: "div",
                text: { tag: "lark_md", content: "此合规告警已被人工标记为误判" },
              }],
            },
          }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }

        if (parsed.action === "improvement_acknowledged") {
          const reportId = (parsed as Record<string, string>).report_id || "";
          const agentName = (parsed as Record<string, string>).agent_name || "";
          const operatorOpenId = ((cardEvent.operator as Record<string, unknown>)?.open_id) as string | undefined;

          await supabase.from("audit_logs").insert({
            id: uuidv4(),
            action: "improvement_acknowledged",
            resource_type: "quality_report",
            resource_id: reportId,
            detail: {
              agent_name: agentName,
              report_id: reportId,
              operator_open_id: operatorOpenId || null,
            },
            correlation_id: `feishu_imp_${uuidv4().slice(0, 12)}`,
            created_at: new Date().toISOString(),
          });

          console.log(`[Improvement] Acknowledged: report=${reportId}, agent=${agentName}`);

          // Return updated card with confirmation
          return new Response(JSON.stringify({
            toast: {
              type: "success",
              content: "已记录，感谢你的认真对待！",
            },
            card: {
              header: {
                title: { tag: "plain_text", content: "📝 质检改进建议" },
                template: "green",
              },
              elements: [
                {
                  tag: "div",
                  text: {
                    tag: "lark_md",
                    content: "✅ 已确认\n\n已记录你的认真对待，感谢你为提升服务质量所做的努力！",
                  },
                },
              ],
            },
          }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
      }
    } catch (err) {
      console.error("[Feishu] Card action error:", err);
    }
    // Fallback for unhandled card actions — return toast confirmation
    return new Response(JSON.stringify({ toast: { type: "info", content: "操作已记录" } }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }

  // 3c. Handle im.message.receive_v1
  if (eventType === "im.message.receive_v1") {
    try {
      const evt = eventBody;
      const message = evt.message as Record<string, unknown>;
      const sender = evt.sender as Record<string, unknown> | undefined;

      const chatId = message?.chat_id as string;
      const msgType = (message?.message_type as string) || "text";
      const contentJson = (message?.content as string) || "{}";
      const senderId = (sender?.sender_id as Record<string, string>)?.open_id || "unknown";

      const text = parseMessageText(msgType, contentJson);

      // ── Fetch active bot config (once per message) ──
      let botConfig: { id: string; transfer_keywords: string[]; welcome_message: string; working_hours: Record<string, unknown>; prompt_id: string | null; model_config_id: string | null } | null = null;
      try {
        const { data: bot } = await supabase
          .from("bots")
          .select("id, transfer_keywords, welcome_message, working_hours, prompt_id, model_config_id")
          .eq("is_active", true)
          .eq("platform", "feishu")
          .maybeSingle();
        if (bot) {
          botConfig = {
            id: bot.id as string,
            transfer_keywords: (Array.isArray(bot.transfer_keywords) ? bot.transfer_keywords : []) as string[],
            welcome_message: (bot.welcome_message as string) || "",
            working_hours: (bot.working_hours || {}) as Record<string, unknown>,
            prompt_id: (bot.prompt_id as string) || null,
            model_config_id: (bot.model_config_id as string) || null,
          };
          console.log("[Bot] Active bot config loaded:", botConfig.id.slice(0, 8));
        }
      } catch (e) {
        console.warn("[Bot] Failed to fetch bot config:", String(e).slice(0, 80));
      }

      // ── Real-time compliance scan (fire-and-forget) ──
      if ((Deno.env.get("FEISHU_REALTIME_COMPLIANCE") ?? "true") === "true") {
        const vercelUrl = Deno.env.get("VERCEL_APP_URL") || "https://qa-system-ain2k9x2x-yyy99045s-projects.vercel.app";
        fetch(`${vercelUrl}/api/qa/compliance/check`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content: text, source_type: "chat_message", source_id: eventId }),
        }).catch((e) => console.error("[Feishu] Compliance scan error:", String(e)));
      }

      // Resolve feishu platform
      const { data: pf, error: pfErr } = await supabase
        .from("platforms")
        .select("id")
        .eq("code", "feishu")
        .maybeSingle();

      if (pfErr) console.error("[Feishu] Platform query error:", pfErr.message);

      let platformId = (pf?.id as number) ?? undefined;

      if (!platformId) {
        const { data: created, error: createErr } = await supabase
          .from("platforms")
          .insert({ name: "飞书", code: "feishu" })
          .select("id")
          .single();
        if (createErr) console.error("[Feishu] Platform create error:", createErr.message, createErr.details);
        platformId = (created?.id as number) ?? undefined;
      }

      if (!platformId) {
        console.error("[Feishu] Cannot resolve feishu platform_id");
      } else {
        // Upsert bot_chat_sessions
        const { data: existing } = await supabase
          .from("bot_chat_sessions")
          .select("id, conversation, total_messages")
          .eq("external_session_id", chatId)
          .maybeSingle();

        // ── Text actions (feedback + overturn) ──
        const trimmed = text.trim();
        if (/^驳回\s*(.*)/i.test(trimmed)) {
          const checkContent = trimmed.match(/^驳回\s*(.*)/i)?.[1] || trimmed;
          await supabase.from("audit_logs").insert({
            id: uuidv4(), action: "compliance_overturn", resource_type: "compliance_check",
            resource_id: chatId,
            detail: { check_id: checkContent, reason: "人工驳回", operator: senderId },
            created_at: new Date().toISOString(),
          });
          sendFeishuReply(chatId, `✅ 已驳回误判「${checkContent.slice(0, 50)}」，下次不再告警`);
          return;
        }
        if (/^(有帮助|无帮助|没用|帮到了|谢谢)/.test(trimmed)) {
          const fbType = /没用|无帮助/.test(text.trim()) ? "unhelpful" : "helpful";
          await supabase.from("audit_logs").insert({
            id: uuidv4(), action: "reply_feedback", resource_type: "bot_reply",
            resource_id: chatId,
            detail: { feedback_type: fbType, original_message: text.trim() },
            created_at: new Date().toISOString(),
          });
          sendFeishuReply(chatId, fbType === "helpful" ? "感谢反馈！我们会继续优化回复质量 ❤️" : "已记录您的反馈，我们会努力改进！");
          return;
        }
        if (/^(撤回|撤销)$/.test(trimmed)) {
          const result = await recallLastBotMessage(chatId);
          sendFeishuReply(chatId, result);
          return;
        }
        if (/^编辑\s+(\S+)\s+(.+)/s.test(trimmed)) {
          const editMatch = trimmed.match(/^编辑\s+(\S+)\s+(.+)/s);
          if (editMatch) {
            const [, targetMsgId, newContent] = editMatch;
            const adminIds = (Deno.env.get("ADMIN_OPEN_IDS") || "").split(",").map(s => s.trim()).filter(Boolean);
            const isAdmin = adminIds.includes(senderId);
            if (!isAdmin) {
              sendFeishuReply(chatId, "权限不足：仅管理员可编辑卡片内容");
            } else {
              const ok = await updateFeishuCard(targetMsgId, {
                header: { title: { tag: "plain_text", content: "已编辑" }, template: "blue" },
                elements: [{ tag: "div", text: { tag: "lark_md", content: newContent } }],
              });
              sendFeishuReply(chatId, ok ? "消息已更新" : "编辑失败，请检查消息ID是否正确");
            }
          }
          return;
        }

        // ── Fetch session context for conversational memory ──
        const { context: sessionContext, prevCustomerMsg } = await getSessionContext(supabase, chatId, senderId);
        const followUpContext = detectFollowUp(text, prevCustomerMsg);
        const effectiveContext = followUpContext
          ? `${sessionContext}\n[追问提示] 这是对"${followUpContext}"的追问`
          : sessionContext;

        // ── Bot Command detection (use mentions array, not text matching) ──
        const mentions = (message?.mentions || []) as Array<Record<string,unknown>>;
        const isBotMention = mentions.some((m) => m.mentioned_type === "bot");

        // ── Bot config: check transfer_keywords even when not @mentioned ──
        if (!isBotMention && botConfig && botConfig.transfer_keywords && botConfig.transfer_keywords.length > 0) {
          const matchedKeyword = botConfig.transfer_keywords.find((kw: string) => text.includes(kw));
          if (matchedKeyword) {
            console.log("[Bot] Transfer triggered by keyword (no @mention):", matchedKeyword);
            const transferReply = "当前暂不支持自动转接人工客服。\n\n💡 建议：\n- 复杂问题请联系客服主管\n- 紧急投诉请直接电话联系\n- 发送「帮助」查看自助服务";
            sendFeishuReply(chatId, transferReply);
            return;
          }
        }

        let commandReply = "";
        const vercelUrl = Deno.env.get("VERCEL_APP_URL") || "https://qa-system-ain2k9x2x-yyy99045s-projects.vercel.app";
        let replyCardSent = false;

        let intent: { action: string; params: Record<string, string>; confidence: number; method: "regex" | "llm" | "fallback" } = {
          action: "general_chat", params: {}, confidence: 0, method: "fallback",
        };

        if (isBotMention) {
          // Remove the @_user_1 style mention key from text
          const mentionKeys = mentions.filter(m => m.mentioned_type === "bot").map(m => String(m.key || ""));
          let cleanText = text;
          for (const key of mentionKeys) {
            cleanText = cleanText.replace(key, "").trim();
          }

          // ── Admin: register/delete custom commands ──
          const adminIds = (Deno.env.get("ADMIN_OPEN_IDS") || "").split(",").map(s => s.trim()).filter(Boolean);
          const isAdmin = adminIds.includes(senderId);

          const addCmdMatch = cleanText.match(/^新增指令\s+(\S+)\s+(\S+)\s+(.+)$/);
          if (addCmdMatch) {
            if (!isAdmin) { commandReply = "权限不足"; }
            else {
              const [, cmdName, regexPattern, replyTemplate] = addCmdMatch;
              const { data: dup } = await supabase.from("bot_commands").select("id").eq("command_name", cmdName).maybeSingle();
              if (dup) { commandReply = "❌ 指令名称已存在"; }
              else {
                await supabase.from("bot_commands").insert({
                  command_name: cmdName, regex_pattern: regexPattern,
                  action_type: "custom_" + cmdName, reply_template: replyTemplate, created_by: senderId,
                });
                commandReply = "✅ 指令已注册";
              }
            }
            if (commandReply) sendFeishuReplyWithFeedback(chatId, commandReply);
            return;
          }

          const delCmdMatch = cleanText.match(/^删除指令\s+(.+)$/);
          if (delCmdMatch) {
            if (!isAdmin) { commandReply = "权限不足"; }
            else {
              const cmdName = delCmdMatch[1].trim();
              await supabase.from("bot_commands").update({ is_active: false }).eq("command_name", cmdName);
              commandReply = `✅ 指令「${cmdName}」已删除`;
            }
            if (commandReply) sendFeishuReplyWithFeedback(chatId, commandReply);
            return;
          }

          // Load custom commands for intent matching
          const customCommands = await loadCustomCommands(supabase);

          // ── Bot config: check transfer_keywords before L0 regex ──
          if (botConfig && botConfig.transfer_keywords && botConfig.transfer_keywords.length > 0) {
            const matchedKeyword = botConfig.transfer_keywords.find((kw: string) => cleanText.includes(kw));
            if (matchedKeyword) {
              intent = { action: "transfer_human", params: { keyword: matchedKeyword }, confidence: 1.0, method: "regex" };
              console.log("[Bot] Transfer triggered by keyword (@mention):", matchedKeyword);
            }
          }

          // Hybrid intent routing (skip if transfer already matched)
          if (intent.action !== "transfer_human") {
            intent = await classifyIntent(cleanText, customCommands, effectiveContext);
          }
          console.log("[Intent]", intent.action, intent.confidence, intent.method);

          switch (intent.action) {
            case "help": {
              // Full command catalog — all registered business intents grouped by category
              const allMenuItems: Array<{ line: string; intent: string; cat: string }> = [
                // 📊 数据查询
                { line: "📊 质检统计 — \"昨天质检怎么样\"", intent: "quality_report", cat: "data" },
                { line: "📈 会话统计 — \"今天会话量多少\"", intent: "chat_stats", cat: "data" },
                { line: "📝 工单查询 — \"最近工单情况\"", intent: "work_orders", cat: "data" },
                { line: "🔀 管线状态 — \"管线状态\"", intent: "pipeline_status", cat: "data" },
                { line: "📋 管线详情 — \"管线详情 <id>\"", intent: "pipeline_detail", cat: "data" },
                { line: "📜 管线历史 — \"管线历史\"", intent: "pipeline_history", cat: "data" },
                { line: "📌 待处理 — \"待处理\" / \"待办\"", intent: "hitl_pending_count", cat: "data" },
                // ⚡ 快捷操作
                { line: "🔍 合规检查 — \"检查全场5折有无违规\"", intent: "compliance_check", cat: "action" },
                { line: "📦 催付提醒 — \"有哪些待催付订单\"", intent: "payment_reminder", cat: "action" },
                { line: "💡 话术建议 — \"物流场景推荐话术\"", intent: "bot_suggest", cat: "action" },
                { line: "💬 快捷回复 — \"快捷回复 退款\"", intent: "quick_reply", cat: "action" },
                { line: "😊 情绪检测 — \"情绪检测\"", intent: "emotion_detect", cat: "action" },
                { line: "✅ 全部确认 — \"全部确认\"", intent: "batch_hitl_confirm", cat: "action" },
                // 📝 内容生成
                { line: "📋 生成报表 — \"生成本周周报\"", intent: "generate_report", cat: "content" },
                { line: "📚 知识缺口 — \"知识库有缺口吗\"", intent: "knowledge_gaps", cat: "content" },
                { line: "📰 今日简报 — \"今日简报\"", intent: "daily_brief", cat: "content" },
                { line: "🎯 质检评测 — \"今日质检情况\"", intent: "qa_evaluate", cat: "content" },
                // 🛠️ 系统工具
                { line: "🚀 会议测试 — \"触发产品评审会议\"", intent: "meeting_pipeline", cat: "tool" },
                { line: "🔄 重试管线 — \"重试管线 <id>\"", intent: "pipeline_retry", cat: "tool" },
                { line: "❤️ 系统健康 — \"系统健康\" / \"健康\"", intent: "system_health", cat: "tool" },
                { line: "📤 导出质检 — \"导出质检报告\"", intent: "export_quality_reports", cat: "tool" },
                { line: "📤 导出会话 — \"导出会话数据\"", intent: "export_chat_sessions", cat: "tool" },
                { line: "📤 导出工单 — \"导出工单\"", intent: "export_work_orders", cat: "tool" },
                { line: "📤 导出管线 — \"导出管线数据\"", intent: "export_pipeline_jobs", cat: "tool" },
                { line: "📝 质检改进 — \"改进建议\" / \"我的质检\"", intent: "quality_improvement", cat: "action" },
              ];

              const profile = await getUserProfile(supabase, senderId);

              const catLabels: Record<string, string> = {
                data: "📊 数据查询", action: "⚡ 快捷操作", content: "📝 内容生成", tool: "🛠️ 系统工具",
              };

              const grouped: Record<string, typeof allMenuItems> = {};
              for (const m of allMenuItems) {
                if (!grouped[m.cat]) grouped[m.cat] = [];
                grouped[m.cat].push(m);
              }

              // Sort within each category by user's usage frequency (most-used first)
              for (const items of Object.values(grouped)) {
                items.sort((a, b) => {
                  const idxA = profile.topIntents.indexOf(a.intent);
                  const idxB = profile.topIntents.indexOf(b.intent);
                  if (idxA !== -1 && idxB !== -1) return idxA - idxB;
                  if (idxA !== -1) return -1;
                  if (idxB !== -1) return 1;
                  return 0;
                });
              }

              let menuText = "";

              // Personalized quick-access section using profile summary
              if (profile.profileStr) {
                menuText += `🔥 你最常用\n  ${profile.profileStr}\n\n`;
              }

              // Category sections with item counts
              for (const [cat, items] of Object.entries(grouped)) {
                menuText += `${catLabels[cat] || cat} (${items.length}项)\n`;
                menuText += items.map(m => `  ${m.line}`).join("\n");
                menuText += "\n\n";
              }

              // Admin-only section
              if (isAdmin) {
                menuText += "🔧 管理员指令\n";
                menuText += "  新增指令 <名称> <正则> <回复>\n";
                menuText += "  删除指令 <名称>\n";
                menuText += "  编辑 <消息ID> <新内容>\n\n";
              }

              menuText += "💬 没找到需要的？直接说你想做什么\n   比如「帮我看看最近投诉多不多」\n";
              menuText += "📍 发送「怎么用 <指令名>」查看具体用法示例";

              commandReply = menuText;
              break;
            }
            case "command_usage": {
              const cmd = intent.params.command || "";
              const usageMap: Record<string, string[]> = {
                "质检报告": ["质检报告昨天 — 查看昨天的质检统计", "质检报告本周 — 查看本周质检数据", "质检报告 — 查看今日质检概况"],
                "合规检查": ["合规检查 全场5折 — 扫描\"全场5折\"是否违规", "合规检查 点击链接加微信 — 检查导流行为", "合规检查 <内容> — 扫描指定内容的合规风险"],
                "生成报表": ["生成日报 — 生成本日数据报表", "生成周报 — 生成本周汇总报表", "生成月报 — 生成月度汇总报表"],
                "催单提醒": ["催单提醒 — 查看所有待催付订单", "催单 — 快速查询未付款工单", "催付 — 查看待催收工单"],
                "工单查询": ["工单 — 查看最近5条工单", "工单列表 — 查看全部工单", "工单 — 带参数查询指定工单"],
                "知识缺口": ["知识缺口 — 查看知识库待补充条目", "话术缺口 — 查看需要补充的话术"],
                "话术建议": ["话术建议 物流 — 获取物流相关话术", "话术建议 退款 — 获取退款场景话术", "话术建议 — 获取通用话术建议"],
                "会话统计": ["会话统计 — 查看总会话和今日数据", "聊天统计 — 同上"],
                "质检评测": ["质检分析 — 查看今日质检统计", "质检评测 — 查看质检评测结果"],
                "会议测试": ["会议测试 产品评审 — 触发产品评审Pipeline", "会议测试 — 触发默认会议Pipeline", "pipeline — 触发Pipeline任务"],
              };
              const examples = usageMap[cmd];
              if (examples) {
                commandReply = `📖 **「${cmd}」用法示例**\n\n${examples.map((e) => `- ${e}`).join("\n")}`;
              } else {
                commandReply = `该指令暂无详细说明，发送「帮助」查看所有指令`;
              }
              break;
            }
            case "quality_report": {
              commandReply = "⏳ 正在处理质检报告...";
              sendFeishuReply(chatId, commandReply);
              const periodRaw = intent.params.period || "今日";
              const now = new Date();
              let dateFrom: string;
              let dateTo: string;
              let reportLabel: string;

              // Natural language time parsing (overrides periodRaw)
              const naturalPeriod = parseNaturalPeriod(cleanText);

              if (naturalPeriod) {
                dateFrom = naturalPeriod.from;
                dateTo = naturalPeriod.to;
                reportLabel = "质检报告";
              } else if (periodRaw === "昨天") {
                const d = new Date(Date.now() - 86400000);
                dateFrom = d.toISOString().slice(0, 10);
                dateTo = now.toISOString().slice(0, 10);
                reportLabel = "日报";
              } else if (periodRaw === "本周") {
                const day = now.getDay();
                const mondayOffset = day === 0 ? -6 : 1 - day;
                const monday = new Date(now.getFullYear(), now.getMonth(), now.getDate() + mondayOffset);
                dateFrom = monday.toISOString().slice(0, 10);
                dateTo = new Date(now.getTime() + 86400000).toISOString().slice(0, 10);
                reportLabel = "周报";
              } else if (periodRaw === "上周") {
                const day = now.getDay();
                const mondayOffset = day === 0 ? -13 : -6 - day;
                const lastMonday = new Date(now.getFullYear(), now.getMonth(), now.getDate() + mondayOffset);
                const lastSunday = new Date(lastMonday.getTime() + 6 * 86400000);
                dateFrom = lastMonday.toISOString().slice(0, 10);
                dateTo = new Date(lastSunday.getTime() + 86400000).toISOString().slice(0, 10);
                reportLabel = "周报";
              } else {
                dateFrom = now.toISOString().slice(0, 10);
                dateTo = new Date(now.getTime() + 86400000).toISOString().slice(0, 10);
                reportLabel = "日报";
              }

              const { data: qStats } = await supabase
                .from("quality_reports")
                .select("risk_level, total_score")
                .gte("created_at", dateFrom)
                .lt("created_at", dateTo)
                .limit(500);

              const total = qStats?.length || 0;
              const critical = qStats?.filter((r: any) => r.risk_level === "critical").length || 0;
              const avgScore = total > 0
                ? Math.round((qStats?.reduce((s: number, r: any) => s + (r.total_score || 0), 0) || 0) / total)
                : 0;

              const riskDist: Record<string, number> = {};
              for (const r of (qStats || [])) {
                const level = (r as any).risk_level || "unknown";
                riskDist[level] = (riskDist[level] || 0) + 1;
              }

              const topViolations = Object.entries(riskDist)
                .sort(([, a], [, b]) => b - a)
                .slice(0, 3)
                .map(([k, v]) => {
                  const label = k === "critical" ? "致命风险" : k === "high" ? "高风险" : k === "medium" ? "中风险" : "低风险";
                  return `${label}(${v}条)`;
                });

              const stats = { total, critical, avgScore, riskDistribution: riskDist, topViolations };
              const reportMd = await generateLLMReport(reportLabel, stats);

              await sendFeishuCard(chatId, {
                header: { title: { tag: "plain_text", content: `📊 质检报告 · ${periodRaw}` }, template: "blue" },
                elements: [
                  { tag: "div", text: { tag: "lark_md", content: reportMd } },
                  { tag: "hr" },
                  { tag: "action", actions: [
                    { tag: "button", text: { tag: "plain_text", content: "📋 查看详情" }, type: "primary", url: `${vercelUrl}/dashboard?tab=reports` },
                  ]},
                ],
              });
              replyCardSent = true;
              commandReply = "";
              break;
            }
            case "generate_report": {
              commandReply = "⏳ 正在处理报表...";
              sendFeishuReply(chatId, commandReply);
              const type = intent.params.type || "日报";
              const now = new Date();
              let dateFrom: string;
              let dateTo: string;
              let reportLabel: string;

              // Natural language time parsing
              const naturalPeriod = parseNaturalPeriod(cleanText);
              if (naturalPeriod) {
                dateFrom = naturalPeriod.from;
                dateTo = naturalPeriod.to;
                reportLabel = "报表";
              } else {
                let daysBack: number;

                if (type === "周报") {
                  daysBack = 7;
                  reportLabel = "周报";
                } else if (type === "月报") {
                  daysBack = 30;
                  reportLabel = "月报";
                } else {
                  daysBack = 1;
                  reportLabel = "日报";
                }

                // Daily: yesterday; Weekly: last 7 days; Monthly: last 30 days
                const endDate = reportLabel === "日报"
                  ? new Date(now.getTime() - 86400000)  // yesterday
                  : now;
                dateFrom = new Date(endDate.getTime() - daysBack * 86400000).toISOString().slice(0, 10);
                dateTo = new Date(endDate.getTime() + 86400000).toISOString().slice(0, 10);
              }

              const { count: sessionCount } = await supabase
                .from("bot_chat_sessions")
                .select("*", { count: "exact", head: true })
                .gte("created_at", dateFrom)
                .lt("created_at", dateTo);

              const { data: qStats } = await supabase
                .from("quality_reports")
                .select("risk_level, total_score")
                .gte("created_at", dateFrom)
                .lt("created_at", dateTo)
                .limit(500);

              const total = qStats?.length || 0;
              const critical = qStats?.filter((r: any) => r.risk_level === "critical").length || 0;
              const avgScore = total > 0
                ? Math.round((qStats?.reduce((s: number, r: any) => s + (r.total_score || 0), 0) || 0) / total)
                : 0;

              const riskDist: Record<string, number> = {};
              for (const r of (qStats || [])) {
                const level = (r as any).risk_level || "unknown";
                riskDist[level] = (riskDist[level] || 0) + 1;
              }

              const topViolations = Object.entries(riskDist)
                .sort(([, a], [, b]) => b - a)
                .slice(0, 3)
                .map(([k, v]) => {
                  const label = k === "critical" ? "致命风险" : k === "high" ? "高风险" : k === "medium" ? "中风险" : "低风险";
                  return `${label}(${v}条)`;
                });

              const stats = {
                total: sessionCount || 0,
                critical,
                avgScore,
                riskDistribution: riskDist,
                topViolations,
              };
              const displayEnd = new Date(new Date(dateTo).getTime() - 86400000).toISOString().slice(0, 10);
              const titleDate = reportLabel === "日报" ? dateFrom : `${dateFrom} ~ ${displayEnd}`;
              const reportMd = await generateLLMReport(reportLabel, stats);

              await sendFeishuCard(chatId, {
                header: {
                  title: { tag: "plain_text", content: `📊 ${reportLabel} · ${titleDate}` },
                  template: "blue",
                },
                elements: [
                  { tag: "div", text: { tag: "lark_md", content: reportMd } },
                  { tag: "hr" },
                  { tag: "action", actions: [
                    { tag: "button", text: { tag: "plain_text", content: "📋 查看详情" }, type: "primary", url: `${vercelUrl}/dashboard?tab=reports` },
                  ]},
                ],
              });
              replyCardSent = true;
              commandReply = "";
              break;
            }
            case "compliance_check": {
              commandReply = "⏳ 正在处理合规检查...";
              sendFeishuReply(chatId, commandReply);
              const content = intent.params.content || cleanText;

              // Fetch active compliance rules from DB, fall back to hardcoded defaults
              let patterns: Array<{ pattern: RegExp; rule: string; risk: number }> = [];
              try {
                const { data: rules } = await supabase
                  .from("compliance_rules")
                  .select("pattern, rule_text, risk_level")
                  .eq("is_active", true)
                  .order("risk_level", { ascending: false });
                if (rules && Array.isArray(rules) && rules.length > 0) {
                  for (const r of rules as Array<{ pattern: string; rule_text: string; risk_level: number }>) {
                    try { patterns.push({ pattern: new RegExp(r.pattern), rule: r.rule_text, risk: r.risk_level }); } catch { /* skip invalid regex */ }
                  }
                }
              } catch { /* fall through to hardcoded */ }

              // Fallback if no DB rules
              if (patterns.length === 0) {
                patterns = [
                  { pattern: /虚假|假一|全场5折|一折|免费送|0元/, rule: "禁止虚假/夸大宣传", risk: 4 },
                  { pattern: /最[好大强]|第一|唯一|顶级|国家级/, rule: "禁止使用绝对化用语", risk: 3 },
                  { pattern: /点击.*链接|加微信|扫码|私信/, rule: "禁止导流外部渠道", risk: 3 },
                  { pattern: /骂|垃圾|傻|死|骗子/, rule: "禁止辱骂或攻击性语言", risk: 4 },
                ];
              }

              const matched: Array<{ rule: string; risk: number; trigger: string }> = [];
              for (const p of patterns) {
                const m = content.match(p.pattern);
                if (m) matched.push({ rule: p.rule, risk: p.risk, trigger: m[0] });
              }
              if (matched.length > 0) {
                const risks = matched.map(m => `- **${m.rule}** [${m.risk === 4 ? '🔴阻断' : '🟠高危'}]`).join("\n");
                const triggerDetails = matched.map(m => `"${m.trigger}"命中规则「${m.rule}」`).join(" | ");
                await sendFeishuCard(chatId, {
                  header: { title: { tag: "plain_text", content: `⚠️ 合规风险 (${matched.length}条)` }, template: "red" },
                  elements: [
                    { tag: "div", text: { tag: "lark_md", content: `**扫描内容：** ${content}\n\n${risks}\n\n📎 判断依据: ${triggerDetails} | 共扫描${patterns.length}条规则` } },
                    { tag: "action", actions: [{
                      tag: "button", text: { tag: "plain_text", content: "🔧 误判驳回" }, type: "danger",
                      value: JSON.stringify({ action: "compliance_overturn", check_id: content.slice(0, 40), reason: "人工复核误判" }),
                    }]},
                  ],
                });

                // Increment match_count for matched rules (fire-and-forget)
                for (const m of matched) {
                  (async () => {
                    const { data: row } = await supabase.from("compliance_rules").select("match_count").eq("rule_text", m.rule).maybeSingle();
                    if (row) {
                      await supabase.from("compliance_rules").update({ match_count: ((row as any).match_count || 0) + 1 }).eq("rule_text", m.rule);
                    }
                  })().catch(() => {});
                }
                commandReply = addTransparency(`⚠️ 检测到 ${matched.length} 条合规风险，详见卡片`, "compliance", {
                  matchedRules: triggerDetails,
                  totalRules: String(patterns.length),
                });
              } else {
                commandReply = `✅ 未检测到合规风险: "${content.slice(0, 80)}"`;
              }
              break;
            }
            case "payment_reminder": {
              const { data: overdueOrders } = await supabase.from("work_orders").select("id,title,status").eq("category", "payment").in("status", ["pending", "open"]).limit(10);
              const count = overdueOrders?.length || 0;
              if (count > 0) {
                const list = overdueOrders?.map((wo: any) => `- ${wo.title} [${wo.status}]`).join("\n") || "";
                commandReply = `📦 待催付: **${count} 笔**\n${list}`;
              } else {
                commandReply = "✅ 当前无待催付订单";
              }
              break;
            }
            case "work_orders": {
              const { data: orders, error: woErr } = await supabase.from("work_orders").select("id,title,status,priority,created_at").order("created_at", { ascending: false }).limit(5);
              if (!woErr && orders && orders.length > 0) {
                const list = orders.map((wo: any) => `- ${wo.title} [${wo.status}]`).join("\n");
                commandReply = `📝 最近工单:\n${list}`;
                commandReply = addTransparency(commandReply, "data_query", {
                  source: "work_orders",
                  timeRange: new Date().toISOString().slice(0, 10),
                  recordCount: String(orders.length),
                });
              } else {
                commandReply = "📝 暂无工单";
                commandReply = addTransparency(commandReply, "data_query", {
                  source: "work_orders",
                  timeRange: new Date().toISOString().slice(0, 10),
                  recordCount: "0",
                });
              }
              break;
            }
            case "knowledge_gaps": {
              const { data: entries } = await supabase.from("knowledge_entries").select("id,title").eq("status", "draft").limit(5);
              commandReply = entries && entries.length > 0
                ? `📚 知识缺口 (${entries.length}条待补充):\n${entries.map((e: any) => `- ${e.title}`).join("\n")}`
                : "✅ 知识库覆盖完整，暂无缺口";
              break;
            }
            case "bot_suggest": {
              const kw = intent.params.keyword || "通用";
              const { data: configs } = await supabase.from("bot_configs").select("config_key,config_value").ilike("config_key", `%${kw}%`).limit(3);
              commandReply = configs && configs.length > 0
                ? `💡 "${kw}" 相关话术:\n${configs.map((c: any) => `- ${c.config_key}`).join("\n")}`
                : `💡 "${kw}" 暂无相关话术，已记录需求`;
              break;
            }
            case "chat_stats": {
              const tStr = new Date().toISOString().slice(0, 10);
              const tmrStr = new Date(Date.now() + 86400000).toISOString().slice(0, 10);
              const { count: total } = await supabase.from("bot_chat_sessions").select("*", { count: "exact", head: true });
              const { count: today } = await supabase.from("bot_chat_sessions").select("*", { count: "exact", head: true }).gte("created_at", tStr).lt("created_at", tmrStr);
              const { data: qd } = await supabase.from("quality_reports").select("total_score").gte("created_at", tStr).lt("created_at", tmrStr).limit(100);
              const avgScore = qd && qd.length > 0 ? Math.round(qd.reduce((s: number, r: any) => s + (r.total_score || 0), 0) / qd.length) : "N/A";
              commandReply = `📊 会话统计\n- 总会话: ${total || 0}\n- 今日: ${today || 0}\n- 均分: ${avgScore}`;
              commandReply = addTransparency(commandReply, "data_query", {
                source: "bot_chat_sessions",
                timeRange: tStr,
                recordCount: String(today || 0),
              });
              break;
            }
            case "qa_evaluate": {
              const tStr = new Date().toISOString().slice(0, 10);
              const tmrStr = new Date(Date.now() + 86400000).toISOString().slice(0, 10);
              const { data: recentEval } = await supabase.from("quality_reports").select("risk_level,total_score").gte("created_at", tStr).lt("created_at", tmrStr).limit(20);
              const todayCount = recentEval?.length || 0;
              const criticalCount = recentEval?.filter((r: any) => r.risk_level === "critical").length || 0;
              commandReply = `🎯 今日质检: ${todayCount} 条\n- 致命风险: ${criticalCount}\n- 合格率: ${todayCount > 0 ? Math.round((1 - criticalCount/todayCount) * 100) : 100}%`;
              commandReply = addTransparency(commandReply, "data_query", {
                source: "quality_reports",
                timeRange: tStr,
                recordCount: String(todayCount),
              });
              break;
            }
            case "daily_brief": {
              const profile = await getUserProfile(supabase, senderId);
              const topIntents = profile.topIntents.length > 0 ? profile.topIntents : ["quality_report", "work_orders"];
              const todayStr = new Date().toISOString().slice(0, 10);
              const tmrStr = new Date(Date.now() + 86400000).toISOString().slice(0, 10);
              const queried = new Set<string>();
              const parts: string[] = [];

              for (const intent of topIntents.slice(0, 3)) {
                if (intent === "quality_report" || intent === "qa_evaluate") {
                  if (queried.has("qa")) continue;
                  queried.add("qa");
                  const { data: qStats } = await supabase.from("quality_reports")
                    .select("risk_level").gte("created_at", todayStr).lt("created_at", tmrStr).limit(200);
                  const total = qStats?.length || 0;
                  const critical = qStats?.filter((r: any) => r.risk_level === "critical").length || 0;
                  parts.push(`📊 今日质检: ${total}条, 致命${critical}条`);
                } else if (intent === "chat_stats") {
                  const { count: today } = await supabase.from("bot_chat_sessions")
                    .select("*", { count: "exact", head: true }).gte("created_at", todayStr).lt("created_at", tmrStr);
                  parts.push(`📈 今日会话: ${today || 0}条`);
                } else if (intent === "work_orders") {
                  if (queried.has("wo")) continue;
                  queried.add("wo");
                  const { data: orders } = await supabase.from("work_orders")
                    .select("id").in("status", ["pending", "open"]).limit(50);
                  parts.push(`📝 待处理工单: ${orders?.length || 0}条`);
                } else if (intent === "payment_reminder") {
                  if (queried.has("wo")) continue;
                  queried.add("wo");
                  const { data: orders } = await supabase.from("work_orders")
                    .select("id").eq("category", "payment").in("status", ["pending", "open"]).limit(50);
                  parts.push(`📦 待催付: ${orders?.length || 0}笔`);
                } else if (intent === "knowledge_gaps") {
                  const { data: entries } = await supabase.from("knowledge_entries")
                    .select("id").eq("status", "draft").limit(50);
                  parts.push(`📚 知识缺口: ${entries?.length || 0}条`);
                }
              }

              commandReply = parts.length > 0
                ? `📋 今日简报\n${profile.profileStr ? profile.profileStr + "\n\n" : ""}${parts.join("\n")}`
                : "📋 今日简报\n暂无数据，发送「帮助」查看可用指令";
              break;
            }
            case "meeting_pipeline": {
              const topic = intent.params.topic || "Bot触发的会议测试";
              commandReply = `⏳ 正在触发 Post-Meeting Pipeline: "${topic}"...`;
              const myAppUrl = Deno.env.get("MY_APP_URL") || "https://my-app-beta-seven-74.vercel.app";
              const apiSecret = Deno.env.get("API_SECRET") || "";
              fetch(`${myAppUrl}/api/pipeline/post-meeting`, {
                method: "POST", headers: { "Content-Type": "application/json", "Authorization": `Bearer ${apiSecret}` },
                body: JSON.stringify({ topic, meeting_type: "vc", operator_id: "bot_command" }),
              }).catch(() => { sendFeishuReply(chatId, "❌ 会议流水线 暂时无法完成\n\n💡 建议：请检查会议链接是否有效\n🆘 如持续失败，请联系管理员"); });
              break;
            }
            case "system_health": {
              const state = getCircuitBreakerState();

              // DeepSeek LLM status
              const dsRecent10 = llmRecentCallLog.filter(e => e.service.startsWith("deepseek-")).slice(-10);
              const dsAllOk = dsRecent10.length > 0 && dsRecent10.every(e => e.ok);
              let dsStatus: string;
              if (state.deepseek === "open") {
                dsStatus = "❌ 断路器打开(熔断中)";
              } else if (dsAllOk) {
                dsStatus = `✅ 正常 (最近10次调用全部成功)`;
              } else {
                dsStatus = `⚠️ 降级 (部分调用失败)`;
              }

              // Embedding API status
              const embRecent10 = llmRecentCallLog.filter(e => e.service.startsWith("embedding-")).slice(-10);
              const embStatus = state.embedding === "open"
                ? "❌ 断路器打开"
                : "✅ 正常";

              // Supabase connectivity check
              let supabaseStatus = "❓ 未知";
              try {
                const { error } = await supabase.from("audit_logs").select("id").limit(1);
                supabaseStatus = error ? `❌ 连接异常: ${error.message}` : "✅ 连接正常";
              } catch {
                supabaseStatus = "❌ 连接失败";
              }

              // Alert status
              let alertStatus = "✅ 无待推送告警";
              try {
                const { data: alerts } = await supabase.from("audit_logs")
                  .select("id")
                  .eq("action", "system_error")
                  .gt("created_at", new Date(Date.now() - 60 * 60 * 1000).toISOString())
                  .limit(10);
                const alertCount = alerts?.length || 0;
                if (alertCount > 0) {
                  alertStatus = `⚠️ ${alertCount}条待推送(静默期)`;
                }
              } catch {
                alertStatus = "❓ 无法查询";
              }

              commandReply = [
                "🏥 系统健康检查",
                `- DeepSeek LLM: ${dsStatus}`,
                `- Embedding API: ${embStatus}`,
                `- Supabase: ${supabaseStatus}`,
                `- 告警状态: ${alertStatus}`,
              ].join("\n");
              break;
            }
            case "batch_hitl_confirm": {
              const count = await handleBatchHitlConfirm(supabase);
              commandReply = `✅ 已确认 ${count} 条待处理任务`;
              break;
            }
            case "hitl_pending_count": {
              const { count: pendingCount, error: countErr } = await supabase
                .from("execution_steps")
                .select("*", { count: "exact", head: true })
                .eq("status", "SUSPENDED_HITL");
              const n = countErr ? 0 : (pendingCount || 0);
              commandReply = `📋 当前 ${n} 条任务待确认`;
              break;
            }
            case "pipeline_status": {
              const { data: jobs, error: jobsErr } = await supabase
                .from("pipeline_jobs")
                .select("id, meeting_id, status, result, created_at")
                .order("created_at", { ascending: false })
                .limit(5);

              if (jobsErr || !jobs || jobs.length === 0) {
                commandReply = "📊 暂无管线记录";
                break;
              }

              const lines: string[] = ["📊 最近管线状态:"];
              for (const job of jobs as Array<{ id: string; meeting_id?: string; status: string; result?: unknown; created_at: string }>) {
                const { data: steps } = await supabase
                  .from("execution_steps")
                  .select("status, step_order")
                  .eq("pipeline_job_id", job.id)
                  .order("step_order");

                const total = steps?.length || 0;
                const completed = (steps || []).filter((s: { status: string }) => s.status === "SUCCEEDED").length;
                const suspended = (steps || []).some((s: { status: string }) => s.status === "SUSPENDED_HITL");

                let statusIcon: string;
                if (suspended) {
                  statusIcon = "⏸️ 待确认";
                } else if (job.status === "SUCCEEDED") {
                  statusIcon = "✅ 已完成";
                } else if (job.status === "FAILED") {
                  statusIcon = "❌ 失败";
                } else if (job.status === "PROCESSING") {
                  statusIcon = "🔄 处理中";
                } else {
                  statusIcon = "⏳ " + job.status;
                }

                const name = job.meeting_id || job.id.slice(0, 8);
                const durationS = job.created_at
                  ? Math.round((Date.now() - new Date(job.created_at).getTime()) / 1000)
                  : 0;
                const durationStr = job.status === "SUCCEEDED" ? `耗时${durationS}s` : `${durationS}s前`;

                lines.push(`- ${name}: ${statusIcon} (${completed}/${total}步, ${durationStr})`);
              }

              commandReply = lines.join("\n");
              break;
            }
            case "pipeline_detail": {
              const jobId = intent.params.job_id;
              if (!jobId) {
                commandReply = "⚠️ 请提供管线ID，如「管线详情 abc123」";
                break;
              }

              // Try exact UUID match first, then partial match
              const { data: job, error: jobErr } = await supabase
                .from("pipeline_jobs")
                .select("id, meeting_id, status, result, created_at")
                .eq("id", jobId)
                .maybeSingle();

              if (jobErr || !job) {
                commandReply = `⚠️ 未找到管线 ${jobId}`;
                break;
              }

              const { data: steps } = await supabase
                .from("execution_steps")
                .select("step_name, step_order, status, error, started_at, completed_at")
                .eq("pipeline_job_id", (job as { id: string }).id)
                .order("step_order");

              const stepLines: string[] = [];
              const statusIcon: Record<string, string> = {
                SUCCEEDED: "✅",
                FAILED: "❌",
                RUNNING: "🔄",
                PENDING: "⏳",
                SUSPENDED_HITL: "⏸️",
                SUSPENDED_ASR: "🔊",
              };

              for (const s of (steps || []) as Array<{ step_name: string; step_order: number; status: string; error?: string }>) {
                const icon = statusIcon[s.status] || "❓";
                const detail = s.error ? ` [${s.error.slice(0, 40)}]` : "";
                stepLines.push(`  ${s.step_order}. ${icon} ${s.step_name} (${s.status})${detail}`);
              }

              const jobData = job as { meeting_id?: string; status: string; id: string };
              const name = jobData.meeting_id || jobData.id.slice(0, 8);
              commandReply = [
                `📋 管线详情: ${name}`,
                `状态: ${jobData.status}`,
                ...stepLines,
              ].join("\n");
              break;
            }
            case "pipeline_retry": {
              const jobId = intent.params.job_id;
              if (!jobId) {
                commandReply = "⚠️ 请提供管线ID，如「重试管线 abc123」";
                break;
              }

              const { data: job, error: jobErr } = await supabase
                .from("pipeline_jobs")
                .select("id, status, result, meeting_id")
                .eq("id", jobId)
                .maybeSingle();

              if (jobErr || !job) {
                commandReply = `⚠️ 未找到管线 ${jobId}`;
                break;
              }

              const j = job as { id: string; status: string; result?: unknown; meeting_id?: string };
              if (j.status !== "FAILED") {
                commandReply = `⚠️ 管线 ${jobId.slice(0, 8)} 状态为 ${j.status}，仅支持重试失败的管线`;
                break;
              }

              let meetingContext: Record<string, unknown> = {};
              try {
                if (j.result && typeof j.result === "object") {
                  meetingContext = j.result as Record<string, unknown>;
                } else if (typeof j.result === "string") {
                  meetingContext = JSON.parse(j.result);
                }
              } catch { /* use empty */ }

              const topic = (meetingContext.topic || meetingContext.meeting_subject || j.meeting_id || "重试管线") as string;
              const meetingType = (meetingContext.meeting_type || "vc") as string;

              commandReply = `⏳ 正在重试管线: "${topic}"...`;
              const myAppUrl = Deno.env.get("MY_APP_URL") || "https://my-app-beta-seven-74.vercel.app";
              const apiSecret = Deno.env.get("API_SECRET") || "";
              fetch(`${myAppUrl}/api/pipeline/post-meeting`, {
                method: "POST",
                headers: { "Content-Type": "application/json", "Authorization": `Bearer ${apiSecret}` },
                body: JSON.stringify({ topic, meeting_type: meetingType, operator_id: "bot_command", retry_job_id: jobId }),
              }).catch(() => { sendFeishuReply(chatId, "❌ 流水线重试 暂时无法完成\n\n💡 建议：请检查Job ID或稍后重试\n🆘 如持续失败，请联系管理员"); });
              break;
            }
            case "pipeline_history": {
              const { data: jobs, error: jobsErr } = await supabase
                .from("pipeline_jobs")
                .select("id, meeting_id, status, result, created_at")
                .order("created_at", { ascending: false })
                .limit(10);

              if (jobsErr || !jobs || jobs.length === 0) {
                commandReply = "📊 暂无管线记录";
                break;
              }

              const lines: string[] = ["📊 最近管线历史 (10条):"];
              for (const job of jobs as Array<{ id: string; meeting_id?: string; status: string; result?: unknown; created_at: string }>) {
                const { data: steps } = await supabase
                  .from("execution_steps")
                  .select("status, step_order")
                  .eq("pipeline_job_id", job.id)
                  .order("step_order");

                const total = steps?.length || 0;
                const completed = (steps || []).filter((s: { status: string }) => s.status === "SUCCEEDED").length;
                const suspended = (steps || []).some((s: { status: string }) => s.status === "SUSPENDED_HITL");

                let statusIcon: string;
                if (suspended) {
                  statusIcon = "⏸️ 待确认";
                } else if (job.status === "SUCCEEDED") {
                  statusIcon = "✅ 已完成";
                } else if (job.status === "FAILED") {
                  statusIcon = "❌ 失败";
                } else if (job.status === "PROCESSING") {
                  statusIcon = "🔄 处理中";
                } else {
                  statusIcon = "⏳ " + job.status;
                }

                const name = job.meeting_id || job.id.slice(0, 8);
                const durationS = job.created_at
                  ? Math.round((Date.now() - new Date(job.created_at).getTime()) / 1000)
                  : 0;
                const durationStr = job.status === "SUCCEEDED" ? `耗时${durationS}s` : `${durationS}s前`;

                lines.push(`- ${name}: ${statusIcon} (${completed}/${total}步, ${durationStr})`);
              }

              commandReply = lines.join("\n");
              break;
            }
            case "transfer_human": {
              commandReply = "当前暂不支持自动转接人工客服。\n\n💡 建议：\n- 复杂问题请联系客服主管\n- 紧急投诉请直接电话联系\n- 发送「帮助」查看自助服务";
              break;
            }
            case "quick_reply": {
              const category = intent.params.category || "general";
              const replies = getQuickReplies(category);
              const categoryLabels: Record<string, string> = {
                logistics: "物流/发货", refund: "退款/退货", quality: "质量问题", general: "通用",
              };
              const catLabel = Object.entries(categoryLabels).find(([k]) => k === category)?.[1]
                || Object.entries(categoryLabels).find(([k]) => new RegExp(k).test(category))?.[1]
                || category;
              commandReply = `快捷回复建议 (${catLabel}):\n${replies.map((r, i) => `${i + 1}. ${r}`).join("\n")}`;
              break;
            }
            case "emotion_detect": {
              const targetMsg = prevCustomerMsg || text.replace(/情绪检测/, "").trim();
              if (!targetMsg && !prevCustomerMsg) {
                commandReply = "未找到可分析的消息。请回复一条客户消息使用此指令。";
              } else {
                const emotion = detectEmotion(prevCustomerMsg || targetMsg);
                const lines = [
                  "情绪检测结果",
                  `- 情绪等级: ${emotion.level}`,
                  `- 触达关键词: ${emotion.keywords.length > 0 ? emotion.keywords.join(", ") : "无"}`,
                  `- 处理建议: ${emotion.suggestion || "正常接待"}`,
                ];
                commandReply = lines.join("\n");
              }
              break;
            }
            case "export_quality_reports": {
              const dFrom = new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10);
              const dTo = new Date().toISOString().slice(0, 10);
              commandReply = [
                `📥 数据导出 - 质检报告`,
                `📅 时间范围: ${dFrom} ~ ${dTo}（默认近7天，可通过URL参数调整）`,
                ``,
                `• Excel: ${vercelUrl}/api/qa/export?table=quality_reports&format=xlsx&from=${dFrom}&to=${dTo}`,
                `• CSV: ${vercelUrl}/api/qa/export?table=quality_reports&format=csv&from=${dFrom}&to=${dTo}`,
                ``,
                `💡 提示: 超过200条记录时响应头会携带 X-Export-Count`,
              ].join("\n");
              break;
            }
            case "export_chat_sessions": {
              const dFrom = new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10);
              const dTo = new Date().toISOString().slice(0, 10);
              commandReply = [
                `📥 数据导出 - 会话数据`,
                `📅 时间范围: ${dFrom} ~ ${dTo}（默认近7天，可通过URL参数调整）`,
                ``,
                `• Excel: ${vercelUrl}/api/qa/export?table=bot_chat_sessions&format=xlsx&from=${dFrom}&to=${dTo}`,
                `• CSV: ${vercelUrl}/api/qa/export?table=bot_chat_sessions&format=csv&from=${dFrom}&to=${dTo}`,
                ``,
                `💡 提示: 超过200条记录时响应头会携带 X-Export-Count`,
              ].join("\n");
              break;
            }
            case "export_work_orders": {
              const dFrom = new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10);
              const dTo = new Date().toISOString().slice(0, 10);
              commandReply = [
                `📥 数据导出 - 工单`,
                `📅 时间范围: ${dFrom} ~ ${dTo}（默认近7天，可通过URL参数调整）`,
                ``,
                `• Excel: ${vercelUrl}/api/qa/export?table=work_orders&format=xlsx&from=${dFrom}&to=${dTo}`,
                `• CSV: ${vercelUrl}/api/qa/export?table=work_orders&format=csv&from=${dFrom}&to=${dTo}`,
                ``,
                `💡 提示: 超过200条记录时响应头会携带 X-Export-Count`,
              ].join("\n");
              break;
            }
            case "export_pipeline_jobs": {
              const myAppUrl = Deno.env.get("MY_APP_URL") || "https://my-app-beta-seven-74.vercel.app";
              const dFrom = new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10);
              const dTo = new Date().toISOString().slice(0, 10);
              commandReply = [
                `📥 数据导出 - 管线任务`,
                `📅 时间范围: ${dFrom} ~ ${dTo}（默认近7天，可通过URL参数调整）`,
                ``,
                `• Excel: ${myAppUrl}/api/export?table=pipeline_jobs&format=xlsx&from=${dFrom}&to=${dTo}`,
                `• CSV: ${myAppUrl}/api/export?table=pipeline_jobs&format=csv&from=${dFrom}&to=${dTo}`,
                ``,
                `💡 提示: 超过200条记录时响应头会携带 X-Export-Count`,
              ].join("\n");
              break;
            }
            case "quality_improvement": {
              commandReply = "⏳ 正在查询最近的质检报告...";
              sendFeishuReply(chatId, commandReply);

              // Find agent_name for this sender
              const agentName = await findAgentName(supabase, senderId, chatId);

              if (!agentName) {
                commandReply = "⚠️ 未找到你的质检记录。请确保已有质检报告后再试。\n\n💡 提示：如果你是新客服，可以先让质检系统进行一次评估。";
                break;
              }

              // Get most recent 3 reports with violations
              const { data: recentReports } = await supabase
                .from("quality_reports")
                .select("*")
                .order("created_at", { ascending: false })
                .limit(3);

              if (!recentReports || recentReports.length === 0) {
                commandReply = "🎉 暂无质检报告，继续保持！";
                break;
              }

              // Filter to reports with violations
              const reportsWithViolations = (recentReports as Array<Record<string, unknown>>)
                .filter((r) => {
                  const v = r.violations;
                  return Array.isArray(v) && v.length > 0;
                });

              if (reportsWithViolations.length === 0) {
                // Check if there are reports with scores below 80
                const lowScoreReports = (recentReports as Array<Record<string, unknown>>)
                  .filter((r) => (r.total_score as number) < 80);

                if (lowScoreReports.length > 0) {
                  // Reports exist but with no violations (or violations not stored properly)
                  commandReply = `📊 找到 ${lowScoreReports.length} 条低分报告（无违规明细记录），请联系主管查看详情。`;
                } else {
                  commandReply = "🎉 最近的质检报告均为满分，无违规记录，继续保持！";
                }
                break;
              }

              // Generate and send improvement cards for each report (up to 3)
              for (const report of reportsWithViolations.slice(0, 3)) {
                const violations = (Array.isArray(report.violations)
                  ? report.violations
                  : []) as Array<{ category: string; rule: string; deduction: number; source_quote?: string }>;

                const suggestions = await generateImprovementSuggestions(violations);
                await sendImprovementCard(
                  chatId,
                  agentName,
                  (report.id as string) || "",
                  violations,
                  suggestions,
                );
              }

              replyCardSent = true;
              commandReply = "";
              break;
            }
            case "personality_switch": {
              const toneInput = intent.params.tone || "";
              // Map Chinese/English input to tone key
              const toneMap: Record<string, string> = {
                "专业": "professional", "正式": "professional", "严谨": "professional", "professional": "professional",
                "亲切": "friendly", "活泼": "friendly", "friendly": "friendly",
                "简洁": "concise", "高效": "concise", "concise": "concise",
              };
              const resolvedTone = toneMap[toneInput] || "professional";
              sessionStyleCache.set(`${chatId}:${senderId}`, resolvedTone);
              const toneLabels: Record<string, string> = { professional: "专业严谨", friendly: "亲切活泼", concise: "简洁高效" };
              commandReply = `✅ 已切换为「${toneLabels[resolvedTone]}」风格`;
              console.log("[Personality] Style switched to", resolvedTone, "for chat", chatId.slice(-12));
              break;
            }
            default: {
              // Check custom commands
              const customCmd = customCommands.find(c => c.action_type === intent.action);
              if (customCmd) {
                if (customCmd.reply_template) {
                  commandReply = customCmd.reply_template.replace(/\{text\}/g, cleanText);
                }
                if (customCmd.api_endpoint) {
                  fetch(customCmd.api_endpoint, {
                    method: customCmd.api_method || "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ text: cleanText, chat_id: chatId, sender_id: senderId }),
                  }).catch(() => { sendFeishuReply(chatId, "❌ 自定义指令执行 暂时无法完成\n\n💡 建议：请稍后重试\n🆘 如持续失败，请联系管理员"); });
                }
                if (!commandReply) {
                  commandReply = `✅ 自定义指令「${customCmd.command_name}」已执行`;
                }
              } else {
                // general_chat or unrecognized — fall through to generateBotReply
                console.log("[Intent] Unrecognized or general_chat, delegating to bot reply");
              }
            }
          }

          // ── Fire-and-forget: track command usage for personalization ──
          trackUsage(supabase, senderId, intent, text);
        }

        // ── Resolve personality injection before generating reply ──
        const userTone = sessionStyleCache.get(`${chatId}:${senderId}`);
        const personalityInjection = userTone ? await getPersonalityInjection(supabase, userTone) : "";

        let reply: string;
        if (replyCardSent) {
          reply = "[报告卡片已发送]";
        } else {
          reply = commandReply || await generateBotReplyWithRAG(supabase, text, effectiveContext, personalityInjection, intent.action);
        }

        // ── Bot config: prepend welcome_message for new sessions ──
        if (!existing && !replyCardSent && botConfig?.welcome_message && !commandReply) {
          reply = botConfig.welcome_message + "\n\n" + reply;
          console.log("[Bot] Welcome message prepended for new session");
        }

        // ── Intent classification transparency: only show when confidence is low ──
        if (isBotMention && intent.method === "llm" && intent.confidence < 0.8 && !reply.includes("🤖 理解:")) {
          const intentLabels: Record<string, string> = {
            quality_report: "质检报告查询", compliance_check: "合规检查", generate_report: "生成报表",
            payment_reminder: "催单提醒", work_orders: "工单查询", knowledge_gaps: "知识缺口",
            bot_suggest: "话术建议", chat_stats: "会话统计", qa_evaluate: "质检评测",
            meeting_pipeline: "会议测试", help: "帮助", general_chat: "通用对话",
            daily_brief: "今日简报", system_health: "系统健康",
            pipeline_retry: "重试管线", pipeline_history: "管线历史",
            export_quality_reports: "导出数据", export_chat_sessions: "导出数据", export_work_orders: "导出数据",
            export_pipeline_jobs: "导出数据", personality_switch: "风格切换",
            quality_improvement: "质检改进",
          };
          const label = intentLabels[intent.action] || intent.action;
          reply = addTransparency(reply, "intent_classification", {
            intentLabel: label,
            confidence: String(Math.round(intent.confidence * 100)) + "%",
            method: "AI语义理解",
          });
        }

        // Update in-memory session cache with this exchange
        saveSessionContext(chatId, senderId, text, reply);

        const emotionResult = detectEmotion(text);

        // ── Proactive angry customer alert (debounced, fire-and-forget) ──
        if (emotionResult.level === "angry") {
          (async () => {
            try {
              // Debounce: max 1 angry alert per chat_id per 30 minutes
              const thirtyMinAgo = new Date(Date.now() - 30 * 60 * 1000).toISOString();
              const { data: recentAlerts } = await supabase
                .from("audit_logs")
                .select("id")
                .eq("action", "angry_customer_alert")
                .eq("resource_type", "bot_chat_sessions")
                .eq("resource_id", chatId)
                .gt("created_at", thirtyMinAgo)
                .limit(1);

              if (recentAlerts && recentAlerts.length > 0) {
                console.log("[Emotion] Angry alert suppressed (debounce active for chatId:", chatId.slice(-12) + ")");
                return;
              }

              // Track in audit_logs
              await supabase.from("audit_logs").insert({
                id: uuidv4(),
                action: "angry_customer_alert",
                resource_type: "bot_chat_sessions",
                resource_id: chatId,
                detail: {
                  emotion_level: "angry",
                  keywords: emotionResult.keywords,
                  text_snippet: text.slice(0, 200),
                },
                created_at: new Date().toISOString(),
              });

              // Send alert card to group or subscribed supervisors
              const alertCard = {
                header: { title: { tag: "plain_text", content: "🚨 客户情绪告警" }, template: "red" },
                elements: [
                  { tag: "div", text: { tag: "lark_md", content: `**检测到愤怒客户**\n\n客户消息: ${text.slice(0, 200)}\n情绪关键词: ${emotionResult.keywords.join("、")}\n\n建议: ${emotionResult.suggestion}` } },
                  { tag: "action", actions: [
                    { tag: "button", text: { tag: "plain_text", content: "📋 创建工单" }, type: "primary", value: JSON.stringify({ action: "create_work_order", session_id: chatId, priority: "high", reason: "angry_customer" }) },
                    { tag: "button", text: { tag: "plain_text", content: "👤 升级主管" }, type: "danger", value: JSON.stringify({ action: "escalate_to_supervisor", session_id: chatId }) },
                  ]},
                ],
              };

              const targets = getAlertTargets();
              await sendAlertToTargets(targets, alertCard);
              console.log("[Emotion] Angry customer alert sent for chatId:", chatId.slice(-12));
            } catch (e) {
              console.error("[Emotion] Angry alert error:", String(e).slice(0, 200));
            }
          })();
        }

        const customerLine = emotionResult.level !== "neutral"
          ? `[客户情绪: ${emotionResult.level}] 顾客: ${text}`
          : `顾客: ${text}`;
        const botLine = `机器人: ${reply}`;

        // Send reply: skip text when report card was already sent
        if (replyCardSent) {
          // Card already sent, no text reply needed
          console.log("[Feishu] Report card sent, skipping text reply");
        } else if (commandReply) {
          sendFeishuReplyWithFeedback(chatId, reply);
        } else {
          const replyWithFeedback = reply + "\n\n———\n👍 有帮助  |  👎 无帮助\n回复「有帮助」或「无帮助」";
          sendFeishuReply(chatId, replyWithFeedback);
        }

        if (existing) {
          const { error: updErr } = await supabase
            .from("bot_chat_sessions")
            .update({
              conversation: `${existing.conversation}\n${customerLine}\n${botLine}`,
              total_messages: (existing.total_messages as number) + 1,
              ...(botConfig ? { bot_id: botConfig.id } : {}),
            })
            .eq("id", existing.id);
          if (updErr) {
            console.error("[Feishu] Update error:", updErr.message, updErr.details);
          } else {
            triggerAutoEvaluation(supabase, chatId, senderId, text, eventId, reply).then((ticketId) => {
              if (ticketId) autoSendImprovementAfterEval(supabase, chatId, senderId, ticketId);
            });
          }
        } else {
          const { error: insErr } = await supabase
            .from("bot_chat_sessions")
            .insert({
              id: uuidv4(),
              platform_id: platformId,
              session_type: "pre_sale",
              external_session_id: chatId,
              customer_id: senderId,
              bot_handled: true,
              is_inquiry: false,
              first_response_ms: 0,
              tags: [],
              conversation: `${customerLine}\n${botLine}`,
              total_messages: 1,
              correlation_id: `feishu_sess_${uuidv4().slice(0, 12)}`,
              ...(botConfig ? { bot_id: botConfig.id } : {}),
            });
          if (insErr) {
            console.error("[Feishu] Insert error:", insErr.message, insErr.details, insErr.hint);
          } else {
            console.log(`[Feishu] ${chatId}: ${customerLine.slice(0, 80)}`);
            triggerAutoEvaluation(supabase, chatId, senderId, text, eventId, reply).then((ticketId) => {
              if (ticketId) autoSendImprovementAfterEval(supabase, chatId, senderId, ticketId);
            });
          }
        }
      }
    } catch (err) {
      console.error("[Feishu] Message processing error:", String(err).slice(0, 200));
      const errChatId = extractChatId(event) || "";
      if (errChatId) {
        sendFeishuReply(errChatId, "❌ 指令处理 暂时无法完成\n\n💡 建议：请稍后重试\n🆘 如持续失败，请联系管理员").catch(() => {});
      }
    }
  }

  // 3d. Audit log
  await supabase
    .from("audit_logs")
    .insert({
      id: uuidv4(),
      action: "feishu_event_receive",
      resource_type: "feishu_raw_events",
      resource_id: eventId,
      detail: {
        event_type: eventType,
        chat_id: extractChatId(event),
        sender_open_id: extractSenderId(event),
      },
      correlation_id: correlationId,
      created_at: new Date().toISOString(),
    });

  // ── Proactive alert check (fire-and-forget, <2s timeout, non-blocking) ──
  Promise.race([
    checkProactiveAlerts(supabase),
    new Promise<void>((r) => setTimeout(r, 2000)),
  ]).catch((e) => console.error("[Proactive] Alert check failed:", String(e).slice(0, 100)));

  // ── HITL timeout card auto-update (fire-and-forget) ──
  checkHitlTimeouts(supabase).catch((e) => console.error("[HITL] Timeout check failed:", String(e).slice(0, 100)));

  // ── Silent session check (fire-and-forget, <2s timeout, non-blocking) ──
  Promise.race([
    checkSilentSessions(supabase),
    new Promise<void>((r) => setTimeout(r, 2000)),
  ]).catch((e) => console.error("[SilentSession] Check failed:", String(e).slice(0, 100)));

  return new Response(JSON.stringify({ code: 0 }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
  } catch (err) {
    const errorMsg = String(err).slice(0, 500);
    console.error("[Feishu] UNHANDLED ERROR:", errorMsg);
    handleSystemAlert("Edge Function 未捕获异常", { error: errorMsg, timestamp: new Date().toISOString() })
      .catch(e => console.error("[Feishu] Alert send failed:", String(e)));
    try {
      const errSupabase = createClient(
        Deno.env.get("SUPABASE_URL") || "",
        Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "",
      );
      await errSupabase.from("audit_logs").insert({
        id: uuidv4(),
        action: "system_error",
        resource_type: "edge_function",
        resource_id: "feishu-event",
        detail: { error: errorMsg, timestamp: new Date().toISOString() },
        created_at: new Date().toISOString(),
      });
    } catch (auditErr) {
      console.error("[Feishu] Failed to write system_error audit:", String(auditErr));
    }
    return new Response(JSON.stringify({ code: 0 }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }
});
