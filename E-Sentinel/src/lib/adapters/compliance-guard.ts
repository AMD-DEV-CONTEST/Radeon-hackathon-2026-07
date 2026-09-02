// ============================================================================
// Compliance Guard — hardcoded safety rules for real platform replies.
// These are NOT configurable via env vars — they are legal requirements.
//
// Tmall Rule 5.2: All AI replies must carry 【AI助手】 prefix.
// Tmall Rule 4.7: Sensitive keywords MUST route to human agents, never AI.
// ============================================================================

/** Legal requirements — hardcoded, not environment-driven */
export const COMPLIANCE = {
  /** Tmall rule 5.2 — mandatory AI identifier prefix */
  mandatoryPrefix: "【AI助手】",

  /** Tmall rule 4.7 — these keywords force human handoff, zero AI reply */
  sensitiveKeywords: [
    "投诉", "赔偿", "315", "举报", "监管",
    "消费者协会", "工商", "法院", "律师", "起诉",
    "假货", "欺诈", "诈骗", "维权", "曝光",
  ],

  /** Human agent fallback link injected at end of every AI reply */
  humanFallbackLink: "如需人工客服，请点击：https://store.taobao.com/service",

  /** Max length for AI-generated reply before truncation */
  maxReplyLength: 300,
} as const;

export interface ComplianceResult {
  /** true = safe to send AI reply */
  safe: boolean;
  /** If blocked, the reason why */
  blockReason?: string;
  /** The cleaned and prefixed reply text, or null if blocked */
  sanitizedReply: string | null;
}

/**
 * Scan message text for sensitive keywords.
 * Returns true if any sensitive keyword is found (case-insensitive).
 */
export function hasSensitiveContent(text: string): boolean {
  return COMPLIANCE.sensitiveKeywords.some((kw) => text.includes(kw));
}

/**
 * Apply compliance rules to a generated reply.
 * - Blocks entirely if the original message contains sensitive keywords
 * - Injects mandatory 【AI助手】 prefix
 * - Appends human fallback link
 * - Truncates to max length
 *
 * Pure function — no side effects, no DB calls.
 */
export function applyComplianceGuard(
  originalMessage: string,
  generatedReply: string,
): ComplianceResult {
  // Rule 1: Sensitive keywords → force human handoff, NO AI reply
  if (hasSensitiveContent(originalMessage)) {
    return {
      safe: false,
      blockReason: `sensitive_content:${findFirstMatch(originalMessage)}`,
      sanitizedReply: null,
    };
  }

  // Rule 2: Inject 【AI助手】 prefix
  let sanitized = generatedReply;

  if (!sanitized.startsWith(COMPLIANCE.mandatoryPrefix)) {
    sanitized = `${COMPLIANCE.mandatoryPrefix} ${sanitized}`;
  }

  // Rule 3: Append human fallback link (if not already present)
  if (!sanitized.includes("人工客服") && !sanitized.includes("人工服务")) {
    sanitized = `${sanitized}\n\n${COMPLIANCE.humanFallbackLink}`;
  }

  // Rule 4: Truncate to max length
  if (sanitized.length > COMPLIANCE.maxReplyLength) {
    sanitized = sanitized.slice(0, COMPLIANCE.maxReplyLength - 3) + "...";
  }

  return { safe: true, sanitizedReply: sanitized };
}

function findFirstMatch(text: string): string {
  return COMPLIANCE.sensitiveKeywords.find((kw) => text.includes(kw)) || "unknown";
}
