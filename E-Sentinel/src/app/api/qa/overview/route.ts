import { NextResponse } from "next/server";
import { authorizeRequest } from "@/lib/api-auth";
import { supabaseAdmin } from "@/lib/supabase";

/**
 * 经营总览 API
 * 汇总 AI 客服价值、诊断统计、任务统计、知识库与质检指标
 * 所有指标均来自数据库真实查询，无数据时返回 0，不做任何估算或填充
 * 性能：全部查询用 Promise.all 并行，避免本地→生产 Supabase 网络延迟串行累加
 */
export async function GET(request: Request) {
  const auth = await authorizeRequest(request);
  if (auth.error) return auth.error;

  // 租户解析：优先取 x-tenant-id 请求头，缺失时回退到单租户默认值 "default"。
  const tenantId = request.headers.get("x-tenant-id")?.trim() || "default";

  try {
    // 默认统计（无数据时保持 0，不做估算）
    const diagnosisStats = {
      total_sessions: 0,
      diagnosed_findings: 0,
      accepted_findings: 0,
      pending_review: 0,
      top_reasons: [] as { category: string; count: number }[],
    };
    const csStats = {
      total_conversations: 0,
      ai_handled: 0,
      transferred_to_human: 0,
      avg_response_time_ms: 0,
      satisfaction_rate: 0,
    };
    const workOrderStats = {
      total: 0,
      pending: 0,
      in_progress: 0,
      completed: 0,
      overdue: 0,
    };
    const knowledgeStats = {
      total_entries: 0,
      pending_approval: 0,
    };
    const qualityStats = {
      total_reports: 0,
      critical_count: 0,
      pending_review: 0,
      avg_score: 0,
    };

    if (supabaseAdmin) {
      const sevenDaysAgo = new Date(Date.now() - 7 * 86400000).toISOString();

      // ── 并行发起全部查询（本地→生产 Supabase 网络延迟 ~0.7s/次，并行避免串行累加） ──
      const [
        { data: diagSessions },
        { count: totalConv },
        { count: aiHandled },
        { count: transferred },
        { count: woTotal },
        { count: woPending },
        { count: woInProgress },
        { count: woCompleted },
        { count: kbPublished },
        { count: kbDraft },
        { data: recentReports },
      ] = await Promise.all([
        supabaseAdmin
          .from("diagnosis_sessions")
          .select("id, status, summary")
          .eq("tenant_id", tenantId)
          .order("created_at", { ascending: false })
          .limit(10),
        supabaseAdmin
          .from("bot_chat_sessions")
          .select("*", { count: "exact", head: true }),
        supabaseAdmin
          .from("bot_chat_sessions")
          .select("*", { count: "exact", head: true })
          .eq("bot_handled", true),
        supabaseAdmin
          .from("bot_chat_sessions")
          .select("*", { count: "exact", head: true })
          .eq("bot_handled", false),
        supabaseAdmin
          .from("work_orders")
          .select("*", { count: "exact", head: true }),
        supabaseAdmin
          .from("work_orders")
          .select("*", { count: "exact", head: true })
          .eq("status", "pending"),
        supabaseAdmin
          .from("work_orders")
          .select("*", { count: "exact", head: true })
          .eq("status", "in_progress"),
        supabaseAdmin
          .from("work_orders")
          .select("*", { count: "exact", head: true })
          .eq("status", "completed"),
        supabaseAdmin
          .from("knowledge_entries")
          .select("*", { count: "exact", head: true })
          .eq("status", "published")
          .eq("tenant_id", tenantId),
        supabaseAdmin
          .from("knowledge_entries")
          .select("*", { count: "exact", head: true })
          .eq("status", "draft")
          .eq("tenant_id", tenantId),
        supabaseAdmin
          .from("quality_reports")
          .select("risk_level, total_score, status")
          .eq("tenant_id", tenantId)
          .gte("created_at", sevenDaysAgo),
      ]);

      // 1. 诊断统计
      if (diagSessions && diagSessions.length > 0) {
        diagnosisStats.total_sessions = diagSessions.length;
        for (const session of diagSessions) {
          const summary = session.summary as {
            diagnosed_count?: number;
            top_reasons?: { category: string; count: number }[];
          } | null;
          if (summary) {
            diagnosisStats.diagnosed_findings += summary.diagnosed_count ?? 0;
            if (summary.top_reasons) {
              for (const reason of summary.top_reasons) {
                const existing = diagnosisStats.top_reasons.find(
                  (r) => r.category === reason.category
                );
                if (existing) {
                  existing.count += reason.count;
                } else {
                  diagnosisStats.top_reasons.push({ ...reason });
                }
              }
            }
          }
        }
      }

      // 2. 客服统计（bot_chat_sessions）
      csStats.total_conversations = totalConv ?? 0;
      csStats.ai_handled = aiHandled ?? 0;
      csStats.transferred_to_human = transferred ?? 0;
      if (csStats.total_conversations > 0) {
        csStats.satisfaction_rate = csStats.ai_handled / csStats.total_conversations;
      }

      // 3. 工单统计
      workOrderStats.total = woTotal ?? 0;
      workOrderStats.pending = woPending ?? 0;
      workOrderStats.in_progress = woInProgress ?? 0;
      workOrderStats.completed = woCompleted ?? 0;

      // 4. 知识库统计
      knowledgeStats.total_entries = kbPublished ?? 0;
      knowledgeStats.pending_approval = kbDraft ?? 0;

      // 5. 质检统计（近 7 天）
      const reports = recentReports ?? [];
      qualityStats.total_reports = reports.length;
      qualityStats.critical_count = reports.filter(
        (r) => r.risk_level === "critical"
      ).length;
      qualityStats.pending_review = reports.filter(
        (r) => r.status === "pending_review" || r.status === "overturn"
      ).length;
      if (reports.length > 0) {
        qualityStats.avg_score = Math.round(
          reports.reduce((sum, r) => sum + (r.total_score ?? 0), 0) / reports.length
        );
      }
    }

    // 6. 构建响应
    const overview = {
      generated_at: new Date().toISOString(),

      // AI 客服价值（真实会话统计，不含成本估算）
      ai_service_value: {
        total_conversations: csStats.total_conversations,
        ai_handled: csStats.ai_handled,
        ai_handle_rate:
          csStats.total_conversations > 0
            ? csStats.ai_handled / csStats.total_conversations
            : 0,
        transferred_to_human: csStats.transferred_to_human,
      },

      // 诊断统计
      diagnosis: {
        total_sessions: diagnosisStats.total_sessions,
        diagnosed_findings: diagnosisStats.diagnosed_findings,
        top_reasons: diagnosisStats.top_reasons.slice(0, 3),
      },

      // 任务统计
      work_orders: workOrderStats,

      // 知识库统计
      knowledge_base: knowledgeStats,

      // 质检统计（近 7 天）
      quality: qualityStats,
    };

    return NextResponse.json(overview);
  } catch (error) {
    console.error("[overview] Error:", error);
    return NextResponse.json(
      { error: "Failed to generate overview" },
      { status: 500 }
    );
  }
}
