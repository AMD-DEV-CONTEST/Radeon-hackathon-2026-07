// ============================================================================
// Cron: Capture Unresolved Questions
// 自动从 bot_chat_sessions 中捕获AI未处理/满意度低的会话，
// 记录到 unresolved_questions 表，并推送飞书通知
// ============================================================================

import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { sendFeishuNotification } from "@/lib/feishu";
import { logAudit } from "@/lib/audit";
import { createCorrelationId } from "@/lib/correlation";
import { requireApiKey } from "@/lib/api-auth";
import { reportCronFailure } from "@/lib/cron-health";

export async function GET(request: Request) {
  const auth = requireApiKey(request);
  if (auth.error) return auth.error;

  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ status: "failed", success: false, error: "Supabase not configured" }, { status: 500 });
    }

    // ── 1. 查询最近24小时 bot 未处理或满意度低的会话 ──
    const since = new Date(Date.now() - 86400000).toISOString();
    const { data: sessions, error: sessErr } = await supabaseAdmin
      .from("bot_chat_sessions")
      .select("id, platform_id, session_type, external_session_id, customer_id, bot_handled, transfer_reason, satisfaction, conversation")
      .or("bot_handled.eq.false,satisfaction.eq.bad,satisfaction.eq.neutral")
      .gte("created_at", since)
      .limit(100);

    if (sessErr) throw sessErr;
    if (!sessions || sessions.length === 0) {
      return NextResponse.json({ status: "ok", success: true, captured: 0, message: "No unresolved sessions found" });
    }

    // ── 2. 提取用户问题并去重 ──
    const correlationId = createCorrelationId("capture");
    const entries: Array<Record<string, unknown>> = [];

    for (const s of sessions as Array<Record<string, unknown>>) {
      const conv = String(s.conversation || "");
      if (!conv) continue;

      // 提取第一条用户消息作为 user_question
      const lines = conv.split("\n");
      let userQuestion = "";
      let aiReply = "";
      let foundUser = false;
      let foundAI = false;

      for (const line of lines) {
        const um = line.match(/^(?:用户|顾客|Customer|买家)[：:]\s*(.+)/i);
        if (um && !foundUser) {
          userQuestion = um[1].trim().slice(0, 500);
          foundUser = true;
          continue;
        }
        const am = line.match(/^(?:客服|机器人|Bot|AI)[：:]\s*(.+)/i);
        if (am && foundUser && !foundAI) {
          aiReply = am[1].trim().slice(0, 500);
          foundAI = true;
        }
      }

      if (!userQuestion) continue;

      entries.push({
        session_id: String(s.external_session_id || s.id),
        platform_id: s.platform_id || null,
        user_question: userQuestion,
        ai_reply: aiReply || null,
        transfer_reason: s.transfer_reason || null,
        satisfaction: s.satisfaction || null,
        conversation: conv.slice(0, 2000),
        correlation_id: correlationId,
        status: "pending",
      });
    }

    if (entries.length === 0) {
      return NextResponse.json({ status: "degraded", success: true, captured: 0, message: "Failed to extract user questions" });
    }

    // ── 3. 批量写入（跳过已存在的 session_id） ──
    const { data: existing } = await supabaseAdmin
      .from("unresolved_questions")
      .select("session_id")
      .in("session_id", entries.map((e) => String(e.session_id)))
      .limit(entries.length);

    const existingIds = new Set((existing || []).map((e: Record<string, string>) => e.session_id));
    const toInsert = entries.filter((e) => !existingIds.has(String(e.session_id)));

    if (toInsert.length === 0) {
      return NextResponse.json({ status: "ok", success: true, captured: 0, duplicate_skipped: entries.length });
    }

    const { data: inserted, error: insertErr } = await supabaseAdmin
      .from("unresolved_questions")
      .insert(toInsert)
      .select("id");

    if (insertErr) throw insertErr;

    const capturedCount = (inserted || []).length;

    // ── 4. 写操作日志 ──
    for (const row of inserted || []) {
      await supabaseAdmin.from("unresolved_question_logs").insert({
        unresolved_id: (row as Record<string, unknown>).id,
        action: "create",
        detail: { source: "cron_capture" },
      });
    }

    // ── 5. 飞书推送（如果有新记录） ──
    if (capturedCount > 0) {
      const statusBreakdown: Record<string, number> = { bad: 0, neutral: 0, unhandled: 0 };
      for (const e of toInsert) {
        if (e.satisfaction === "bad") statusBreakdown.bad++;
        else if (e.satisfaction === "neutral") statusBreakdown.neutral++;
        else statusBreakdown.unhandled++;
      }

      const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || process.env.VERCEL_URL || "https://qa-system-pied.vercel.app";

      sendFeishuNotification({
        header: {
          title: { tag: "plain_text", content: `🤖 AI未解决问题汇总 — ${capturedCount} 条新记录` },
          template: "orange",
        },
        elements: [
          {
            tag: "div",
            text: {
              tag: "lark_md",
              content: `**捕获时段**: 过去 24 小时\n**新记录**: ${capturedCount} 条（去重跳过 ${entries.length - toInsert.length} 条）\n\n**数据分布**:\n- 😰 满意度"差": ${statusBreakdown.bad} 条\n- 😐 满意度"一般": ${statusBreakdown.neutral} 条\n- 🤷 AI未处理: ${statusBreakdown.unhandled} 条`,
            },
          },
          {
            tag: "action",
            actions: [
              {
                tag: "button",
                text: { tag: "plain_text", content: "📋 查看并处理" },
                type: "primary",
                url: `${SITE_URL}/dashboard?panel=unresolved`,
              },
              {
                tag: "button",
                text: { tag: "plain_text", content: "📤 导出训练数据" },
                type: "default",
                url: `${SITE_URL}/api/qa/unresolved/export?format=json`,
              },
            ],
          },
        ],
      }).catch(() => {});
    }

    await logAudit({
      action: "unresolved_questions_capture",
      resource_type: "unresolved_questions",
      detail: {
        sessions_scanned: sessions.length,
        collected: toInsert.length,
        duplicate_skipped: entries.length - toInsert.length,
      },
      correlation_id: correlationId,
    });

    return NextResponse.json({
      status: "ok",
      success: true,
      captured: capturedCount,
      duplicate_skipped: entries.length - toInsert.length,
      total_scanned: sessions.length,
    });
  } catch (error) {
    console.error("[CaptureUnresolved] Error:", error);
    await reportCronFailure("capture-unresolved", error);
    return NextResponse.json({ status: "failed", success: false, error: String(error) }, { status: 500 });
  }
}
