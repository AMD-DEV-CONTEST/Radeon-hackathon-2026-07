import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";

interface SessionRow {
  platform_id: number | string | null;
  inquiry_result: string | null;
  transfer_reason: string | null;
}

interface PlatformRow {
  id: number;
  name: string;
}

export async function GET(request: Request) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { searchParams } = new URL(request.url);
    const platformId = searchParams.get("platform_id");
    const dateFrom = searchParams.get("date_from");
    const dateTo = searchParams.get("date_to");

    let query = supabaseAdmin
      .from("bot_chat_sessions")
      .select("*")
      .eq("is_inquiry", true);

    if (platformId) query = query.eq("platform_id", platformId);
    if (dateFrom) query = query.gte("created_at", dateFrom);
    if (dateTo) query = query.lte("created_at", dateTo + "T23:59:59.999Z");

    const { data: sessionsData } = await query;
    const sessions = (sessionsData ?? []) as SessionRow[];

    if (sessions.length === 0) {
      return NextResponse.json({
        total_inquiries: 0, converted: 0, lost: 0, pending: 0,
        conversion_rate: 0, loss_by_reason: [], loss_by_platform: [],
      });
    }

    const converted = sessions.filter((s) => s.inquiry_result === "converted").length;
    const lost = sessions.filter((s) => s.inquiry_result === "lost").length;
    const pending = sessions.filter((s) => s.inquiry_result === "pending").length;

    const lostSessions = sessions.filter((s) => s.inquiry_result === "lost");
    const reasonMap: Record<string, number> = {};
    for (const s of lostSessions) {
      const reason = s.transfer_reason || "未记录";
      reasonMap[reason] = (reasonMap[reason] || 0) + 1;
    }
    const lossByReason = Object.entries(reasonMap)
      .map(([reason, cnt]) => ({ reason, count: cnt }))
      .sort((a, b) => b.count - a.count);

    // Build platform_id -> name map (table has only ~9 rows, full scan is cheap).
    const { data: platformsData } = await supabaseAdmin
      .from("platforms")
      .select("id, name");
    const platformNameById = new Map<number, string>();
    for (const p of (platformsData ?? []) as PlatformRow[]) {
      platformNameById.set(p.id, p.name);
    }

    // Loss by platform — resolve numeric platform_id to Chinese name.
    const platformMap: Record<string, { name: string; total: number; lost: number }> = {};
    for (const s of sessions) {
      const pid = s.platform_id;
      if (pid === null || pid === undefined) continue;
      const key = String(pid);
      if (!platformMap[key]) {
        const numericId = typeof pid === "number" ? pid : Number(pid);
        const name = platformNameById.get(numericId) ?? key;
        platformMap[key] = { name, total: 0, lost: 0 };
      }
      platformMap[key].total++;
      if (s.inquiry_result === "lost") platformMap[key].lost++;
    }
    const lossByPlatform = Object.values(platformMap).map((p) => ({
      ...p,
      loss_rate: p.total > 0 ? p.lost / p.total : 0,
    }));

    const resolvedTotal = converted + lost;
    return NextResponse.json({
      total_inquiries: sessions.length,
      converted, lost, pending,
      conversion_rate: resolvedTotal > 0 ? converted / resolvedTotal : 0,
      loss_by_reason: lossByReason,
      loss_by_platform: lossByPlatform,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[InquiryLoss] Error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
