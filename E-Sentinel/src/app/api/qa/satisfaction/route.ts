import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";

export async function GET(request: Request) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { searchParams } = new URL(request.url);
    const platformId = searchParams.get("platform_id");
    const sessionType = searchParams.get("session_type");
    const dateFrom = searchParams.get("date_from");
    const dateTo = searchParams.get("date_to");

    let query = supabaseAdmin
      .from("bot_chat_sessions")
      .select("*")
      .not("satisfaction", "is", null);

    if (platformId) query = query.eq("platform_id", platformId);
    if (sessionType) query = query.eq("session_type", sessionType);
    if (dateFrom) query = query.gte("created_at", dateFrom);
    if (dateTo) query = query.lte("created_at", dateTo + "T23:59:59.999Z");

    const { data: sessions } = await query;

    if (!sessions || sessions.length === 0) {
      return NextResponse.json({
        total_feedback: 0, good_count: 0, neutral_count: 0, bad_count: 0,
        good_rate: 0, bad_rate: 0, trend: [],
      });
    }

    const good = sessions.filter((s: any) => s.satisfaction === "good").length;
    const neutral = sessions.filter((s: any) => s.satisfaction === "neutral").length;
    const bad = sessions.filter((s: any) => s.satisfaction === "bad").length;
    const total = sessions.length;

    // 7-day trend
    const trendMap: Record<string, { good: number; neutral: number; bad: number }> = {};
    for (const s of sessions) {
      const d = s.created_at?.slice(0, 10) || "unknown";
      if (!trendMap[d]) trendMap[d] = { good: 0, neutral: 0, bad: 0 };
      if (s.satisfaction === "good") trendMap[d].good++;
      else if (s.satisfaction === "bad") trendMap[d].bad++;
      else trendMap[d].neutral++;
    }
    const sortedDates = Object.entries(trendMap).sort(([a], [b]) => a.localeCompare(b));

    const trend = sortedDates.slice(-7).map(([date, d]) => {
      const dayTotal = d.good + d.neutral + d.bad;
      return {
        date,
        good: d.good,
        neutral: d.neutral,
        bad: d.bad,
        total: dayTotal,
        good_rate: dayTotal > 0 ? d.good / dayTotal : 0,
      };
    });

    // Previous 7-day window for change comparison
    const prevEntries = sortedDates.slice(-14, -7);
    const prevGood = prevEntries.reduce((sum, [, d]) => sum + d.good, 0);
    const prevTotal = prevEntries.reduce((sum, [, d]) => sum + d.good + d.neutral + d.bad, 0);
    const prevGoodRate = prevTotal > 0 ? prevGood / prevTotal : 0;
    const trendChangePp = prevTotal > 0 ? (good / total - prevGoodRate) * 100 : 0;

    return NextResponse.json({
      total_feedback: total,
      good_count: good, neutral_count: neutral, bad_count: bad,
      good_rate: total > 0 ? good / total : 0,
      bad_rate: total > 0 ? bad / total : 0,
      prev_good_rate: prevGoodRate,
      trend_change_pp: Math.round(trendChangePp * 10) / 10,
      trend,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[Satisfaction] Error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
