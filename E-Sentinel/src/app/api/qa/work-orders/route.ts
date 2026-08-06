import { NextRequest, NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { logAudit } from "@/lib/audit";
import { createCorrelationId } from "@/lib/correlation";
import { sendFeishuMessage } from "@/lib/feishu";

// GET /api/qa/work-orders — list with filters
export async function GET(request: NextRequest) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { searchParams } = new URL(request.url);
    const status = searchParams.get("status");
    const priority = searchParams.get("priority");
    const limit = parseInt(searchParams.get("limit") || "50");

    // Graceful fallback — table may not exist yet in production
    let query = supabaseAdmin
      .from("work_orders")
      .select("*")
      .order("created_at", { ascending: false })
      .limit(limit);

    if (status) query = query.eq("status", status);
    if (priority) query = query.eq("priority", priority);

    const { data, error } = await query;
    if (error) {
      if (error.message?.includes("does not exist")) {
        return NextResponse.json({ work_orders: [] });
      }
      throw error;
    }

    return NextResponse.json({ work_orders: data || [] });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    // Return empty data for missing tables instead of 500
    if (message.includes("does not exist")) {
      return NextResponse.json({ work_orders: [] });
    }
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

// POST /api/qa/work-orders — create work order
export async function POST(request: NextRequest) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const body = await request.json();
    const { title, description, source, source_id, priority, category, platform_id, assigned_to, evidence_refs, source_event_id } = body;

    if (!title || !description) {
      return NextResponse.json({ error: "title and description are required" }, { status: 400 });
    }

    const correlationId = createCorrelationId("wo");

    // 支持证据关联，便于从 EvidenceEvent / DiagnosisFinding 创建时可追溯来源（Sprint 2 要求）
    const baseMetadata = body.metadata || {};
    const enrichedMetadata = {
      ...baseMetadata,
      ...(evidence_refs ? { evidence_refs } : {}),
      ...(source_event_id ? { source_event_id } : {}),
    };

    const { data, error } = await supabaseAdmin
      .from("work_orders")
      .insert({
        title,
        description,
        source: source || "manual",
        source_id: source_id || source_event_id || null,
        priority: priority || "medium",
        category: category || "general",
        platform_id: platform_id || null,
        assigned_to: assigned_to || null,
        metadata: enrichedMetadata,
      })
      .select()
      .single();

    if (error) throw error;

    // Log creation action
    await supabaseAdmin.from("work_order_actions").insert({
      work_order_id: data.id,
      action: "created",
      metadata: {
        auto_generated: source === "qa_evaluate" || source === "cron",
        ...(evidence_refs ? { evidence_refs } : {}),
        ...(source_event_id ? { source_event_id } : {}),
      },
    });

    await logAudit({
      action: "knowledge_create", // reusing generic audit type for work order
      resource_type: "work_orders",
      resource_id: data.id,
      detail: { title, priority, source },
      correlation_id: correlationId,
    });

    // Send personal notification to assignee
    if (assigned_to) {
      const { data: profile } = await supabaseAdmin
        .from("profiles")
        .select("feishu_open_id")
        .eq("id", assigned_to)
        .maybeSingle();
      const openId = profile?.feishu_open_id as string | undefined;
      if (openId) {
        sendFeishuMessage({
          receive_id: openId,
          receive_id_type: "open_id",
          msg_type: "text",
          content: `📋 新工单已分配: ${title}`,
        }).catch(() => {});
      }
    }

    return NextResponse.json({ work_order: data }, { status: 201 });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
