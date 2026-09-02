// Compliance scan engine — 4-level risk prevention system.
// Pure matching logic separated from DB I/O for testability.
//
// Risk levels:
//   1 = fatal   → block + Feishu alert (Advertising Law violations)
//   2 = high    → block + require human review
//   3 = medium  → flag + context-dependent approval
//   4 = low     → flag + auto-correct if possible

export interface ComplianceRule {
  id: string;
  rule_text: string;
  pattern: string;
  risk_level: number;  // 1-4
  category: string;
  action_type: "block" | "warn" | "flag";
  exemption_tags: string[];
}

export interface ComplianceMatch {
  rule: ComplianceRule;
  matched_text: string;
}

export interface ComplianceResult {
  passed: boolean;
  highest_risk: number; // 0 = no match
  decision: "blocked" | "flagged" | "passed";
  matches: ComplianceMatch[];
  summary: string;
}

const DECISION_MAP: Record<number, ComplianceResult["decision"]> = {
  0: "passed",
  1: "blocked",
  2: "blocked",
  3: "flagged",
  4: "flagged",
};

/**
 * Scan content against a set of compliance rules.
 * Pure function — does not touch DB or network.
 */
export function scanCompliance(
  content: string,
  rules: ComplianceRule[]
): ComplianceResult {
  const matches: ComplianceMatch[] = [];

  for (const rule of rules) {
    try {
      const regex = new RegExp(rule.pattern, "giu");
      const m = regex.exec(content);
      if (m) {
        matches.push({ rule, matched_text: m[0] });
      }
    } catch {
      // Skip malformed regex patterns
    }
  }

  if (matches.length === 0) {
    return { passed: true, highest_risk: 0, decision: "passed", matches: [], summary: "No compliance issues detected." };
  }

  // Sort by risk_level ascending (1 = worst) then by rule text
  matches.sort((a, b) => a.rule.risk_level - b.rule.risk_level || a.rule.rule_text.localeCompare(b.rule.rule_text));

  const highest = matches[0].rule.risk_level;
  const decision = DECISION_MAP[highest] || "flagged";

  const fatalCount = matches.filter((m) => m.rule.risk_level === 1).length;
  const highCount = matches.filter((m) => m.rule.risk_level === 2).length;
  const mediumCount = matches.filter((m) => m.rule.risk_level === 3).length;
  const lowCount = matches.filter((m) => m.rule.risk_level === 4).length;

  const parts: string[] = [];
  if (fatalCount > 0) parts.push(`${fatalCount} 致命违规`);
  if (highCount > 0) parts.push(`${highCount} 高风险`);
  if (mediumCount > 0) parts.push(`${mediumCount} 中风险`);
  if (lowCount > 0) parts.push(`${lowCount} 低风险`);

  const summary = `发现 ${matches.length} 项合规问题：${parts.join("、")}。最高风险等级：${riskLabel(highest)}。`;

  return { passed: false, highest_risk: highest, decision, matches, summary };
}

function riskLabel(level: number): string {
  switch (level) {
    case 1: return "致命";
    case 2: return "高风险";
    case 3: return "中风险";
    case 4: return "低风险";
    default: return "无风险";
  }
}

/** Lightweight local scan for pre-publish checks. Falls back to built-in rules if DB unavailable. */
export const BUILT_IN_FATAL_PATTERNS: ComplianceRule[] = [
  {
    id: "builtin-01",
    rule_text: "禁止使用绝对化用语",
    pattern: "国家级|最高级|最佳|最优|第一品牌|独一无二|顶级|极品|全网第一|全球第一|全国第一|万能|全能",
    risk_level: 1,
    category: "absolute_claim",
    action_type: "block",
    exemption_tags: [],
  },
  {
    id: "builtin-02",
    rule_text: "禁止声称治愈率或有效率",
    pattern: "治愈率|有效率|根治|药到病除|永不复发|彻底治愈|无任何副作用|100%[\\s]*有效",
    risk_level: 1,
    category: "advertising_law",
    action_type: "block",
    exemption_tags: [],
  },
  {
    id: "builtin-03",
    rule_text: "禁止虚假承诺",
    pattern: "假一赔万|假一赔命|永不|永久有效|终身保修|终身免费|万无一失|稳赚不赔|保本保息|零风险",
    risk_level: 1,
    category: "false_promise",
    action_type: "block",
    exemption_tags: [],
  },
  {
    id: "builtin-04",
    rule_text: "禁止使用国家标志或暗示国家背书",
    pattern: "国宴|国宾|人民大会堂|国务院|中南海|国家免检|国家推荐",
    risk_level: 1,
    category: "advertising_law",
    action_type: "block",
    exemption_tags: [],
  },
  {
    id: "builtin-05",
    rule_text: "禁止贬低其他经营者",
    pattern: "远超|秒杀(?!活动|专区|价)|吊打|完胜|碾压|甩.*几条街|别人.*不行",
    risk_level: 2,
    category: "competitor_mention",
    action_type: "block",
    exemption_tags: [],
  },
  {
    id: "builtin-06",
    rule_text: "禁止违规比较广告",
    pattern: "价格最低|全网最低价|全国最低价|历史最低|跌破底价|赔本",
    risk_level: 2,
    category: "platform_rule",
    action_type: "warn",
    exemption_tags: [],
  },
  {
    id: "builtin-07",
    rule_text: "禁止诱导点击文案",
    pattern: "点击领取|免费领取|点击抽奖|不点就亏了|马上抢",
    risk_level: 3,
    category: "platform_rule",
    action_type: "warn",
    exemption_tags: [],
  },
  {
    id: "builtin-08",
    rule_text: "禁止使用禁用营销词",
    pattern: "最后一天|仅此一天|清仓|倒闭|破产|跑路|老板哭了|老板疯了",
    risk_level: 3,
    category: "platform_rule",
    action_type: "flag",
    exemption_tags: [],
  },
];

// ── 硬红线下限（ADR-0003 5 层架构：第 1 层） ───────────────────────────────
// 仅在"客服行"生效的硬红线：索要验证码/银行卡/密码、威胁、辱骂。
// 与 BUILT_IN_FATAL_PATTERNS（广告法，全文生效）合并为不可降级风险下限。

export type RiskLevel = "low" | "medium" | "high" | "critical";

export const AGENT_ONLY_REDLINES: ComplianceRule[] = [
  {
    id: "redline-privacy-01",
    rule_text: "禁止索要短信/支付验证码",
    // 只匹配"索要/发给"等主动索取行为，避免误命中"已发送验证码到您的手机"这类合规话术
    pattern: "(请|麻烦)?(把|将)[^。！？]{0,12}(验证码|短信码)(发给我|给我|发过来|发我)|(发给我|发过来|发我|给我|提供|告诉我)[^。！？]{0,18}(验证码|短信码)",
    risk_level: 1,
    category: "privacy",
    action_type: "block",
    exemption_tags: [],
  },
  {
    id: "redline-privacy-02",
    rule_text: "禁止索要银行卡号/完整账号/密码",
    pattern: "(发|发给我|给我|提供|告诉我|把)[^。！？]{0,18}(银行卡号|卡号|支付密码|登录密码|取款密码|账号|密码)|(验证码|银行卡号|卡号|支付密码|登录密码)[^。！？]{0,12}(发给我|给我|提供|告诉我)",
    risk_level: 1,
    category: "privacy",
    action_type: "block",
    exemption_tags: [],
  },
  {
    id: "redline-threat-01",
    rule_text: "禁止威胁客户",
    pattern: "拉黑|再闹|威胁|报警抓",
    risk_level: 1,
    category: "threat",
    action_type: "block",
    exemption_tags: [],
  },
  {
    id: "redline-abuse-01",
    rule_text: "禁止辱骂客户",
    pattern: "你(是)?(傻|蠢|笨|白痴)|闭嘴|滚(开|蛋)?",
    risk_level: 1,
    category: "abuse",
    action_type: "block",
    exemption_tags: [],
  },
];

/** 把最高风险等级映射为可用风险下限（1→critical, 2→high, 3→medium, 4/0→low）。 */
export function floorFromHighestRisk(highestRisk: number): RiskLevel {
  if (highestRisk === 1) return "critical";
  if (highestRisk === 2) return "high";
  if (highestRisk === 3) return "medium";
  return "low";
}

/** 合并两个合规扫描结果，按风险等级升序取最严重者。 */
export function mergeComplianceResults(a: ComplianceResult, b: ComplianceResult): ComplianceResult {
  const matches = [...a.matches, ...b.matches].sort(
    (x, y) => x.rule.risk_level - y.rule.risk_level || x.rule.rule_text.localeCompare(y.rule.rule_text)
  );
  if (matches.length === 0) {
    return { passed: true, highest_risk: 0, decision: "passed", matches: [], summary: "No compliance issues detected." };
  }
  const highest = matches[0].rule.risk_level;
  const decision = highest <= 2 ? "blocked" : "flagged";
  const summary = `发现 ${matches.length} 项合规问题：最高风险等级：${riskLabel(highest)}。`;
  return { passed: false, highest_risk: highest, decision, matches, summary };
}

/**
 * 硬红线下限扫描（ADR-0003 第 1 层）：
 * - 广告法红线（BUILT_IN_FATAL_PATTERNS）全文生效；
 * - 隐私索要/威胁/辱骂（AGENT_ONLY_REDLINES）仅客服行生效，避免客户词误命中。
 */
export function scanHardRedlines(conversation: string): ComplianceResult {
  const agentLines = conversation
    .split("\n")
    .filter((line) => /^客服[:：]/.test(line))
    .join("\n");
  const full = scanCompliance(conversation, BUILT_IN_FATAL_PATTERNS);
  const agent = scanCompliance(agentLines, AGENT_ONLY_REDLINES);
  return mergeComplianceResults(full, agent);
}

// ── 软关键词信号（ADR-0003 第 3 层） ──────────────────────────────────────
// 客户行关键词只产生信号与复核提示，不直接锁定 high/critical。
// 修复关键词陷阱误报（case-005/008/011/015）：客户提退款/12315/假货/二手，
// 客服处理得当时不应升为严重违规。

export interface SoftSignalFlag {
  code: string;
  label: string;
  matched: string;
}

export const SOFT_SIGNAL_RULES: Array<{ code: string; label: string; pattern: RegExp }> = [
  { code: "legal_action_threat", label: "客户诉诸法律/监管", pattern: /12315|工商局|食药监|律师函|起诉|报警|法院|法律/ },
  { code: "complaint_escalation", label: "客户升级投诉/曝光", pattern: /投诉|举报|消费者协会|消协|差评|曝光|媒体/ },
  { code: "refund_dispute", label: "客户退款/退换纠纷", pattern: /退款|退货|退钱|退差价|二手|假货|翻新/ },
  { code: "product_defect", label: "客户反馈产品缺陷", pattern: /破损|瑕疵|坏了|烂了|质量|变砖|固件升级失败/ },
  { code: "logistics_delay", label: "客户物流催促", pattern: /发货|物流|快递|没发|还没发|还没到|没到/ },
  { code: "emotional_intensifier", label: "客户情绪强烈", pattern: /急死|气死|愤怒|没完没了|投诉到底/ },
];

/**
 * 客户行软关键词分类：只产生 flags 与 requiresHumanReview 提示，不改变风险等级。
 * requiresHumanReview 仅在客户诉诸法律/监管（最严重信号）时为 true，其余只是上下文。
 */
export function classifySoftSignals(conversation: string): { flags: SoftSignalFlag[]; requiresHumanReview: boolean } {
  const customerLines = conversation
    .split("\n")
    .filter((line) => /^(顾客|客户|买家|用户)[：:]/.test(line))
    .join("\n");
  const flags: SoftSignalFlag[] = [];
  for (const rule of SOFT_SIGNAL_RULES) {
    const m = customerLines.match(rule.pattern);
    if (m) flags.push({ code: rule.code, label: rule.label, matched: m[0] });
  }
  return {
    flags,
    requiresHumanReview: flags.some((f) => f.code === "legal_action_threat"),
  };
}

/**
 * Fast scan using built-in fatal patterns only. Used as fallback when DB is unavailable.
 * Returns true if content passes basic checks.
 */
export function quickComplianceCheck(content: string): ComplianceResult {
  return scanCompliance(content, BUILT_IN_FATAL_PATTERNS);
}
