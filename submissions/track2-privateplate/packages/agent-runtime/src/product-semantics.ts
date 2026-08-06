/**
 * Unified product semantics shared by:
 * - deterministic demo routing (no model)
 * - trusted argument policy (after model routing)
 * - future local_vllm product path
 *
 * Safe defaults vs must-clarify rules are documented here so Demo / Mock / vLLM
 * cannot invent different high-risk values.
 */

export const CAREGIVER_RECIPIENT_LABELS = [
  "家庭保姆",
  "保姆",
  "阿姨"
] as const;

export type CaregiverRecipientLabel =
  (typeof CAREGIVER_RECIPIENT_LABELS)[number];

/** Fields the product may fill when the user is silent. */
export const SAFE_DEFAULTS = {
  /**
   * Preview-only: "time not specified" is safer than inventing a clock time.
   * Real send still requires user confirm of the task card contents.
   */
  handoffServeAt: "unspecified" as const,
  /**
   * When the user plans a meal without saying lunch/dinner, ask rather than
   * silently force lunch — except locked UI flows that already chose a meal.
   */
  mealType: null as "lunch" | "dinner" | null,
  /**
   * Guidance card count when the user does not specify 1–3.
   * Demo deterministic path and trusted policy must share this value.
   */
  guidanceTopK: 2 as const
} as const;

/**
 * Resolve meal type. Demo, mock policy, and live model path share this.
 * Silent or conflicting lunch/dinner → needs clarification (no silent lunch default).
 */
export function resolveMealTypeSlot(
  userText: string
): SlotResolution<"lunch" | "dinner"> {
  const dinner = /晚|晚饭|晚餐|今晚/.test(userText);
  const lunch = /午|午饭|午餐|中午/.test(userText);
  if (dinner && !lunch) {
    return { status: "ok", value: "dinner", source: "user_text" };
  }
  if (lunch && !dinner) {
    return { status: "ok", value: "lunch", source: "user_text" };
  }
  if (dinner && lunch) {
    return { status: "needs_clarification", reason: "meal_type_ambiguous" };
  }
  return { status: "needs_clarification", reason: "meal_type_missing" };
}

/**
 * Resolve guidance topK in [1,3]. Unspecified uses SAFE_DEFAULTS.guidanceTopK.
 */
export function resolveGuidanceTopK(userText: string): SlotResolution<number> {
  const match = userText.match(
    /(?:最多(?:返回|给)|只(?:返回(?:最相关的)?|给|找|要)|返回)\s*([1-3一二三])\s*条/
  );
  if (match) {
    const count = { 一: 1, 二: 2, 三: 3 }[match[1]!] ?? Number(match[1]);
    return { status: "ok", value: count, source: "user_text" };
  }
  return {
    status: "ok",
    value: SAFE_DEFAULTS.guidanceTopK,
    source: "safe_default"
  };
}

export type SlotResolution<T> =
  | { status: "ok"; value: T; source: "user_text" | "safe_default" | "locked" }
  | { status: "needs_clarification"; reason: string };

/**
 * Resolve handoff recipient from user wording.
 * Never expand 保姆 → 家庭保姆. Prefer longer labels first.
 */
export function resolveHandoffRecipient(
  userText: string,
  allowed: readonly string[] = CAREGIVER_RECIPIENT_LABELS
): SlotResolution<string> {
  const hits = recipientMentions(userText, allowed).filter(
    (hit) => !recipientMentionIsNegated(userText, hit.index, hit.label.length)
  );
  if (hits.length === 0) {
    // Common paraphrase without exact enum label
    if (/执行者|家政|护工/.test(userText) && !/保姆|阿姨/.test(userText)) {
      return {
        status: "needs_clarification",
        reason: "recipient_label_ambiguous"
      };
    }
    return {
      status: "needs_clarification",
      reason: "recipient_label_missing"
    };
  }
  // Corrections are resolved by conversational order: the latest
  // non-negated recipient wins.
  return {
    status: "ok",
    value: hits[hits.length - 1]!.label,
    source: "user_text"
  };
}

function recipientMentions(
  userText: string,
  allowed: readonly string[]
): Array<{ label: string; index: number }> {
  const candidates: Array<{ label: string; index: number }> = [];
  for (const label of [...allowed].sort((a, b) => b.length - a.length)) {
    let index = userText.indexOf(label);
    while (index >= 0) {
      const overlapsLongerLabel = candidates.some(
        (hit) =>
          hit.label.length > label.length &&
          index >= hit.index &&
          index + label.length <= hit.index + hit.label.length
      );
      if (!overlapsLongerLabel) {
        candidates.push({ label, index });
      }
      index = userText.indexOf(label, index + label.length);
    }
  }
  return candidates.sort((a, b) => a.index - b.index);
}

function recipientMentionIsNegated(
  userText: string,
  index: number,
  length: number
): boolean {
  const clauseStart =
    Math.max(
      userText.lastIndexOf("，", index - 1),
      userText.lastIndexOf(",", index - 1),
      userText.lastIndexOf("。", index - 1),
      userText.lastIndexOf("；", index - 1),
      userText.lastIndexOf(";", index - 1)
    ) + 1;
  const prefix = userText.slice(clauseStart, index).trim();
  const suffix = userText.slice(index + length).split(/[，,。；;]/, 1)[0] ?? "";
  return (
    /(?:别|不要|不是|并非)(?:再)?(?:发给|给|交给|找)?$/.test(prefix) ||
    /(?:除外|不要|不行)/.test(suffix)
  );
}

/**
 * Resolve serveAt. Explicit times win; otherwise safe default "unspecified".
 * Does not invent "今天 12:30" from weak words like 中午 alone on handoff.
 */
export function resolveHandoffServeAt(userText: string): SlotResolution<string> {
  const iso = userText.match(
    /\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)/
  );
  if (iso) {
    return { status: "ok", value: iso[0], source: "user_text" };
  }
  const today = userText.match(/今天\s*(?:[01]\d|2[0-3]):[0-5]\d/);
  if (today) {
    return {
      status: "ok",
      value: today[0].replace(/\s+/, " "),
      source: "user_text"
    };
  }
  // Spoken clock: 「晚饭六点」「6点」「18点」→ 今天 HH:00 (preview contract).
  const cnHour: Record<string, number> = {
    零: 0,
    〇: 0,
    一: 1,
    二: 2,
    两: 2,
    三: 3,
    四: 4,
    五: 5,
    六: 6,
    七: 7,
    八: 8,
    九: 9,
    十: 10
  };
  const spokenHour = userText.match(
    /(?:今天)?(?:早上|上午|中午|下午|晚上|傍晚|晚饭|晚餐|午饭|午餐)?\s*([0-2]?\d|[零〇一二两三四五六七八九十]{1,3})\s*点(?:整|钟)?/
  );
  if (spokenHour) {
    const raw = spokenHour[1]!;
    let hour: number;
    if (/^\d+$/.test(raw)) {
      hour = Number(raw);
    } else if (raw === "十") {
      hour = 10;
    } else if (raw.startsWith("十")) {
      hour = 10 + (cnHour[raw.slice(1)] ?? 0);
    } else if (raw.endsWith("十") && raw.length === 2) {
      hour = (cnHour[raw[0]!] ?? 0) * 10;
    } else if (raw.length === 1) {
      hour = cnHour[raw] ?? NaN;
    } else {
      hour = NaN;
    }
    if (Number.isInteger(hour) && hour >= 0 && hour <= 23) {
      // Bare 1–11 with 晚/晚饭 defaults to evening when not already 24h.
      if (hour > 0 && hour <= 11 && /晚|晚饭|晚餐|傍晚/.test(userText)) {
        hour += 12;
      }
      if (/下午/.test(userText) && hour > 0 && hour <= 11) {
        hour += 12;
      }
      return {
        status: "ok",
        value: `今天 ${String(hour).padStart(2, "0")}:00`,
        source: "user_text"
      };
    }
  }
  if (
    /serveAt\s*(?:使用|为|是|=)\s*unspecified|时间未定|暂不指定时间|时间再说/.test(
      userText
    )
  ) {
    return { status: "ok", value: "unspecified", source: "user_text" };
  }
  return {
    status: "ok",
    value: SAFE_DEFAULTS.handoffServeAt,
    source: "safe_default"
  };
}

const SUPPORTED_SERVE_AT =
  /^(?:unspecified|今天 (?:[01]\d|2[0-3]):[0-5]\d|\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d))$/;

/**
 * Canonicalize model-emitted serveAt into the product contract.
 *
 * - Valid ISO / 今天 HH:MM / unspecified → keep
 * - Bare clock "12:00" or other under-specified values → do **not** invent a
 *   full datetime; fall back to user-text resolution or "unspecified"
 *
 * This is an interface normalization, not a score patch.
 */
export function canonicalizeCaregiverServeAt(
  rawServeAt: unknown,
  userText: string,
  knownServeAt?: string
): string {
  const fromUser = resolveHandoffServeAt(userText);
  if (fromUser.status === "ok" && fromUser.source === "user_text") {
    return fromUser.value;
  }
  if (knownServeAt && SUPPORTED_SERVE_AT.test(knownServeAt)) {
    return knownServeAt;
  }
  if (typeof rawServeAt === "string") {
    const trimmed = rawServeAt.trim();
    if (SUPPORTED_SERVE_AT.test(trimmed)) {
      if (
        trimmed === "unspecified" ||
        trimmed.startsWith("今天 ") ||
        Number.isFinite(Date.parse(trimmed))
      ) {
        return trimmed;
      }
    }
  }
  return SAFE_DEFAULTS.handoffServeAt;
}

/**
 * Normalize preview tool args so incomplete model clocks do not hard-fail
 * schema before the trusted policy layer can run.
 */
export function canonicalizePreviewToolArgs(
  rawArgs: Record<string, unknown>,
  userText: string,
  knownServeAt?: string
): Record<string, unknown> {
  return {
    ...rawArgs,
    serveAt: canonicalizeCaregiverServeAt(
      rawArgs.serveAt,
      userText,
      knownServeAt
    )
  };
}

/**
 * Models sometimes omit empty list fields. Treat missing arrays as [] for
 * compose/revise contracts (empty = no this-turn reject/priority), not as
 * inventing content. Rejections stay typed until the model schema validates
 * and converts them into the business-facing food/template arrays.
 */
export function canonicalizeListToolArgs(
  tool: "find_dish_candidates" | "finalize_meal_plan",
  rawArgs: Record<string, unknown>
): Record<string, unknown> {
  if (tool === "find_dish_candidates" || tool === "finalize_meal_plan") {
    return {
      ...rawArgs,
      rejections: Array.isArray(rawArgs.rejections)
        ? rawArgs.rejections
        : [],
      requestedDishIds: Array.isArray(rawArgs.requestedDishIds)
        ? rawArgs.requestedDishIds
        : [],
      requestedPriorityFoodIds: Array.isArray(rawArgs.requestedPriorityFoodIds)
        ? rawArgs.requestedPriorityFoodIds
        : []
    };
  }
  return {
    ...rawArgs,
    rejections: Array.isArray(rawArgs.rejections)
      ? rawArgs.rejections
      : []
  };
}

export function resolveHandoffSlots(
  userText: string,
  allowedRecipients: readonly string[] = CAREGIVER_RECIPIENT_LABELS
):
  | {
      status: "ok";
      recipientLabel: string;
      serveAt: string;
      serveAtSource: "user_text" | "safe_default";
    }
  | { status: "needs_clarification"; reasons: string[] } {
  const recipient = resolveHandoffRecipient(userText, allowedRecipients);
  const serveAt = resolveHandoffServeAt(userText);
  if (recipient.status === "needs_clarification") {
    return {
      status: "needs_clarification",
      reasons: [recipient.reason]
    };
  }
  if (serveAt.status === "needs_clarification") {
    return {
      status: "needs_clarification",
      reasons: [serveAt.reason]
    };
  }
  return {
    status: "ok",
    recipientLabel: recipient.value,
    serveAt: serveAt.value,
    serveAtSource: serveAt.source === "safe_default" ? "safe_default" : "user_text"
  };
}

export function clarificationMessageForHandoff(reasons: string[]): string {
  if (reasons.includes("recipient_label_missing")) {
    return "请说明任务交给谁（例如：保姆、阿姨或家庭保姆），以及是否指定用餐时间。未指定时间时会使用「时间未定」预览，不会直接发送。";
  }
  if (reasons.includes("recipient_label_ambiguous")) {
    return "请从支持的接收人标签中选择：家庭保姆、保姆、阿姨。";
  }
  return "请补充执行任务卡的接收人和用餐时间信息。";
}

/** Evidence classification for evals/submission. */
export type RoutingEvidenceKind =
  | "deterministic_demo" // legacy scorer guard only; no longer emitted
  | "model_routed"
  | "model_clarification";
