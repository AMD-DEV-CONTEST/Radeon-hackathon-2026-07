import { NextResponse } from "next/server";
import { authorizeRequest } from "@/lib/api-auth";
import { supabaseAdmin } from "@/lib/supabase";
import { loadGovernanceContext } from "@/lib/governance/roles";
import {
  runDiagnosis,
  ENGINE_VERSION,
  type ConversationEvidence,
  type FunnelContext,
  type DiagnosisInput,
} from "@/lib/diagnosis/engine";
import { getTraceparentFromRequest, parseTraceparent } from "@/lib/monitoring/tracing";

/**
 * POST /api/qa/diagnosis
 * Generate a diagnosis for a set of lost conversations.
 *
 * Body: { conversation_ids: string[], campaign_id?, product_id?, time_window_start?, time_window_end? }
 */
export async function POST(request: Request) {
  const auth = await authorizeRequest(request, { mutation: true });
  if (auth.error) return auth.error;

  if (!supabaseAdmin) {
    return NextResponse.json({ error: "Database not configured" }, { status: 500 });
  }

  try {
    const body = await request.json();
    const conversationIds: string[] = body.conversation_ids;

    if (!Array.isArray(conversationIds) || conversationIds.length === 0) {
      return NextResponse.json(
        { error: "conversation_ids must be a non-empty array" },
        { status: 400 },
      );
    }
    if (conversationIds.length > 100) {
      return NextResponse.json(
        { error: "conversation_ids exceeds maximum of 100" },
        { status: 400 },
      );
    }

    // Resolve tenant
    let tenantId = "default";
    if (auth.user) {
      const ctx = await loadGovernanceContext(auth.user.id);
      if (!ctx?.tenantId) {
        return NextResponse.json({ error: "No tenant context" }, { status: 403 });
      }
      tenantId = ctx.tenantId;
    }

    // Create diagnosis session
    const { data: session, error: sessionError } = await supabaseAdmin
      .from("diagnosis_sessions")
      .insert({
        tenant_id: tenantId,
        trigger_type: "manual",
        status: "running",
        conversation_ids: conversationIds,
        campaign_id: body.campaign_id ?? null,
        product_id: body.product_id ?? null,
        time_window_start: body.time_window_start ?? null,
        time_window_end: body.time_window_end ?? null,
        engine_version: ENGINE_VERSION,
        created_by: auth.user?.id ?? null,
      })
      .select("id")
      .single();

    if (sessionError || !session) {
      return NextResponse.json(
        { error: "Failed to create diagnosis session", detail: sessionError?.message },
        { status: 500 },
      );
    }

    // Gather conversation evidence from bot_chat_sessions
    const conversations = await gatherConversationEvidence(conversationIds, tenantId);

    // Gather funnel context if campaign is specified
    const funnel = body.campaign_id
      ? await gatherFunnelContext(body.campaign_id, tenantId)
      : null;

    // QAE-016: 提取 trace 上下文并关联到 diagnosis
    const traceparent = getTraceparentFromRequest(request);
    const trace_context = parseTraceparent(traceparent);

    // Run diagnosis engine
    const input: DiagnosisInput = {
      tenant_id: tenantId,
      conversation_ids: conversationIds,
      campaign_id: body.campaign_id ?? null,
      product_id: body.product_id ?? null,
      time_window_start: body.time_window_start ?? null,
      time_window_end: body.time_window_end ?? null,
    };
    const result = runDiagnosis(input, conversations, funnel, trace_context);

    // Persist findings
    if (result.findings.length > 0) {
      const findingRows = result.findings.map((f) => ({
        session_id: session.id,
        tenant_id: tenantId,
        reason_category: f.reason_category,
        fact_statement: f.fact_statement,
        inference_statement: f.inference_statement,
        confidence: f.confidence,
        confidence_score: f.confidence_score,
        counter_evidence: f.counter_evidence,
        suggestion: f.suggestion,
        suggestion_actionable: f.suggestion_actionable,
        evidence_refs: f.evidence_refs,
        funnel_stage: f.funnel_stage,
        conversation_id: f.conversation_id,
        product_id: f.product_id,
        campaign_id: f.campaign_id,
      }));

      const { error: findingsError } = await supabaseAdmin
        .from("diagnosis_findings")
        .insert(findingRows);

      if (findingsError) {
        // Mark session as failed but still return partial results
        await supabaseAdmin
          .from("diagnosis_sessions")
          .update({ status: "failed", finished_at: new Date().toISOString() })
          .eq("id", session.id);
        return NextResponse.json(
          { error: "Failed to persist findings", detail: findingsError.message },
          { status: 500 },
        );
      }
    }

    // Update session as completed
    await supabaseAdmin
      .from("diagnosis_sessions")
      .update({
        status: "completed",
        finished_at: new Date().toISOString(),
        summary: result.summary,
      })
      .eq("id", session.id);

    return NextResponse.json({
      session_id: session.id,
      engine_version: result.engine_version,
      findings: result.findings,
      summary: result.summary,
      trace_context: result.trace_context,  // QAE-016
    }, { status: 201 });
  } catch (error) {
    const message = error instanceof Error ? error.message : "diagnosis_failed";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

/**
 * GET /api/qa/diagnosis
 * List diagnosis sessions for the tenant.
 */
export async function GET(request: Request) {
  const auth = await authorizeRequest(request);
  if (auth.error) return auth.error;

  if (!supabaseAdmin) {
    return NextResponse.json({ error: "Database not configured" }, { status: 500 });
  }

  const { searchParams } = new URL(request.url);
  const limit = Math.min(parseInt(searchParams.get("limit") ?? "20", 10), 100);
  const offset = parseInt(searchParams.get("offset") ?? "0", 10);
  const status = searchParams.get("status");

  let tenantId = "default";
  if (auth.user) {
    const ctx = await loadGovernanceContext(auth.user.id);
    tenantId = ctx?.tenantId ?? "default";
  }

  let query = supabaseAdmin
    .from("diagnosis_sessions")
    .select("*", { count: "exact" })
    .eq("tenant_id", tenantId)
    .order("created_at", { ascending: false })
    .range(offset, offset + limit - 1);

  if (status) {
    query = query.eq("status", status);
  }

  const { data, error, count } = await query;
  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ sessions: data ?? [], total: count ?? 0 });
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function gatherConversationEvidence(
  conversationIds: string[],
  tenantId: string,
): Promise<ConversationEvidence[]> {
  if (!supabaseAdmin) return [];

  const { data: sessions } = await supabaseAdmin
    .from("bot_chat_sessions")
    .select("*")
    .in("id", conversationIds)
    .eq("tenant_id", tenantId);

  if (!sessions) return [];

  return sessions.map((s: Record<string, unknown>) => ({
    conversation_id: String(s.id ?? ""),
    campaign_id: s.campaign_id != null ? String(s.campaign_id) : null,
    product_id: s.product_id != null ? String(s.product_id) : null,
    messages: parseMessages(s.messages ?? s.conversation_content ?? []),
    had_cart: Boolean(s.had_cart ?? s.is_add_cart ?? false),
    had_order: Boolean(s.had_order ?? s.inquiry_result === "converted"),
    had_payment: Boolean(s.had_payment ?? s.inquiry_result === "paid"),
    transferred_to_human: Boolean(s.transferred_to_human ?? s.is_transfer ?? false),
    duration_seconds: Number(s.duration_seconds ?? s.chat_duration ?? 0),
    customer_sentiment: normalizeSentiment(s.customer_sentiment ?? s.sentiment),
  }));
}

function parseMessages(raw: unknown): ConversationEvidence["messages"] {
  if (!Array.isArray(raw)) return [];
  return raw.slice(0, 50).map((m: Record<string, unknown>) => ({
    role: m.role === "customer" || m.role === "user" ? "customer" as const
      : m.role === "system" ? "system" as const
      : "agent" as const,
    content: String(m.content ?? m.text ?? ""),
    timestamp: String(m.timestamp ?? m.created_at ?? ""),
    tags: Array.isArray(m.tags) ? m.tags.map(String) : undefined,
  }));
}

function normalizeSentiment(raw: unknown): ConversationEvidence["customer_sentiment"] {
  if (raw === "positive" || raw === "negative" || raw === "neutral") return raw;
  return "unknown";
}

async function gatherFunnelContext(
  campaignId: string,
  tenantId: string,
): Promise<FunnelContext | null> {
  if (!supabaseAdmin) return null;

  // Try to get funnel data from evidence_events or bot_chat_sessions
  const { data: sessions } = await supabaseAdmin
    .from("bot_chat_sessions")
    .select("id, is_add_cart, inquiry_result, is_transfer")
    .eq("tenant_id", tenantId)
    .eq("campaign_id", campaignId);

  if (!sessions || sessions.length === 0) return null;

  const conversationCount = sessions.length;
  const cartCount = sessions.filter((s: Record<string, unknown>) => s.is_add_cart).length;
  const orderCount = sessions.filter(
    (s: Record<string, unknown>) => s.inquiry_result === "converted" || s.inquiry_result === "paid",
  ).length;

  return {
    traffic_count: Math.round(conversationCount * 6.5), // Estimate: ~15% conversion from traffic
    conversation_count: conversationCount,
    cart_count: cartCount,
    order_count: orderCount,
    payment_count: sessions.filter((s: Record<string, unknown>) => s.inquiry_result === "paid").length,
  };
}
