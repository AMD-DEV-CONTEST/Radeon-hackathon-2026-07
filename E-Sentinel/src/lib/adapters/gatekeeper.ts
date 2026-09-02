// ============================================================================
// Shadow Reply Gatekeeper — 4-tier gradual rollout gating.
// Pure functions: no DB, no side effects, deterministically testable.
//
// Tiers (progressive):
//   off              — No shadow processing, zero LLM cost
//   whitelist        — Only sessions in SHADOW_REPLY_WHITELIST
//   simple_questions — All sessions, but only known e-commerce intents
//   ratio            — All sessions, all questions, traffic-percentage sampling
// ============================================================================

export type ShadowTier = "off" | "whitelist" | "simple_questions" | "ratio";

export interface ShadowGateConfig {
  tier: ShadowTier;
  whitelist: Set<string>;
  trafficRatio: number; // 0–1
}

export interface GateDecision {
  allowed: boolean;
  reason: string;
  tier: ShadowTier;
}

const SIMPLE_QUESTION_KEYWORDS = [
  "发货", "物流", "快递", "订单", "退款", "退货", "退钱",
  "优惠券", "满减", "活动", "质量", "瑕疵", "破损", "坏了", "烂了",
  "尺码", "颜色", "换货", "价格", "降价", "客服", "投诉",
];

function isSimpleQuestion(text: string): boolean {
  return SIMPLE_QUESTION_KEYWORDS.some((kw) => text.includes(kw));
}

export function evaluateShadowGate(
  config: ShadowGateConfig,
  sessionId: string,
  messageText: string,
): GateDecision {
  if (config.tier === "off") {
    return { allowed: false, reason: "shadow_disabled", tier: "off" };
  }

  if (config.tier === "whitelist") {
    if (config.whitelist.has(sessionId)) {
      return { allowed: true, reason: "whitelist_match", tier: "whitelist" };
    }
    return { allowed: false, reason: "not_in_whitelist", tier: "whitelist" };
  }

  if (config.tier === "simple_questions") {
    if (isSimpleQuestion(messageText)) {
      return { allowed: true, reason: "simple_question_match", tier: "simple_questions" };
    }
    return { allowed: false, reason: "not_simple_question", tier: "simple_questions" };
  }

  // tier === "ratio"
  if (Math.random() < config.trafficRatio) {
    return { allowed: true, reason: "traffic_ratio_hit", tier: "ratio" };
  }
  return { allowed: false, reason: "traffic_ratio_miss", tier: "ratio" };
}

/** Build config from env vars. Call once per request. */
export function buildShadowGateConfig(env: Record<string, string | undefined>): ShadowGateConfig {
  const enabled = env.SHADOW_REPLY_ENABLED === "true";
  return {
    tier: (enabled ? (env.SHADOW_REPLY_TIER || "off") : "off") as ShadowTier,
    whitelist: new Set(
      (env.SHADOW_REPLY_WHITELIST || "")
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
    ),
    trafficRatio: clamp(parseFloat(env.SHADOW_REPLY_RATIO || "0.1")),
  };
}

function clamp(n: number): number {
  if (isNaN(n)) return 0.1;
  return Math.min(1, Math.max(0, n));
}
