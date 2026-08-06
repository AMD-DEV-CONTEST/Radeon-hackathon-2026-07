/**
 * seed-bot-configs-all-platforms.ts
 *
 * Setup prep: every platform needs话术配置 so the BotConfigPanel doesn't show
 * "暂无话术配置" when switching tabs.
 *
 * The /bot-configs/bootstrap endpoint refuses to write if ANY config exists
 * for a platform, so we bypass it and insert missing config_keys per platform
 * directly. Idempotent — uses (platform_id, config_type, config_key, status='active')
 * as the dedupe pivot.
 *
 * Run: npx tsx --env-file=.env.local scripts/seed-bot-configs-all-platforms.ts
 */
import { supabaseAdmin } from "../src/lib/supabase";

interface ConfigSpec {
  config_type: "pre_sale" | "after_sale";
  config_key: string;
  config_value: Record<string, unknown>;
  change_summary: string;
}

const COMMON_CONFIGS: ConfigSpec[] = [
  {
    config_type: "pre_sale",
    config_key: "greeting_template",
    config_value: {
      enable: true,
      greeting: "您好，欢迎光临！我是您的专属客服助手，请问有什么可以帮您？",
    },
    change_summary: "初始欢迎语",
  },
  {
    config_type: "after_sale",
    config_key: "return_policy",
    config_value: {
      enable: true,
      reason: "7天无理由退换货，质量问题包邮退",
      redirect_msg: "已为您记录退换货需求，客服将尽快与您联系处理。",
    },
    change_summary: "初始退换货政策",
  },
  {
    config_type: "after_sale",
    config_key: "objection_handling",
    config_value: {
      enable: true,
      fallback_message: "非常抱歉给您带来不好的体验，我会立即帮您反馈处理。",
      max_retries: 3,
    },
    change_summary: "初始异议处理",
  },
  {
    config_type: "after_sale",
    config_key: "compensation_tiers",
    config_value: {
      enable: true,
      priority_level: 1,
      response_template: "差评赔付：补偿{amount}元优惠券，预计24小时内到账",
    },
    change_summary: "初始补偿等级",
  },
  {
    config_type: "after_sale",
    config_key: "complaint_escalation",
    config_value: {
      enable: true,
      escalation_path: "客服主管",
      timeout_sec: 300,
    },
    change_summary: "初始投诉升级",
  },
];

const PLATFORM_SPECIFIC: Record<string, ConfigSpec[]> = {
  jd: [
    {
      config_type: "pre_sale",
      config_key: "jd_price_match",
      config_value: { enable: true, reason: "京东价保政策", redirect_msg: "支持30天价保，购买后降价可申请差价补偿" },
      change_summary: "京东比价策略",
    },
  ],
  pdd: [
    {
      config_type: "pre_sale",
      config_key: "pdd_low_price_strategy",
      config_value: { enable: true, response_template: "已是全网底价，可叠加百亿补贴" },
      change_summary: "拼多多低价策略",
    },
  ],
  douyin: [
    {
      config_type: "pre_sale",
      config_key: "live_stream_script",
      config_value: { enable: true, greeting: "直播间宝宝们好！现在下单立享专属优惠" },
      change_summary: "直播话术",
    },
    {
      config_type: "after_sale",
      config_key: "douyin_after_sales",
      config_value: { enable: true, timeout_sec: 7200, response_template: "抖音售后2小时内响应" },
      change_summary: "抖音售后SLA",
    },
  ],
};

async function main() {
  if (!supabaseAdmin) throw new Error("Supabase not configured");

  const { data: platforms, error: platformErr } = await supabaseAdmin
    .from("platforms")
    .select("id, code, name");
  if (platformErr) throw new Error(platformErr.message);
  if (!platforms || platforms.length === 0) throw new Error("No platforms found");

  console.log(`Found ${platforms.length} platforms\n`);

  let insertedTotal = 0;
  let skippedTotal = 0;
  let failedTotal = 0;

  for (const platform of platforms as Array<{ id: number; code: string; name: string }>) {
    const configsForPlatform = [
      ...COMMON_CONFIGS,
      ...(PLATFORM_SPECIFIC[platform.code] || []),
    ];

    const { data: existingRows } = await supabaseAdmin
      .from("bot_configs")
      .select("config_key, config_type, status")
      .eq("platform_id", platform.id)
      .eq("status", "active");

    const existingKeys = new Set(
      (existingRows || []).map((r: { config_key: string; config_type: string }) =>
        `${r.config_type}:${r.config_key}`
      )
    );

    let inserted = 0;
    let skipped = 0;
    let failed = 0;
    const now = new Date().toISOString();

    for (const spec of configsForPlatform) {
      const pivot = `${spec.config_type}:${spec.config_key}`;
      if (existingKeys.has(pivot)) {
        skipped++;
        continue;
      }
      const { error: insErr } = await supabaseAdmin.from("bot_configs").insert({
        id: crypto.randomUUID(),
        platform_id: platform.id,
        config_type: spec.config_type,
        config_key: spec.config_key,
        config_value: spec.config_value,
        version: 1,
        status: "active",
        change_summary: spec.change_summary,
        created_at: now,
        updated_at: now,
      });
      if (insErr) {
        console.log(`  ❌ ${platform.name} ${spec.config_key}: ${insErr.message}`);
        failed++;
      } else {
        inserted++;
      }
    }

    console.log(
      `  ${platform.name.padEnd(6)} (${platform.code.padEnd(11)}): +${inserted} new, ${skipped} kept, ${failed} failed`
    );
    insertedTotal += inserted;
    skippedTotal += skipped;
    failedTotal += failed;
  }

  console.log(`\n${"=".repeat(60)}`);
  console.log(`Done: +${insertedTotal} inserted, ${skippedTotal} kept, ${failedTotal} failed`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
