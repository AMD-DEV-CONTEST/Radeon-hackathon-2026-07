/**
 * FunctionRouter — automatic request dispatch to the right Subagent.
 *
 * Two-layer routing strategy:
 *   Layer 1: Keyword matching (fast, ~0ms, covers ~80% of cases)
 *   Layer 2: LLM intent classification (fallback for ambiguous queries, ~2-3s)
 *
 * If both layers fail to route with confidence > threshold, defaults to 'general'.
 *
 * Design goals:
 *   Speed: Layer 1 is zero-latency keyword match
 *   Accuracy: Layer 2 LLM fallback handles ambiguous queries
 *   Coverage: 5 subagents cover project mgmt, knowledge, data, writing, chat
 */

import type { SubagentId, SubagentConfig, RouteResult } from './types';
import { getAllSubagents, getSubagent } from './subagents';
import { keywordWeightAdjuster, feedbackStore } from './router-learning';

// ─── Layer 1: Keyword Matching ────────────────────────────────────────────────

/**
 * Score each subagent by counting keyword matches in the user's message.
 * Returns the best match if confidence > threshold, null otherwise.
 */
function keywordRoute(message: string): RouteResult | null {
  const lower = message.toLowerCase();
  const scores: Array<{ config: SubagentConfig; score: number; matched: string[] }> = [];

  for (const config of getAllSubagents()) {
    const matched: string[] = [];
    for (const keyword of config.routingKeywords) {
      if (lower.includes(keyword.toLowerCase())) {
        matched.push(keyword);
      }
    }
    if (matched.length > 0) {
      scores.push({ config, score: matched.length, matched });
    }
  }

  if (scores.length === 0) return null;

  // Sort by score descending
  scores.sort((a, b) => b.score - a.score);

  const best = scores[0];
  const second = scores[1];

  // Confidence: ratio of best score to total matches
  const totalMatches = scores.reduce((s, x) => s + x.score, 0);
  const confidence = totalMatches > 0 ? best.score / totalMatches : 0;

  // Route if best is clearly ahead (confidence > 0.4) or is the only match
  if (confidence >= 0.4 || scores.length === 1) {
    // Tie-breaker: if best and second have the same score, prefer non-general
    if (second && best.score === second.score && best.config.id === 'general') {
      return {
        subagent: second.config.id,
        confidence: 0.5,
        routedBy: 'keyword',
        reason: `Tie-breaker: ${second.config.id} over general (${second.matched.join(', ')})`,
      };
    }
    return {
      subagent: best.config.id,
      confidence: Math.round(confidence * 100) / 100,
      routedBy: 'keyword',
      reason: `Matched keywords: ${best.matched.join(', ')}`,
    };
  }

  // If top two are close, prefer the more specific one (non-general)
  if (second && best.score === second.score) {
    const specific = best.config.id === 'general' ? second : best;
    return {
      subagent: specific.config.id,
      confidence: 0.5,
      routedBy: 'keyword',
      reason: `Tie-breaker: ${specific.config.id} over general (${best.matched.join(', ')})`,
    };
  }

  return null;
}

// ─── Layer 2: LLM Intent Classification ────────────────────────────────────────

/**
 * Use the LLM to classify the user's intent when keyword matching is ambiguous.
 *
 * This sends a short prompt with all routing examples and asks the LLM to
 * pick the best subagent. Falls back to 'general' on any error.
 */
async function llmRoute(
  message: string,
  llmCall: (prompt: string) => Promise<string>
): Promise<RouteResult | null> {
  const examples = getAllSubagents()
    .map((s) => {
      const exs = s.routingExamples.map((e) => `  - "${e}"`).join('\n');
      return `${s.id} (${s.label}):\n${exs}`;
    })
    .join('\n\n');

  const prompt = `You are a FunctionRouter. Classify the user's message into one of these subagent categories.

Subagents:
${examples}

User message: "${message}"

Respond with ONLY the subagent id (one of: general, knowledge_rag, data_analysis, writing_assistant, quick_chat). No explanation.`;

  try {
    const response = await llmCall(prompt);
    const cleaned = response.trim().toLowerCase();

    // Validate response — derive valid IDs dynamically from the registry
    const validIds = getAllSubagents().map((s) => s.id);
    const match = validIds.find((id) => cleaned.includes(id));

    if (match) {
      return {
        subagent: match,
        confidence: 0.7,
        routedBy: 'llm',
        reason: `LLM classified as: ${match}`,
      };
    }
  } catch {
    // LLM call failed, fall through to default
  }

  return null;
}

// ─── Public API ───────────────────────────────────────────────────────────────

/**
 * Route a user message to the best Subagent.
 *
 * @param message - The user's latest message
 * @param llmCall - Optional: function to call LLM for Layer 2 routing.
 *                  If not provided, only Layer 1 (keyword) is used.
 * @returns RouteResult with subagent, confidence, and routing reason
 */
export async function routeMessage(
  message: string,
  llmCall?: (prompt: string) => Promise<string>
): Promise<RouteResult> {
  // Layer 1: Fast keyword matching
  const keywordResult = keywordRoute(message);
  if (keywordResult && keywordResult.confidence >= 0.5) {
    return keywordResult;
  }

  // Layer 2: LLM intent classification (if available)
  if (llmCall) {
    const llmResult = await llmRoute(message, llmCall);
    if (llmResult) {
      return llmResult;
    }
  }

  // Default: general subagent
  return {
    subagent: 'general',
    confidence: 0.3,
    routedBy: 'default',
    reason: 'No keyword match; defaulted to general',
  };
}

/**
 * Synchronous variant — only uses Layer 1 (keyword matching).
 * Use this when you don't want the latency of LLM classification.
 */
export function routeMessageSync(message: string): RouteResult {
  const result = keywordRoute(message);
  if (result) return result;

  return {
    subagent: 'general',
    confidence: 0.3,
    routedBy: 'default',
    reason: 'No keyword match; defaulted to general',
  };
}

/**
 * Get the tool names for a routed subagent.
 * All subagents (including 'general') return only their configured tools.
 * This enforces tool isolation per subagent, preventing the LLM from
 * invoking tools outside the routed subagent's scope.
 */
export function getRoutedTools(subagentId: SubagentId, allToolNames: string[]): string[] {
  const config = getSubagent(subagentId);

  // Quick chat: no tools
  if (config.lightweight) return [];

  // All subagents: only their configured tools (including general)
  return config.tools;
}

// ─── Layer 1.5: Self-learning enhanced routing ───────────────────────────────

/**
 * Confidence floor below which keyword routing normally abstains. When the
 * learning layer detects low confidence, it lowers this floor adaptively (see
 * routeMessageWithLearning) because the learned weights are trusted to have
 * compensated for the keyword ambiguity that low confidence signals.
 */
const BASE_KEYWORD_THRESHOLD = 0.4;

/** Hard lower bound for the adaptive threshold. */
const MIN_ADAPTIVE_THRESHOLD = 0.2;

/**
 * How aggressively the correction rate lowers the threshold. A correction rate
 * of 1.0 lowers the floor by 0.2 (from 0.4 to the MIN_ADAPTIVE_THRESHOLD).
 */
const THRESHOLD_ADAPT_STEP = 0.2;

/**
 * Route a message using keyword matching augmented by learned weight
 * adjustments (the Router self-learning path).
 *
 * For each subagent, every matched keyword contributes its learned multiplier
 * (default 1.0, range [0.1, 2.0]) instead of a flat count of 1. The subagent
 * with the highest total weighted score wins, and confidence is that score's
 * share of all weighted matches.
 *
 * When the resulting confidence falls below the normal BASE_KEYWORD_THRESHOLD,
 * the threshold is lowered proportionally to the observed correction rate:
 * the more corrections the system has absorbed, the more we trust the learned
 * weights to disambiguate, so a lower raw confidence is acceptable.
 *
 * This function is purely additive — `routeMessage()` and `routeMessageSync()`
 * are untouched, so the non-learning path remains a safe fallback.
 */
export function routeMessageWithLearning(message: string): RouteResult {
  const lower = message.toLowerCase();
  const scores: Array<{
    config: SubagentConfig;
    matched: string[];
    weightedScore: number;
  }> = [];

  for (const config of getAllSubagents()) {
    const matched: string[] = [];
    let weightedScore = 0;
    for (const keyword of config.routingKeywords) {
      if (lower.includes(keyword.toLowerCase())) {
        matched.push(keyword);
        // Multiply each keyword's contribution by its learned weight.
        const weight = keywordWeightAdjuster.getAdjustedWeight(config.id, keyword);
        weightedScore += weight;
      }
    }
    if (matched.length > 0) {
      scores.push({ config, matched, weightedScore });
    }
  }

  // No keyword match at all — same default as routeMessageSync.
  if (scores.length === 0) {
    return {
      subagent: 'general',
      confidence: 0.3,
      routedBy: 'default',
      reason: 'No keyword match; defaulted to general',
    };
  }

  // Rank by learned weighted score (descending).
  scores.sort((a, b) => b.weightedScore - a.weightedScore);
  const best = scores[0];
  const second = scores[1];

  // Confidence = best's weighted share of the total weighted matches.
  const totalWeighted = scores.reduce((s, x) => s + x.weightedScore, 0);
  const confidence = totalWeighted > 0 ? best.weightedScore / totalWeighted : 0;

  // Adaptive threshold: low confidence signals keyword ambiguity. Lower the
  // floor based on how much learning data we have accumulated — learned
  // weights are trusted to have corrected the underlying inaccuracy.
  const { rate } = feedbackStore.getCorrectionRate();
  const effectiveThreshold =
    confidence < BASE_KEYWORD_THRESHOLD
      ? Math.max(MIN_ADAPTIVE_THRESHOLD, BASE_KEYWORD_THRESHOLD - rate * THRESHOLD_ADAPT_STEP)
      : BASE_KEYWORD_THRESHOLD;

  // Route if confidence clears the (possibly lowered) threshold, or it is the
  // only matching subagent.
  if (confidence >= effectiveThreshold || scores.length === 1) {
    const learned = keywordWeightAdjuster.hasAdjustments();
    return {
      subagent: best.config.id,
      confidence: Math.round(confidence * 100) / 100,
      routedBy: 'keyword',
      reason: `Learned match${learned ? ' (weights applied)' : ''}: ${best.matched.join(', ')} (threshold ${effectiveThreshold.toFixed(2)})`,
    };
  }

  // Tie-breaker: when the top two weighted scores are equal, prefer the more
  // specific (non-general) subagent — same heuristic as keywordRoute.
  if (second && best.weightedScore === second.weightedScore) {
    const specific = best.config.id === 'general' ? second : best;
    return {
      subagent: specific.config.id,
      confidence: 0.5,
      routedBy: 'keyword',
      reason: `Learned tie-breaker: ${specific.config.id} over general (${best.matched.join(', ')})`,
    };
  }

  // Still ambiguous after learning — fall back to general.
  return {
    subagent: 'general',
    confidence: 0.3,
    routedBy: 'default',
    reason: 'Ambiguous after learned weights; defaulted to general',
  };
}
