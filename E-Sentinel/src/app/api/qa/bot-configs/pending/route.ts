import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";

export async function GET(request: Request) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { searchParams } = new URL(request.url);
    const limit = Math.min(parseInt(searchParams.get("limit") || "30"), 100);
    const platformId = searchParams.get("platform_id");
    const configType = searchParams.get("config_type");

    let query = supabaseAdmin
      .from("bot_configs")
      .select("*")
      .eq("status", "draft")
      .order("updated_at", { ascending: false })
      .limit(limit);

    if (platformId) query = query.eq("platform_id", platformId);
    if (configType) query = query.eq("config_type", configType);

    const { data, error } = await query;

    if (error) throw error;

    return NextResponse.json({ configs: data || [] });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[BotConfigs Pending] GET error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
