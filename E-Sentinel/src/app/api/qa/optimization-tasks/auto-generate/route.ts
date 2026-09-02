import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { callLLM } from "@/lib/llm-provider";
import { logAudit, logLlmCall } from "@/lib/audit";

export async function POST(request: Request) {
  const t0 = Date.now();
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const body = await request.json().catch(() => ({}));
    const { session_ids, source_type } = body as {
      session_ids?: string[];
      source_type?: "chat_inspection" | "inquiry_loss" | "satisfaction" | "knowledge_gap";
    };

    if (!source_type) {
      return NextResponse.json({ error: "source_type is required" }, { status: 400 });
    }

    let sessions: any[] = [];
    let query = supabaseAdmin.from("bot_chat_sessions").select("id, conversation, transfer_reason, satisfaction, inquiry_result");

    switch (source_type) {
      case "inquiry_loss":
        query = query.eq("is_inquiry", true).eq("inquiry_result", "lost");
        break;
      case "satisfaction":
        query = query.in("satisfaction", ["bad", "neutral"]);
        break;
      default:
        query = query.eq("bot_handled", false);
    }

    if (session_ids && session_ids.length > 0) {
      query = query.in("id", session_ids.slice(0, 20));
    } else {
      query = query.order("created_at", { ascending: false }).limit(15);
    }

    const { data } = await query;
    sessions = data || [];

    if (sessions.length === 0) {
      return NextResponse.json({ tasks: [], message: "No relevant sessions found" });
    }

    const convoText = sessions.map((s: any) =>
      `[id=${s.id}] transfer=${s.transfer_reason || ""} satisfaction=${s.satisfaction || ""} result=${s.inquiry_result || ""}\n${s.conversation.slice(0, 300)}`
    ).join("\n---\n");

    const { content, model, cached, wasFallback } = await callLLM({
      messages: [
        {
          role: "system",
          content: `你是电商客服机器人运营专家。请根据分析结果自动生成可执行的优化任务。

对每条任务输出：
- source: "${source_type}"
- category: 任务类别 (knowledge_gap/script_improvement/policy_update/product_data_fix/logic_bug)
- title: 任务标题（动词+对象，20字以内）
- description: 任务描述
- priority: low/medium/high/critical
- impact_estimate: 预计提升效果

输出纯 JSON 数组。最多生成 10 条高质量任务，宁缺毋滥。`,
        },
        { role: "user", content: `根据以下 ${sessions.length} 条问题会话生成优化任务：\n\n${convoText.slice(0, 10000)}` },
      ],
      max_tokens: 2048,
    });

    await logLlmCall({ model, prompt_type: "auto_generate_tasks", latency_ms: Date.now() - t0, was_fallback: wasFallback, cached, correlation_id: "auto-gen-tasks" });

    const raw = content.replace(/```json\s*/gi, "").replace(/```\s*/gi, "").trim();
    const arrStart = raw.indexOf("[");
    const arrEnd = raw.lastIndexOf("]");
    const suggestions: any[] = arrStart !== -1 && arrEnd !== -1
      ? JSON.parse(raw.substring(arrStart, arrEnd + 1))
      : [];

    const created: unknown[] = [];
    for (const s of suggestions) {
      if (!s.title || !s.description) continue;
      const { data: row } = await supabaseAdmin
        .from("optimization_tasks")
        .insert({
          source: source_type,
          category: s.category || "general",
          title: s.title,
          description: s.description,
          priority: s.priority || "medium",
          impact_estimate: s.impact_estimate || null,
        })
        .select()
        .single();
      if (row) created.push(row);
    }

    await logAudit({
      action: "optimization_task_create",
      resource_type: "optimization_tasks",
      detail: { source_type, tasks_created: created.length },
    });

    return NextResponse.json({ tasks: created, count: created.length }, { status: 201 });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[OptTasks] Auto-generate error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
