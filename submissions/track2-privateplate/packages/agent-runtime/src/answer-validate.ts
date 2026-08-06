export type ProvenanceNumber = {
  path: string;
  value: number;
};

export type ValidationInput = {
  answer: string;
  toolOk: boolean;
  claimedSuccessWrite: boolean;
  hasCommitResult: boolean;
  successfulTools?: string[];
  /** Structured action status; when present, replaces regex-based send detection. */
  actionStatus?: import("./contracts.js").ActionStatus;
  retrievalSourceIds: string[];
  citedSourceIds: string[];
  allowedNumbers: number[];
  mentionedNumbers: number[];
  allowedDates?: string[];
  mentionedDates?: string[];
  knownTemplates?: Array<{ id: string; name: string }>;
  allowedTemplateIds?: string[];
  groundedTexts?: string[];
  hasCurrencyEvidence?: boolean;
};

export type ValidationResult =
  | { ok: true }
  | { ok: false; reasons: string[] };

const FORBIDDEN_MEDICAL = [
  /诊断为/,
  /你患有/,
  /为你开处方/,
  /请停药/,
  /保证治愈/,
  /根治糖尿病/,
  /根治高血压/
];

export function validateFinalAnswer(input: ValidationInput): ValidationResult {
  const reasons: string[] = [];

  if (!input.toolOk && /已为你安排|规划成功|发送成功/.test(input.answer)) {
    reasons.push("tool_failed_but_success_wording");
  }

  if (input.claimedSuccessWrite && !input.hasCommitResult) {
    reasons.push("write_success_without_commit");
  }

  for (const reason of prematureWriteClaimReasons(
    input.answer,
    input.successfulTools ?? [],
    input.hasCommitResult
  )) {
    reasons.push(reason);
  }

  // Structured action status is the single source of truth for send claims.
  // "已发送" wording is only valid when confirmationStatus === "committed".
  // No regex-based fallback: state is authoritative.
  const claimsSent =
    /已发送|已保存到收件箱|发送成功|已经交给保姆执行完毕/.test(input.answer);
  if (claimsSent && input.actionStatus !== "committed") {
    reasons.push("send_wording_without_commit");
  }

  for (const pattern of FORBIDDEN_MEDICAL) {
    if (pattern.test(input.answer)) {
      reasons.push("medical_boundary");
      break;
    }
  }

  for (const id of input.citedSourceIds) {
    if (!input.retrievalSourceIds.includes(id)) {
      reasons.push(`citation_not_in_packet:${id}`);
    }
  }

  // Numbers in the answer that look like measurements should come from tools.
  for (const n of input.mentionedNumbers) {
    if (!input.allowedNumbers.some((a) => almostEqual(a, n))) {
      // Allow small integers used as counts (1-3 diners, top-k) without provenance.
      if (n >= 0 && n <= 3 && Number.isInteger(n)) continue;
      reasons.push(`unproven_number:${n}`);
    }
  }

  const allowedDates = new Set(input.allowedDates ?? []);
  for (const date of new Set(input.mentionedDates ?? [])) {
    if (!allowedDates.has(date)) {
      reasons.push(`unproven_date:${date}`);
    }
  }

  if (
    /\d(?:[\d.]*)\s*元/.test(input.answer) &&
    input.hasCurrencyEvidence !== true
  ) {
    reasons.push("currency_without_provenance");
  }

  // Template provenance guards plan claims. A knowledge answer may name a dish
  // as prose ("用糙米代替白米饭") without putting it on the plan, so a turn whose
  // only successful tool was retrieval asserts no template.
  const successfulTools = input.successfulTools ?? [];
  const retrievalOnlyTurn =
    successfulTools.length > 0 &&
    successfulTools.every((tool) => tool === "retrieve_local_knowledge");
  const allowedTemplateIds = new Set(input.allowedTemplateIds ?? []);
  if (!retrievalOnlyTurn) {
    for (const template of input.knownTemplates ?? []) {
      if (
        input.answer.includes(template.name) &&
        !allowedTemplateIds.has(template.id) &&
        !(input.groundedTexts ?? []).some((text) =>
          text.includes(template.name)
        )
      ) {
        reasons.push(`unproven_template:${template.id}`);
      }
    }
  }

  if (containsDiseaseDisclosure(input.answer)) {
    reasons.push("disease_name_in_handoff_context");
  }

  return reasons.length === 0 ? { ok: true } : { ok: false, reasons };
}

/**
 * A model may describe a preview, but it must not describe the write as done.
 * This is intentionally a small safety check over completion wording; it is
 * not used to route the user's business intent.
 */
function prematureWriteClaimReasons(
  answer: string,
  successfulTools: string[],
  hasCommitResult: boolean
): string[] {
  if (hasCommitResult) return [];

  const reasons: string[] = [];
  const has = (tool: string) => successfulTools.includes(tool);
  if (
    has("finalize_meal_plan") &&
    (/(?:已|已经|成功|完成).{0,10}(?:扣|减少|消耗).{0,10}库存/.test(answer) ||
      /库存(?:中的)?[^。]{0,32}(?:已|已经)(?:被)?(?:从现有库存中)?(?:扣除|扣减|减少|消耗)/.test(
        answer
      ) ||
      /(?:已|已经)(?:扣除|扣减|减少|消耗)(?:了)?库存/.test(answer))
  ) {
    reasons.push("plan_write_claim_without_commit");
  }
  if (
    has("preview_inventory_change") &&
    /(?:已|已经)(?:成功|完成)?(?:入库|记入库存|补充库存)/.test(answer)
  ) {
    reasons.push("inventory_write_claim_without_commit");
  }
  if (
    has("preview_member_memory_change") &&
    /(?:已|已经)(?:成功|完成)?(?:保存|写入|更新)(?:了)?(?:家庭资料|家庭记忆|偏好|健康事实)/.test(
      answer
    )
  ) {
    reasons.push("member_memory_write_claim_without_commit");
  }
  if (
    has("preview_meal_completion") &&
    /(?:已|已经)(?:成功|完成)?(?:记入摄入|扣减库存|扣库存|标记本餐完成)/.test(
      answer
    )
  ) {
    reasons.push("meal_completion_write_claim_without_commit");
  }
  return reasons;
}

export function extractNumbers(text: string): number[] {
  // Ignore codes like P0/v1/kc-...; allow unit suffixes (kcal, g, mg).
  // Ranges like 65g-130g must yield [65, 130], not [65, -130].
  const scrubbed = text
    // List-marker scrubbing below is line-anchored, and the model often
    // separates list items with an HTML break instead of a newline. Without
    // this, the marker in "<br>4. 北豆腐" reads as the measurement 4.
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/\b\d{4}-\d{2}-\d{2}\b/g, (date) =>
      " ".repeat(date.length)
    )
    .replace(/^[ \t]*\d+(?:[.)、])(?=[ \t]|$|[^\d])/gm, (marker) =>
      " ".repeat(marker.length)
    )
    .replace(/\bP\d+\b/gi, " ")
    .replace(/\bv\d+\b/gi, " ")
    .replace(/kc-[a-z0-9-]+/gi, " ")
    .replace(/pendingActionId=\S+/gi, " ")
    .replace(/payloadHash=\S+/gi, " ")
    .replace(/expiresAt=\S+/gi, " ");
  const out: number[] = [];
  // Positive range with optional units: 65g-130g, 65-130, 1.5~2.0
  const rangeRe =
    /(\d+(?:\.\d+)?)\s*(?:[a-zA-Zμ%]{0,4})\s*[-–—~]\s*(\d+(?:\.\d+)?)/g;
  let rangeMatch: RegExpExecArray | null;
  const rangeSpans: Array<{ start: number; end: number }> = [];
  while ((rangeMatch = rangeRe.exec(scrubbed)) !== null) {
    const a = Number(rangeMatch[1]);
    const b = Number(rangeMatch[2]);
    if (Number.isFinite(a)) out.push(a);
    if (Number.isFinite(b)) out.push(b);
    rangeSpans.push({
      start: rangeMatch.index,
      end: rangeMatch.index + rangeMatch[0].length
    });
  }
  const singleRe = /-?\d+(?:\.\d+)?/g;
  let singleMatch: RegExpExecArray | null;
  while ((singleMatch = singleRe.exec(scrubbed)) !== null) {
    const start = singleMatch.index;
    const end = start + singleMatch[0].length;
    if (rangeSpans.some((span) => start >= span.start && end <= span.end)) {
      continue;
    }
    const n = Number(singleMatch[0]);
    if (Number.isFinite(n)) out.push(n);
  }
  return out;
}

export function extractDates(text: string): string[] {
  return [...text.matchAll(/\b\d{4}-\d{2}-\d{2}\b/g)].map(
    (match) => match[0]!
  );
}

export function collectAllowedDates(toolPayloads: unknown[]): string[] {
  const dates = new Set<string>();
  const walk = (value: unknown, field?: string): void => {
    if (
      field === "serviceDate" &&
      typeof value === "string" &&
      /^\d{4}-\d{2}-\d{2}$/.test(value)
    ) {
      dates.add(value);
      return;
    }
    if (Array.isArray(value)) {
      for (const item of value) walk(item, field);
      return;
    }
    if (value && typeof value === "object") {
      for (const [key, nested] of Object.entries(
        value as Record<string, unknown>
      )) {
        walk(nested, key);
      }
    }
  };
  for (const payload of toolPayloads) walk(payload);
  return [...dates];
}

export function collectAllowedNumbers(toolPayloads: unknown[]): number[] {
  const out: number[] = [];
  const walk = (value: unknown, field?: string): void => {
    if (typeof value === "number" && Number.isFinite(value)) {
      out.push(value);
      return;
    }
    if (
      typeof value === "string" &&
      field &&
      NUMBER_BEARING_TEXT_FIELDS.has(field)
    ) {
      out.push(...extractNumbers(value));
      return;
    }
    if (Array.isArray(value)) {
      for (const item of value) walk(item, field);
      return;
    }
    if (value && typeof value === "object") {
      for (const [key, nested] of Object.entries(
        value as Record<string, unknown>
      )) {
        walk(nested, key);
      }
    }
  };
  for (const payload of toolPayloads) walk(payload);
  return out;
}

export function collectGroundedTexts(toolPayloads: unknown[]): string[] {
  const texts = new Set<string>();
  const walk = (value: unknown): void => {
    if (typeof value === "string") {
      texts.add(value);
      return;
    }
    if (Array.isArray(value)) {
      for (const item of value) walk(item);
      return;
    }
    if (value && typeof value === "object") {
      for (const nested of Object.values(value as Record<string, unknown>)) {
        walk(nested);
      }
    }
  };
  for (const payload of toolPayloads) walk(payload);
  return [...texts];
}

export function collectIds(
  toolPayloads: unknown[],
  prefix: string
): string[] {
  const ids = new Set<string>();
  const walk = (value: unknown): void => {
    if (typeof value === "string") {
      if (value.startsWith(prefix)) ids.add(value);
      return;
    }
    if (Array.isArray(value)) {
      for (const item of value) walk(item);
      return;
    }
    if (value && typeof value === "object") {
      for (const nested of Object.values(value as Record<string, unknown>)) {
        walk(nested);
      }
    }
  };
  for (const payload of toolPayloads) walk(payload);
  return [...ids];
}

export function hasCurrencyEvidence(toolPayloads: unknown[]): boolean {
  let found = false;
  const walk = (value: unknown): void => {
    if (found || !value || typeof value !== "object") return;
    if (Array.isArray(value)) {
      for (const item of value) walk(item);
      return;
    }
    for (const [key, nested] of Object.entries(
      value as Record<string, unknown>
    )) {
      if (/price|currency|cost/i.test(key)) {
        found = true;
        return;
      }
      walk(nested);
    }
  };
  for (const payload of toolPayloads) walk(payload);
  return found;
}

function almostEqual(a: number, b: number): boolean {
  if (Math.abs(a - b) < 0.15) return true;
  // A readable Chinese answer presents tool numbers rounded ("约535g" for
  // 534.6g) and ceils purchase quantities to whole units. Those presentations
  // are still provable; only figures with no tool support stay unproven.
  return Math.abs(a - b) <= Math.max(1, Math.abs(a) * ROUNDING_TOLERANCE);
}

const ROUNDING_TOLERANCE = 0.005;

const NUMBER_BEARING_TEXT_FIELDS = new Set([
  "serveAt",
  // Retrieved corpus text is evidence: "relevantContent" is the deterministic
  // retriever's chunk field, "content" and "title" are the vector retriever's.
  // Without them every figure the knowledge base states reads as invented.
  "relevantContent",
  "content",
  "title",
  "executionNotes",
  "rawExpression"
]);

function containsDiseaseDisclosure(answer: string): boolean {
  const clauses = answer.split(
    /[。！？\n，；,;]|但(?:是)?|不过|然而/
  );
  return clauses.some((clause) => {
    if (
      !/糖尿病|高血压/.test(clause) ||
      !/任务卡|交接卡|保姆/.test(clause)
    ) {
      return false;
    }
    return HANDOFF_DISEASE_DISCLOSURE_PATTERNS.some((pattern) => {
      const match = pattern.exec(clause);
      if (!match || match.index == null) return false;
      const localStart = Math.max(0, match.index - 4);
      const localEnd = Math.min(
        clause.length,
        match.index + match[0].length + 10
      );
      return !isNegatedDisclosure(clause.slice(localStart, localEnd));
    });
  });
}

function isNegatedDisclosure(sentence: string): boolean {
  return (
    /(?:不|未|不会|不能|不得|无需|避免|而不是).{0,16}(?:写|披露|标注|注明|包含|显示|告诉|告知|发送|提供|公开|疾病名)/.test(
      sentence
    ) ||
    /(?:写|披露|标注|注明|包含|显示|告诉|告知|发送|提供|公开).{0,8}(?:不|未|无需|避免)/.test(
      sentence
    )
  );
}

const HANDOFF_DISEASE_DISCLOSURE_PATTERNS = [
  /(?:任务卡|交接卡).{0,20}(?:写(?:明|着|入|进)?|注明|标注|包含|显示|披露|提供).{0,20}(?:糖尿病|高血压)/,
  /(?:糖尿病|高血压).{0,20}(?:写入|写进|注明|标注|披露|提供给).{0,20}(?:任务卡|交接卡|保姆)/,
  /(?:糖尿病|高血压).{0,24}保姆.{0,12}(?:需要|应当|必须)?(?:知道|了解)/,
  /保姆.{0,12}(?:需要|应当|必须)?(?:知道|了解).{0,20}(?:糖尿病|高血压)/,
  /(?:告诉|告知|发送给|提供给)保姆.{0,20}(?:糖尿病|高血压)/,
  /(?:任务卡|交接卡)\s*[:：].{0,20}(?:糖尿病|高血压)/
];
