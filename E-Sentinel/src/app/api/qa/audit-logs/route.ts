import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { authorizeRequest } from "@/lib/api-auth";

function safeJsonParse(v: unknown): Record<string, unknown> | null {
  if (!v || typeof v !== "string") return null;
  try { return JSON.parse(v); } catch { return null; }
}

export async function GET(request: Request) {
  const auth = await authorizeRequest(request);
  if (auth.error) return auth.error;

  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { searchParams } = new URL(request.url);
    const limit = Math.min(parseInt(searchParams.get("limit") || "30"), 100);
    const offset = parseInt(searchParams.get("offset") || "0");
    const action = searchParams.get("action");
    const correlationId = searchParams.get("correlation_id");
    const dateFrom = searchParams.get("date_from");
    const dateTo = searchParams.get("date_to");

    let query = supabaseAdmin
      .from("audit_logs")
      .select("*", { count: "exact" })
      .order("created_at", { ascending: false })
      .range(offset, offset + limit - 1);

    if (action) query = query.eq("action", action);
    if (correlationId) query = query.eq("correlation_id", correlationId);
    if (dateFrom) query = query.gte("created_at", dateFrom);
    if (dateTo) query = query.lte("created_at", dateTo + "T23:59:59.999Z");

    const { data: logs, count, error } = await query;

    if (error) throw error;

    // Stats for the header
    const { data: statsData } = await supabaseAdmin
      .from("audit_logs")
      .select("action");

    const stats = {
      total: count || 0,
      byAction: (statsData || []).reduce<Record<string, number>>((acc, row) => {
        acc[row.action] = (acc[row.action] || 0) + 1;
        return acc;
      }, {}),
    };

    const parsedLogs = (logs || []).map((log) => ({
      ...log,
      detail: typeof log.detail === "string" ? safeJsonParse(log.detail) : log.detail,
    }));

    return NextResponse.json({ logs: parsedLogs, stats, total: count || 0 });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[AuditLogs] Error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
