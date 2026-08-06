// ============================================================================
// Alert Engine — three-tier quality/risk alerting with Feishu integration.
// L1: Single store quality drop → auto-disable store + notify
// L2: Global quality trend degradation → global circuit breaker + notify
// L3: Compliance violation detected → immediate shutdown + notify all
// ============================================================================

import { sendFeishuNotification, isFeishuEnabled } from "../feishu";
import type { GlobalQualitySnapshot, IntentQualityScore } from "./quality-metrics";

// ── Types ──

export type AlertLevel = "L1" | "L2" | "L3";

export interface AlertRule {
  level: AlertLevel;
  name: string;
  condition: (snapshot: GlobalQualitySnapshot, previousSnapshot?: GlobalQualitySnapshot) => boolean;
  buildMessage: (snapshot: GlobalQualitySnapshot, previousSnapshot?: GlobalQualitySnapshot) => string;
  autoAction: string;
}

export interface AlertResult {
  triggered: boolean;
  level: AlertLevel;
  rule: string;
  message: string;
  autoAction: string;
  timestamp: string;
}

// ── Rule definitions ──

const ALERT_RULES: AlertRule[] = [
  // L1: Per-intent quality drops below threshold with sufficient samples
  {
    level: "L1",
    name: "单意图质量下降",
    condition: (snapshot) => {
      return snapshot.intents.some(
        (i) => i.sampleCount >= 10 && i.qualityScore < 50 && i.riskScore > 20,
      );
    },
    buildMessage: (snapshot) => {
      const problematic = snapshot.intents.filter(
        (i) => i.sampleCount >= 10 && i.qualityScore < 50,
      );
      const names = problematic.map((i) => `${i.intent}(质量${i.qualityScore})`).join(", ");
      return `⚠️ 以下意图回复质量低于阈值: ${names}`;
    },
    autoAction: "该意图自动降级为影子模式",
  },

  // L1: Compliance block rate spikes
  {
    level: "L1",
    name: "合规拦截率异常",
    condition: (snapshot) => {
      return snapshot.complianceBlocked24h >= 5;
    },
    buildMessage: (snapshot) => {
      return `🚨 24小时内合规拦截 ${snapshot.complianceBlocked24h} 条回复，请立即检查`;
    },
    autoAction: "自动暂停该店铺真实回复",
  },

  // L2: Global quality drops significantly
  {
    level: "L2",
    name: "全局质量骤降",
    condition: (snapshot, prev) => {
      if (!prev) return false;
      const drop = prev.overallQuality - snapshot.overallQuality;
      return drop > 20 && snapshot.totalReplies24h >= 50;
    },
    buildMessage: (snapshot, prev) => {
      const drop = (prev?.overallQuality ?? 0) - snapshot.overallQuality;
      return `🔴 全局回复质量下降 ${drop} 分 (${prev?.overallQuality ?? "?"} → ${snapshot.overallQuality})，建议触发全局熔断`;
    },
    autoAction: "全局熔断 + 触发代码审计",
  },

  // L2: Fallback rate exceeds 30%
  {
    level: "L2",
    name: "兜底率过高",
    condition: (snapshot) => {
      const totalFallback = snapshot.intents.reduce((s, i) => s + i.fallbackRate * i.sampleCount, 0);
      const totalSamples = snapshot.intents.reduce((s, i) => s + i.sampleCount, 0);
      const overallFallback = totalSamples > 0 ? totalFallback / totalSamples : 0;
      return overallFallback > 30 && totalSamples >= 20;
    },
    buildMessage: (snapshot) => {
      const totalFallback = snapshot.intents.reduce((s, i) => s + i.fallbackRate * i.sampleCount, 0);
      const totalSamples = snapshot.intents.reduce((s, i) => s + i.sampleCount, 0);
      const overallFallback = totalSamples > 0 ? Math.round(totalFallback / totalSamples) : 0;
      return `🟡 关键词兜底率 ${overallFallback}% 超过阈值 30%，可能 LLM 服务异常`;
    },
    autoAction: "检查 LLM 服务健康状态",
  },

  // L3: Compliance guard detects sensitive keywords in generated replies
  {
    level: "L3",
    name: "合规违规检测",
    condition: (snapshot) => {
      return snapshot.complianceBlocked24h >= 10;
    },
    buildMessage: (snapshot) => {
      return `🚨🚨🚨 严重合规告警: 24小时内拦截 ${snapshot.complianceBlocked24h} 条违规回复，可能模型输出异常`;
    },
    autoAction: "立即关闭所有真实回复 + 通知法务",
  },

  // L3: Pending approval queue exceeds capacity
  {
    level: "L3",
    name: "审核队列积压",
    condition: (snapshot) => {
      return snapshot.pendingApproval > 100;
    },
    buildMessage: (snapshot) => {
      return `🔴 待审核回复积压 ${snapshot.pendingApproval} 条，超过处理能力`;
    },
    autoAction: "暂停新回复生成，清空审核队列",
  },

  // QAE-022: SLO violation based alert (MVP)
  {
    level: "L2",
    name: "SLO 违反",
    condition: (snapshot) => {
      // 仅当 SLO 真实被突破才告警；unknown（无数据）不触发误报
      return (snapshot.sloStatuses || []).some((s) => s.status === "breached");
    },
    buildMessage: (snapshot) => {
      const violated = (snapshot.sloStatuses || [])
        .filter((s) => s.status === "breached")
        .map((s) => `${s.name} (当前${s.current ?? "未知"} 目标${s.target})`)
        .join("; ");
      return `⚠️ SLO 违反: ${violated || "未知"}，错误预算受影响`;
    },
    autoAction: "检查 SLI 并触发回退或人工介入",
  },
];

// ── Alert engine ──

export function evaluateAlerts(
  snapshot: GlobalQualitySnapshot,
  previousSnapshot?: GlobalQualitySnapshot,
): AlertResult[] {
  const results: AlertResult[] = [];

  for (const rule of ALERT_RULES) {
    if (rule.condition(snapshot, previousSnapshot)) {
      results.push({
        triggered: true,
        level: rule.level,
        rule: rule.name,
        message: rule.buildMessage(snapshot, previousSnapshot),
        autoAction: rule.autoAction,
        timestamp: new Date().toISOString(),
      });
    }
  }

  // Sort by severity: L3 first, then L2, then L1
  results.sort((a, b) => {
    const order = { L3: 0, L2: 1, L1: 2 };
    return order[a.level] - order[b.level];
  });

  return results;
}

// ── Feishu notification integration ──

export async function dispatchAlerts(
  alerts: AlertResult[],
  reviewerFeishuOpenId?: string,
): Promise<void> {
  if (alerts.length === 0) return;
  if (!isFeishuEnabled()) return; // Dify 稳定使用：完全禁用飞书告警

  // L3 alerts: build a critical card
  const l3Alerts = alerts.filter((a) => a.level === "L3");
  if (l3Alerts.length > 0) {
    const card = {
      config: { wide_screen_mode: true },
      header: {
        title: { tag: "plain_text", content: "🚨 E-Sentinel 严重告警" },
        template: "red" as const,
      },
      elements: l3Alerts.map((a) => ({
        tag: "div",
        text: { tag: "lark_md" as const, content: `**${a.rule}**\n${a.message}\n自动操作: ${a.autoAction}` },
      })),
    };
    sendFeishuNotification(card, reviewerFeishuOpenId).catch(() => {});
  }

  // L2 alerts: build warning card
  const l2Alerts = alerts.filter((a) => a.level === "L2");
  if (l2Alerts.length > 0) {
    const card = {
      config: { wide_screen_mode: true },
      header: {
        title: { tag: "plain_text", content: "⚠️ E-Sentinel 质量告警" },
        template: "yellow" as const,
      },
      elements: l2Alerts.map((a) => ({
        tag: "div",
        text: { tag: "lark_md" as const, content: `**${a.rule}**\n${a.message}\n建议操作: ${a.autoAction}` },
      })),
    };
    sendFeishuNotification(card, reviewerFeishuOpenId).catch(() => {});
  }

  // L1 alerts: summary only (don't spam)
  const l1Alerts = alerts.filter((a) => a.level === "L1");
  if (l1Alerts.length > 0) {
    const card = {
      config: { wide_screen_mode: true },
      header: {
        title: { tag: "plain_text", content: "ℹ️ E-Sentinel 运营提醒" },
        template: "blue" as const,
      },
      elements: [
        {
          tag: "div",
          text: {
            tag: "lark_md" as const,
            content: l1Alerts.map((a) => `- **${a.rule}**: ${a.message}`).join("\n"),
          },
        },
      ],
    };
    sendFeishuNotification(card, reviewerFeishuOpenId).catch(() => {});
  }
}
