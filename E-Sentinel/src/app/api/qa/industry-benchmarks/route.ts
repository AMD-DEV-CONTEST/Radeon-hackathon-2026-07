import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";

export async function GET() {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { data, error } = await supabaseAdmin
      .from("industry_benchmarks")
      .select("*")
      .order("metric_name");

    if (error) {
      // Table may not exist yet — return empty with hint
      if (error.code === "PGRST204" || error.message?.includes("schema cache")) {
        return NextResponse.json({ benchmarks: [], hint: "Table not found — run migration-003 first" });
      }
      throw error;
    }

    return NextResponse.json({ benchmarks: data || [] });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[Benchmarks] GET error:", message);
    return NextResponse.json({ benchmarks: [], error: message }, { status: 200 });
  }
}

export async function POST(request: Request) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const body = await request.json().catch(() => ({}));
    const { metric_name, industry_avg, industry_top, category } = body;

    if (!metric_name || industry_avg == null) {
      return NextResponse.json({ error: "metric_name and industry_avg are required" }, { status: 400 });
    }

    const { data, error } = await supabaseAdmin
      .from("industry_benchmarks")
      .insert({
        metric_name,
        industry_avg,
        industry_top: industry_top || null,
        category: category || null,
      })
      .select()
      .single();

    if (error) throw error;

    return NextResponse.json({ benchmark: data }, { status: 201 });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[Benchmarks] POST error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
