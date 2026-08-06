import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { callLLM } from "@/lib/llm-provider";
import { logAudit, logLlmCall } from "@/lib/audit";
import { parseLlmJson } from "@/lib/parse-llm-response";

export async function POST(request: Request) {
  const t0 = Date.now();
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const body = await request.json().catch(() => ({}));
    const { report_type, period_start, period_end, platform_id } = body as {
      report_type: "daily" | "weekly" | "monthly";
      period_start: string;
      period_end: string;
      platform_id?: string;
    };

    if (!report_type || !period_start || !period_end) {
      return NextResponse.json(
        { error: "report_type, period_start, period_end are required" },
        { status: 400 }
      );
    }

    // Gather metrics — each table may not exist yet, guard individually
    const safeQuery = async <T>(queryFn: () => PromiseLike<{ data: T | null; error: any }>): Promise<T[]> => {
      try {
        const { data, error } = await queryFn();
        if (error && (error.code === "PGRST204" || error.message?.includes("schema cache"))) return [];
        if (error) throw error;
        return (data as T[]) || [];
      } catch (e: any) {
        if (e?.code === "PGRST204" || e?.message?.includes("schema cache")) return [];
        throw e;
      }
    };

    const allSessions = await safeQuery<any>(() => {
      if (!supabaseAdmin) return Promise.resolve({ data: [], error: null });
      let q = supabaseAdmin.from("bot_chat_sessions").select("*")
        .gte("created_at", period_start)
        .lte("created_at", period_end.slice(0, 10) + "T23:59:59.999Z");
      if (platform_id) q = q.eq("platform_id", platform_id);
      return q;
    });

    const total = allSessions.length;
    const botHandled = allSessions.filter((s: any) => s.bot_handled).length;
    const independentRate = total > 0 ? (botHandled / total) * 100 : 0;
    const good = allSessions.filter((s: any) => s.satisfaction === "good").length;
    const bad = allSessions.filter((s: any) => s.satisfaction === "bad").length;
    const rated = good + bad + allSessions.filter((s: any) => s.satisfaction === "neutral").length;
    const inquiries = allSessions.filter((s: any) => s.is_inquiry);
    const converted = inquiries.filter((s: any) => s.inquiry_result === "converted").length;
    const lost = inquiries.filter((s: any) => s.inquiry_result === "lost").length;

    const optTasks = await safeQuery<any>(() => {
      if (!supabaseAdmin) return Promise.resolve({ data: [], error: null });
      return supabaseAdmin.from("optimization_tasks").select("status, priority");
    });
    const resolvedTasks = (optTasks || []).filter((t: any) => t.status === "resolved").length;
    const openTasks = (optTasks || []).filter((t: any) => t.status === "open").length;

    const benchmarks = await safeQuery<any>(() => {
      if (!supabaseAdmin) return Promise.resolve({ data: [], error: null });
      return supabaseAdmin.from("industry_benchmarks").select("*");
    });

    const metrics = {
      period: { start: period_start, end: period_end, type: report_type },
      sessions: { total, bot_handled: botHandled, independent_reception_rate: independentRate },
      satisfaction: { good, bad, rated, good_rate: rated > 0 ? (good / rated) * 100 : 0, bad_rate: rated > 0 ? (bad / rated) * 100 : 0 },
      inquiries: { total: inquiries.length, converted, lost, conversion_rate: inquiries.length > 0 ? (converted / inquiries.length) * 100 : 0 },
      optimization: { open: openTasks, resolved: resolvedTasks },
    };

    const typeLabel = report_type === "daily" ? "日报" : report_type === "weekly" ? "周报" : "月报";

    // Gather context for actionable insights
    const lostSessions = await safeQuery<any>(() => {
      if (!supabaseAdmin) return Promise.resolve({ data: [], error: null });
      return supabaseAdmin.from("bot_chat_sessions")
        .select("id, transfer_reason, tags, session_type, sentiment_score")
        .eq("inquiry_result", "lost")
        .gte("created_at", period_start)
        .lte("created_at", period_end.slice(0, 10) + "T23:59:59.999Z");
    });

    const badSessions = await safeQuery<any>(() => {
      if (!supabaseAdmin) return Promise.resolve({ data: [], error: null });
      return supabaseAdmin.from("bot_chat_sessions")
        .select("id, tags, session_type, conversation")
        .eq("satisfaction", "bad")
        .gte("created_at", period_start)
        .lte("created_at", period_end.slice(0, 10) + "T23:59:59.999Z")
        .limit(5);
    });

    // Build structured overview for card display
    const overviewMd = [
      `## 整体概览`,
      `- 总会话数: ${total}`,
      `- 机器人处理率: ${total > 0 ? ((botHandled / total) * 100).toFixed(1) : "0.0"}%`,
      `- 独立接待率: ${independentRate.toFixed(1)}%`,
      `- 好评率: ${rated > 0 ? ((good / rated) * 100).toFixed(1) : "0.0"}%`,
      `- 询单转化率: ${inquiries.length > 0 ? ((converted / inquiries.length) * 100).toFixed(1) : "0.0"}%`,
      `- 优化任务进度: ${resolvedTasks}/${resolvedTasks + openTasks} 已完成`,
    ].join("\n");

    const lostContext = lostSessions.length > 0
      ? `\n流失会话详情：\n${lostSessions.map((s: any) => `- 原因: ${s.transfer_reason || "未知"}, 标签: ${(s.tags || []).join("/")}, 类型: ${s.session_type}`).join("\n")}`
      : "";

    const parseConversation = (conv: unknown): { role: string; content: string }[] => {
      if (Array.isArray(conv)) return conv;
      if (typeof conv === "string") {
        try { const parsed = JSON.parse(conv); return Array.isArray(parsed) ? parsed : []; } catch { return []; }
      }
      return [];
    };

    const badContext = badSessions.length > 0
      ? `\n差评会话摘录：\n${badSessions.map((s: any) => {
          const msgs = parseConversation(s.conversation);
          const userMsgs = msgs.filter((m: any) => m.role === "customer" || m.role === "user").slice(0, 3);
          return `- 标签: ${(s.tags || []).join("/")}, 用户消息: ${userMsgs.map((m: any) => m.content?.slice(0, 80)).join(" | ")}`;
        }).join("\n")}`
      : "";

    const { content, model, cached, wasFallback } = await callLLM({
      messages: [
        {
          role: "system",
          content: `你是电商客服机器人运营专家。请根据提供的指标数据，生成一份专业的${typeLabel}。

## 格式要求
- summary_md 是一份 Markdown 报告，整体概览部分必须使用 \`- 指标名: 数值\` 格式列出每一项核心指标
- 分析部分必须引用具体数据，给出可执行的运营建议
- 优化方案必须基于提供的流失原因和差评会话，给出针对性改进方案（不是泛泛的"提升好评率"）

## 报告结构
1. ## 整体概览 — 6项核心指标，每项一行 \`- 名称: 数值\` 格式
2. ## 接待效率分析 — 独立接待率/转人工率对标 + 解读
3. ## 满意度分析 — 好评/差评数据 + 差评原因定位
4. ## 询单转化分析 — 转化率 + 流失原因分类统计 + 根因摘要
5. ## 优化进展 — 已解决/进行中任务数 + 趋势判断
6. ## 行业对标 — 与行业基准的差距分析
7. ## 优化方案建议 — TOP3 优先改进项，每项包含：问题定位 + 具体措施 + 预期效果

输出纯 JSON：
{
  "summary_md": "Markdown 报告全文",
  "optimization_plan": "TOP3 优化方案（编号列表，每条含具体措施）",
  "industry_compare": { "指标名": { "our": number, "industry_avg": number, "industry_top": number } }
}`,
        },
        {
          role: "user",
          content: [
            `报告类型：${report_type}`,
            `周期：${period_start} 至 ${period_end}`,
            `\n结构化概览（请直接使用此格式）：\n${overviewMd}`,
            `\n详细指标：${JSON.stringify(metrics, null, 2)}`,
            `\n行业基准：${JSON.stringify(benchmarks || [], null, 2)}`,
            lostContext,
            badContext,
          ].join("\n"),
        },
      ],
      max_tokens: 4096,
    });

    await logLlmCall({ model, prompt_type: "report_generate", latency_ms: Date.now() - t0, was_fallback: wasFallback, cached, correlation_id: "report-gen" });

    const parsed = parseLlmJson(content);
    const report = parsed || { summary_md: content, optimization_plan: "", industry_compare: {} };

    const baseRow = {
      id: crypto.randomUUID(),
      report_type,
      period_start,
      period_end,
      platform_id: platform_id || null,
      summary_md: report.summary_md || "",
      metrics,
      optimization_plan: report.optimization_plan || null,
      generated_by: "auto",
      created_at: new Date().toISOString(),
    };

    let saved: any = null;
    try {
      const { data: inserted } = await supabaseAdmin
        .from("robot_reports")
        .insert({ ...baseRow, industry_compare: report.industry_compare || null } as any)
        .select()
        .single();
      saved = inserted;
    } catch (e: any) {
      if (e?.message?.includes("industry_compare")) {
        try {
          const { data: inserted } = await supabaseAdmin
            .from("robot_reports")
            .insert(baseRow)
            .select()
            .single();
          saved = inserted;
        } catch (e2: any) {
          console.error("[Reports] Retry insert failed:", e2?.message);
        }
      } else if (e?.code === "PGRST204" || e?.message?.includes("schema cache")) {
        saved = null;
      } else {
        throw e;
      }
    }

    if (saved) {
      await logAudit({
        action: "report_generate",
        resource_type: "robot_reports",
        resource_id: saved.id,
        detail: { report_type, period: period_start },
      });
    }

    return NextResponse.json({ report: saved || { ...report, metrics } });
  } catch (error) {
    const message = error instanceof Error ? error.message : (typeof error === "object" ? JSON.stringify(error) : String(error ?? "internal_error"));
    console.error("[Reports] Generate error:", typeof error, message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
