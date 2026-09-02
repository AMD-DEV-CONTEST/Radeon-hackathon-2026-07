// ============================================================================
// Push to Dify API — 一键推送到 Dify 知识库
// 从 knowledge_entries 中拉取已发布条目，批量推送到 Dify
// ============================================================================

import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { pushKnowledgeEntries } from "@/lib/dify-client";
import { logAudit } from "@/lib/audit";
import { createCorrelationId } from "@/lib/correlation";
import { authorizeRequest } from "@/lib/api-auth";
import { canWrite, loadGovernanceContext } from "@/lib/governance/roles";

export async function POST(request: Request) {
  const auth = await authorizeRequest(request, { mutation: true });
  if (auth.error) return auth.error;
  const context = auth.user ? await loadGovernanceContext(auth.user.id) : null;
  if (auth.user) {
    if (!context || !canWrite(context.role)) {
      return NextResponse.json({ error: "Operator role required" }, { status: 403 });
    }
  }

  try {
    const body = await request.json().catch(() => ({}));
    const { category, platform_id, limit } = body;

    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    if (!process.env.DIFY_BASE_URL || !process.env.DIFY_API_KEY) {
      return NextResponse.json(
        { error: "DIFY_BASE_URL and DIFY_API_KEY not configured" },
        { status: 400 },
      );
    }

    // Fetch published knowledge entries
    let query = supabaseAdmin
      .from("knowledge_entries")
      .select("id, title, content, category, tags")
      .eq("status", "published")
      .eq("tenant_id", context?.tenantId || "default")
      .order("hit_count", { ascending: false })
      .limit(Math.min(limit || 100, 500));

    if (category) query = query.eq("category", category);
    if (platform_id) query = query.eq("platform_id", platform_id);

    const { data: entries, error } = await query;
    if (error) throw error;
    if (!entries || entries.length === 0) {
      return NextResponse.json({ pushed: 0, message: "No published entries to push" });
    }

    // Push to Dify
    const result = await pushKnowledgeEntries(
      entries.map((e) => ({
        knowledge_id: e.id,
        title: e.title,
        content: e.content,
        category: e.category,
      })),
    );

    // Audit
    const correlationId = createCorrelationId("dify");
    for (const document of result.documents) {
      await supabaseAdmin.from("knowledge_update_logs").insert({
        knowledge_id: document.knowledge_id,
        update_type: "update",
        field_changed: "dify_push",
        new_value: JSON.stringify({ dataset_id: result.dataset_id, document_id: document.document_id, batch: document.batch }),
        correlation_id: correlationId,
      });
    }
    await logAudit({
      action: "import_trained_knowledge",
      resource_type: "dify_push",
      detail: {
        dataset_id: result.dataset_id,
        total: result.total,
        succeeded: result.succeeded,
        failed: result.failed,
        errors: result.errors.slice(0, 5),
      },
      correlation_id: correlationId,
    });

    return NextResponse.json({
      dataset_id: result.dataset_id,
      dataset_name: result.dataset_name,
      total: result.total,
      succeeded: result.succeeded,
      failed: result.failed,
      errors: result.errors.slice(0, 10),
      documents: result.documents,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[PushToDify] Error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
