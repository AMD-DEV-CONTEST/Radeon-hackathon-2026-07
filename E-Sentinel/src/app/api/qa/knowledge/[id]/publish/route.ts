import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { logAudit } from "@/lib/audit";
import { createCorrelationId } from "@/lib/correlation";
import { scanCompliance, quickComplianceCheck, type ComplianceRule } from "@/lib/compliance-engine";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { id } = await params;

    // Get the entry to verify it exists and is in draft
    const { data: entry, error: fetchErr } = await supabaseAdmin
      .from("knowledge_entries")
      .select("id, title, content, status, version")
      .eq("id", id)
      .single();

    if (fetchErr || !entry) {
      return NextResponse.json({ error: "Knowledge entry not found" }, { status: 404 });
    }

    if (entry.status !== "draft") {
      return NextResponse.json({ error: `Cannot publish: entry is in "${entry.status}" status` }, { status: 400 });
    }

    // ── Compliance scan before publish ──
    const contentToCheck = `${entry.title} ${String(entry.content || "")}`;
    let rules: ComplianceRule[] = [];
    const { data: dbRules } = await supabaseAdmin
      .from("compliance_rules")
      .select("id, rule_text, pattern, risk_level, category, action_type, exemption_tags")
      .eq("is_active", true);

    if (dbRules && dbRules.length > 0) {
      rules = dbRules.map((r: Record<string, unknown>) => ({
        id: String(r.id),
        rule_text: String(r.rule_text),
        pattern: String(r.pattern),
        risk_level: Number(r.risk_level),
        category: String(r.category),
        action_type: String(r.action_type) as ComplianceRule["action_type"],
        exemption_tags: Array.isArray(r.exemption_tags) ? r.exemption_tags.map(String) : [],
      }));
    }

    const complianceResult = rules.length > 0
      ? scanCompliance(contentToCheck, rules)
      : quickComplianceCheck(contentToCheck);

    if (complianceResult.decision === "blocked") {
      return NextResponse.json({
        error: "Compliance check failed",
        compliance: {
          blocked: true,
          highest_risk: complianceResult.highest_risk,
          summary: complianceResult.summary,
          matches: complianceResult.matches.map((m) => ({
            rule: m.rule.rule_text,
            category: m.rule.category,
            matched: m.matched_text,
          })),
        },
      }, { status: 422 });
    }

    const correlationId = createCorrelationId("kn");

    const { error: updateErr } = await supabaseAdmin
      .from("knowledge_entries")
      .update({ status: "published", updated_at: new Date().toISOString() })
      .eq("id", id);

    if (updateErr) throw updateErr;

    // Log the publish action
    await supabaseAdmin.from("knowledge_update_logs").insert({
      knowledge_id: id,
      update_type: "publish",
      field_changed: "status",
      old_value: "draft",
      new_value: "published",
      correlation_id: correlationId,
    });

    await logAudit({
      action: "knowledge_publish",
      resource_type: "knowledge_entries",
      resource_id: id,
      detail: {
        title: entry.title,
        compliance_passed: complianceResult.passed,
        compliance_risk: complianceResult.highest_risk,
      },
      correlation_id: correlationId,
    });

    return NextResponse.json({
      success: true,
      entry: { ...entry, status: "published" },
      compliance: complianceResult.passed ? undefined : {
        flagged: complianceResult.decision === "flagged",
        risk_level: complianceResult.highest_risk,
        summary: complianceResult.summary,
      },
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[Knowledge Publish] POST error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
