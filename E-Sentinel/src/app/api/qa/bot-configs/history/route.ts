import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";

export async function GET(request: Request) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { searchParams } = new URL(request.url);
    const platformId = searchParams.get("platform_id");
    const configType = searchParams.get("config_type");
    const configKey = searchParams.get("config_key");
    const limit = Math.min(parseInt(searchParams.get("limit") || "20"), 50);

    if (!platformId || !configType || !configKey) {
      return NextResponse.json(
        { error: "platform_id, config_type, config_key are required" },
        { status: 400 }
      );
    }

    const { data, error } = await supabaseAdmin
      .from("bot_configs")
      .select("id, version, status, change_summary, updated_by, created_at, updated_at")
      .eq("platform_id", platformId)
      .eq("config_type", configType)
      .eq("config_key", configKey)
      .order("version", { ascending: false })
      .limit(limit);

    if (error) throw error;

    return NextResponse.json({ versions: data || [] });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[BotConfigs] History error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
