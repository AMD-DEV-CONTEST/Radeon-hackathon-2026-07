// ============================================================================
// Import Trained Knowledge — 话术训练系统训练后导入
// 接受 CSV / JSON / 纯文本格式，自动解析、向量化、写入 knowledge_entries
// 支持格式:
//   JSON: [{"title":"...","content":"...","category":"faq","keywords":["k1","k2"]}]
//   CSV:  title,content,category,keywords
//   纯文本: 问答对（由LLM自动提取）
// ============================================================================

import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { textToEmbedding, embeddingToPgVector } from "@/lib/embedding";
import { callLLM } from "@/lib/llm-provider";
import { createCorrelationId } from "@/lib/correlation";
import { logAudit, logLlmCall } from "@/lib/audit";
import { resolveCategory, parseJsonEntries, parseCsvEntries } from "@/lib/knowledge-import-utils";
import { authorizeGovernanceRequest } from "@/lib/governance/authorization";

const SYSTEM_PROMPT = `你是一个知识库管理助手。以下文本来自话术训练系统的训练输出。
请提取所有问答对，对每对输出：
- title: 问题标题（10-30字）
- content: 标准回答（含具体信息和步骤）
- category: 分类（product/faq/after_sales_policy/campaign/greeting）
- keywords: 搜索关键词数组（3-5个）

以JSON数组格式返回。`;

export async function POST(request: Request) {
  const authorization = await authorizeGovernanceRequest(request, { mutation: true });
  if (authorization.error) return authorization.error;
  const tenantId = authorization.context?.tenantId;
  if (!tenantId) return NextResponse.json({ error: "Tenant scope required" }, { status: 403 });

  const t0 = Date.now();
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    // ── 解析请求 ──
    let text: string | null = null;
    let sourceFile: string | null = null;
    const contentType = request.headers.get("content-type") || "";

    if (contentType.includes("multipart/form-data")) {
      const formData = await request.formData();
      const file = formData.get("file") as File | null;
      const textField = formData.get("text") as string | null;

      if (file) {
        const fileName = file.name.toLowerCase();
        sourceFile = file.name;
        const allowedExtensions = [".txt", ".csv", ".md", ".json"];
        const hasAllowedExt = allowedExtensions.some((ext) => fileName.endsWith(ext));
        if (!hasAllowedExt) {
          return NextResponse.json({ error: "Unsupported file type. Allowed: .txt, .csv, .md, .json" }, { status: 400 });
        }
        if (file.size > 10 * 1024 * 1024) {
          return NextResponse.json({ error: "File too large. Max 10MB." }, { status: 400 });
        }
        text = await file.text();
      } else if (textField && textField.trim()) {
        text = textField;
      }
    } else {
      const body = await request.json().catch(() => ({}));
      text = body.text || null;
      sourceFile = body.source || null;
    }

    if (!text || !text.trim()) {
      return NextResponse.json({ error: "No text content provided" }, { status: 400 });
    }

    const trimmed = text.trim().slice(0, 50000);

    // ── 尝试直接解析 ──
    let parsed: Record<string, unknown>[] = [];

    // 尝试JSON
    if (trimmed.startsWith("[") || trimmed.startsWith("```json")) {
      parsed = parseJsonEntries(trimmed);
    }

    // 尝试CSV
    if (parsed.length === 0 && trimmed.includes("\n") && trimmed.toLowerCase().includes("title")) {
      parsed = parseCsvEntries(trimmed);
    }

    // 都不行→LLM提取
    if (parsed.length === 0) {
      const llmResult = await callLLM({
        prompt: `以下是话术训练系统的训练输出，请提取所有问答对：\n\n${trimmed.slice(0, 8000)}`,
        systemPrompt: SYSTEM_PROMPT,
        maxTokens: 4096,
        useCache: false,
      });

      if (llmResult) {
        parsed = parseJsonEntries(llmResult);

        await logLlmCall({
          model: "deepseek-chat",
          prompt_type: "import_trained_extract",
          latency_ms: Date.now() - t0,
          correlation_id: createCorrelationId("import"),
        });
      }
    }

    if (parsed.length === 0) {
      return NextResponse.json(
        { error: "未能解析训练输出中的问答对，请检查格式后重试" },
        { status: 422 }
      );
    }

    // ── 写入知识库 ──
    const correlationId = createCorrelationId("kn");
    const created: Record<string, unknown>[] = [];
    const skipped: string[] = [];

    for (const entry of parsed) {
      const title = String(entry.title || "").trim();
      const contentBody = String(entry.content || "").trim();
      if (!title || !contentBody) { skipped.push(entry.title ? String(entry.title) : "未命名"); continue; }

      const category = resolveCategory(
        typeof entry.category === "string" ? entry.category : undefined
      );
      const keywords = Array.isArray(entry.keywords)
        ? entry.keywords.map((k) => String(k).trim()).filter(Boolean)
        : [];
      const tags = Array.isArray(entry.tags)
        ? entry.tags.map((t) => String(t).trim()).filter(Boolean)
        : ["trained", "imported"];

      const embedding = textToEmbedding(`${title} ${contentBody}`);

      const { data: row, error } = await supabaseAdmin
        .from("knowledge_entries")
        .insert({
          category,
          title,
          content: contentBody,
          keywords,
          tags,
          tone: "professional",
          priority: 5,
          source: sourceFile ? `trained_import:${sourceFile}` : "trained_import",
          status: "draft",
          embedding: embeddingToPgVector(embedding),
          version: 1,
          tenant_id: tenantId,
        })
        .select()
        .single();

      if (row) created.push(row);
      if (error) {
        console.error("[ImportTrained] Insert error:", error.message);
        skipped.push(title);
      }
    }

    // ── 关联 unresolved_questions（如果有session_id） ──
    const sessionId = request.headers.get("x-session-id") || null;
    if (sessionId && created.length > 0) {
      await supabaseAdmin
        .from("unresolved_questions")
        .update({ status: "resolved", resolved_by: "import_trained", resolved_at: new Date().toISOString() })
        .eq("session_id", sessionId)
        .eq("tenant_id", tenantId);
    }

    // ── 审计 ──
    await logAudit({
      action: "import_trained_knowledge",
      resource_type: "knowledge_entries",
      detail: { created: created.length, skipped: skipped.length, source: sourceFile, correlation_id: correlationId },
      correlation_id: correlationId,
    });

    return NextResponse.json({
      imported: created.length,
      skipped_count: skipped.length,
      skipped_titles: skipped,
      entries: created,
    }, { status: 201 });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[ImportTrained] Error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
