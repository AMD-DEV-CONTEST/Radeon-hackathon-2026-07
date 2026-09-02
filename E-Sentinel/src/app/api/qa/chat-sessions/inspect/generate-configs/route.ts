import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { callLLM } from "@/lib/llm-provider";
import { logAudit, logLlmCall } from "@/lib/audit";
import { triggerTaskPipeline } from "@/lib/pipeline";
import { parseLlmJsonArray } from "@/lib/parse-llm-response";
import { shouldAutoPublish, BOT_CONFIG_SAFE_KEYS } from "@/lib/auto-publish";
import { scanCompliance, quickComplianceCheck, type ComplianceRule } from "@/lib/compliance-engine";
import { createCorrelationId } from "@/lib/correlation";
import { getConfigNumber } from "@/lib/system-config";
import { sendFeishuNotification } from "@/lib/feishu";

const CONFIG_KEY_DESCRIPTIONS: Record<string, { desc: string; examples: string[]; constraints: string }> = {
  greeting_template: {
    desc: "欢迎语模板 — 客户进入对话时的首条自动消息",
    examples: [
      "\"亲，欢迎光临{shop_name}！今天有{activity_name}活动，满{amount}减{discount}哦~\"",
      "\"您好！我是您的专属顾问小美，请问有什么可以帮您的？\"",
    ],
    constraints: "必须包含品牌名称占位符，控制在100字以内，不能承诺具体折扣金额（使用占位符）",
  },
  product_recommend: {
    desc: "产品推荐策略 — 根据客户需求推荐产品的逻辑和话术",
    examples: [
      "\"根据您的需求，为您推荐{product_a}和{product_b}，{product_a}主打{feature}，{product_b}性价比更高...\"",
    ],
    constraints: "禁止虚假宣传，推荐必须基于实际库存和评价数据，不能承诺效果",
  },
  return_policy: {
    desc: "退换货政策 — 处理退换货请求的标准回复",
    examples: [
      "\"亲，我们支持7天无理由退货，15天质量问题换货。退货运费由{who_bears}承担...\"",
    ],
    constraints: "必须符合《消费者权益保护法》，不能设置过高的退换门槛，物流信息使用占位符",
  },
  compensation_tiers: {
    desc: "补偿等级 — 针对不同客诉严重程度的补偿方案（优惠券/退款/赠品）",
    examples: [
      "\"对于轻微延迟：5元无门槛券；严重延迟：10-20元补偿；货损：全额退款+10元券...\"",
    ],
    constraints: "金额使用范围区间而非固定值，最高补偿不超过订单金额的50%，需注明有效期",
  },
  live_stream_script: {
    desc: "直播话术脚本 — 直播带货场景下的标准讲解和互动话术",
    examples: [
      "\"宝宝们，今天直播间福利价只要{price}！前100名下单额外赠送{gift}，手慢无！\"",
    ],
    constraints: "话术需符合广告法，避免绝对化用语（最/第一/100%），合规提醒必须标注",
  },
  douyin_after_sales: {
    desc: "抖音售后SLA — 抖音平台的售后响应时效、处理流程、平台规则适配",
    examples: [
      "\"退款时效：24小时内处理；换货时效：48小时发出；纠纷率控制目标：<0.3%\"",
    ],
    constraints: "时效指标使用具体数字，必须符合抖音平台最新规则，不可超出平台承诺",
  },
  jd_price_match: {
    desc: "京东比价策略 — 处理客户比价（友商/其他平台）时的应对话术和保价规则",
    examples: [
      "\"京东自营同款如发现价格更低，差价双倍退还；第三方店铺价格差异需提供截图核实...\"",
    ],
    constraints: "保价承诺不超过平台规定（通常7-15天），比价必须有凭证（截图链接），不能虚假承诺全网最低",
  },
  pdd_low_price_strategy: {
    desc: "拼多多低价策略 — 应对拼多多平台低价竞争的话术和价值锚点转移",
    examples: [
      "\"拼多多价格确实更低，但我们的优势是{quality_assurance/reliable_logistics/after_sales_guarantee}...\"",
    ],
    constraints: "不要贬低友商，聚焦自身优势（品质/物流/售后），用价值感而非价格竞争",
  },
  objection_handling: {
    desc: "异议处理话术 — 客户质疑价格、质量、服务时的标准应答",
    examples: [
      "\"1. 先共情：理解您的顾虑 2. 澄清：这个价格包含了{value_added_services} 3. 举证：已有{number}位客户选择...\"",
    ],
    constraints: "遵循LAP流程（Listen→Acknowledge→Probe），禁止直接反驳客户，禁止使用「但是」「可是」",
  },
  complaint_escalation: {
    desc: "投诉升级机制 — 客诉分级、升级条件、升级后处理SOP",
    examples: [
      "\"一级：轻微不满→客服自主处理；二级：重复投诉→组长介入；三级：工商/平台投诉→经理+公关响应\"",
    ],
    constraints: "升级条件必须量化（如：同一问题3次以上），强制记录升级原因，高危客诉（涉及人身安全/法律）必须15分钟内升级",
  },
};

const DEDUP_WINDOW_DAYS = 7;

export async function POST(request: Request) {
  const t0 = Date.now();
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const body = await request.json().catch(() => ({}));
    const { inspect_results, session_ids } = body as {
      inspect_results?: { session_id: string; suggestions: { type: string; title: string; detail: string; expected_impact: string }[] }[];
      session_ids?: string[];
    };

    if (!inspect_results || inspect_results.length === 0) {
      return NextResponse.json({ error: "inspect_results[] is required" }, { status: 400 });
    }

    // Collect only script-type suggestions
    const scriptSuggestions = inspect_results.flatMap((r) =>
      (r.suggestions || [])
        .filter((s) => s.type === "script")
        .map((s) => ({ ...s, session_id: r.session_id }))
    );

    if (scriptSuggestions.length === 0) {
      return NextResponse.json({ message: "No script-type suggestions to process", configs: [] });
    }

    // Fetch related sessions for context
    const allSessionIds = inspect_results.map((r) => r.session_id);
    const { data: sessions } = await supabaseAdmin
      .from("bot_chat_sessions")
      .select("id, conversation, platform_id")
      .in("id", allSessionIds);

    if (!sessions || sessions.length === 0) {
      return NextResponse.json({ error: "No sessions found" }, { status: 404 });
    }

    const sessionMap = new Map(sessions.map((s: Record<string, unknown>) => [String(s.id), s]));

    // Fetch current active configs for context
    const platformIds = [...new Set(sessions.map((s: Record<string, unknown>) => Number(s.platform_id)))];
    const { data: activeConfigs } = await supabaseAdmin
      .from("bot_configs")
      .select("id, platform_id, config_type, config_key, config_value, version")
      .eq("status", "active")
      .in("platform_id", platformIds);

    const activeConfigsByPlatform = new Map<number, Record<string, unknown>[]>();
    if (activeConfigs) {
      for (const c of activeConfigs) {
        const pid = c.platform_id;
        if (!activeConfigsByPlatform.has(pid)) activeConfigsByPlatform.set(pid, []);
        activeConfigsByPlatform.get(pid)!.push(c);
      }
    }

    // ── Dedup: check for existing drafts within DEDUP_WINDOW_DAYS ──
    const dedupCheckDate = new Date();
    dedupCheckDate.setDate(dedupCheckDate.getDate() - DEDUP_WINDOW_DAYS);
    const dedupCutoff = dedupCheckDate.toISOString();

    const { data: existingDrafts } = await supabaseAdmin
      .from("bot_configs")
      .select("platform_id, config_key, config_type")
      .eq("status", "draft")
      .in("platform_id", platformIds)
      .gte("created_at", dedupCutoff);

    const existingDraftKeys = new Set(
      (existingDrafts || []).map((d: Record<string, unknown>) =>
        `${d.platform_id}::${d.config_key}::${d.config_type}`
      )
    );

    // Filter out suggestions whose config_key already has a recent draft
    const dedupedSuggestions = scriptSuggestions.filter((s) => {
      const key = `${sessionMap.get(s.session_id)}::${s.title}`;
      return true; // We can't know the config_key before LLM, so we filter post-LLM
    });

    const skippedCount = scriptSuggestions.length - dedupedSuggestions.length;
    // ── End dedup ──

    // Build LLM prompt with detailed config_key descriptions
    const configKeyGuide = Object.entries(CONFIG_KEY_DESCRIPTIONS)
      .map(([key, info]) =>
        `### ${key}
描述: ${info.desc}
约束: ${info.constraints}
示例:\n${info.examples.map((e) => "  " + e).join("\n")}`
      )
      .join("\n\n");

    const suggestionsText = scriptSuggestions
      .map((s, i) => {
        const session = sessionMap.get(s.session_id) as Record<string, unknown> | undefined;
        const convo = session ? String(session.conversation || "").slice(0, 800) : "";
        return `[建议 ${i + 1}]
session_id: ${s.session_id}
标题: ${s.title}
详情: ${s.detail}
预期影响: ${s.expected_impact}
对话片段: ${convo}`;
      })
      .join("\n\n---\n\n");

    const configsContext = platformIds.map((pid) => {
      const configs = activeConfigsByPlatform.get(pid) || [];
      return `平台 ${pid} 当前生效配置:
${configs.map((c) => `  - ${c.config_key} (${c.config_type}) v${c.version}: ${JSON.stringify(c.config_value).slice(0, 300)}`).join("\n")}`;
    }).join("\n\n");

    const { content, model, cached, wasFallback } = await callLLM({
      messages: [
        {
          role: "system",
          content: `你是电商客服机器人话术配置专家。根据质检发现的 script 类型建议，为每个建议精确映射到对应的 config_key 并生成改进后的 bot_config 草稿。

## config_key 详细说明（必须精确匹配，不可编造）

${configKeyGuide}

## 映射规则

1. 根据建议的标题和详情，选择语义最匹配的 config_key
2. 如果建议涉及多个 config_key，生成多条配置（每个 config_key 一条）
3. 如果建议无法匹配任何 config_key，输出 reason 字段说明原因并跳过

## config_type 规则

- pre_sale: 售前相关（直播话术、产品推荐、欢迎语、比价）
- post_sale: 售后相关（退换货、补偿、投诉升级、售后SLA、异议处理）

## config_value 生成规则

- 必须是一个完整的 JSON 对象，包含该配置所需的所有字段
- 基于当前 active 版本进行改进，融入建议的修改点
- 如果是全新配置（无 active 版本），生成合理的默认 JSON
- 涉及金额/时效的地方使用占位符（如 {amount}）而非硬编码

## 输出格式

输出纯 JSON 数组，每个元素包含：
{
  "platform_id": <number>,
  "config_type": "pre_sale|post_sale",
  "config_key": "上述列表之一",
  "config_value": { <完整的 JSON 配置对象> },
  "change_summary": "变更说明（中文，30字以内）",
  "confidence": <0-1之间的数字，表示映射置信度>
}

不包裹 markdown 代码块。`,
        },
        {
          role: "user",
          content: `当前生效配置:\n${configsContext}\n\n质检建议:\n${suggestionsText}\n\n请为每个建议精确映射 config_key 并生成改进后的配置草稿。对于无法映射的建议，输出 [] 空数组。`,
        },
      ],
      max_tokens: 4096,
    });

    const parsed = parseLlmJsonArray(content);
    const generatedConfigs: Array<{
      platform_id: number;
      config_type: string;
      config_key: string;
      config_value: Record<string, unknown>;
      change_summary: string;
      confidence: number;
      suggestion_title?: string;
      suggestion_detail?: string;
      session_id?: string;
    }> = [];

    if (parsed && Array.isArray(parsed)) {
      for (const item of parsed) {
        if (
          item &&
          typeof item === "object" &&
          typeof (item as Record<string, unknown>).platform_id === "number" &&
          typeof (item as Record<string, unknown>).config_key === "string" &&
          (item as Record<string, unknown>).config_value
        ) {
          const configKey = String((item as Record<string, unknown>).config_key);
          // Validate config_key is in the known list
          if (!CONFIG_KEY_DESCRIPTIONS[configKey]) {
            console.warn(`[GenerateConfigs] LLM returned unknown config_key: ${configKey}, skipping`);
            continue;
          }
          generatedConfigs.push({
            platform_id: (item as Record<string, unknown>).platform_id as number,
            config_type: String((item as Record<string, unknown>).config_type || "post_sale"),
            config_key: configKey,
            config_value: (item as Record<string, unknown>).config_value as Record<string, unknown>,
            change_summary: String((item as Record<string, unknown>).change_summary || "质检建议优化"),
            confidence: Number((item as Record<string, unknown>).confidence) || 0.8,
          });
        }
      }
    }

    await logLlmCall({
      model,
      prompt_type: "inspect_generate_configs",
      latency_ms: Date.now() - t0,
      was_fallback: wasFallback,
      cached,
      correlation_id: "generate-configs",
    });

    if (generatedConfigs.length === 0) {
      return NextResponse.json({
        message: "LLM could not generate valid configs",
        configs: [],
        skipped_duplicates: 0,
      });
    }

    // ── Post-LLM dedup: filter out config_key+platform already in recent drafts ──
    const dedupedConfigs = generatedConfigs.filter((gc) => {
      const key = `${gc.platform_id}::${gc.config_key}::${gc.config_type}`;
      if (existingDraftKeys.has(key)) {
        console.log(`[GenerateConfigs] Skipping duplicate draft: ${key}`);
        return false;
      }
      return true;
    });

    const postDedupSkipped = generatedConfigs.length - dedupedConfigs.length;

    // Insert draft configs into bot_configs (auto-publish high-confidence low-risk)
    const createdConfigs: Record<string, unknown>[] = [];
    let autoPublishedCount = 0;

    for (const gc of dedupedConfigs) {
      const { data: versions } = await supabaseAdmin
        .from("bot_configs")
        .select("version")
        .eq("platform_id", gc.platform_id)
        .eq("config_type", gc.config_type)
        .eq("config_key", gc.config_key)
        .order("version", { ascending: false })
        .limit(1);

      const nextVersion = (versions?.[0]?.version || 0) + 1;

      // Auto-publish: high confidence + safe config key + small change
      const autoPublishThreshold = await getConfigNumber("auto_publish_threshold", 0.95);
      const maxChangeLen = await getConfigNumber("auto_publish_max_change_length", 50);
      let canAutoPublish = shouldAutoPublish({
        confidence: gc.confidence,
        category: gc.config_key,
        safeCategories: BOT_CONFIG_SAFE_KEYS,
        threshold: autoPublishThreshold,
        maxChangeLength: maxChangeLen,
        changeLength: gc.change_summary.length,
      });

      // Compliance scan before auto-publish
      if (canAutoPublish) {
        const configText = typeof gc.config_value === "string" ? gc.config_value : JSON.stringify(gc.config_value);
        let complianceRules: ComplianceRule[] = [];
        const { data: activeRules } = await supabaseAdmin
          .from("compliance_rules")
          .select("id, rule_text, pattern, risk_level, category, action_type, exemption_tags")
          .eq("is_active", true);
        if (activeRules && activeRules.length > 0) {
          complianceRules = activeRules.map((r: Record<string, unknown>) => ({
            id: String(r.id), rule_text: String(r.rule_text), pattern: String(r.pattern),
            risk_level: Number(r.risk_level), category: String(r.category),
            action_type: String(r.action_type) as ComplianceRule["action_type"],
            exemption_tags: Array.isArray(r.exemption_tags) ? r.exemption_tags.map(String) : [],
          }));
        }
        const compResult = complianceRules.length > 0
          ? scanCompliance(configText, complianceRules)
          : quickComplianceCheck(configText);
        if (!compResult.passed && compResult.decision === "blocked") {
          canAutoPublish = false;
          await supabaseAdmin.from("compliance_audit_logs").insert({
            source_type: "bot_config", content_snippet: configText.substring(0, 200),
            risk_level: compResult.highest_risk,
            matched_rules: compResult.matches.map((m) => ({ rule_id: m.rule.id, rule_text: m.rule.rule_text })),
            decision: "blocked", correlation_id: createCorrelationId("cmp"),
          });
        }
      }

      const status = canAutoPublish ? "active" : "draft";

      if (canAutoPublish) {
        // Archive current active version for same config_key before activating
        await supabaseAdmin
          .from("bot_configs")
          .update({ status: "archived" })
          .eq("platform_id", gc.platform_id)
          .eq("config_type", gc.config_type)
          .eq("config_key", gc.config_key)
          .eq("status", "active");
      }

      const { data: created, error: insertErr } = await supabaseAdmin
        .from("bot_configs")
        .insert({
          platform_id: gc.platform_id,
          config_type: gc.config_type,
          config_key: gc.config_key,
          config_value: gc.config_value,
          version: nextVersion,
          status,
          change_summary: gc.change_summary,
          source_type: "inspect_script",
          effect_metrics: { llm_confidence: gc.confidence, auto_published: canAutoPublish },
        })
        .select()
        .single();

      if (insertErr) {
        console.error("[GenerateConfigs] Insert error:", insertErr);
        continue;
      }

      createdConfigs.push(created!);
      if (canAutoPublish) autoPublishedCount++;

      await logAudit({
        action: canAutoPublish ? "bot_config_publish" : "bot_config_generate",
        resource_type: "bot_configs",
        resource_id: (created as Record<string, unknown>).id as string,
        detail: {
          config_key: gc.config_key,
          config_type: gc.config_type,
          version: nextVersion,
          change_summary: gc.change_summary,
          llm_confidence: gc.confidence,
          auto_published: canAutoPublish,
          source: "inspect_script",
        },
      });
    }

    // Feishu notification for new drafts needing review
    if (createdConfigs.length > 0) {
      const pendingCount = createdConfigs.length - autoPublishedCount;
      if (pendingCount > 0) {
        const draftSummaries = createdConfigs
          .filter((c: Record<string, unknown>) => (c as Record<string, unknown>).status === "draft")
          .map((c: Record<string, unknown>) =>
            `- ${(c as Record<string, unknown>).config_key} v${(c as Record<string, unknown>).version}: ${(c as Record<string, unknown>).change_summary || ""}`
          )
          .join("\n");

        sendFeishuNotification({
          header: {
            title: { tag: "plain_text", content: `📝 话术草稿待审核 — ${pendingCount} 条新草稿` },
            template: "blue",
          },
          elements: [
            {
              tag: "div",
              text: { tag: "lark_md", content: `**质检自动生成** ${pendingCount} 条话术配置草稿，请前往审核。\n\n${draftSummaries}\n\n${autoPublishedCount > 0 ? `✅ ${autoPublishedCount} 条高置信度低风险配置已自动发布。` : ""}` },
            },
            {
              tag: "action",
              actions: [{
                tag: "button",
                text: { tag: "plain_text", content: "前往审核" },
                type: "primary",
                url: `${process.env.NEXT_PUBLIC_SITE_URL || process.env.VERCEL_URL || ""}/dashboard`,
              }],
            },
          ],
        }).catch(() => {});
      }
    }

    if (createdConfigs.length > 0) {
      await triggerTaskPipeline({
        source_type: "chat_inspection",
        session_ids: allSessionIds,
        context: {
          total_inspected: inspect_results.length,
          configs_generated: createdConfigs.length,
          auto_published: autoPublishedCount,
          generated_config_ids: createdConfigs.map((c) => (c as Record<string, unknown>).id),
          duplicates_skipped: postDedupSkipped,
        },
      });
    }

    return NextResponse.json({
      success: true,
      configs_generated: createdConfigs.length,
      auto_published: autoPublishedCount,
      duplicates_skipped: postDedupSkipped,
      configs: createdConfigs,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[GenerateConfigs] Error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
