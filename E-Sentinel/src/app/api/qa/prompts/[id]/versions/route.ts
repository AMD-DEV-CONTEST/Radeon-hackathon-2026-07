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
      .from("prompt_versions")
      .select("*")
      .eq("prompt_id", id)
      .order("version", { ascending: false });

    if (error) throw error;

    return NextResponse.json({ versions: data || [] });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[Prompts] GET versions error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
