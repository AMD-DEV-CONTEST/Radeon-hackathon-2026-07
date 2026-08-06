import { NextResponse } from "next/server";
import { guardPublic } from "@/lib/api-auth";
import { sendFeishuGroupCard, isFeishuEnabled } from "@/lib/feishu";

type CardType = "quality_report" | "chat_stats" | "work_orders" | "custom";

function buildQualityReportCard(data: Record<string, unknown>) {
  const score = (data.score as number) ?? 0;
  const violations = (data.violations as number) ?? 0;
  const riskLevel = (data.risk_level as string) ?? "low";
  const snippet = (data.session_snippet as string) ?? "";
  const agentName = (data.agent_name as string) ?? "未知";
  const ticketId = (data.ticket_id as string) ?? "—";
  const riskEmoji =
    riskLevel === "critical" ? "🔴" : riskLevel === "high" ? "🟠" : "🟡";

  return {
    header: {
      template: riskLevel === "critical" ? "red" : "orange",
      title: {
        tag: "plain_text" as const,
        content: `${riskEmoji} 质检报告 | ${agentName} | ${score}分`,
      },
    },
    elements: [
      {
        tag: "div",
        text: {
          tag: "lark_md" as const,
          content: [
            `**工单号：** ${ticketId}`,
            `**得分：** ${score}/100`,
            `**风险等级：** ${riskLevel.toUpperCase()}`,
            `**违规项：** ${violations} 条`,
            snippet ? `\n> ${snippet}` : "",
          ]
            .filter(Boolean)
            .join("\n"),
        },
      },
      { tag: "hr" as const },
      {
        tag: "action",
        actions: [
          {
            tag: "button",
            text: { tag: "plain_text" as const, content: "📋 查看详情" },
            type: "primary",
            url: `${process.env.NEXT_PUBLIC_APP_URL || "http://localhost:3001"}/dashboard`,
          },
        ],
      },
    ],
  };
}

function buildChatStatsCard(data: Record<string, unknown>) {
  const total = (data.total_sessions as number) ?? 0;
  const today = (data.today_sessions as number) ?? 0;
  const avgScore = (data.avg_score as number) ?? 0;
  const botHandledRate = (data.bot_handled_rate as number) ?? 0;

  return {
    header: {
      template: "blue" as const,
      title: {
        tag: "plain_text" as const,
        content: `📊 聊天监控统计`,
      },
    },
    elements: [
      {
        tag: "div",
        text: {
          tag: "lark_md" as const,
          content: [
            `**总会话数：** ${total}`,
            `**今日会话：** ${today}`,
            `**平均情绪值：** ${avgScore}`,
            `**机器人处理率：** ${botHandledRate}%`,
          ].join("\n"),
        },
      },
      { tag: "hr" as const },
      {
        tag: "action",
        actions: [
          {
            tag: "button",
            text: { tag: "plain_text" as const, content: "📋 查看详情" },
            type: "primary",
            url: `${process.env.NEXT_PUBLIC_APP_URL || "http://localhost:3001"}/dashboard`,
          },
        ],
      },
    ],
  };
}

function buildWorkOrdersCard(data: Record<string, unknown>) {
  const orders = (data.orders as Array<{ title: string; priority: string; status: string }>) ?? [];
  const total = (data.total as number) ?? orders.length;
  const openCount = (data.open_count as number) ?? 0;

  const ordersMd = orders
    .slice(0, 10)
    .map(
      (o, i) =>
        `${i + 1}. [${o.priority}] ${o.title} — ${o.status}`
    )
    .join("\n");

  return {
    header: {
      template: "turquoise" as const,
      title: {
        tag: "plain_text" as const,
        content: `📋 工单概览 | 共 ${total} 条`,
      },
    },
    elements: [
      {
        tag: "div",
        text: {
          tag: "lark_md" as const,
          content: [
            `**待处理：** ${openCount} 条`,
            orders.length > 0 ? `\n**最近工单：**\n${ordersMd}` : "",
          ]
            .filter(Boolean)
            .join("\n"),
        },
      },
      { tag: "hr" as const },
      {
        tag: "action",
        actions: [
          {
            tag: "button",
            text: { tag: "plain_text" as const, content: "📋 查看详情" },
            type: "primary",
            url: `${process.env.NEXT_PUBLIC_APP_URL || "http://localhost:3001"}/dashboard`,
          },
        ],
      },
    ],
  };
}

export async function POST(request: Request) {
  const guardErr = guardPublic(request, {});
  if (guardErr) return guardErr;

  try {
    const body = await request.json().catch(() => ({}));
    const cardType: CardType = body.card_type ?? "custom";
    const cardData: Record<string, unknown> = body.card_data ?? {};

    let card: Record<string, unknown>;

    switch (cardType) {
      case "quality_report":
        card = buildQualityReportCard(cardData);
        break;
      case "chat_stats":
        card = buildChatStatsCard(cardData);
        break;
      case "work_orders":
        card = buildWorkOrdersCard(cardData);
        break;
      case "custom":
      default:
        card = cardData;
        break;
    }

    if (!isFeishuEnabled()) {
      return NextResponse.json({ success: true, messageId: null, disabled: "Dify mode or Feishu alerts disabled" });
    }

    console.log("[ShareCard] Sending card:", { cardType, hasGroupId: !!process.env.FEISHU_GROUP_CHAT_ID, hasAppId: !!process.env.FEISHU_APP_ID });
    const messageId = await sendFeishuGroupCard(card);
    console.log("[ShareCard] Result:", { messageId: messageId || "null" });

    if (!messageId) {
      return NextResponse.json(
        { success: false, error: "Failed to send card to Feishu group", debug: { hasGroupId: !!process.env.FEISHU_GROUP_CHAT_ID, hasAppId: !!process.env.FEISHU_APP_ID, hasAppSecret: !!process.env.FEISHU_APP_SECRET } },
        { status: 502 }
      );
    }

    return NextResponse.json({ success: true, message_id: messageId });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[ShareCard] Error:", error instanceof Error ? error.stack : message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
