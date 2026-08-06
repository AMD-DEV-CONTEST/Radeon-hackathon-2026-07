import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { logAudit } from "@/lib/audit";
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

    // Get the draft config
    const { data: draft, error: fetchErr } = await supabaseAdmin
      .from("bot_configs")
      .select("id, platform_id, config_type, config_key, status, version, config_value")
      .eq("id", id)
      .single();

    if (fetchErr || !draft) {
      return NextResponse.json({ error: "Config not found" }, { status: 404 });
    }

    if (draft.status !== "draft") {
      return NextResponse.json({ error: `Cannot publish: config is in "${draft.status}" status` }, { status: 400 });
    }

    // ── Compliance scan before publish ──
    const configText = typeof draft.config_value === "string"
      ? draft.config_value
      : JSON.stringify(draft.config_value);
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
      ? scanCompliance(configText, rules)
      : quickComplianceCheck(configText);

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

    // Archive current active version
    await supabaseAdmin
      .from("bot_configs")
      .update({ status: "archived" })
      .eq("platform_id", draft.platform_id)
      .eq("config_type", draft.config_type)
      .eq("config_key", draft.config_key)
      .eq("status", "active");

    // Activate the draft
    const { error: updateErr } = await supabaseAdmin
      .from("bot_configs")
      .update({ status: "active", updated_at: new Date().toISOString() })
      .eq("id", id);

    if (updateErr) throw updateErr;

    // Snapshot pre-publish effect metrics
    try { await supabaseAdmin.rpc("snapshot_bot_config_effect", { p_config_id: id }); } catch { /* skip if function doesn't exist yet */ }

    await logAudit({
      action: "bot_config_publish",
      resource_type: "bot_configs",
      resource_id: id,
      detail: {
        config_key: draft.config_key,
        config_type: draft.config_type,
        version: draft.version,
        compliance_passed: complianceResult.passed,
        compliance_risk: complianceResult.highest_risk,
      },
    });

    return NextResponse.json({
      success: true,
      config: { ...draft, status: "active" },
      compliance: complianceResult.passed ? undefined : {
        flagged: complianceResult.decision === "flagged",
        risk_level: complianceResult.highest_risk,
        summary: complianceResult.summary,
      },
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[BotConfigs Publish] POST error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
