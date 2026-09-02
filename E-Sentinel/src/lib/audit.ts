// ============================================================================
// Audit logger — records auth, operations, AI calls, QA changes
// ============================================================================

import { supabaseAdmin } from "./supabase";
import { createCorrelationId } from "./correlation";

export type AuditAction =
  | "login"
  | "logout"
  | "evaluate"
  | "overturn"
  | "dispatch_feishu"
  | "llm_call"
  | "knowledge_create"
  | "knowledge_update"
  | "knowledge_delete"
  | "bot_config_create"
  | "bot_config_activate"
  | "bot_config_archive"
  | "optimization_task_create"
  | "optimization_task_update"
  | "report_generate"
  | "campaign_import"
  | "rule_create"
  | "rule_delete"
  | "feishu_event_receive"
  | "auto_evaluate_failed"
  | "knowledge_publish"
  | "knowledge_reject"
  | "bot_config_publish"
  | "bot_config_reject"
  | "bot_config_generate"
  | "compliance_block"
  | "compliance_warn"
  | "compliance_pass"
  | "tmall_event_receive"
  | "tmall_shadow_reply"
  | "tmall_real_reply"
  | "tmall_compliance_block"
  | "tmall_human_fallback"
  | "prompt_create"
  | "prompt_update"
  | "prompt_archive"
  | "prompt_version_new"
  | "prompt_activate"
  | "knowledge_archive"
  | "knowledge_batch_operation"
  | "model_config_create"
  | "model_config_update"
  | "model_config_delete"
  | "bot_create"
  | "bot_update"
  | "bot_delete"
  | "unresolved_questions_create"
  | "unresolved_questions_update"
  | "unresolved_questions_export"
  | "unresolved_questions_capture"
  | "import_trained_knowledge"
  | "rate_limit_hit"
  | "guard_block"
  | "auth_failure"
  | "admin_action";

export async function logAudit(params: {
  action: AuditAction;
  user_id?: string | null;
  user_name?: string | null;
  resource_type?: string;
  resource_id?: string;
  detail?: Record<string, unknown>;
  correlation_id?: string;
}) {
  try {
    if (!supabaseAdmin) {
      console.error("[Audit] write failed: Supabase is not configured");
      return;
    }

    // Try the audit_logs table; if it doesn't exist, skip
    const { error } = await supabaseAdmin.from("audit_logs").insert({
      action: params.action,
      user_id: params.user_id || null,
      user_name: params.user_name || null,
      resource_type: params.resource_type || null,
      resource_id: params.resource_id || null,
      detail: params.detail || null,
      correlation_id: params.correlation_id || createCorrelationId(),
    });

    if (error) {
      console.error(`[Audit] write failed: ${error.message}`);
    }
  } catch {
    console.error("[Audit] write failed: unexpected error");
  }
}

export async function logLlmCall(params: {
  model: string;
  prompt_type: string;
  tokens_used?: number;
  latency_ms?: number;
  was_fallback?: boolean;
  cached?: boolean;
  correlation_id: string;
}) {
  try {
    if (!supabaseAdmin) return;
    await supabaseAdmin.from("audit_logs").insert({
      action: "llm_call" as AuditAction,
      resource_type: "llm",
      detail: {
        model: params.model,
        prompt_type: params.prompt_type,
        tokens_used: params.tokens_used || 0,
        latency_ms: params.latency_ms || 0,
        was_fallback: params.was_fallback || false,
        cached: params.cached || false,
      },
      correlation_id: params.correlation_id,
    });
  } catch {
    // Silently skip
  }
}
