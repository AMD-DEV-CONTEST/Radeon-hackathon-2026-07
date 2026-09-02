import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";

export async function GET(request: Request) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { searchParams } = new URL(request.url);
    const date = searchParams.get("date") || new Date().toISOString().slice(0, 10);
    const platformId = searchParams.get("platform_id");

    let query = supabaseAdmin
      .from("robot_reports")
      .select("*")
      .eq("report_type", "daily")
      .eq("period_start", date);

    if (platformId) query = query.eq("platform_id", platformId);

    const { data } = await query;

    if (!data || data.length === 0) {
      return NextResponse.json({ report: null, message: `No report found for ${date}` });
    }

    return NextResponse.json({ report: data[0] });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[Reports] Daily error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
