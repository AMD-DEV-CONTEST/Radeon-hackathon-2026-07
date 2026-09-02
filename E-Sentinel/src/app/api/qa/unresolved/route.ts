// ============================================================================
// Unresolved Questions API — CRUD + List + Stats
// AI未解决问题记录：bot未处理的会话自动落库，支持查询和状态流转
// ============================================================================

import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { createCorrelationId } from "@/lib/correlation";
import { logAudit } from "@/lib/audit";
import { authorizeGovernanceRequest } from "@/lib/governance/authorization";
import {
  buildConversationText,
  cleanText,
  normalizeCheckedSteps,
  type UnresolvedQuestionInput,
} from "@/lib/unresolved-questions";

function toPublicError(error: unknown): { message: string; status: number } {
  const err = error as { code?: string; message?: string };
  if (err?.code === "PGRST205" || err?.message?.includes("unresolved_questions")) {
    return {
      message: "unresolved_questions table is not ready. Please run supabase/migration-015-unresolved-questions.sql first.",
      status: 503,
    };
  }
  return { message: error instanceof Error ? error.message : "internal_error", status: 500 };
}

function normalizeRow(raw: Record<string, unknown>): Record<string, unknown> {
  return {
    ...raw,
    tags: Array.isArray(raw.tags) ? raw.tags : [],
    category: raw.category || null,
    note: raw.note || null,
    assigned_to: raw.assigned_to || null,
  };
}

// ── LIST ──────────────────────────────────────────────
export async function GET(request: Request) {
  const authorization = await authorizeGovernanceRequest(request);
  if (authorization.error) return authorization.error;
  const tenantId = authorization.context?.tenantId;
  if (!tenantId) return NextResponse.json({ error: "Tenant scope required" }, { status: 403 });

  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { searchParams } = new URL(request.url);
    const status = searchParams.get("status") || "all";
    const category = searchParams.get("category");
    const platformCode = searchParams.get("platform_code");
    const limit = Math.min(parseInt(searchParams.get("limit") || "50"), 100);
    const offset = parseInt(searchParams.get("offset") || "0");
    const sort = searchParams.get("sort") || "newest";

    let query = supabaseAdmin
      .from("unresolved_questions")
      .select("*", { count: "exact" })
      .limit(limit)
      .range(offset, offset + limit - 1)
      .eq("tenant_id", tenantId);

    if (status !== "all") query = query.eq("status", status);
    if (category) query = query.eq("category", category);
    if (platformCode) query = query.eq("platform_code", platformCode);

    if (sort === "priority") {
      query = query.order("priority", { ascending: false }).order("created_at", { ascending: false });
    } else {
      query = query.order("created_at", { ascending: false });
    }

    const { data, error, count } = await query;

    if (error) throw error;

    const rows = (data || []).map(normalizeRow);

    return NextResponse.json({ entries: rows, total: count || 0 });
  } catch (error) {
    const { message, status } = toPublicError(error);
    console.error("[Unresolved] GET error:", message);
    return NextResponse.json({ error: message }, { status });
  }
}

// ── CREATE ─────────────────────────────────────────────
export async function POST(request: Request) {
  const authorization = await authorizeGovernanceRequest(request, { mutation: true });
  if (authorization.error) return authorization.error;
  const tenantId = authorization.context?.tenantId;
  if (!tenantId) return NextResponse.json({ error: "Tenant scope required" }, { status: 403 });

  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const body = await request.json().catch(() => ({}));
    // 批量创建
    if (Array.isArray(body.entries)) {
      const correlationId = createCorrelationId("uq");
      const entries = body.entries.map((e: UnresolvedQuestionInput, index: number) => {
        const userQuestion = cleanText(e.user_question, 1000);
        const sessionId = cleanText(e.session_id, 120) || `${correlationId}_${index + 1}`;
        const platformCode = cleanText(e.platform_code ?? e.channel, 80);
        const category = cleanText(e.category ?? e.issue_type, 120);
        const transferReason = cleanText(e.transfer_reason ?? e.unresolved_reason, 500);
        const checkedSteps = normalizeCheckedSteps(e.checked_steps);

        return {
          session_id: sessionId,
          platform_code: platformCode || null,
          user_question: userQuestion,
          ai_reply: cleanText(e.ai_reply, 1000) || null,
          transfer_reason: transferReason || null,
          satisfaction: cleanText(e.satisfaction, 40) || null,
          conversation: buildConversationText(e) || null,
          category: category || null,
          tags: checkedSteps.length > 0 ? ["has_checked_steps"] : [],
          note: cleanText(e.note, 1000) || null,
          priority: typeof e.priority === "number" ? e.priority : 0,
          correlation_id: correlationId,
          status: "pending",
          tenant_id: tenantId,
        };
      }).filter((e: Record<string, unknown>) => e.user_question);

      if (entries.length === 0) {
        return NextResponse.json({ error: "No valid entries provided" }, { status: 400 });
      }

      const { data, error } = await supabaseAdmin
        .from("unresolved_questions")
        .insert(entries)
        .select();

      if (error) throw error;

      // 写操作日志
      for (const row of data || []) {
        await supabaseAdmin.from("unresolved_question_logs").insert({
          unresolved_id: row.id,
          action: "create",
          detail: { source: "api_batch", count: entries.length },
        });
      }

      await logAudit({
        action: "unresolved_questions_create",
        resource_type: "unresolved_questions",
        detail: { count: entries.length, correlation_id: correlationId },
        correlation_id: correlationId,
      });

      return NextResponse.json({ entries: (data || []).map(normalizeRow) }, { status: 201 });
    }

    // 单条创建
    const correlationId = createCorrelationId("uq");
    const entry = body as UnresolvedQuestionInput;
    const userQuestion = cleanText(entry.user_question, 1000);
    const sessionId = cleanText(entry.session_id, 120) || correlationId;
    const platformCode = cleanText(entry.platform_code ?? entry.channel, 80);
    const category = cleanText(entry.category ?? entry.issue_type, 120);
    const transferReason = cleanText(entry.transfer_reason ?? entry.unresolved_reason, 500);
    const checkedSteps = normalizeCheckedSteps(entry.checked_steps);

    if (!userQuestion) {
      return NextResponse.json({ error: "user_question is required" }, { status: 400 });
    }

    const { data, error } = await supabaseAdmin
      .from("unresolved_questions")
      .insert({
        session_id: sessionId,
        platform_code: platformCode || null,
        user_question: userQuestion,
        ai_reply: cleanText(entry.ai_reply, 1000) || null,
        transfer_reason: transferReason || null,
        satisfaction: cleanText(entry.satisfaction, 40) || null,
        conversation: buildConversationText(entry) || null,
        category: category || null,
        tags: checkedSteps.length > 0 ? ["has_checked_steps"] : [],
        note: cleanText(entry.note, 1000) || null,
        priority: typeof entry.priority === "number" ? entry.priority : 0,
        correlation_id: correlationId,
        status: "pending",
        tenant_id: tenantId,
      })
      .select()
      .single();

    if (error) throw error;

    // 写操作日志
    await supabaseAdmin.from("unresolved_question_logs").insert({
      unresolved_id: data.id,
      action: "create",
      detail: { source: "api_single" },
    });

    await logAudit({
      action: "unresolved_questions_create",
      resource_type: "unresolved_questions",
      resource_id: data.id,
      detail: { session_id: sessionId, user_question: userQuestion.slice(0, 100), platform_code: platformCode },
      correlation_id: correlationId,
    });

    return NextResponse.json({ entry: normalizeRow(data) }, { status: 201 });
  } catch (error) {
    const { message, status } = toPublicError(error);
    console.error("[Unresolved] POST error:", message);
    return NextResponse.json({ error: message }, { status });
  }
}
