// ============================================================================
// Pipeline orchestrator — connects QA → cluster → optimize → verify
// ============================================================================

import { supabaseAdmin } from "./supabase";
import { createCorrelationId } from "./correlation";
import { logAudit } from "./audit";

export interface PipelineTrigger {
  source_type: "chat_inspection" | "inquiry_loss" | "satisfaction" | "knowledge_gap" | "manual";
  session_ids?: string[];
  context?: Record<string, unknown>;
  correlation_id?: string;
}

export interface PipelineResult {
  tasks_created: number;
  correlation_id: string;
}

/**
 * After any analysis completes, auto-create optimization tasks from the findings.
 * This is the central "closing the loop" function.
 */
export async function triggerTaskPipeline(params: PipelineTrigger): Promise<PipelineResult> {
  const cid = params.correlation_id || createCorrelationId("pipeline");

  try {
    if (!supabaseAdmin) {
      return { tasks_created: 0, correlation_id: cid };
    }

    // Call the auto-generate endpoint internally
    const baseUrl = process.env.NEXT_PUBLIC_SITE_URL
      || (process.env.VERCEL_URL ? `https://${process.env.VERCEL_URL}` : null)
      || "http://localhost:3001";
    const url = `${baseUrl}/api/qa/optimization-tasks/auto-generate`;

    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "x-correlation-id": cid },
      body: JSON.stringify({
        source_type: params.source_type,
        session_ids: params.session_ids || [],
      }),
    });

    if (!res.ok) {
      console.error(`[Pipeline] auto-generate failed for ${params.source_type}`);
      return { tasks_created: 0, correlation_id: cid };
    }

    const data = await res.json();
    const count = data.tasks?.length || data.count || 0;

    await logAudit({
      action: "optimization_task_create",
      resource_type: "pipeline",
      detail: { source_type: params.source_type, tasks_created: count, context: params.context },
      correlation_id: cid,
    });

    console.log(`[Pipeline] ${cid} Created ${count} optimization tasks from ${params.source_type}`);
    return { tasks_created: count, correlation_id: cid };
  } catch (err) {
    console.error(`[Pipeline] Error for ${params.source_type}:`, err);
    return { tasks_created: 0, correlation_id: cid };
  }
}
