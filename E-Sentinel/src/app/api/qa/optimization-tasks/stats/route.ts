import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";

export async function GET() {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { data: tasks } = await supabaseAdmin
      .from("optimization_tasks")
      .select("status, priority, source, created_at, resolved_at");

    const all = tasks || [];

    const statusCounts = { open: 0, in_progress: 0, resolved: 0, wont_fix: 0 };
    const priorityCounts: Record<string, number> = {};
    const sourceCounts: Record<string, number> = {};
    let totalResolutionDays = 0;
    let resolvedCount = 0;

    for (const t of all) {
      statusCounts[t.status as keyof typeof statusCounts]++;
      priorityCounts[t.priority] = (priorityCounts[t.priority] || 0) + 1;
      sourceCounts[t.source] = (sourceCounts[t.source] || 0) + 1;
      if (t.status === "resolved" && t.resolved_at) {
        const days = (new Date(t.resolved_at).getTime() - new Date(t.created_at).getTime()) / (86400000);
        totalResolutionDays += days;
        resolvedCount++;
      }
    }

    return NextResponse.json({
      total: all.length,
      by_status: statusCounts,
      by_priority: priorityCounts,
      by_source: sourceCounts,
      avg_resolution_days: resolvedCount > 0 ? Math.round((totalResolutionDays / resolvedCount) * 10) / 10 : 0,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[OptTasks] Stats error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
