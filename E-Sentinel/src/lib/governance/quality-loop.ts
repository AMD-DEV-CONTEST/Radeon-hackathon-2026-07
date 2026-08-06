import { supabaseAdmin } from "@/lib/supabase";
import { EVIDENCE_EVENT_VERSION } from "./evidence-event";

export interface QualityViolation {
  category?: string;
  rule?: string;
  deduction?: number;
  severity?: string;
  source_quote?: string;
}

export interface QualityEvaluationInput {
  reportId: string;
  tenantId: string;
  teamId?: string | null;
  ticketId: string;
  correlationId: string;
  conversationLength: number;
  intent: string;
  sentimentScore: number;
  totalScore: number;
  riskLevel: "low" | "medium" | "high" | "critical";
  violations: QualityViolation[];
  summary?: string;
  reviewMode: "shadow" | "active";
  reviewerId?: string | null;
  rulesExcerpt?: string;
  modelVersion?: string;
}

export interface QualityLoopResult {
  evaluationId: string | null;
  findingIds: string[];
  workItemIds: string[];
  persisted: boolean;
}

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function isUuid(value: string | null | undefined): value is string {
  return Boolean(value && UUID_PATTERN.test(value));
}

export function qualityDecision(
  riskLevel: QualityEvaluationInput["riskLevel"],
  reviewMode: QualityEvaluationInput["reviewMode"],
): "pass" | "review" | "block" {
  if (reviewMode === "shadow") return "review";
  if (riskLevel === "critical") return "block";
  if (riskLevel === "high" || riskLevel === "medium") return "review";
  return "pass";
}

export function qualityEvidenceRefs(violations: QualityViolation[]): Array<Record<string, unknown>> {
  return violations
    .filter((violation) => typeof violation.source_quote === "string" && violation.source_quote.trim())
    .slice(0, 20)
    .map((violation) => ({
      type: "conversation_quote",
      category: violation.category || "unknown",
      rule: violation.rule || "unknown",
      quote: violation.source_quote!.trim().slice(0, 500),
    }));
}

function findingSeverity(violation: QualityViolation, riskLevel: QualityEvaluationInput["riskLevel"]): "info" | "minor" | "major" | "critical" {
  if (violation.severity === "critical" || riskLevel === "critical") return "critical";
  if (violation.severity === "major" || riskLevel === "high") return "major";
  if (violation.severity === "minor") return "minor";
  return "info";
}

function workItemPriority(severity: "info" | "minor" | "major" | "critical"): "low" | "medium" | "high" | "critical" {
  if (severity === "critical") return "critical";
  if (severity === "major") return "high";
  if (severity === "minor") return "medium";
  return "low";
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** Persist the layered QA decision without making the legacy report path fail closed. */
export async function persistQualityEvaluation(input: QualityEvaluationInput): Promise<QualityLoopResult> {
  const empty: QualityLoopResult = { evaluationId: null, findingIds: [], workItemIds: [], persisted: false };
  if (!supabaseAdmin) return empty;

  try {
    const evidenceRefs = qualityEvidenceRefs(input.violations);
    const decision = qualityDecision(input.riskLevel, input.reviewMode);
    const eventKey = `qa-evaluation:${input.reportId}`;
    let eventDbId: string | null = null;

    const { data: insertedEvent, error: eventError } = await supabaseAdmin
      .from("evidence_events")
      .insert({
        event_id: eventKey,
        idempotency_key: `qa-system:${eventKey}`,
        schema_version: EVIDENCE_EVENT_VERSION,
        tenant_id: input.tenantId,
        team_id: input.teamId || null,
        source: "qa-system",
        event_type: "quality.evaluation.completed",
        occurred_at: new Date().toISOString(),
        actor_id: "qa-system",
        actor_type: "system",
        correlation_id: input.correlationId,
        payload_ref: input.reportId,
        payload: {
          report_id: input.reportId,
          ticket_id: input.ticketId,
          risk_level: input.riskLevel,
          review_mode: input.reviewMode,
        },
      })
      .select("id")
      .maybeSingle();

    if (insertedEvent?.id) {
      eventDbId = insertedEvent.id as string;
    } else if (eventError?.code === "23505") {
      const { data: existingEvent } = await supabaseAdmin
        .from("evidence_events")
        .select("id")
        .eq("event_id", eventKey)
        .maybeSingle();
      eventDbId = (existingEvent?.id as string | undefined) || null;
    } else if (eventError) {
      console.error(`[QualityLoop] Evidence event write failed: ${eventError.message}`);
    }

    const { data: existingEvaluation } = await supabaseAdmin
      .from("evaluations")
      .select("id")
      .eq("tenant_id", input.tenantId)
      .eq("subject_type", "quality_report")
      .eq("subject_id", input.reportId)
      .eq("rule_version", "qa-quality-standard-v1.0")
      .maybeSingle();

    let evaluationId = (existingEvaluation?.id as string | undefined) || null;
    if (evaluationId) {
      const { data: existingFindings } = await supabaseAdmin
        .from("findings")
        .select("id")
        .eq("evaluation_id", evaluationId);
      const existingFindingIds = (existingFindings || [])
        .map((finding: { id?: unknown }) => finding.id)
        .filter((id): id is string => typeof id === "string");
      if (existingFindingIds.length > 0 || input.violations.length === 0) {
        const { data: existingWorkItems } = existingFindingIds.length > 0
          ? await supabaseAdmin
            .from("governance_work_items")
            .select("id")
            .in("source_finding_id", existingFindingIds)
          : { data: [] as Array<{ id: string }> };
        return {
          evaluationId,
          findingIds: existingFindingIds,
          workItemIds: (existingWorkItems || [])
            .map((item: { id?: unknown }) => item.id)
            .filter((id): id is string => typeof id === "string"),
          persisted: true,
        };
      }
    }
    if (!evaluationId) {
      const { data: evaluation, error: evaluationError } = await supabaseAdmin
        .from("evaluations")
        .insert({
          tenant_id: input.tenantId,
          team_id: input.teamId || null,
          subject_type: "quality_report",
          subject_id: input.reportId,
          event_id: eventDbId,
          rule_version: "qa-quality-standard-v1.0",
          model_version: input.modelVersion || process.env.LLM_MODEL_VERSION || process.env.DEEPSEEK_MODEL || "auto",
          score: input.totalScore,
          risk: input.riskLevel,
          explanations: {
            facts: {
              ticket_id: input.ticketId,
              conversation_length: input.conversationLength,
              intent: input.intent,
              sentiment_score: input.sentimentScore,
            },
            rules: {
              version: "qa-quality-standard-v1.0",
              excerpt: (input.rulesExcerpt || "").slice(0, 1000),
            },
            model: {
              summary: input.summary || "",
              violation_count: input.violations.length,
            },
            decision: {
              value: decision,
              review_mode: input.reviewMode,
            },
          },
          evidence_refs: evidenceRefs,
          decision,
          correlation_id: input.correlationId,
        })
        .select("id")
        .maybeSingle();

      if (evaluationError || !evaluation?.id) {
        console.error(`[QualityLoop] Evaluation write failed: ${evaluationError?.message || "missing id"}`);
        return empty;
      }
      evaluationId = evaluation.id as string;
    }

    const findingIds: string[] = [];
    const workItemIds: string[] = [];
    for (const violation of input.violations) {
      const severity = findingSeverity(violation, input.riskLevel);
      const { data: finding, error: findingError } = await supabaseAdmin
        .from("findings")
        .insert({
          tenant_id: input.tenantId,
          evaluation_id: evaluationId,
          severity,
          category: (violation.category || "quality").slice(0, 128),
          evidence_refs: qualityEvidenceRefs([violation]),
        })
        .select("id")
        .maybeSingle();

      if (findingError || !finding?.id) {
        console.error(`[QualityLoop] Finding write failed: ${findingError?.message || "missing id"}`);
        continue;
      }

      const findingId = finding.id as string;
      findingIds.push(findingId);
      if (severity !== "critical" && severity !== "major") continue;

      const { data: workItem, error: workItemError } = await supabaseAdmin
        .from("governance_work_items")
        .insert({
          tenant_id: input.tenantId,
          team_id: input.teamId || null,
          source_finding_id: findingId,
          source_type: "finding",
          source_id: findingId,
          title: `[客服质检] ${(violation.rule || violation.category || "需要复核").slice(0, 120)}`,
          description: (violation.source_quote || input.summary || "客服回复存在待处理质量问题").slice(0, 2000),
          owner_id: isUuid(input.reviewerId) ? input.reviewerId : null,
          priority: workItemPriority(severity),
        })
        .select("id")
        .maybeSingle();

      if (!workItemError && workItem?.id) workItemIds.push(workItem.id as string);
      if (workItemError && workItemError.code !== "23505") {
        console.error(`[QualityLoop] Work item write failed: ${workItemError.message}`);
      }
    }

    return { evaluationId, findingIds, workItemIds, persisted: true };
  } catch (error) {
    console.error(`[QualityLoop] Persist failed: ${errorMessage(error)}`);
    return empty;
  }
}

export async function recordQualityOverturn(params: {
  reportId: string;
  tenantId: string;
  approverId?: string | null;
  reason: string;
  correlationId?: string;
}): Promise<{ evaluationUpdated: boolean; findingsUpdated: boolean; approvalSaved: boolean }> {
  const result = { evaluationUpdated: false, findingsUpdated: false, approvalSaved: false };
  if (!supabaseAdmin) return result;

  try {
    const { data: evaluation } = await supabaseAdmin
      .from("evaluations")
      .select("id")
      .eq("tenant_id", params.tenantId)
      .eq("subject_type", "quality_report")
      .eq("subject_id", params.reportId)
      .order("created_at", { ascending: false })
      .limit(1)
      .maybeSingle();

    if (evaluation?.id) {
      const evaluationUpdate = await supabaseAdmin
        .from("evaluations")
        .update({ decision: "override" })
        .eq("id", evaluation.id);
      result.evaluationUpdated = !evaluationUpdate.error;

      const findingsUpdate = await supabaseAdmin
        .from("findings")
        .update({ decision: "rejected", review_status: "overturned" })
        .eq("evaluation_id", evaluation.id);
      result.findingsUpdated = !findingsUpdate.error;

      const { data: findings } = await supabaseAdmin
        .from("findings")
        .select("id")
        .eq("evaluation_id", evaluation.id);
      const findingIds = (findings || [])
        .map((finding: { id?: unknown }) => finding.id)
        .filter((id): id is string => typeof id === "string");
      if (findingIds.length > 0) {
        await supabaseAdmin
          .from("governance_work_items")
          .update({
            status: "closed",
            close_evidence: { reason: params.reason, decision: "overturned", approver_id: params.approverId || null },
            closed_at: new Date().toISOString(),
          })
          .eq("tenant_id", params.tenantId)
          .eq("source_type", "finding")
          .in("status", ["open", "in_progress", "blocked"])
          .in("source_finding_id", findingIds);
      }
    }

    if (isUuid(params.approverId)) {
      const { error: approvalError } = await supabaseAdmin.from("approvals").insert({
        tenant_id: params.tenantId,
        action_type: "quality_report_overturn",
        subject_type: "quality_report",
        subject_id: params.reportId,
        approver_id: params.approverId,
        decision: "approved",
        reason: params.reason,
        correlation_id: params.correlationId || `overturn:${params.reportId}`,
        decided_at: new Date().toISOString(),
      });
      result.approvalSaved = !approvalError;
      if (approvalError) console.error(`[QualityLoop] Approval write failed: ${approvalError.message}`);
    }
  } catch (error) {
    console.error(`[QualityLoop] Overturn persistence failed: ${errorMessage(error)}`);
  }

  return result;
}
