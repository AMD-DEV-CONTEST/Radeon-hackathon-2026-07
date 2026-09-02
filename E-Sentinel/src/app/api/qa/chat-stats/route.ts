import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import type { ChatStats } from "@/lib/types/bot";
import { getPublicErrorMessage, toUtcRangeEnd } from "@/lib/api-error";

export async function GET(request: Request) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { searchParams } = new URL(request.url);
    const platformId = searchParams.get("platform_id");
    const dateFrom = searchParams.get("date_from");
    const dateTo = searchParams.get("date_to");

    let query = supabaseAdmin.from("bot_chat_sessions").select("*", { count: "exact" });
    if (platformId) query = query.eq("platform_id", platformId);
    if (dateFrom) query = query.gte("created_at", dateFrom);
    if (dateTo) query = query.lte("created_at", toUtcRangeEnd(dateTo));

    const { data: sessions, count } = await query;

    if (!sessions || sessions.length === 0) {
      return NextResponse.json({
        total_sessions: 0, bot_handled_rate: 0, independent_reception_rate: 0, avg_sentiment: 0,
        satisfaction_distribution: { good: 0, neutral: 0, bad: 0 },
        transfer_rate: 0,
        top_issue_categories: [],
        pending_review_count: 0,
        pending_breakdown: { bad: 0, lost: 0, high_risk: 0 },
      } satisfies ChatStats);
    }

    const total = count || sessions.length;
    const botHandled = sessions.filter((s: any) => s.bot_handled).length;
    const sentiments = sessions.filter((s: any) => s.sentiment_score != null);
    const avgSentiment = sentiments.length > 0
      ? sentiments.reduce((sum: number, s: any) => sum + s.sentiment_score, 0) / sentiments.length
      : 0;

    const goodCount = sessions.filter((s: any) => s.satisfaction === "good").length;
    const neutralCount = sessions.filter((s: any) => s.satisfaction === "neutral").length;
    const badCount = sessions.filter((s: any) => s.satisfaction === "bad").length;

    const transfers = sessions.filter((s: any) => !s.bot_handled);
    const transferReasons: Record<string, number> = {};
    for (const t of transfers) {
      const reason = t.transfer_reason || "未记录";
      transferReasons[reason] = (transferReasons[reason] || 0) + 1;
    }
    const topIssues = Object.entries(transferReasons)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 10)
      .map(([category, cnt]) => ({ category, count: cnt }));

    // Pending review: bad satisfaction + lost inquiry + high risk (low sentiment)
    const pendingBad = sessions.filter((s: any) => s.satisfaction === "bad").length;
    const pendingLost = sessions.filter((s: any) => s.inquiry_result === "lost").length;
    const pendingHighRisk = sessions.filter((s: any) =>
      s.sentiment_score != null && s.sentiment_score < 2.5
    ).length;

    return NextResponse.json({
      total_sessions: total,
      bot_handled_rate: total > 0 ? (botHandled / total) : 0,
      independent_reception_rate: total > 0 ? (botHandled / total) : 0, // deprecated — same as bot_handled_rate, kept for PlatformManagementPanel compat
      avg_sentiment: Math.round(avgSentiment * 100) / 100,
      satisfaction_distribution: { good: goodCount, neutral: neutralCount, bad: badCount },
      transfer_rate: total > 0 ? ((total - botHandled) / total) : 0,
      top_issue_categories: topIssues,
      pending_review_count: pendingBad + pendingLost + pendingHighRisk,
      pending_breakdown: { bad: pendingBad, lost: pendingLost, high_risk: pendingHighRisk },
    } satisfies ChatStats);
  } catch (error) {
    const message = getPublicErrorMessage(error, "加载聊天统计失败");
    console.error("[ChatStats] Error:", message, "| typeof:", typeof error);
    return NextResponse.json({ error: message || "internal_error" }, { status: 500 });
  }
}
