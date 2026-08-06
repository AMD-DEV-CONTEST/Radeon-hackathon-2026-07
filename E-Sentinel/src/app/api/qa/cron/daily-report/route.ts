import { NextResponse } from "next/server";
import { requireApiKey } from "@/lib/api-auth";
import { supabaseAdmin } from "@/lib/supabase";
import { callLLM } from "@/lib/llm-provider";
import { logAudit, logLlmCall } from "@/lib/audit";
import { sendFeishuGroupCard } from "@/lib/feishu";
import { reportCronFailure } from "@/lib/cron-health";

interface DailySession {
  satisfaction: string | null;
  inquiry_result: string | null;
  transfer_reason: string | null;
}

export async function GET(request: Request) {
  const auth = requireApiKey(request);
  if (auth.error) return auth.error;

  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ status: "failed", success: false, error: "Supabase not configured" }, { status: 500 });
    }

    const today = new Date().toISOString().slice(0, 10);
    const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);

    // Check if already generated today
    const { data: existing } = await supabaseAdmin
      .from("robot_reports")
      .select("id")
      .eq("report_type", "daily")
      .eq("period_start", today)
      .maybeSingle();

    if (existing) {
      return NextResponse.json({ status: "ok", success: true, message: "Daily report already generated", report_id: existing.id });
    }

    // Gather metrics
    const [{ data: stats }, { data: sessions }] = await Promise.all([
      supabaseAdmin.rpc("get_chat_stats_for_date", { target_date: yesterday }).maybeSingle(),
      supabaseAdmin.from("bot_chat_sessions")
        .select("satisfaction, inquiry_result, transfer_reason")
        .gte("created_at", yesterday)
        .lt("created_at", today)
        .limit(200),
    ]);

    const totalSessions = sessions?.length || 0;
    const dailySessions = (sessions || []) as DailySession[];
    const badCount = dailySessions.filter((s) => s.satisfaction === "bad").length;
    const lostCount = dailySessions.filter((s) => s.inquiry_result === "lost").length;
    const transferCount = dailySessions.filter((s) => s.transfer_reason).length;

    // Generate report via LLM
    const t0 = Date.now();
    const { content, model, cached } = await callLLM({
      messages: [
        {
          role: "system",
          content: `你是电商客服机器人运营分析师。请根据数据生成一份结构化的日报（Markdown格式）。

输出格式：
# 日报 · ${yesterday}

## 概览
- 总会话数、差评率、流失率、转人工率

## 关键发现
- 3-5 条重要的数据洞察

## 优化建议
- 3 条具体的优化行动项

## 风险提示
- 需要关注的风险点（如有）`,
        },
        {
          role: "user",
          content: `日期: ${yesterday}\n总会话: ${totalSessions}\n差评: ${badCount} (${totalSessions ? ((badCount/totalSessions)*100).toFixed(1) : 0}%)\n流失: ${lostCount} (${totalSessions ? ((lostCount/totalSessions)*100).toFixed(1) : 0}%)\n转人工: ${transferCount} (${totalSessions ? ((transferCount/totalSessions)*100).toFixed(1) : 0}%)\n${JSON.stringify(stats || {})}`,
        },
      ],
      max_tokens: 2048,
    });

    const latency = Date.now() - t0;

    // Save report
    const { data: report } = await supabaseAdmin
      .from("robot_reports")
      .insert({
        report_type: "daily",
        period_start: yesterday,
        period_end: today,
        summary_md: content,
        metrics: { total_sessions: totalSessions, bad_rate: badCount / Math.max(1, totalSessions), loss_rate: lostCount / Math.max(1, totalSessions), transfer_rate: transferCount / Math.max(1, totalSessions) },
        generated_by: "cron",
      })
      .select("id")
      .single();

    await logAudit({
      action: "report_generate",
      resource_type: "robot_reports",
      resource_id: report?.id,
      detail: { report_type: "daily", period: yesterday },
    });

    await logLlmCall({
      model,
      prompt_type: "daily_report",
      latency_ms: latency,
      cached,
      correlation_id: report?.id || "unknown",
    });

    // Push summary card to Feishu group
    const badRate = totalSessions ? ((badCount / totalSessions) * 100).toFixed(1) : "0";
    const lossRate = totalSessions ? ((lostCount / totalSessions) * 100).toFixed(1) : "0";
    sendFeishuGroupCard({
      header: { title: { tag: "plain_text", content: `📊 客服日报 · ${yesterday}` }, template: "blue" },
      elements: [
        { tag: "div", text: { tag: "lark_md", content: `**总会话：** ${totalSessions} | **差评率：** ${badRate}% | **流失率：** ${lossRate}%\n**转人工：** ${transferCount} 次\n\n${content?.substring(0, 500) || ""}` } },
        { tag: "hr" },
        { tag: "action", actions: [{
          tag: "button", text: { tag: "plain_text", content: "📋 查看完整报告" }, type: "primary",
          url: `${process.env.NEXT_PUBLIC_APP_URL || "https://qa-system-pied.vercel.app"}/dashboard`,
        }]},
      ],
    }).catch(() => {});

    return NextResponse.json({
      status: "ok",
      success: true,
      report_id: report?.id,
      model,
      cached,
      latency_ms: latency,
    });
  } catch (error) {
    console.error("[Cron] Daily report error:", error);
    await reportCronFailure("daily-report", error);
    return NextResponse.json({ status: "failed", success: false, error: String(error) }, { status: 500 });
  }
}
