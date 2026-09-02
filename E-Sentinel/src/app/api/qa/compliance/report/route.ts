import { NextRequest, NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { generateComplianceReport } from "@/lib/compliance-learner";

// GET /api/qa/compliance/report — compliance audit report
export async function GET(request: NextRequest) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { searchParams } = new URL(request.url);
    const days = parseInt(searchParams.get("days") || "7");

    const report = await generateComplianceReport(Math.min(days, 90));

    return NextResponse.json(report);
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
