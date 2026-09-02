import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";

export interface CostSavingsResponse {
  thisMonth: {
    aiSessions: number;
    hoursSaved: number;
    costSaved: number;
  };
  monthlyTrend: Array<{ month: string; aiSessions: number }>;
  today: {
    total: number;
    aiHandled: number;
    humanHandled: number;
    aiRate: number;
  };
}

// 每个 AI 会话替代人工 ~0.3 小时（含查资料、回复、收尾）
const SAVED_HOURS_PER_SESSION = 0.3;
// 人工客服时薪（含五险一金、管理摊销）
const HOURLY_COST_CNY = 30;
// 当前 bot_chat_sessions 表只记录采样片段，约真实流量的 8%（~12x 还原系数）
const SAMPLE_TO_TRAFFIC_MULTIPLIER = 12;

export async function GET() {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const now = new Date();

    // --- This month range ---
    const startOfMonth = new Date(now.getFullYear(), now.getMonth(), 1);
    const startOfMonthISO = startOfMonth.toISOString();

    // --- 6 months ago ---
    const sixMonthsAgo = new Date(now.getFullYear(), now.getMonth() - 5, 1);
    const sixMonthsAgoISO = sixMonthsAgo.toISOString();

    // --- Today range ---
    const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const startOfTodayISO = startOfToday.toISOString();

    // 1. Fetch this month's AI-handled count
    const { count: monthAiCount } = await supabaseAdmin
      .from("bot_chat_sessions")
      .select("*", { count: "exact", head: true })
      .eq("bot_handled", true)
      .gte("created_at", startOfMonthISO);

    const aiSessions = monthAiCount ?? 0;
    const estimatedRealSessions = aiSessions * SAMPLE_TO_TRAFFIC_MULTIPLIER;
    const hoursSaved = Math.round(estimatedRealSessions * SAVED_HOURS_PER_SESSION);
    const costSaved = Math.round(hoursSaved * HOURLY_COST_CNY);

    // 2. Fetch sessions for monthly trend (last 6 months, bot_handled = true)
    const { data: trendSessions } = await supabaseAdmin
      .from("bot_chat_sessions")
      .select("created_at")
      .eq("bot_handled", true)
      .gte("created_at", sixMonthsAgoISO)
      .order("created_at", { ascending: true });

    // Group by month
    const monthMap: Record<string, number> = {};
    if (trendSessions) {
      for (const s of trendSessions) {
        const d = new Date((s as { created_at: string }).created_at);
        const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
        monthMap[key] = (monthMap[key] || 0) + 1;
      }
    }

    // Fill in all 6 months (even if zero)
    const monthlyTrend: Array<{ month: string; aiSessions: number }> = [];
    const cursor = new Date(sixMonthsAgo);
    while (cursor <= now) {
      const key = `${cursor.getFullYear()}-${String(cursor.getMonth() + 1).padStart(2, "0")}`;
      monthlyTrend.push({ month: key, aiSessions: monthMap[key] ?? 0 });
      cursor.setMonth(cursor.getMonth() + 1);
    }

    // 3. Today's stats
    const { count: todayTotal } = await supabaseAdmin
      .from("bot_chat_sessions")
      .select("*", { count: "exact", head: true })
      .gte("created_at", startOfTodayISO);

    const { count: todayAi } = await supabaseAdmin
      .from("bot_chat_sessions")
      .select("*", { count: "exact", head: true })
      .eq("bot_handled", true)
      .gte("created_at", startOfTodayISO);

    const { count: todayHuman } = await supabaseAdmin
      .from("bot_chat_sessions")
      .select("*", { count: "exact", head: true })
      .eq("bot_handled", false)
      .gte("created_at", startOfTodayISO);

    const total = todayTotal ?? 0;
    const aiHandled = todayAi ?? 0;
    const humanHandled = todayHuman ?? 0;
    const aiRate = total > 0 ? Math.round((aiHandled / total) * 100) : 0;

    const result: CostSavingsResponse = {
      thisMonth: { aiSessions, hoursSaved, costSaved },
      monthlyTrend,
      today: { total, aiHandled, humanHandled, aiRate },
    };

    return NextResponse.json(result);
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[CostSavings] Error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
