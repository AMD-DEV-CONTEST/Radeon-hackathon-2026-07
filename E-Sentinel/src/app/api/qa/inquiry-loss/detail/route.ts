import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";

export async function GET(request: Request) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { searchParams } = new URL(request.url);
    const platformId = searchParams.get("platform_id");
    const dateFrom = searchParams.get("date_from");
    const dateTo = searchParams.get("date_to");
    const reasonCategory = searchParams.get("reason_category");
    const limit = Math.min(parseInt(searchParams.get("limit") || "50"), 100);
    const offset = parseInt(searchParams.get("offset") || "0");

    let query = supabaseAdmin
      .from("bot_chat_sessions")
      .select("*, platforms!inner(name)")
      .eq("is_inquiry", true)
      .eq("inquiry_result", "lost")
      .order("created_at", { ascending: false })
      .range(offset, offset + limit - 1);

    if (platformId) query = query.eq("platform_id", platformId);
    if (dateFrom) query = query.gte("created_at", dateFrom);
    if (dateTo) query = query.lte("created_at", dateTo + "T23:59:59.999Z");
    if (reasonCategory) query = query.eq("transfer_reason", reasonCategory);

    const { data, error } = await query;
    if (error) throw error;

    const sessions = (data || []).map((row: any) => ({
      ...row,
      platform_name: row.platforms?.name || null,
      platforms: undefined,
    }));

    return NextResponse.json({ sessions });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[InquiryLoss] Detail error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
