import { z } from "zod";
import {
  CAREGIVER_RECIPIENT_LABELS,
  CaregiverRecipientLabelSchema,
  CaregiverServeAtSchema,
  MealRoleSchema
} from "@privateplate/contracts";
import type { AgentToolName } from "../state.js";
import type { AgentGoal } from "../contracts.js";
import { applyInterfaceDefaults } from "./tool-field-contract.js";

type JsonSchema = {
  type: "object";
  additionalProperties: false;
  properties: Record<string, unknown>;
  required: string[];
};

export type ModelToolDefinition = {
  type: "function";
  function: {
    name: AgentToolName;
    description: string;
    strict: true;
    parameters: JsonSchema;
  };
};

const FixtureIdSchema = z.string().min(1).max(96);
const ModelToolGoalSchema = z.enum([
  "inspect_context",
  "inspect_inventory",
  "compose_meal",
  "revise_meal",
  "retrieve_guidance",
  "preview_handoff",
  "send_handoff",
  "preview_inventory",
  "update_inventory",
  "preview_member_memory",
  "update_member_memory",
  "preview_meal_completion",
  "complete_meal"
]);
const FixtureIdsSchema = z.array(FixtureIdSchema).max(16);
const DinerIdsSchema = z.array(FixtureIdSchema).min(1).max(3);
const ContextGoalSchema = z
  .enum(["inspect_context", "compose_meal", "revise_meal"])
  .optional();
const PlanningGoalSchema = z.enum(["compose_meal", "revise_meal"]).optional();
const CompletionGoalSchema = z
  .enum(["preview_meal_completion", "complete_meal"])
  .optional();
const InventoryGoalSchema = z
  .enum(["preview_inventory", "update_inventory"])
  .optional();
const MemberMemoryGoalSchema = z
  .enum(["preview_member_memory", "update_member_memory"])
  .optional();

const GetDayContextArgsSchema = z
  .object({
    goal: ContextGoalSchema,
    dinerIds: DinerIdsSchema,
    serviceDate: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional()
  })
  .strict()
  .transform(({ goal: _goal, ...args }) => args);

const CanonicalGetDayContextArgsSchema = z
  .object({
    dinerIds: DinerIdsSchema,
    serviceDate: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional()
  })
  .strict();

const CanonicalGetInventoryArgsSchema = z.object({}).strict();

const GetInventoryArgsSchema = z
  .object({
    goal: z.literal("inspect_inventory").optional()
  })
  .strict()
  .transform(({ goal: _goal, ...args }) => args);

const FindDishCandidatesArgsSchema = z
  .object({
    goal: PlanningGoalSchema,
    dinerIds: DinerIdsSchema,
    rejectedFoodIds: FixtureIdsSchema.default([]),
    rejectedTemplateIds: FixtureIdsSchema.default([])
  })
  .strict()
  .transform(({ goal: _goal, ...args }) => args);

const CanonicalFindDishCandidatesArgsSchema = z
  .object({
    dinerIds: DinerIdsSchema,
    rejectedFoodIds: FixtureIdsSchema.default([]),
    rejectedTemplateIds: FixtureIdsSchema.default([])
  })
  .strict();

const SelectedDishSchema = z
  .object({
    templateId: FixtureIdSchema,
    relativePortion: z.enum(["small", "standard", "large"])
  })
  .strict();

const MealStructureArgsSchema = z
  .object({
    mode: z.enum(["standard", "simple", "one_pot"]),
    requiredRoles: z.array(MealRoleSchema).default([]),
    omittedRoles: z.array(MealRoleSchema).default([]),
    reason: z.string().max(200).optional()
  })
  .strict();

const FinalizeMealPlanArgsSchema = z
  .object({
    goal: PlanningGoalSchema,
    dinerIds: DinerIdsSchema,
    mealType: z.enum(["lunch", "dinner"]),
    candidateSetId: FixtureIdSchema,
    selectedDishes: z.array(SelectedDishSchema).min(1).max(12),
    mealPortionScale: z.number().gt(0).max(1.5),
    mealStructure: MealStructureArgsSchema.optional(),
    selectionReason: z.string().min(1).max(500)
  })
  .strict()
  .transform(({ goal: _goal, ...args }) => args);

const CanonicalFinalizeMealPlanArgsSchema = z
  .object({
    dinerIds: DinerIdsSchema,
    mealType: z.enum(["lunch", "dinner"]),
    candidateSetId: FixtureIdSchema,
    selectedDishes: z.array(SelectedDishSchema).min(1).max(12),
    mealPortionScale: z.number().gt(0).max(1.5),
    mealStructure: MealStructureArgsSchema.optional(),
    selectionReason: z.string().min(1).max(500)
  })
  .strict();

/** Models often confuse mealStructure.mode; always normalize to the sole product mode. */
const PreviewMealModeSchema = z
  .string()
  .optional()
  .transform(() => "as_planned" as const);

/** Transport accepts any short clock phrase; policy canonicalizes to the product contract. */
const ModelServeAtSchema = z.string().max(128).optional();

const PreviewMealCompletionArgsSchema = z
  .object({
    goal: CompletionGoalSchema,
    mode: PreviewMealModeSchema
  })
  .strict()
  .transform(({ goal: _goal, ...args }) => args);

const CanonicalPreviewMealCompletionArgsSchema = z
  .object({
    mode: z.enum(["as_planned"]).default("as_planned")
  })
  .strict();

const HandoffGoalSchema = z.enum(["preview_handoff", "send_handoff"]);

const PreviewCaregiverTaskArgsSchema = z
  .object({
    goal: HandoffGoalSchema.optional(),
    recipientLabel: CaregiverRecipientLabelSchema,
    serveAt: ModelServeAtSchema
  })
  .strict()
  .transform(({ goal: _goal, ...args }) => args);

const CanonicalPreviewCaregiverTaskArgsSchema = z
  .object({
    recipientLabel: CaregiverRecipientLabelSchema,
    serveAt: CaregiverServeAtSchema
  })
  .strict();

const RetrieveLocalKnowledgeArgsSchema = z
  .object({
    goal: z.literal("retrieve_guidance").optional(),
    query: z.string().min(1).max(500),
    topK: z.number().int().min(1).max(5).default(3)
  })
  .strict()
  .transform(({ goal: _goal, ...args }) => args);

const CanonicalRetrieveLocalKnowledgeArgsSchema = z
  .object({
    query: z.string().min(1).max(500),
    topK: z.number().int().min(1).max(5).default(3)
  })
  .strict();

const PreviewInventoryChangeArgsSchema = z
  .object({
    goal: InventoryGoalSchema,
    foodId: FixtureIdSchema,
    quantity: z.number().positive().max(100).default(1),
    unit: z.string().min(1).max(16).default("盒")
  })
  .strict()
  .transform(({ goal: _goal, ...args }) => args);

const CanonicalPreviewInventoryChangeArgsSchema = z
  .object({
    foodId: FixtureIdSchema,
    quantity: z.number().positive().max(100).default(1),
    unit: z.string().min(1).max(16).default("盒")
  })
  .strict();

const PreviewMemberMemoryChangeArgsSchema = z
  .object({
    goal: MemberMemoryGoalSchema,
    memberId: FixtureIdSchema,
    kind: z.enum(["preference", "health_fact"]).default("preference"),
    summary: z.string().min(1).max(300),
    polarity: z.enum(["prefer", "avoid", "note"]).optional()
  })
  .strict()
  .transform(({ goal: _goal, ...args }) => args);

const CanonicalPreviewMemberMemoryChangeArgsSchema = z
  .object({
    memberId: FixtureIdSchema,
    kind: z.enum(["preference", "health_fact"]).default("preference"),
    summary: z.string().min(1).max(300),
    polarity: z.enum(["prefer", "avoid", "note"]).optional()
  })
  .strict();

const TOOL_ARGUMENT_SCHEMAS = {
  get_day_context: GetDayContextArgsSchema,
  get_inventory: GetInventoryArgsSchema,
  find_dish_candidates: FindDishCandidatesArgsSchema,
  finalize_meal_plan: FinalizeMealPlanArgsSchema,
  preview_meal_completion: PreviewMealCompletionArgsSchema,
  preview_caregiver_task: PreviewCaregiverTaskArgsSchema,
  retrieve_local_knowledge: RetrieveLocalKnowledgeArgsSchema,
  preview_inventory_change: PreviewInventoryChangeArgsSchema,
  preview_member_memory_change: PreviewMemberMemoryChangeArgsSchema
} satisfies Record<AgentToolName, z.ZodTypeAny>;

const CANONICAL_TOOL_ARGUMENT_SCHEMAS = {
  get_day_context: CanonicalGetDayContextArgsSchema,
  get_inventory: CanonicalGetInventoryArgsSchema,
  find_dish_candidates: CanonicalFindDishCandidatesArgsSchema,
  finalize_meal_plan: CanonicalFinalizeMealPlanArgsSchema,
  preview_meal_completion: CanonicalPreviewMealCompletionArgsSchema,
  preview_caregiver_task: CanonicalPreviewCaregiverTaskArgsSchema,
  retrieve_local_knowledge: CanonicalRetrieveLocalKnowledgeArgsSchema,
  preview_inventory_change: CanonicalPreviewInventoryChangeArgsSchema,
  preview_member_memory_change: CanonicalPreviewMemberMemoryChangeArgsSchema
} satisfies Record<AgentToolName, z.ZodTypeAny>;

const stringArray = {
  type: "array",
  items: { type: "string", minLength: 1, maxLength: 96 },
  maxItems: 16
};

const dinerIds = {
  ...stringArray,
  minItems: 1,
  maxItems: 3
};

/**
 * Tool selection chooses the operation. Optional semantic goals record the
 * requested result (preview vs update/complete) without replacing state checks.
 */
export const PRIVATEPLATE_MODEL_TOOLS: ModelToolDefinition[] = [
  {
    type: "function",
    function: {
      name: "get_day_context",
      description:
        "Read today's household memory: daily nutrition targets, consumed intake, remaining budget, inventory, completed meals, preferences and hard constraints. Call this first when planning a meal.",
      strict: true,
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          goal: {
            type: "string",
            enum: [
              "inspect_context",
              "compose_meal",
              "revise_meal"
            ]
          },
          dinerIds,
          serviceDate: {
            type: "string",
            pattern: "^\\d{4}-\\d{2}-\\d{2}$",
            description: "Optional YYYY-MM-DD; default is local service date."
          }
        },
        required: ["dinerIds"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "get_inventory",
      description:
        "Read-only household inventory: current items, estimated grams, and priority-use flags. Does not include nutrition budgets, intake, or member memory. Use when the user only wants to inspect existing stock without making changes.",
      strict: true,
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          goal: {
            type: "string",
            enum: ["inspect_inventory"]
          }
        },
        required: []
      }
    }
  },
  {
    type: "function",
    function: {
      name: "find_dish_candidates",
      description:
        "Return the full hard-filtered dish candidate pool with inventory and nutrition facts (typically many dishes across shared_main, shared_side and staple). This is not a 3-dish shortlist. Domain does not rank or pick a winner. Call after get_day_context when planning; then choose 1–12 dishes via finalize_meal_plan, covering required roles and optionally multiple dishes per role.",
      strict: true,
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          goal: {
            type: "string",
            enum: ["compose_meal", "revise_meal"]
          },
          dinerIds,
          rejectedFoodIds: stringArray,
          rejectedTemplateIds: stringArray
        },
        required: ["dinerIds"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "finalize_meal_plan",
      description:
        "Submit your complete dish selection from the candidate set. Priority: cover shared_main, shared_side and staple. Each role is not limited to one dish — select multiple dishes in the same role when a richer combination fits the candidates and budget, and share that role's total budget with relativePortion. selectedDishes may contain 1–12 different dishes; the count is not fixed at three. Declare mealStructure mode simple or one_pot with a reason when the user explicitly asks for an exception. mealPortionScale changes the base serving directly; remaining budget is only an upper cap. Absolute energy/carbohydrate/protein floors and the sodium ceiling do not shrink with the scale. Domain validates IDs/versions/members and never substitutes dishes. On nutrition reject, follow the structured recovery details and reselect — do not stop.",
      strict: true,
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          goal: {
            type: "string",
            enum: ["compose_meal", "revise_meal"]
          },
          dinerIds,
          mealType: { type: "string", enum: ["lunch", "dinner"] },
          candidateSetId: { type: "string", minLength: 1 },
          selectedDishes: {
            type: "array",
            minItems: 1,
            maxItems: 12,
            items: {
              type: "object",
              additionalProperties: false,
              properties: {
                templateId: { type: "string", minLength: 1 },
                relativePortion: {
                  type: "string",
                  enum: ["small", "standard", "large"]
                }
              },
              required: ["templateId", "relativePortion"]
            }
          },
          mealPortionScale: {
            type: "number",
            exclusiveMinimum: 0,
            maximum: 1.5,
            description:
              "Base serving scale for this meal (0–1.5). It changes grams directly. Remaining daily nutrition is a cap, not another multiplier."
          },
          mealStructure: {
            type: "object",
            additionalProperties: false,
            properties: {
              mode: { type: "string", enum: ["standard", "simple", "one_pot"] },
              requiredRoles: {
                type: "array",
                items: { type: "string", enum: ["shared_main", "shared_side", "staple"] }
              },
              omittedRoles: {
                type: "array",
                items: { type: "string", enum: ["shared_main", "shared_side", "staple"] }
              },
              reason: { type: "string", maxLength: 200 }
            },
          },
          selectionReason: { type: "string", minLength: 1, maxLength: 500 }
        },
        required: [
          "dinerIds",
          "mealType",
          "candidateSetId",
          "selectedDishes",
          "mealPortionScale",
          "selectionReason"
        ]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "preview_meal_completion",
      description:
        "Preview recording a completed meal as planned. Creates a pending action; does not write intake or inventory until the user confirms with token/hash. Do not pass mode — the product always previews as_planned.",
      strict: true,
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          goal: {
            type: "string",
            enum: ["preview_meal_completion", "complete_meal"]
          }
        },
        required: []
      }
    }
  },
  {
    type: "function",
    function: {
      name: "preview_caregiver_task",
      description:
        "Preview a minimum-disclosure caregiver task card for the active plan (menu, inventory use, shopping list). This never commits or sends. recipientLabel must be one exact caregiver label (保姆 / 阿姨 / 家庭保姆).",
      strict: true,
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          goal: {
            type: "string",
            enum: ["preview_handoff", "send_handoff"]
          },
          recipientLabel: {
            type: "string",
            enum: [...CAREGIVER_RECIPIENT_LABELS],
            description:
              "Exact label from the user utterance; do not invent a different caregiver"
          },
          serveAt: {
            type: "string",
            description:
              "Optional serve time. Prefer '今天 HH:MM' (e.g. '今天 18:00') when the user gave a clock time; use 'unspecified' when they did not. ISO-8601 with offset is also accepted (e.g. '2026-08-04T18:30:00+08:00'). Omit when unsure — defaults to unspecified."
          }
        },
        required: ["recipientLabel"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "retrieve_local_knowledge",
      description:
        "Local RAG over the approved household knowledge corpus: embed the query (vLLM embeddings when configured) and return top chunks with source paths and scores. Use for policy/privacy/process questions. Do not invent sources when hits are empty.",
      strict: true,
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          goal: { type: "string", enum: ["retrieve_guidance"] },
          query: {
            type: "string",
            minLength: 1,
            maxLength: 500,
            description: "Natural-language retrieval query in Chinese or English"
          },
          topK: {
            type: "integer",
            minimum: 1,
            maximum: 5,
            description: "Number of chunks to return (default 3)"
          }
        },
        required: ["query"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "preview_inventory_change",
      description:
        "Preview an inventory adjustment. Does not write until UI confirms.",
      strict: true,
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          goal: {
            type: "string",
            enum: ["preview_inventory", "update_inventory"]
          },
          foodId: { type: "string", minLength: 1 },
          quantity: { type: "number", exclusiveMinimum: 0, maximum: 100 },
          unit: { type: "string", minLength: 1, maxLength: 16 }
        },
        required: ["foodId"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "preview_member_memory_change",
      description:
        "Preview saving an explicit member preference or user-stated health fact. Does not write until UI confirms. Never invent medical diagnoses.",
      strict: true,
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          goal: {
            type: "string",
            enum: ["preview_member_memory", "update_member_memory"]
          },
          memberId: { type: "string", minLength: 1 },
          kind: { type: "string", enum: ["preference", "health_fact"] },
          summary: { type: "string", minLength: 1, maxLength: 300 },
          polarity: { type: "string", enum: ["prefer", "avoid", "note"] }
        },
        required: ["memberId", "summary"]
      }
    }
  }
];

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function unwrapJsonString(value: unknown): unknown {
  if (typeof value !== "string") return value;
  const trimmed = value.trim();
  if (!trimmed.startsWith('"') || !trimmed.endsWith('"')) return value;
  try {
    const parsed = JSON.parse(trimmed);
    return typeof parsed === "string" ? parsed : value;
  } catch {
    return value;
  }
}

type TransportPath = readonly (string | "*")[];

const QUOTED_STRING_PATHS: Record<AgentToolName, readonly TransportPath[]> = {
  get_day_context: [["goal"], ["dinerIds", "*"], ["serviceDate"]],
  get_inventory: [["goal"]],
  find_dish_candidates: [
    ["goal"],
    ["dinerIds", "*"],
    ["rejectedFoodIds", "*"],
    ["rejectedTemplateIds", "*"]
  ],
  finalize_meal_plan: [
    ["goal"],
    ["dinerIds", "*"],
    ["mealType"],
    ["candidateSetId"],
    ["selectedDishes", "*", "templateId"],
    ["selectedDishes", "*", "relativePortion"],
    ["mealStructure", "mode"],
    ["mealStructure", "requiredRoles", "*"],
    ["mealStructure", "omittedRoles", "*"],
    ["mealStructure", "reason"],
    ["selectionReason"]
  ],
  preview_meal_completion: [["goal"], ["mode"]],
  preview_caregiver_task: [
    ["goal"],
    ["recipientLabel"],
    ["serveAt"]
  ],
  retrieve_local_knowledge: [["goal"], ["query"]],
  preview_inventory_change: [["goal"], ["foodId"], ["unit"]],
  preview_member_memory_change: [
    ["goal"],
    ["memberId"],
    ["kind"],
    ["summary"],
    ["polarity"]
  ]
};

function normalizeTransportPath(
  value: unknown,
  path: TransportPath,
  index = 0
): unknown {
  if (index === path.length) return unwrapJsonString(value);
  const segment = path[index]!;
  if (segment === "*") {
    return Array.isArray(value)
      ? value.map((item) => normalizeTransportPath(item, path, index + 1))
      : value;
  }
  if (!isObject(value) || !(segment in value)) return value;
  return {
    ...value,
    [segment]: normalizeTransportPath(value[segment], path, index + 1)
  };
}

/** Declared model-facing properties accepted by the runtime contract. */
const TOOL_KNOWN_KEYS: Record<AgentToolName, ReadonlySet<string>> = {
  get_day_context: new Set(["goal", "dinerIds", "serviceDate"]),
  get_inventory: new Set(["goal"]),
  find_dish_candidates: new Set([
    "goal",
    "dinerIds",
    "rejectedFoodIds",
    "rejectedTemplateIds"
  ]),
  finalize_meal_plan: new Set([
    "goal",
    "dinerIds",
    "mealType",
    "candidateSetId",
    "selectedDishes",
    "mealPortionScale",
    "mealStructure",
    "selectionReason"
  ]),
  preview_meal_completion: new Set(["goal", "mode"]),
  preview_caregiver_task: new Set(["goal", "recipientLabel", "serveAt"]),
  retrieve_local_knowledge: new Set(["goal", "query", "topK"]),
  preview_inventory_change: new Set(["goal", "foodId", "quantity", "unit"]),
  preview_member_memory_change: new Set([
    "goal",
    "memberId",
    "kind",
    "summary",
    "polarity"
  ])
};

/**
 * Reject undeclared model keys before strict Zod parsing. Unknown semantic
 * fields must trigger the provider's bounded schema retry, never disappear.
 */
export function assertKnownToolKeys(
  tool: AgentToolName,
  input: Record<string, unknown>
): Record<string, unknown> {
  const allowed = TOOL_KNOWN_KEYS[tool];
  const unknown = Object.keys(input).filter((key) => !allowed.has(key));
  if (unknown.length > 0) {
    throw new Error(
      `Unknown fields for ${tool}: ${unknown.sort().join(", ")}`
    );
  }
  return input;
}

export function parseModelToolArguments(
  tool: AgentToolName,
  input: unknown
): Record<string, unknown> {
  const normalized = normalizeStructuredTransport(tool, input);
  const withDefaults = applyInterfaceDefaults(
    tool,
    isObject(normalized) ? normalized : {}
  );
  const checked = assertKnownToolKeys(tool, withDefaults);
  return TOOL_ARGUMENT_SCHEMAS[tool].parse(checked) as Record<
    string,
    unknown
  >;
}

/**
 * A tool name selects the operation; an optional goal records the model's
 * semantic target (for example update_inventory vs preview_inventory).
 * compose vs revise is still finalized in graph from activePlanId/state.
 */
export function parseModelToolGoal(
  tool: AgentToolName,
  input: Record<string, unknown>
): AgentGoal {
  const normalized = normalizeStructuredTransport(tool, input);
  const goal = isObject(normalized) ? normalized.goal : undefined;
  if (goal !== undefined && goal !== null && goal !== "") {
    return ModelToolGoalSchema.parse(goal);
  }
  switch (tool) {
    case "get_day_context":
      return "inspect_context";
    case "get_inventory":
      return "inspect_inventory";
    case "find_dish_candidates":
    case "finalize_meal_plan":
      // Soft default; graph upgrades to revise_meal when activePlanId is set.
      return "compose_meal";
    case "retrieve_local_knowledge":
      return "retrieve_guidance";
    case "preview_caregiver_task":
      return "preview_handoff";
    case "preview_meal_completion":
      return "complete_meal";
    case "preview_inventory_change":
      return "update_inventory";
    case "preview_member_memory_change":
      return "update_member_memory";
  }
}

export function normalizeStructuredTransport(
  tool: AgentToolName,
  input: unknown
): unknown {
  if (!isObject(input)) return input;
  return QUOTED_STRING_PATHS[tool].reduce(
    (normalized, path) => normalizeTransportPath(normalized, path),
    input as unknown
  );
}

export function parseCanonicalToolArguments(
  tool: AgentToolName,
  input: unknown
): Record<string, unknown> {
  return CANONICAL_TOOL_ARGUMENT_SCHEMAS[tool].parse(input) as Record<
    string,
    unknown
  >;
}

export function toExpectedModelToolArguments(
  tool: AgentToolName,
  input: Record<string, unknown> | null
): Record<string, unknown> | null {
  if (!input) return null;
  return input;
}
