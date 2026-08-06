// ============================================================================
// Feishu helpers with Dify-safe disable
// For Dify deployment: set DIFY_MODE=true or DISABLE_FEISHU_ALERTS=true
// All send* functions become no-op; evaluate/compliance keep returning
// correlation_id + final_note (with composer for low-conf) + source_quote
// for answerability and full traceability without external alerts.
// ============================================================================

const FEISHU_APP_ID = process.env.FEISHU_APP_ID || "";
const FEISHU_APP_SECRET = process.env.FEISHU_APP_SECRET || "";
const FEISHU_GROUP_CHAT_ID = process.env.FEISHU_GROUP_CHAT_ID || "";
const FEISHU_WEBHOOK_URL = process.env.FEISHU_WEBHOOK_URL || "";

// Dify 部署或稳定使用专用：显式关闭所有飞书告警（用户要求在 Dify 场景只需稳定使用，不需要飞书通知）
// 优先级：DIFY_MODE 或 DISABLE_FEISHU_ALERTS > FEISHU_ALERTS_ENABLED=false
const FEISHU_ENABLED =
  process.env.DIFY_MODE !== "true" &&
  process.env.DISABLE_FEISHU_ALERTS !== "true" &&
  (process.env.FEISHU_ALERTS_ENABLED ?? "true").toLowerCase() !== "false";

export function isFeishuEnabled(): boolean {
  return FEISHU_ENABLED;
}

interface FeishuCardParams {
  reportId: string;
  ticketId: string;
  agentName: string;
  totalScore: number;
  riskLevel: string;
  sentimentScore: number;
  violations: Array<{
    category: string;
    rule: string;
    deduction: number;
    source_quote: string;
  }>;
  correlationId: string;
}

async function getTenantToken(): Promise<string | null> {
  if (!FEISHU_ENABLED || !FEISHU_APP_ID || !FEISHU_APP_SECRET) return null;
  const res = await fetch(
    "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ app_id: FEISHU_APP_ID, app_secret: FEISHU_APP_SECRET }),
    }
  );
  const data = await res.json();
  return data.tenant_access_token || null;
}

/**
 * Shared 4-level fallback routing for interactive cards.
 * Route 1: Private message → Route 2: Personal webhook → Route 3: Group chat → Route 4: Global webhook
 */
async function routeWithFallback(
  card: Record<string, unknown>,
  reviewerFeishuOpenId?: string | null,
  reviewerWebhookUrl?: string | null,
  label: string = "Notification",
): Promise<{ method: string; target: string | null }> {
  if (!FEISHU_ENABLED) {
    return { method: "disabled", target: null };
  }
  const token = await getTenantToken();

  // Route 1: Private message
  if (token && reviewerFeishuOpenId) {
    try {
      const res = await fetch("https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ receive_id: reviewerFeishuOpenId, msg_type: "interactive", content: JSON.stringify(card) }),
      });
      if (res.ok) { console.log(`[Feishu] ${label} private → ${reviewerFeishuOpenId}`); return { method: "private", target: reviewerFeishuOpenId }; }
      console.warn(`[Feishu] ${label} private failed:`, await res.text().catch(() => ""));
    } catch (err: any) { console.warn(`[Feishu] ${label} private error:`, err.message); }
  }

  // Route 2: Personal webhook
  if (reviewerWebhookUrl) {
    try {
      const res = await fetch(reviewerWebhookUrl, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ msg_type: "interactive", card }),
      });
      if (res.ok) return { method: "personal_webhook", target: "reviewer" };
    } catch (err: any) { console.warn(`[Feishu] ${label} webhook error:`, err.message); }
  }

  // Route 3: Global group chat
  if (token && FEISHU_GROUP_CHAT_ID) {
    try {
      const res = await fetch("https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ receive_id: FEISHU_GROUP_CHAT_ID, msg_type: "interactive", content: JSON.stringify(card) }),
      });
      if (res.ok) return { method: "group_chat", target: FEISHU_GROUP_CHAT_ID };
    } catch (err: any) { console.warn(`[Feishu] ${label} group chat error:`, err.message); }
  }

  // Route 4: Global webhook
  if (FEISHU_WEBHOOK_URL) {
    try {
      const res = await fetch(FEISHU_WEBHOOK_URL, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ msg_type: "interactive", card }),
      });
      if (res.ok) return { method: "global_webhook", target: "global" };
    } catch (err: any) { console.warn(`[Feishu] ${label} global webhook error:`, err.message); }
  }

  return { method: "none", target: null };
}

function buildAlertCard(params: FeishuCardParams) {
  const riskEmoji =
    params.riskLevel === "critical" ? "🔴" : params.riskLevel === "high" ? "🟠" : "🟡";

  const violationsMd = params.violations
    .map(
      (v, i) =>
        `${i + 1}. **${v.category}** [-${v.deduction}分] ${v.rule}\n> ${v.source_quote}`
    )
    .join("\n\n");

  return {
    config: { wide_screen_mode: true },
    header: {
      template: params.riskLevel === "critical" ? "red" : "orange",
      title: {
        tag: "plain_text",
        content: `${riskEmoji} 质检预警 | ${params.agentName} | ${params.totalScore}分`,
      },
    },
    elements: [
      {
        tag: "div",
        text: {
          tag: "lark_md",
          content: [
            `**工单号：** ${params.ticketId}`,
            `**风险等级：** ${params.riskLevel.toUpperCase()}`,
            `**客户情绪：** ${"★".repeat(params.sentimentScore)}${"☆".repeat(5 - params.sentimentScore)}`,
            `**违规项：** ${params.violations.length} 条`,
            "",
            violationsMd,
            "",
            `> 追踪ID: ${params.correlationId}`,
          ].join("\n"),
        },
      },
      { tag: "hr" },
      {
        tag: "action",
        actions: [
          {
            tag: "button",
            text: { tag: "plain_text", content: "📋 查看详情" },
            type: "primary",
            url: `${process.env.NEXT_PUBLIC_APP_URL || "http://localhost:3001"}/reports/${params.reportId}`,
          },
          {
            tag: "button",
            text: { tag: "plain_text", content: "❌ 误判驳回" },
            type: "danger",
            value: { action: "overturn", report_id: params.reportId },
          },
        ],
      },
    ],
  };
}

/**
 * 飞书四级降级派发 — 质检预警专用，构建 alert card 后走统一路由。
 */
export async function dispatchAlert(
  params: FeishuCardParams,
  reviewerFeishuOpenId?: string | null,
  reviewerWebhookUrl?: string | null
): Promise<{ method: string; target: string | null }> {
  const card = buildAlertCard(params);
  return routeWithFallback(card, reviewerFeishuOpenId, reviewerWebhookUrl, "Alert");
}

/**
 * Send an interactive card to the configured Feishu group chat.
 * Used for audit cards (compliance, shadow approval) with action buttons.
 */
export async function sendFeishuGroupCard(card: Record<string, unknown>): Promise<string | null> {
  if (!FEISHU_ENABLED || !FEISHU_GROUP_CHAT_ID) return null;
  const token = await getTenantToken();
  if (!token) return null;
  try {
    const res = await fetch(
      `https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id`,
      {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({
          receive_id: FEISHU_GROUP_CHAT_ID,
          msg_type: "interactive",
          content: JSON.stringify({ config: { wide_screen_mode: true }, ...card }),
        }),
      },
    );
    const data = await res.json() as { code?: number; msg?: string; data?: { message_id?: string } };
    if (res.ok && data.code === 0) {
      console.log(`[Feishu] Group card sent, msg_id=${data.data?.message_id}`);
      return data.data?.message_id || null;
    }
    console.warn("[Feishu] Group card send failed:", data.msg, "code:", data.code, "http:", res.status);
    throw new Error(`Feishu card send failed: ${data.msg || 'unknown'} (code: ${data.code}, http: ${res.status})`);
  } catch (e) {
    console.error("[Feishu] Group card send error:", String(e));
    return null;
  }
}

/**
 * Send a text message to a Feishu chat or user.
 * Uses the Feishu Open API; requires FEISHU_APP_ID + FEISHU_APP_SECRET.
 * Falls back to FEISHU_WEBHOOK_URL if tenant token unavailable.
 */
export async function sendFeishuMessage(params: {
  receive_id: string;
  receive_id_type?: "chat_id" | "open_id" | "user_id";
  content: string;
  msg_type?: "text" | "interactive";
}): Promise<{ success: boolean; method: string }> {
  const { receive_id, receive_id_type = "chat_id", content, msg_type = "text" } = params;

  if (!FEISHU_ENABLED) {
    return { success: false, method: "disabled" };
  }

  const token = await getTenantToken();

  // Route 1: Feishu Open API (preferred)
  if (token) {
    try {
      const res = await fetch(
        `https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=${receive_id_type}`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            receive_id,
            msg_type,
            content: msg_type === "text"
              ? JSON.stringify({ text: content })
              : content,
          }),
        },
      );
      const data = await res.json().catch(() => ({}));
      if (res.ok && (data as Record<string, unknown>).code === 0) {
        console.log(`[Feishu] Message sent to ${receive_id_type}=${receive_id}`);
        return { success: true, method: "api" };
      }
      console.warn("[Feishu] Send message API error:", JSON.stringify(data).slice(0, 200));
    } catch (err) {
      console.warn("[Feishu] Send message fetch error:", String(err).slice(0, 100));
    }
  }

  // Route 2: Global webhook fallback
  if (FEISHU_WEBHOOK_URL) {
    try {
      const res = await fetch(FEISHU_WEBHOOK_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          msg_type: "interactive",
          card: {
            header: {
              template: "blue",
              title: { tag: "plain_text", content: "机器人回复" },
            },
            elements: [
              {
                tag: "div",
                text: { tag: "lark_md", content },
              },
            ],
          },
        }),
      });
      if (res.ok) return { success: true, method: "webhook" };
    } catch (err) {
      console.warn("[Feishu] Webhook fallback error:", String(err).slice(0, 100));
    }
  }

  return { success: false, method: "none" };
}

/**
 * Send a Feishu interactive card notification with 4-level fallback routing.
 *
 * General-purpose counterpart to dispatchAlert() — accepts a pre-built card object.
 * Used for: knowledge drafts, bot config drafts, compliance alerts, intent accuracy alerts.
 */
export async function sendFeishuNotification(
  card: Record<string, unknown>,
  reviewerFeishuOpenId?: string | null,
  reviewerWebhookUrl?: string | null,
): Promise<{ method: string; target: string | null }> {
  return routeWithFallback(card, reviewerFeishuOpenId, reviewerWebhookUrl, "Notification");
}
