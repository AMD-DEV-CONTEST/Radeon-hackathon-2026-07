// ============================================================================
// Unresolved Questions Export API
// 导出未解决问题为CSV/JSON/Markdown格式，供话术训练系统使用
// ============================================================================

import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { logAudit } from "@/lib/audit";
import { createCorrelationId } from "@/lib/correlation";
import { csvEscape, htmlEscape, toExportRecord } from "@/lib/unresolved-questions";
import { authorizeGovernanceRequest } from "@/lib/governance/authorization";

function toPublicError(error: unknown): { message: string; status: number } {
  const err = error as { code?: string; message?: string };
  if (err?.code === "PGRST205" || err?.message?.includes("unresolved_questions")) {
    return {
      message: "unresolved_questions table is not ready. Please run supabase/migration-015-unresolved-questions.sql first.",
      status: 503,
    };
  }
  return { message: error instanceof Error ? error.message : "internal_error", status: 500 };
}

export async function GET(request: Request) {
  const authorization = await authorizeGovernanceRequest(request, { mutation: true });
  if (authorization.error) return authorization.error;
  const tenantId = authorization.context?.tenantId;
  if (!tenantId) return NextResponse.json({ error: "Tenant scope required" }, { status: 403 });

  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { searchParams } = new URL(request.url);
    const format = searchParams.get("format") || "json";
    const status = searchParams.get("status") || "pending";
    const category = searchParams.get("category");
    const limit = Math.min(parseInt(searchParams.get("limit") || "200"), 1000);

    let query = supabaseAdmin
      .from("unresolved_questions")
      .select("id, session_id, platform_code, user_question, ai_reply, transfer_reason, conversation, category, status, created_at")
      .order("priority", { ascending: false })
      .order("created_at", { ascending: false })
      .limit(limit)
      .eq("tenant_id", tenantId);

    if (status !== "all") query = query.eq("status", status);
    if (category) query = query.eq("category", category);

    const { data, error } = await query;
    if (error) throw error;

    if (!data || data.length === 0) {
      return NextResponse.json({ entries: [], message: "No unresolved questions to export" });
    }

    const validFormats = ["json", "csv", "markdown", "excel", "xls"];
    const fmt = validFormats.includes(format) ? format : "json";
    const exportRows = (data || []).map(toExportRecord);

    await logAudit({
      action: "unresolved_questions_export",
      resource_type: "unresolved_questions",
      detail: { format: fmt, count: data.length },
      correlation_id: createCorrelationId("export"),
    });

    // 更新导出的条目为 exported 状态
    const ids = data.map((d: Record<string, unknown>) => d.id);
    await supabaseAdmin
      .from("unresolved_questions")
      .update({ status: "exported" })
      .eq("tenant_id", tenantId)
      .in("id", ids);

    // 写操作日志
    for (const id of ids) {
      await supabaseAdmin.from("unresolved_question_logs").insert({
        unresolved_id: id,
        action: "export",
        detail: { format: fmt },
      });
    }

    if (fmt === "csv") {
      const headers = ["记录ID", "会话ID", "渠道", "用户原话", "问题类型", "AI回复", "AI已排查步骤", "未解决原因", "状态", "创建时间"];
      const rows = exportRows.map((row) => headers.map((header) => csvEscape(row[header])).join(","));
      const csv = `\uFEFF${[headers.join(","), ...rows].join("\r\n")}`;
      return new NextResponse(csv, {
        headers: {
          "Content-Type": "text/csv; charset=utf-8",
          "Content-Disposition": `attachment; filename="unresolved_questions_${new Date().toISOString().slice(0, 10)}.csv"`,
        },
      });
    }

    if (fmt === "excel" || fmt === "xls") {
      const headers = ["记录ID", "会话ID", "渠道", "用户原话", "问题类型", "AI回复", "AI已排查步骤", "未解决原因", "状态", "创建时间"];
      const tableRows = exportRows.map((row) => (
        `<tr>${headers.map((header) => `<td>${htmlEscape(row[header])}</td>`).join("")}</tr>`
      )).join("");
      const html = `<!doctype html>
<html>
<head>
  <meta charset="UTF-8" />
  <style>
    table { border-collapse: collapse; }
    th, td { border: 1px solid #999; padding: 6px; mso-number-format:"\\@"; }
    th { background: #f2f2f2; }
  </style>
</head>
<body>
  <table>
    <thead><tr>${headers.map((header) => `<th>${htmlEscape(header)}</th>`).join("")}</tr></thead>
    <tbody>${tableRows}</tbody>
  </table>
</body>
</html>`;
      return new NextResponse(html, {
        headers: {
          "Content-Type": "application/vnd.ms-excel; charset=utf-8",
          "Content-Disposition": `attachment; filename="unresolved_questions_${new Date().toISOString().slice(0, 10)}.xls"`,
        },
      });
    }

    if (fmt === "markdown") {
      let md = `# AI未解决问题导出\n\n导出时间: ${new Date().toLocaleString("zh-CN")}\n总数: ${data.length}\n\n`;
      for (const row of exportRows) {
        md += `## ${row["用户原话"]}\n\n`;
        md += `- **会话ID**: ${row["会话ID"]}\n`;
        md += `- **渠道**: ${row["渠道"]}\n`;
        md += `- **问题类型**: ${row["问题类型"]}\n`;
        md += `- **未解决原因**: ${row["未解决原因"] || "未填写"}\n`;
        md += `- **时间**: ${row["创建时间"]}\n`;
        if (row["AI已排查步骤"]) md += `\n**AI已排查步骤**:\n${row["AI已排查步骤"]}\n`;
        if (row["AI回复"]) md += `\n**AI回复**:\n${row["AI回复"]}\n`;
        md += `\n---\n\n`;
      }
      return new NextResponse(md, {
        headers: {
          "Content-Type": "text/markdown; charset=utf-8",
          "Content-Disposition": `attachment; filename="unresolved_questions_${new Date().toISOString().slice(0, 10)}.md"`,
        },
      });
    }

    // Default: JSON
    return NextResponse.json({ entries: data, exported_count: data.length });
  } catch (error) {
    const { message, status } = toPublicError(error);
    console.error("[Unresolved Export] Error:", message);
    return NextResponse.json({ error: message }, { status });
  }
}
