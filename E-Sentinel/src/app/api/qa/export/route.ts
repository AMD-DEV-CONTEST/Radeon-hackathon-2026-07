import { NextResponse } from "next/server";
import { requireAuth, guardPublic } from "@/lib/api-auth";
import { supabaseAdmin } from "@/lib/supabase";

// ── Sensitive data masking ──

const maskSensitive = (val: string): string => val
  .replace(/(1[3-9]\d)\d{4}(\d{4})/g, '$1****$2')
  .replace(/(\d{6})\d{8}(\d{4})/g, '$1********$2')
  .replace(/([a-zA-Z0-9._%+-]{1,3})[a-zA-Z0-9._%+-]*@/g, '$1***@');

function maskedValue(val: unknown): string {
  if (val === null || val === undefined) return "";
  const s = typeof val === "object" ? JSON.stringify(val) : String(val);
  return maskSensitive(s);
}

// ── CSV helpers ──

function toCsv(rows: Record<string, unknown>[]): string {
  if (rows.length === 0) return "";
  const headers = Object.keys(rows[0]);
  const lines = [headers.join(",")];
  for (const row of rows) {
    const values = headers.map((h) => {
      const s = maskedValue(row[h]);
      if (s.includes(",") || s.includes('"') || s.includes("\n")) {
        return `"${s.replace(/"/g, '""')}"`;
      }
      return s;
    });
    lines.push(values.join(","));
  }
  return lines.join("\n");
}

// ── XLS (HTML table) helper — Excel opens HTML tables natively ──

function escapeXml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function toXls(rows: Record<string, unknown>[]): string {
  if (rows.length === 0) return "";
  const headers = Object.keys(rows[0]);
  const headerRow = `<tr>${headers.map((h) => `<th>${escapeXml(h)}</th>`).join("")}</tr>`;
  const dataRows = rows
    .map((row) =>
      `<tr>${headers.map((h) => `<td>${escapeXml(maskedValue(row[h]))}</td>`).join("")}</tr>`,
    )
    .join("");
  return [
    `<?xml version="1.0"?>`,
    `<html xmlns="http://www.w3.org/1999/xhtml">`,
    `<head><meta charset="UTF-8"/></head>`,
    `<body><table border="1">${headerRow}${dataRows}</table></body>`,
    `</html>`,
  ].join("");
}

// ── Table column whitelists — export-only useful columns ──

const TABLE_COLUMNS: Record<string, string> = {
  quality_reports:
    "id,ticket_id,agent_id,total_score,risk_level,sentiment_score,violations,intent,status,review_mode,correlation_id,created_at",
  bot_chat_sessions:
    "id,platform_id,external_session_id,session_type,customer_id,bot_handled,transfer_reason,is_inquiry,inquiry_result,satisfaction,sentiment_score,total_messages,first_response_ms,resolution_ms,tags,correlation_id,created_at",
  work_orders:
    "id,title,description,status,priority,category,source,source_id,assigned_to,platform_id,created_at",
};

const TABLE_NAMES: Record<string, string> = {
  quality_reports: "质检报告",
  bot_chat_sessions: "会话数据",
  work_orders: "工单",
};

const ALLOWED_TABLES = Object.keys(TABLE_COLUMNS);

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const auth = await requireAuth(request);
  if (auth.error) return auth.error;

  const guardErr = guardPublic(request, {});
  if (guardErr) return guardErr;

  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { searchParams } = new URL(request.url);
    const table = searchParams.get("table") || "";
    const format = searchParams.get("format") || "csv";
    const limit = Math.min(
      parseInt(searchParams.get("limit") || "500"),
      5000,
    );

    // Default date range: last 7 days
    const defaultFrom = new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10);
    const defaultTo = new Date().toISOString().slice(0, 10);
    const dateFrom = searchParams.get("from") || "";
    const dateTo = searchParams.get("to") || "";

    if (!ALLOWED_TABLES.includes(table)) {
      return NextResponse.json(
        { error: `Invalid table. Allowed: ${ALLOWED_TABLES.join(", ")}` },
        { status: 400 },
      );
    }

    const columns = TABLE_COLUMNS[table];

    let query = supabaseAdmin
      .from(table)
      .select(columns)
      .order("created_at", { ascending: false })
      .limit(limit);

    if (dateFrom) query = query.gte("created_at", dateFrom);
    if (dateTo) query = query.lte("created_at", dateTo + "T23:59:59.999Z");

    const { data, error } = await query;

    if (error) {
      console.error(`[Export] ${table} query error:`, error.message);
      return NextResponse.json({ error: error.message }, { status: 500 });
    }

    const rows = (data || []) as unknown as Record<string, unknown>[];

    // ── Standardized file naming: {表名}_{开始日期}_{结束日期}.{格式} ──
    const fromDate = (dateFrom || defaultFrom).replace(/-/g, "");
    const toDate = (dateTo || defaultTo).replace(/-/g, "");
    const displayName = TABLE_NAMES[table] || table;
    const ext = format === "xlsx" ? "xls" : format; // HTML-table xls fallback
    const filename = `${displayName}_${fromDate}_${toDate}.${ext}`;
    const encodedFilename = encodeURIComponent(filename);

    // ── Progress hint for large exports (>200 rows) ──
    const extraHeaders: Record<string, string> = {
      ...corsHeaders(),
    };
    if (rows.length > 200) {
      extraHeaders["X-Export-Count"] = String(rows.length);
    }

    if (format === "json") {
      return NextResponse.json({ table, count: rows.length, rows }, {
        headers: extraHeaders,
      });
    }

    if (format === "xlsx" || format === "xls") {
      const xls = toXls(rows);
      return new Response(xls, {
        status: 200,
        headers: {
          ...extraHeaders,
          "Content-Type": "application/vnd.ms-excel; charset=utf-8",
          "Content-Disposition":
            `attachment; filename="${encodedFilename}"; filename*=UTF-8''${encodedFilename}`,
        },
      });
    }

    // CSV (default)
    const csv = toCsv(rows);
    return new Response(csv, {
      status: 200,
      headers: {
        ...extraHeaders,
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition":
          `attachment; filename="${encodedFilename}"; filename*=UTF-8''${encodedFilename}`,
      },
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[Export] Error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

function corsHeaders(): Record<string, string> {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
  };
}

export async function OPTIONS() {
  return new Response(null, {
    status: 204,
    headers: corsHeaders(),
  });
}
