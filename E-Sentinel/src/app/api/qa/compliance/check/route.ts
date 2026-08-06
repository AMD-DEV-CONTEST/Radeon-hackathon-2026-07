import { NextRequest } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { scanCompliance, quickComplianceCheck, type ComplianceRule } from "@/lib/compliance-engine";
import { learnFromComplianceBlock } from "@/lib/compliance-learner";
import { logAudit } from "@/lib/audit";
import { createCorrelationId } from "@/lib/correlation";
import { sendFeishuNotification, sendFeishuGroupCard, isFeishuEnabled } from "@/lib/feishu";
import { apiOk, apiErr } from "@/lib/api-response";

const isDifyMode = !isFeishuEnabled();

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const content = String(body.content || "");
    const sourceType = String(body.source_type || "chat_message");
    const sourceId = body.source_id || null;

    if (!content || content.length < 3) {
      return apiOk({ passed: true, decision: "passed", matches: [], summary: "Content too short for compliance check." });
    }

    const correlationId = createCorrelationId("cmp");

    // Load rules from DB, fall back to built-in
    let rules: ComplianceRule[] = [];
    if (supabaseAdmin) {
      const { data } = await supabaseAdmin
        .from("compliance_rules")
        .select("id, rule_text, pattern, risk_level, category, action_type, exemption_tags")
        .eq("is_active", true)
        .order("risk_level", { ascending: true });

      if (data && data.length > 0) {
        rules = data.map((r: Record<string, unknown>) => ({
          id: String(r.id),
          rule_text: String(r.rule_text),
          pattern: String(r.pattern),
          risk_level: Number(r.risk_level),
          category: String(r.category),
          action_type: String(r.action_type) as ComplianceRule["action_type"],
          exemption_tags: Array.isArray(r.exemption_tags) ? r.exemption_tags.map(String) : [],
        }));
      }
    }

    const result = rules.length > 0
      ? scanCompliance(content, rules)
      : quickComplianceCheck(content);

    // Log the compliance check
    if (supabaseAdmin) {
      await supabaseAdmin.from("compliance_audit_logs").insert({
        source_type: sourceType,
        source_id: sourceId,
        content_snippet: content.substring(0, 200),
        risk_level: result.highest_risk || null,
        matched_rules: result.matches.map((m) => ({
          rule_id: m.rule.id,
          rule_text: m.rule.rule_text,
          category: m.rule.category,
          action_type: m.rule.action_type,
        })),
        decision: result.decision,
        correlation_id: correlationId,
      });
    }

    await logAudit({
      action: result.decision === "blocked"
        ? "compliance_block"
        : result.decision === "flagged"
          ? "compliance_warn"
          : "compliance_pass",
      resource_type: sourceType,
      resource_id: sourceId,
      detail: {
        highest_risk: result.highest_risk,
        match_count: result.matches.length,
        summary: result.summary,
      },
      correlation_id: correlationId,
    });

    // Convert blocked events to Few-Shot training data
    if (!result.passed && result.highest_risk <= 2) {
      learnFromComplianceBlock({
        compliance_log_id: correlationId,
        source_type: sourceType,
        content_snippet: content.substring(0, 500),
        risk_level: result.highest_risk,
        matched_rules: result.matches.map((m) => ({
          rule_id: String(m.rule.id),
          rule_text: m.rule.rule_text,
          category: m.rule.category,
        })),
        decision: result.decision,
      });
    }

    // Feishu alert for fatal/high — disabled in Dify mode (稳定使用优先)
    if (!isDifyMode && !result.passed && result.highest_risk <= 2) {
      const fatalMatches = result.matches.filter((m) => m.rule.risk_level <= 2);
      sendFeishuNotification({
        header: {
          title: {
            tag: "plain_text",
            content: result.highest_risk === 1
              ? `🔴 致命合规风险 — 已拦截`
              : `🟠 高风险合规问题 — 已拦截`,
          },
          template: result.highest_risk === 1 ? "red" : "orange",
        },
        elements: [
          {
            tag: "div",
            text: {
              tag: "lark_md",
              content: [
                `**来源类型：** ${sourceType}`,
                `**风险等级：** ${result.highest_risk === 1 ? "致命" : "高风险"}`,
                `**违规项：**`,
                ...fatalMatches.map((m) => `- [${m.rule.category}] ${m.rule.rule_text}\n  > 匹配: "${m.matched_text}"`),
                "",
                `**检查内容片段：** ${content.substring(0, 150)}...`,
              ].join("\n"),
            },
          },
        ],
      }).catch(() => {});
    }

    // Push compliance card to group chat — disabled in Dify mode
    if (!isDifyMode && !result.passed) {
      const riskLabel = result.highest_risk === 1 ? "🔴 致命" : result.highest_risk === 2 ? "🟠 高风险" : result.highest_risk === 3 ? "🟡 中风险" : "🔵 低风险";
      const riskMatches = result.matches.slice(0, 5);
      sendFeishuGroupCard({
        header: { title: { tag: "plain_text", content: `⚠️ ${riskLabel}合规风险` }, template: result.highest_risk <= 2 ? "red" : "yellow" },
        elements: [
          { tag: "div", text: { tag: "lark_md", content: `**扫描内容：** ${content.substring(0, 200)}\n\n**违规项：**\n${riskMatches.map((m) => `- [${m.rule.category}] ${m.rule.rule_text}`).join("\n")}` } },
          { tag: "hr" },
          { tag: "action", actions: [{
            tag: "button", text: { tag: "plain_text", content: "🔧 误判驳回" }, type: "danger",
            value: JSON.stringify({ action: "compliance_overturn", check_id: correlationId, reason: "人工复核误判" }),
          }]},
        ],
      }).catch(() => {});
    }

    return apiOk(result as unknown as Record<string, unknown>);
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[Compliance Check] POST error:", message);
    return apiErr(message, "INTERNAL_ERROR", 500);
  }
}
