import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { callLLMForSuggestion } from "@/lib/suggestion-engine";

export async function POST(request: Request) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const body = await request.json().catch(() => ({}));
    const { platform_id } = body;

    let query = supabaseAdmin
      .from("bot_configs")
      .select("config_key, config_value, config_type, version")
      .eq("status", "active")
      .order("config_type");

    if (platform_id) query = query.eq("platform_id", platform_id);

    const { data: configs, error } = await query;
    if (error) throw error;

    if (!configs || configs.length === 0) {
      return NextResponse.json({ suggestion: "当前没有生效的话术配置可供分析。", confidence: 0 });
    }

    const { data: sessions } = await supabaseAdmin
      .from("bot_chat_sessions")
      .select("conversation, transfer_reason, satisfaction")
      .eq("bot_handled", false)
      .order("created_at", { ascending: false })
      .limit(5);

    const result = await callLLMForSuggestion({
      context_type: "bot_config",
      context_data: {
        configs,
        recent_problem_sessions: sessions?.map((s) => ({
          conversation: s.conversation.slice(0, 500),
          transfer_reason: s.transfer_reason,
          satisfaction: s.satisfaction,
        })) || [],
      },
      question: "请分析当前话术配置中存在的问题，给出具体可执行的优化建议。包括：话术逻辑缺陷、缺失场景覆盖、具体修改方案、优先级排序。",
      max_tokens: 4096,
    });

    return NextResponse.json({ suggestion: result.suggestion });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[BotConfigs] Suggest error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
