// ============================================================================
// Auto-Throttle Engine — data-driven gradual rollout control.
// Reads quality metrics and outputs throttle actions per intent category.
// Replaces manual gating decisions with automated, evidence-based adjustments.
// ============================================================================

import type { IntentQualityScore, GlobalQualitySnapshot } from "./quality-metrics";

// ── Types ──

export type ThrottleAction =
  | "INCREASE"            // quality good → raise traffic ratio
  | "HOLD"                // insufficient data or borderline quality
  | "DECREASE"            // quality declining → lower traffic ratio
  | "EMERGENCY_DOWNGRADE"; // risk spike → immediate shadow-mode fallback

export interface ThrottleDecision {
  action: ThrottleAction;
  reason: string;
  /** Suggested new traffic ratio (0-1) */
  suggestedRatio: number;
  /** Current quality score that drove this decision */
  currentQuality: number;
  /** Current risk score */
  currentRisk: number;
  /** Minimum sample count for this decision to be statistically meaningful */
  confidenceLevel: "high" | "medium" | "low";
}

export interface AutoThrottleConfig {
  /** Quality score above which we consider increasing traffic */
  qualityIncreaseThreshold: number;
  /** Risk score below which we consider increasing traffic */
  riskIncreaseThreshold: number;
  /** Quality score below which we force decrease */
  qualityDecreaseThreshold: number;
  /** Risk score above which we force decrease */
  riskDecreaseThreshold: number;
  /** Risk score above which we trigger emergency downgrade */
  riskEmergencyThreshold: number;
  /** Minimum sample count to make statistically meaningful decisions */
  minSampleCount: number;
  /** Maximum traffic ratio (never exceed this) */
  maxRatio: number;
  /** Step size for ratio adjustments */
  ratioStep: number;
}

const DEFAULT_CONFIG: AutoThrottleConfig = {
  qualityIncreaseThreshold: 85,
  riskIncreaseThreshold: 15,
  qualityDecreaseThreshold: 60,
  riskDecreaseThreshold: 25,
  riskEmergencyThreshold: 40,
  minSampleCount: 10,
  maxRatio: 0.8,
  ratioStep: 0.1,
};

// ── Decision engine ──

export function decideIntentThrottle(
  intent: IntentQualityScore,
  currentRatio: number,
  config: Partial<AutoThrottleConfig> = {},
): ThrottleDecision {
  const cfg = { ...DEFAULT_CONFIG, ...config };

  // Confidence level based on sample count
  let confidenceLevel: "high" | "medium" | "low";
  if (intent.sampleCount >= 50) confidenceLevel = "high";
  else if (intent.sampleCount >= cfg.minSampleCount) confidenceLevel = "medium";
  else confidenceLevel = "low";

  // Not enough data → hold
  if (intent.sampleCount < cfg.minSampleCount) {
    return {
      action: "HOLD",
      reason: `样本量不足 (${intent.sampleCount} < ${cfg.minSampleCount})，保持当前比例`,
      suggestedRatio: currentRatio,
      currentQuality: intent.qualityScore,
      currentRisk: intent.riskScore,
      confidenceLevel: "low",
    };
  }

  // Emergency: risk spike
  if (intent.riskScore >= cfg.riskEmergencyThreshold) {
    return {
      action: "EMERGENCY_DOWNGRADE",
      reason: `风险评分 ${intent.riskScore} 超过紧急阈值 ${cfg.riskEmergencyThreshold}，立即降级为影子模式`,
      suggestedRatio: 0,
      currentQuality: intent.qualityScore,
      currentRisk: intent.riskScore,
      confidenceLevel,
    };
  }

  // Quality good AND risk low → increase
  if (intent.qualityScore >= cfg.qualityIncreaseThreshold && intent.riskScore <= cfg.riskIncreaseThreshold) {
    const newRatio = Math.min(cfg.maxRatio, currentRatio + cfg.ratioStep);
    if (newRatio <= currentRatio) {
      return {
        action: "HOLD",
        reason: `已达最大比例 ${cfg.maxRatio}`,
        suggestedRatio: currentRatio,
        currentQuality: intent.qualityScore,
        currentRisk: intent.riskScore,
        confidenceLevel,
      };
    }
    return {
      action: "INCREASE",
      reason: `质量 ${intent.qualityScore} ≥ ${cfg.qualityIncreaseThreshold} 且 风险 ${intent.riskScore} ≤ ${cfg.riskIncreaseThreshold}`,
      suggestedRatio: newRatio,
      currentQuality: intent.qualityScore,
      currentRisk: intent.riskScore,
      confidenceLevel,
    };
  }

  // Quality poor OR risk elevated → decrease
  if (intent.qualityScore < cfg.qualityDecreaseThreshold || intent.riskScore > cfg.riskDecreaseThreshold) {
    const newRatio = Math.max(0, currentRatio - cfg.ratioStep);
    if (newRatio <= 0) {
      return {
        action: "EMERGENCY_DOWNGRADE",
        reason: `质量 ${intent.qualityScore} 或 风险 ${intent.riskScore} 触发降级至零`,
        suggestedRatio: 0,
        currentQuality: intent.qualityScore,
        currentRisk: intent.riskScore,
        confidenceLevel,
      };
    }
    return {
      action: "DECREASE",
      reason: `质量 ${intent.qualityScore} < ${cfg.qualityDecreaseThreshold} 或 风险 ${intent.riskScore} > ${cfg.riskDecreaseThreshold}`,
      suggestedRatio: newRatio,
      currentQuality: intent.qualityScore,
      currentRisk: intent.riskScore,
      confidenceLevel,
    };
  }

  // Borderline → hold
  return {
    action: "HOLD",
    reason: `质量 ${intent.qualityScore} 和 风险 ${intent.riskScore} 处于观察区间`,
    suggestedRatio: currentRatio,
    currentQuality: intent.qualityScore,
    currentRisk: intent.riskScore,
    confidenceLevel,
  };
}

export function decideGlobalThrottle(
  snapshot: GlobalQualitySnapshot,
  currentRatio: number,
  config: Partial<AutoThrottleConfig> = {},
): ThrottleDecision {
  const cfg = { ...DEFAULT_CONFIG, ...config };

  if (snapshot.totalReplies24h < cfg.minSampleCount) {
    return {
      action: "HOLD",
      reason: `全局样本量不足 (${snapshot.totalReplies24h} < ${cfg.minSampleCount})`,
      suggestedRatio: currentRatio,
      currentQuality: snapshot.overallQuality,
      currentRisk: snapshot.overallRisk,
      confidenceLevel: "low",
    };
  }

  // Emergency check first
  if (snapshot.overallRisk >= cfg.riskEmergencyThreshold) {
    return {
      action: "EMERGENCY_DOWNGRADE",
      reason: `全局风险 ${snapshot.overallRisk} ≥ ${cfg.riskEmergencyThreshold}`,
      suggestedRatio: 0,
      currentQuality: snapshot.overallQuality,
      currentRisk: snapshot.overallRisk,
      confidenceLevel: "high",
    };
  }

  // Composite decision
  if (snapshot.overallQuality >= cfg.qualityIncreaseThreshold && snapshot.overallRisk <= cfg.riskIncreaseThreshold) {
    return {
      action: "INCREASE",
      reason: `全局质量 ${snapshot.overallQuality} 达标`,
      suggestedRatio: Math.min(cfg.maxRatio, currentRatio + cfg.ratioStep),
      currentQuality: snapshot.overallQuality,
      currentRisk: snapshot.overallRisk,
      confidenceLevel: "high",
    };
  }

  if (snapshot.overallQuality < cfg.qualityDecreaseThreshold || snapshot.overallRisk > cfg.riskDecreaseThreshold) {
    return {
      action: "DECREASE",
      reason: `全局质量下降或风险上升`,
      suggestedRatio: Math.max(0, currentRatio - cfg.ratioStep),
      currentQuality: snapshot.overallQuality,
      currentRisk: snapshot.overallRisk,
      confidenceLevel: "high",
    };
  }

  return {
    action: "HOLD",
    reason: "全局指标处于观察区间",
    suggestedRatio: currentRatio,
    currentQuality: snapshot.overallQuality,
    currentRisk: snapshot.overallRisk,
    confidenceLevel: "high",
  };
}
