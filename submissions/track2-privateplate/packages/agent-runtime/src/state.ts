import { z } from "zod";

export type AgentIntent =
  | "inspect_context"
  | "plan_meal"
  | "revise_meal"
  | "handoff_task"
  | "retrieve_guidance"
  | "medical_risk"
  | "out_of_scope_write"
  | "unknown";

export type GraphPhase =
  | "IDLE"
  | "CLASSIFYING"
  | "COLLECTING_CONTEXT"
  | "PLANNING"
  | "PRESENTING_PLAN"
  | "PRESENTING_INFEASIBLE"
  | "REVISING"
  | "PREVIEWING_WRITE"
  | "AWAITING_CONFIRMATION"
  | "AWAITING_USER"
  | "SAFE_STOP"
  | "ERROR"
  | "COMPLETED";

export type AgentState = {
  sessionId: string;
  householdId: string;
  phase: GraphPhase;
  intent: AgentIntent;
  dinerIds: string[];
  householdContextVersion: number | null;
  inventoryVersion: number | null;
  mealPolicyVersion: string | null;
  mealSessionId: string | null;
  activePlanId: string | null;
  activePlanVersion: number | null;
  activeConstraintIds: string[];
  rejectedTemplateIds: string[];
  rejectedFoodIds: string[];
  requestedPriorityFoodIds: string[];
  preferLowEffort: boolean;
  pendingActionId: string | null;
  lastCommittedActionId: string | null;
  lastCommittedPayloadHash: string | null;
  /**
   * Structured action status for irreversible writes.
   * - not_started: no preview or commit attempted
   * - previewed: task card preview generated, awaiting confirmation
   * - confirmation_required: user confirmation pending
   * - committed: confirmed and written to local household task queue
   * - cancelled: pending action cancelled
   * - failed: preview or commit failed
   */
  confirmationStatus:
    | "not_started"
    | "previewed"
    | "confirmation_required"
    | "committed"
    | "cancelled"
    | "failed";
  lastToolStatus: "none" | "success" | "failure";
  errorCode: string | null;
  toolSteps: number;
  maxToolSteps: number;
};

export const AgentStateSchema: z.ZodType<AgentState> = z
  .object({
    sessionId: z.string().min(1),
    householdId: z.string().min(1),
    phase: z.enum([
      "IDLE",
      "CLASSIFYING",
      "COLLECTING_CONTEXT",
      "PLANNING",
      "PRESENTING_PLAN",
      "PRESENTING_INFEASIBLE",
      "REVISING",
      "PREVIEWING_WRITE",
      "AWAITING_CONFIRMATION",
      "AWAITING_USER",
      "SAFE_STOP",
      "ERROR",
      "COMPLETED"
    ]),
    intent: z.enum([
      "inspect_context",
      "plan_meal",
      "revise_meal",
      "handoff_task",
      "medical_risk",
      "out_of_scope_write",
      "unknown"
    ]),
    dinerIds: z.array(z.string().min(1)).min(1).max(3),
    householdContextVersion: z.number().int().nullable(),
    inventoryVersion: z.number().int().nullable(),
    mealPolicyVersion: z.string().nullable(),
    mealSessionId: z.string().nullable(),
    activePlanId: z.string().nullable(),
    activePlanVersion: z.number().int().positive().nullable(),
    activeConstraintIds: z.array(z.string()),
    rejectedTemplateIds: z.array(z.string()),
    rejectedFoodIds: z.array(z.string()),
    requestedPriorityFoodIds: z.array(z.string()),
    preferLowEffort: z.boolean(),
    pendingActionId: z.string().nullable(),
    lastCommittedActionId: z.string().nullable(),
    lastCommittedPayloadHash: z.string().nullable(),
    confirmationStatus: z.enum([
      "not_started",
      "previewed",
      "confirmation_required",
      "committed",
      "cancelled",
      "failed"
    ]),
    lastToolStatus: z.enum(["none", "success", "failure"]),
    errorCode: z.string().nullable(),
    toolSteps: z.number().int().nonnegative(),
    maxToolSteps: z.number().int().positive()
  })
  .strict();

export function createInitialState(input: {
  sessionId: string;
  householdId: string;
  dinerIds: string[];
}): AgentState {
  return {
    sessionId: input.sessionId,
    householdId: input.householdId,
    phase: "IDLE",
    intent: "unknown",
    dinerIds: input.dinerIds,
    householdContextVersion: null,
    inventoryVersion: null,
    mealPolicyVersion: null,
    mealSessionId: null,
    activePlanId: null,
    activePlanVersion: null,
    activeConstraintIds: [],
    rejectedTemplateIds: [],
    rejectedFoodIds: [],
    requestedPriorityFoodIds: [],
    preferLowEffort: false,
    pendingActionId: null,
    lastCommittedActionId: null,
    lastCommittedPayloadHash: null,
    confirmationStatus: "not_started",
    lastToolStatus: "none",
    errorCode: null,
    toolSteps: 0,
    maxToolSteps: 6
  };
}

/**
 * Product tools (protocol v2 planning + handoff preview + meal-complete preview).
 * No commit_*. No legacy compose_family_meal / revise ranking path.
 * Nutrition math and shopping gaps live in Domain (finalize + task card).
 */
export const AGENT_TOOL_ALLOWLIST = [
  "get_day_context",
  "get_inventory",
  "find_dish_candidates",
  "finalize_meal_plan",
  "preview_meal_completion",
  "preview_caregiver_task",
  "retrieve_local_knowledge",
  "preview_inventory_change",
  "preview_member_memory_change"
] as const;

export type AgentToolName = (typeof AGENT_TOOL_ALLOWLIST)[number];

export const PHASE_ALLOWED_TOOLS: Record<GraphPhase, readonly AgentToolName[]> = {
  IDLE: [],
  CLASSIFYING: [],
  COLLECTING_CONTEXT: [
    "get_day_context",
    "get_inventory",
    "retrieve_local_knowledge",
    "preview_inventory_change",
    "preview_member_memory_change"
  ],
  PLANNING: [
    "find_dish_candidates",
    "finalize_meal_plan",
    "retrieve_local_knowledge",
    "preview_inventory_change"
  ],
  PRESENTING_PLAN: [
    "get_day_context",
    "get_inventory",
    "find_dish_candidates",
    "finalize_meal_plan",
    "preview_caregiver_task",
    "preview_meal_completion",
    "retrieve_local_knowledge",
    "preview_inventory_change",
    "preview_member_memory_change"
  ],
  PRESENTING_INFEASIBLE: [
    "find_dish_candidates",
    "finalize_meal_plan",
    "retrieve_local_knowledge"
  ],
  REVISING: ["find_dish_candidates", "finalize_meal_plan", "retrieve_local_knowledge"],
  PREVIEWING_WRITE: [
    "preview_caregiver_task",
    "preview_meal_completion",
    "preview_inventory_change",
    "preview_member_memory_change"
  ],
  AWAITING_CONFIRMATION: ["get_day_context", "get_inventory"],
  AWAITING_USER: [
    "get_day_context",
    "get_inventory",
    "find_dish_candidates",
    "preview_caregiver_task",
    "retrieve_local_knowledge",
    "preview_inventory_change",
    "preview_member_memory_change"
  ],
  SAFE_STOP: [],
  ERROR: [],
  COMPLETED: []
};
