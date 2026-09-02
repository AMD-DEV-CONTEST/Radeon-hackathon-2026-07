import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";

const DEFAULT_CONFIGS: Record<string, Record<string, unknown>> = {
  greeting_template: {
    enable: true,
    greeting: "您好，欢迎光临！我是您的专属客服助手，请问有什么可以帮您？",
  },
  return_policy: {
    enable: true,
    reason: "7天无理由退换货，质量问题包邮退",
    redirect_msg: "已为您记录退换货需求，客服将尽快与您联系处理。",
  },
  objection_handling: {
    enable: true,
    fallback_message: "非常抱歉给您带来不好的体验，我会立即帮您反馈处理。",
    max_retries: 3,
  },
  compensation_tiers: {
    enable: true,
    priority_level: 1,
    response_template: "差评赔付：补偿{amount}元优惠券，预计24小时内到账",
  },
  complaint_escalation: {
    enable: false,
    escalation_path: "客服主管",
    timeout_sec: 300,
  },
};

export async function POST(request: Request) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const body = await request.json().catch(() => ({}));
    const platformId = body.platform_id;

    if (!platformId) {
      return NextResponse.json({ error: "platform_id is required" }, { status: 400 });
    }

    // Check if platform already has configs
    const { data: existing } = await supabaseAdmin
      .from("bot_configs")
      .select("id")
      .eq("platform_id", platformId)
      .limit(1);

    if (existing && existing.length > 0) {
      return NextResponse.json({ error: "该平台已存在话术配置" }, { status: 409 });
    }

    // Insert default configs
    const now = new Date().toISOString();
    const entries = Object.entries(DEFAULT_CONFIGS).map(([configKey, configValue]) => ({
      id: crypto.randomUUID(),
      platform_id: platformId,
      config_type: configKey === "greeting_template" ? "pre_sale" : "after_sale",
      config_key: configKey,
      config_value: configValue,
      version: 1,
      status: "active",
      change_summary: "系统自动生成的初始配置",
      created_at: now,
      updated_at: now,
    }));

    const { data, error } = await supabaseAdmin
      .from("bot_configs")
      .insert(entries)
      .select();

    if (error) throw error;

    return NextResponse.json({ configs: data, count: data?.length || 0 }, { status: 201 });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[BotConfigs] Bootstrap error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
