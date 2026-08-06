import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";

export async function POST(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }
    const { id } = await params;

    // Fetch the target config
    const { data: target } = await supabaseAdmin
      .from("bot_configs")
      .select("*")
      .eq("id", id)
      .single();

    if (!target) return NextResponse.json({ error: "Not found" }, { status: 404 });

    // Archive all active versions for same key
    await supabaseAdmin
      .from("bot_configs")
      .update({ status: "archived" })
      .eq("platform_id", target.platform_id)
      .eq("config_type", target.config_type)
      .eq("config_key", target.config_key)
      .eq("status", "active");

    // Activate this one
    const { data, error } = await supabaseAdmin
      .from("bot_configs")
      .update({ status: "active", updated_at: new Date().toISOString() })
      .eq("id", id)
      .select()
      .single();

    if (error) throw error;

    return NextResponse.json({ config: data, activated: true });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[BotConfigs] Activate error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
