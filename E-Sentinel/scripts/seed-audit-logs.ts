// ============================================================================
// seed-audit-logs.ts — 注入 18 条时间线合理的审计日志
// 与已有 28 条种子数据形成因果链，供系统审计面板展示
// 用法: npx tsx scripts/seed-audit-logs.ts
// ============================================================================

import { createClient } from "@supabase/supabase-js";
import { config } from "dotenv";
import { resolve } from "path";
import { randomUUID } from "crypto";

config({ path: resolve(__dirname, "../.env.local") });

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
const supabaseKey = process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

if (!supabaseUrl || !supabaseKey) {
  console.error("缺少 Supabase 环境变量。请确认 .env.local 中有 NEXT_PUBLIC_SUPABASE_URL 和 SUPABASE_SERVICE_ROLE_KEY");
  process.exit(1);
}

const supabase = createClient(supabaseUrl, supabaseKey);

const NOW = new Date();
function ago(hours: number, minutes = 0): string {
  const d = new Date(NOW.getTime() - (hours * 3600 + minutes * 60) * 1000);
  return d.toISOString();
}

const USER_ID = "5a0a26d8-2f78-4f82-9ed4-adb83847bc84";
const USER_NAME = "张运营";

interface AuditLog {
  action: string;
  user_id?: string;
  user_name?: string;
  resource_type?: string;
  resource_id?: string;
  detail: Record<string, unknown> | null;
  correlation_id: string;
  created_at: string;
}

const LOGS: AuditLog[] = [
  // ── Chain 1: 物流怒火会话 → LLM 质检 → 飞书派发 ──────────────────────
  {
    action: "llm_call",
    user_id: USER_ID,
    user_name: USER_NAME,
    resource_type: "llm",
    detail: {
      model: "moonshot-v1-8k",
      prompt_type: "chat_inspect",
      tokens_used: 1840,
      latency_ms: 2340,
      was_fallback: false,
      cached: false,
    },
    correlation_id: "corr-logistics-fury-001",
    created_at: ago(6, 0),
  },
  {
    action: "evaluate",
    user_id: USER_ID,
    user_name: USER_NAME,
    resource_type: "quality_reports",
    resource_id: "eval-001",
    detail: {
      score: 35,
      risk_level: "high",
      violations_count: 4,
      needs_alert: true,
    },
    correlation_id: "corr-logistics-fury-001",
    created_at: ago(5, 55),
  },
  {
    action: "dispatch_feishu",
    user_id: USER_ID,
    user_name: USER_NAME,
    resource_type: "feishu_dispatch",
    detail: {
      route: "private_message",
      target: "李主管",
      method: "飞书私信 (open_id)",
      alert_method: "private_message",
      delivery_status: "success",
    },
    correlation_id: "corr-logistics-fury-001",
    created_at: ago(5, 54),
  },

  // ── Chain 2: 优惠券死循环 → LLM 质检 → 结果正常（无需派发）────────
  {
    action: "llm_call",
    user_id: USER_ID,
    user_name: USER_NAME,
    resource_type: "llm",
    detail: {
      model: "moonshot-v1-8k",
      prompt_type: "chat_inspect",
      tokens_used: 2100,
      latency_ms: 1800,
      was_fallback: false,
      cached: true,
    },
    correlation_id: "corr-deadloop-001",
    created_at: ago(5, 30),
  },
  {
    action: "evaluate",
    user_id: USER_ID,
    user_name: USER_NAME,
    resource_type: "quality_reports",
    resource_id: "eval-002",
    detail: {
      score: 65,
      risk_level: "medium",
      violations_count: 2,
      needs_alert: false,
    },
    correlation_id: "corr-deadloop-001",
    created_at: ago(5, 28),
  },

  // ── Chain 3: 满意度分析 → 流水线自动建任务 ─────────────────────────
  {
    action: "llm_call",
    user_id: USER_ID,
    user_name: USER_NAME,
    resource_type: "llm",
    detail: {
      model: "moonshot-v1-8k",
      prompt_type: "satisfaction_analyze",
      tokens_used: 3200,
      latency_ms: 4520,
      was_fallback: false,
      cached: false,
    },
    correlation_id: "satisfaction-analyze",
    created_at: ago(4, 45),
  },
  {
    action: "optimization_task_create",
    user_id: USER_ID,
    user_name: USER_NAME,
    resource_type: "pipeline",
    detail: {
      source_type: "satisfaction",
      tasks_created: 2,
      context: { cause_count: 3 },
    },
    correlation_id: "satisfaction-analyze",
    created_at: ago(4, 44),
  },

  // ── Chain 4: 周报生成 ──────────────────────────────────────────────
  {
    action: "llm_call",
    user_id: USER_ID,
    user_name: USER_NAME,
    resource_type: "llm",
    detail: {
      model: "moonshot-v1-8k",
      prompt_type: "report_generate",
      tokens_used: 4100,
      latency_ms: 5120,
      was_fallback: false,
      cached: false,
    },
    correlation_id: "report-gen",
    created_at: ago(3, 30),
  },
  {
    action: "report_generate",
    user_id: USER_ID,
    user_name: USER_NAME,
    resource_type: "robot_reports",
    resource_id: "rpt-weekly-001",
    detail: {
      report_type: "weekly",
      period: "2026-W19",
    },
    correlation_id: "report-gen",
    created_at: ago(3, 25),
  },

  // ── Chain 5: 知识库操作 ────────────────────────────────────────────
  {
    action: "knowledge_create",
    user_id: USER_ID,
    user_name: USER_NAME,
    resource_type: "knowledge_entries",
    resource_id: "ke-fresh-001",
    detail: {
      title: "生鲜食品退换货政策",
      category: "after_sales_policy",
      priority: 8,
    },
    correlation_id: "kb-update-20260514",
    created_at: ago(2, 30),
  },
  {
    action: "knowledge_update",
    user_id: USER_ID,
    user_name: USER_NAME,
    resource_type: "knowledge_entries",
    resource_id: "ke-coupon-001",
    detail: {
      title: "优惠券叠加规则（简化版）",
      category: "faq",
      priority: 9,
    },
    correlation_id: "kb-update-20260514",
    created_at: ago(1, 45),
  },

  // ── Chain 6: 询单流失分析 → 流水线 ─────────────────────────────────
  {
    action: "llm_call",
    user_id: USER_ID,
    user_name: USER_NAME,
    resource_type: "llm",
    detail: {
      model: "moonshot-v1-8k",
      prompt_type: "inquiry_loss_analyze",
      tokens_used: 2800,
      latency_ms: 3890,
      was_fallback: false,
      cached: false,
    },
    correlation_id: "inquiry-loss-analyze",
    created_at: ago(1, 30),
  },
  {
    action: "optimization_task_create",
    user_id: USER_ID,
    user_name: USER_NAME,
    resource_type: "pipeline",
    detail: {
      source_type: "inquiry_loss",
      tasks_created: 1,
      context: { cause_count: 2 },
    },
    correlation_id: "inquiry-loss-analyze",
    created_at: ago(1, 29),
  },

  // ── Chain 7: 退款陷阱回话 → 误判驳回 ──────────────────────────────
  {
    action: "evaluate",
    user_id: USER_ID,
    user_name: USER_NAME,
    resource_type: "quality_reports",
    resource_id: "eval-003",
    detail: {
      score: 55,
      risk_level: "medium",
      violations_count: 2,
      needs_alert: false,
    },
    correlation_id: "corr-refund-trap-001",
    created_at: ago(1, 15),
  },
  {
    action: "overturn",
    user_id: USER_ID,
    user_name: USER_NAME,
    resource_type: "quality_reports",
    resource_id: "eval-003",
    detail: {
      corrected_by: "李主管",
      reason: "客服已正确执行退款流程，AI 对'用户需自行承担退货运费'误判为态度问题",
      corrected_score: 85,
      corrected_risk_level: "low",
    },
    correlation_id: "corr-refund-trap-001",
    created_at: ago(0, 55),
  },

  // ── Chain 8: 话术配置启用 + 活动导入 ──────────────────────────────
  {
    action: "bot_config_activate",
    user_id: USER_ID,
    user_name: USER_NAME,
    resource_type: "bot_configs",
    resource_id: "cfg-jd-price-001",
    detail: {
      platform: "京东",
      config_key: "jd_price_match",
      version: 2,
    },
    correlation_id: "config-update-20260514",
    created_at: ago(0, 40),
  },
  {
    action: "llm_call",
    user_id: USER_ID,
    user_name: USER_NAME,
    resource_type: "llm",
    detail: {
      model: "moonshot-v1-8k",
      prompt_type: "campaign_extract",
      tokens_used: 1500,
      latency_ms: 3200,
      was_fallback: true,
      cached: false,
    },
    correlation_id: "batch-import",
    created_at: ago(0, 30),
  },
  {
    action: "campaign_import",
    user_id: USER_ID,
    user_name: USER_NAME,
    resource_type: "knowledge_entries",
    detail: {
      count: 4,
    },
    correlation_id: "batch-import",
    created_at: ago(0, 29),
  },
];

async function main() {
  console.log(`准备注入 ${LOGS.length} 条审计日志到 audit_logs 表...\n`);

  let inserted = 0;
  let skipped = 0;

  for (const log of LOGS) {
    const { error } = await supabase.from("audit_logs").insert({
      id: randomUUID(),
      action: log.action,
      user_id: log.user_id || null,
      user_name: log.user_name || null,
      resource_type: log.resource_type || null,
      resource_id: log.resource_id || null,
      detail: log.detail,
      correlation_id: log.correlation_id,
      created_at: log.created_at,
    });

    if (error) {
      console.error(`  ✗ ${log.action} — ${error.message}`);
      skipped++;
    } else {
      const time = new Date(log.created_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
      console.log(`  ✓ ${time}  ${log.action.padEnd(26)}  trace: ${log.correlation_id}`);
      inserted++;
    }
  }

  console.log(`\n完成: ${inserted} 条成功${skipped > 0 ? `, ${skipped} 条跳过` : ""}`);

  // Summary of correlation chains
  const chains = [...new Set(LOGS.map((l) => l.correlation_id))];
  console.log(`\n${chains.length} 条 Trace 链:`);
  for (const cid of chains) {
    const events = LOGS.filter((l) => l.correlation_id === cid);
    console.log(`  ${cid}  → ${events.map((e) => e.action).join(" → ")}`);
  }
}

main().catch((err) => {
  console.error("注入失败:", err);
  process.exit(1);
});
