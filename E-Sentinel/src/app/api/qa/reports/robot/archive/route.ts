import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";

export async function GET(request: Request) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { searchParams } = new URL(request.url);
    const reportType = searchParams.get("report_type");
    const dateFrom = searchParams.get("date_from");
    const dateTo = searchParams.get("date_to");
    const limit = Math.min(parseInt(searchParams.get("limit") || "30"), 100);

    let query = supabaseAdmin
      .from("robot_reports")
      .select("id, report_type, period_start, period_end, platform_id, generated_by, created_at, summary_md")
      .order("period_start", { ascending: false })
      .limit(limit);

    if (reportType) query = query.eq("report_type", reportType);
    if (dateFrom) query = query.gte("period_start", dateFrom);
    if (dateTo) query = query.lte("period_end", dateTo);

    const { data, error } = await query;
    if (error) {
      if (error.code === "PGRST204" || error.message?.includes("schema cache")) {
        return NextResponse.json({ reports: [], hint: "Table not found — run migration-003 first" });
      }
      throw error;
    }

    return NextResponse.json({ reports: data || [] });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[Reports] Archive error:", message);
    return NextResponse.json({ reports: [], error: message }, { status: 200 });
  }
}
