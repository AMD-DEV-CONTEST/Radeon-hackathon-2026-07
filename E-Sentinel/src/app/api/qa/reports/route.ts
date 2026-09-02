import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { authorizeRequest } from "@/lib/api-auth";
import { loadGovernanceContext } from "@/lib/governance/roles";

function parseViolations(raw: unknown): Array<Record<string, unknown>> {
  if (Array.isArray(raw)) return raw as Array<Record<string, unknown>>;
  if (typeof raw === "string" && raw.length > 0) {
    try { const p = JSON.parse(raw); if (Array.isArray(p)) return p; } catch { /* empty */ }
  }
  return [];
}

interface ReportRow {
  id: string;
  ticket_id: string;
  agent_id?: string | null;
  agent?: { name?: string } | null;
  total_score: number;
  risk_level: string;
  sentiment_score: number;
  violations?: unknown[] | null;
  intent: string;
  status: string;
  correlation_id: string;
  review_mode?: string | null;
  created_at: string;
}

export async function GET(request: Request) {
  const auth = await authorizeRequest(request);
  if (auth.error) return auth.error;
  const context = auth.user ? await loadGovernanceContext(auth.user.id) : null;

  if (!supabaseAdmin) {
    return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
  }

  const url = new URL(request.url);
  const limit = Math.min(parseInt(url.searchParams.get("limit") || "20"), 100);

  let query = supabaseAdmin
    .from("quality_reports")
    .select(`
      id,
      ticket_id,
      agent_id,
      total_score,
      risk_level,
      sentiment_score,
      violations,
      intent,
      status,
      correlation_id,
      review_mode,
      created_at,
      agent:profiles!quality_reports_agent_id_fkey(name)
    `)
    .order("created_at", { ascending: false })
    .limit(limit);
  query = query.eq("tenant_id", context?.tenantId || "default");

  const { data, error } = await query;

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json(
    (data as ReportRow[] || []).map((r) => {
      // 带出首条违规摘要，供风险队列直接展示命中证据与关联规则
      const violations = parseViolations(r.violations) as Array<{ category?: string; rule?: string; source_quote?: string; deduction?: number }>;
      const top = violations[0] || null;
      return {
        id: r.id,
        ticket_id: r.ticket_id,
        agent_name: r.agent?.name || "未匹配客服",
        agent_id: r.agent_id || null,
        agent_matched: !!r.agent?.name,
        total_score: r.total_score,
        risk_level: r.risk_level,
        sentiment_score: r.sentiment_score,
        violations_count: violations.length,
        intent: r.intent,
        status: r.status,
        correlation_id: r.correlation_id,
        review_mode: r.review_mode || "active",
        created_at: r.created_at,
        topViolation: top
          ? { category: top.category || "其他", rule: top.rule || "", quote: top.source_quote || "", deduction: top.deduction || 0 }
          : null,
      };
    })
  );
}
