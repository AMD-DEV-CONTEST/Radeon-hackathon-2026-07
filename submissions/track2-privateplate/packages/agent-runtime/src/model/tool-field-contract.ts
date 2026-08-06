/**
 * Single source of truth for tool field roles and control-decision enums.
 *
 * Transport-required fields may appear in strict JSON Schema so models always
 * emit them, but empty arrays / false / topK=2 are interface defaults — not
 * user-facing missing slots. User-required fields still need real language
 * understanding and may enter ask_user.missingFields.
 */
import type { AgentToolName } from "../state.js";
import { SAFE_DEFAULTS } from "../product-semantics.js";

/** Slots the product may ask a human to fill. Neutral [] / false are never listed. */
export const MISSING_FIELDS = [
  "dinerIds",
  "mealType",
  "recipientLabel",
  "activePlanId",
  "focusedTemplateId",
  "currentPreview",
  "softPreferenceToRelax",
  "availableFoodIds"
] as const;
export type MissingField = (typeof MISSING_FIELDS)[number];

/** Product-level refuse / block reason codes shared by Provider, TaskOutcome and scorers. */
export const REASON_CODES = [
  "UNSUPPORTED_EXTERNAL_ACTION",
  "CONFIRMATION_REQUIRED",
  "ACTIVE_PLAN_REQUIRED",
  "PLAN_INFEASIBLE",
  "STALE_CONTEXT",
  "RECIPIENT_REQUIRED",
  "UNSUPPORTED_TOOL",
  "UNSUPPORTED_OR_UNCLEAR",
  "UNSUPPORTED"
] as const;
export type ReasonCode = (typeof REASON_CODES)[number];

export type FieldRequirement =
  | "user_required"
  | "transport_neutral"
  | "model_semantic";

export type ToolFieldSpec = {
  name: string;
  requirement: FieldRequirement;
  /** Applied only when the model omitted the field entirely. Never overrides explicit model values. */
  interfaceDefault?: unknown;
  /** When true, this field may appear in ask_user.missingFields. */
  askUserSlot?: boolean;
};

/**
 * Interface defaults for "user said nothing about this class of preference".
 * Must not invent members, recipients, mealType, or explicit rejects.
 */
export const INTERFACE_DEFAULTS = {
  emptyIdList: [] as string[],
  preferLowEffort: false,
  planTags: [] as string[],
  topK: SAFE_DEFAULTS.guidanceTopK,
  serveAtUnspecified: SAFE_DEFAULTS.handoffServeAt
} as const;

const TOOL_FIELD_SPECS: Record<AgentToolName, ToolFieldSpec[]> = {
  get_day_context: [
    { name: "goal", requirement: "model_semantic" },
    { name: "dinerIds", requirement: "user_required", askUserSlot: true },
    { name: "serviceDate", requirement: "model_semantic" }
  ],
  get_inventory: [{ name: "goal", requirement: "model_semantic" }],
  find_dish_candidates: [
    { name: "goal", requirement: "model_semantic" },
    { name: "dinerIds", requirement: "user_required", askUserSlot: true },
    {
      name: "rejectedFoodIds",
      requirement: "transport_neutral",
      interfaceDefault: INTERFACE_DEFAULTS.emptyIdList
    },
    {
      name: "rejectedTemplateIds",
      requirement: "transport_neutral",
      interfaceDefault: INTERFACE_DEFAULTS.emptyIdList
    }
  ],
  finalize_meal_plan: [
    { name: "goal", requirement: "model_semantic" },
    { name: "dinerIds", requirement: "user_required", askUserSlot: true },
    { name: "mealType", requirement: "user_required", askUserSlot: true },
    { name: "candidateSetId", requirement: "model_semantic" },
    { name: "selectedDishes", requirement: "model_semantic" },
    { name: "mealPortionScale", requirement: "model_semantic" },
    { name: "mealStructure", requirement: "model_semantic" },
    { name: "selectionReason", requirement: "model_semantic" }
  ],
  preview_meal_completion: [
    { name: "goal", requirement: "model_semantic" },
    {
      name: "mode",
      requirement: "transport_neutral",
      interfaceDefault: "as_planned"
    }
  ],
  preview_caregiver_task: [
    { name: "goal", requirement: "model_semantic" },
    {
      name: "recipientLabel",
      requirement: "user_required",
      askUserSlot: true
    },
    {
      name: "serveAt",
      requirement: "transport_neutral",
      interfaceDefault: INTERFACE_DEFAULTS.serveAtUnspecified
    }
  ],
  retrieve_local_knowledge: [
    { name: "goal", requirement: "model_semantic" },
    { name: "query", requirement: "model_semantic" },
    {
      name: "topK",
      requirement: "transport_neutral",
      interfaceDefault: INTERFACE_DEFAULTS.topK
    }
  ],
  preview_inventory_change: [
    { name: "goal", requirement: "model_semantic" },
    { name: "foodId", requirement: "model_semantic" },
    {
      name: "quantity",
      requirement: "transport_neutral",
      interfaceDefault: 1
    },
    {
      name: "unit",
      requirement: "transport_neutral",
      interfaceDefault: "盒"
    }
  ],
  preview_member_memory_change: [
    { name: "goal", requirement: "model_semantic" },
    { name: "memberId", requirement: "user_required", askUserSlot: true },
    {
      name: "kind",
      requirement: "transport_neutral",
      interfaceDefault: "preference"
    },
    { name: "summary", requirement: "model_semantic" }
  ]
}

export function toolFieldSpecs(tool: AgentToolName): readonly ToolFieldSpec[] {
  return TOOL_FIELD_SPECS[tool];
}

export function isMissingField(value: string): value is MissingField {
  return (MISSING_FIELDS as readonly string[]).includes(value);
}

export function isReasonCode(value: string): value is ReasonCode {
  return (REASON_CODES as readonly string[]).includes(value);
}

/**
 * Keep only allowlisted user-required slots. Neutral transport fields are dropped
 * so [] / false / topK=2 never become ask_user.missingFields.
 */
export function normalizeMissingFields(values: unknown): MissingField[] {
  if (!Array.isArray(values)) return [];
  const out: MissingField[] = [];
  for (const item of values) {
    if (typeof item !== "string") continue;
    // Compat aliases from older scripts / fixtures.
    const normalized =
      item === "activePlan"
        ? "activePlanId"
        : item === "focusedTemplate"
          ? "focusedTemplateId"
          : item;
    if (isMissingField(normalized) && !out.includes(normalized)) {
      out.push(normalized);
    }
  }
  return out;
}

export function normalizeReasonCode(value: unknown): ReasonCode | null {
  if (typeof value !== "string" || value.trim().length === 0) return null;
  return isReasonCode(value) ? value : null;
}

/**
 * Fill omitted transport-neutral fields only. Explicit model values win.
 * Does not invent dinerIds, mealType, recipientLabel, query, or rejections content.
 */
export function applyInterfaceDefaults(
  tool: AgentToolName,
  input: Record<string, unknown>
): Record<string, unknown> {
  const next: Record<string, unknown> = { ...input };
  for (const field of TOOL_FIELD_SPECS[tool]) {
    if (field.requirement !== "transport_neutral") continue;
    if (field.interfaceDefault === undefined) continue;
    if (next[field.name] === undefined) {
      next[field.name] = cloneDefault(field.interfaceDefault);
    }
  }
  return next;
}

function cloneDefault(value: unknown): unknown {
  if (Array.isArray(value)) return [...value];
  return value;
}

/**
 * Map trusted-policy diagnostic reasons onto user-facing missing slots.
 * Transport-neutral failures (empty rejections, topK, preferLowEffort false)
 * never become ask_user.missingFields.
 */
export function missingFieldsFromPolicyReasons(
  reasons: readonly string[]
): MissingField[] {
  const slots: MissingField[] = [];
  for (const reason of reasons) {
    if (
      reason.includes("diner") ||
      reason.startsWith("member_ids") ||
      reason.includes("member_id")
    ) {
      slots.push("dinerIds");
      continue;
    }
    if (reason.includes("meal_type")) {
      slots.push("mealType");
      continue;
    }
    if (reason.includes("recipient")) {
      slots.push("recipientLabel");
      continue;
    }
    if (reason.includes("active_plan")) {
      slots.push("activePlanId");
      continue;
    }
    if (reason.includes("soft_preference") || reason.includes("relax")) {
      slots.push("softPreferenceToRelax");
      continue;
    }
    if (reason.includes("focused_template") || reason.includes("anaphor")) {
      slots.push("focusedTemplateId");
      continue;
    }
    if (reason.includes("preview") || reason.includes("stale_context")) {
      slots.push("currentPreview");
      continue;
    }
    if (reason.includes("available_food") || reason.includes("infeasible")) {
      slots.push("availableFoodIds");
    }
  }
  return normalizeMissingFields(slots);
}
