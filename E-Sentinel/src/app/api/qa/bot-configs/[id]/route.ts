import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }
    const { id } = await params;

    const { data, error } = await supabaseAdmin
      .from("bot_configs")
      .select("*, platforms(name)")
      .eq("id", id)
      .single();

    if (error) {
      if (error.code === "PGRST116") return NextResponse.json({ error: "Not found" }, { status: 404 });
      throw error;
    }

    return NextResponse.json({ config: { ...data, platform_name: data.platforms?.name, platforms: undefined } });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[BotConfigs] GET/:id error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
