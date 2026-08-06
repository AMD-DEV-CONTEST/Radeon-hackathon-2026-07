// Compliance dynamic learning system.
// Converts blocked compliance events into Few-Shot training data,
// and adjusts rule weights based on human review outcomes.

import { supabaseAdmin } from "./supabase";
import { textToEmbedding, embeddingToPgVector } from "./embedding";

export interface ComplianceLearningEvent {
  compliance_log_id: string;
  source_type: string;
  content_snippet: string;
  risk_level: number;
  matched_rules: Array<{ rule_id: string; rule_text: string; category: string }>;
  decision: string;
  human_review?: {
    upheld: boolean;       // was the block confirmed?
    reviewer_id?: string;
    notes?: string;
  };
}

/**
 * After a compliance block, convert it to a correction_sample for Few-Shot learning.
 * Only fatal (level 1) and high (level 2) blocks are converted.
 */
export async function learnFromComplianceBlock(event: ComplianceLearningEvent): Promise<void> {
  if (!supabaseAdmin) return;

  // Only learn from fatal/high risk blocks
  if (event.risk_level > 2) return;

  try {
    const contentHash = simpleHash(event.content_snippet);
    const embedding = textToEmbedding(event.content_snippet);

    await supabaseAdmin.from("correction_samples").insert({
      conversation: event.content_snippet,
      conversation_hash: contentHash,
      ai_prediction: { type: "compliance_auto_block", risk_level: event.risk_level },
      human_correction: {
        type: "compliance_confirmed",
        rules: event.matched_rules.map((r) => r.rule_text),
        decision: event.decision,
        human_review: event.human_review || null,
      },
      correction_type: "compliance",
      embedding: embeddingToPgVector(embedding),
    });
  } catch (err) {
    console.error("[ComplianceLearning] Failed to create correction sample:", err);
  }
}

/**
 * Adjust rule weights based on human review outcomes.
 * Rules that are frequently overridden get reduced weight.
 */
export async function adjustRuleWeights(): Promise<void> {
  if (!supabaseAdmin) return;

  try {
    // Get rules with their match and override counts
    const { data: rules } = await supabaseAdmin
      .from("compliance_rules")
      .select("id, rule_text, match_count, is_active");

    if (!rules || rules.length === 0) return;

    for (const rule of rules as Array<Record<string, unknown>>) {
      // Count human overrides for this rule (from compliance_audit_logs where decision was overridden)
      const { count: overrideCount } = await supabaseAdmin
        .from("compliance_audit_logs")
        .select("*", { count: "exact", head: true })
        .contains("matched_rules", JSON.stringify([{ rule_id: rule.id }]))
        .not("review_notes", "is", null);

      const totalMatches = Number(rule.match_count) || 0;
      const overrides = overrideCount || 0;

      // If >30% of matches were overridden by humans, flag for review
      if (totalMatches > 10 && overrides / totalMatches > 0.3) {
        console.log(`[ComplianceLearning] Rule ${rule.rule_text} has high override rate: ${(overrides / totalMatches * 100).toFixed(1)}%`);
        // Deactivate rules with >50% override rate
        if (overrides / totalMatches > 0.5) {
          await supabaseAdmin
            .from("compliance_rules")
            .update({ is_active: false, updated_at: new Date().toISOString() })
            .eq("id", rule.id);
          console.log(`[ComplianceLearning] Auto-deactivated rule: ${rule.rule_text}`);
        }
      }
    }
  } catch (err) {
    console.error("[ComplianceLearning] Failed to adjust rule weights:", err);
  }
}

function simpleHash(str: string): string {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    const char = str.charCodeAt(i);
    hash = ((hash << 5) - hash) + char;
    hash |= 0;
  }
  return Math.abs(hash).toString(16);
}

/** Generate a compliance audit report */
export async function generateComplianceReport(days: number = 7): Promise<{
  period: string;
  total_checks: number;
  blocked: number;
  flagged: number;
  passed: number;
  top_rules: Array<{ rule_text: string; match_count: number }>;
}> {
  if (!supabaseAdmin) {
    return { period: `${days}d`, total_checks: 0, blocked: 0, flagged: 0, passed: 0, top_rules: [] };
  }

  const cutoff = new Date(Date.now() - days * 86400000).toISOString();
  const { data: logs } = await supabaseAdmin
    .from("compliance_audit_logs")
    .select("decision, matched_rules")
    .gte("created_at", cutoff);

  const items = (logs || []) as Array<{ decision: string; matched_rules: Array<{ rule_text: string }> }>;
  const blocked = items.filter((l) => l.decision === "blocked").length;
  const flagged = items.filter((l) => l.decision === "flagged").length;
  const passed = items.filter((l) => l.decision === "passed").length;

  // Count top matched rules
  const ruleCounts = new Map<string, number>();
  for (const log of items) {
    for (const m of log.matched_rules || []) {
      ruleCounts.set(m.rule_text, (ruleCounts.get(m.rule_text) || 0) + 1);
    }
  }
  const topRules = Array.from(ruleCounts.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10)
    .map(([rule_text, match_count]) => ({ rule_text, match_count }));

  return { period: `${days}d`, total_checks: items.length, blocked, flagged, passed, top_rules: topRules };
}
