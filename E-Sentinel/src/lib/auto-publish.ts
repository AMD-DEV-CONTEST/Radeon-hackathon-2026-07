// Auto-publish decision matrix shared across bot_config and knowledge loops.
// Extracted as a pure function to enable exhaustive boundary testing.
// Floating-point edge cases matter here: 0.949999 vs 0.950000 mean
// "manual review" vs "deployed to production" — identical semantics, opposite behavior.

export interface AutoPublishParams {
  /** LLM-reported confidence (0-1). If null/undefined/NaN, auto-publish is denied. */
  confidence: number | null | undefined;
  /** The category or config_key being checked. */
  category: string;
  /** Set of categories/config_keys considered safe for auto-publish. */
  safeCategories: Set<string>;
  /** Minimum confidence required. Defaults to 0.95. */
  threshold?: number;
  /** Maximum allowed change description length (chars). If omitted, length is not checked. */
  maxChangeLength?: number;
  /** Actual change description length. Required if maxChangeLength is set. */
  changeLength?: number;
}

export function shouldAutoPublish(params: AutoPublishParams): boolean {
  // Defensive: null/undefined/NaN
  if (params.confidence == null || typeof params.confidence !== "number" || isNaN(params.confidence)) {
    return false;
  }

  // Out of range
  if (params.confidence < 0 || params.confidence > 1) {
    return false;
  }

  // Threshold comparison (floating-point: >= means >= 0.95 exactly passes)
  const threshold = params.threshold ?? 0.95;
  if (params.confidence < threshold) {
    return false;
  }

  // Whitelist check
  if (!params.safeCategories.has(params.category)) {
    return false;
  }

  // Optional change-length gate
  if (params.maxChangeLength != null && params.changeLength != null) {
    if (params.changeLength > params.maxChangeLength) {
      return false;
    }
  }

  return true;
}

/** Config keys safe for auto-publish (non-financial, non-legal). */
export const BOT_CONFIG_SAFE_KEYS = new Set([
  "greeting_template",
  "product_recommend",
  "live_stream_script",
  "objection_handling",
]);

/** Knowledge categories safe for auto-publish. */
export const KNOWLEDGE_SAFE_CATEGORIES = new Set(["faq", "greeting"]);

export const DEFAULT_AUTO_PUBLISH_THRESHOLD = 0.95;
export const DEFAULT_MAX_CHANGE_LENGTH = 50;
