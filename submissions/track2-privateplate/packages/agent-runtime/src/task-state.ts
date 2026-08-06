/**
 * Typed TaskState lifecycle and single-source available actions.
 * Non-secret only: no confirmation tokens or health tags.
 *
 * schemaVersion 2: workflowStage + candidate set refs + pendingActionType.
 */
import type { AgentLoopMode } from "./loop-mode.js";
import type { AgentGoal, MissingField } from "./contracts.js";
import type {
  AgentState,
  AgentToolName,
  GraphPhase
} from "./state.js";
import { AGENT_TOOL_ALLOWLIST } from "./state.js";
import type { ControlDecisionName } from "./model/control-decisions.js";
import { CONTROL_DECISION_NAMES } from "./model/control-decisions.js";
import { normalizeMissingFields } from "./model/tool-field-contract.js";
import {
  classifyToolOutcome,
  isSuccessfulToolOutcome
} from "./tool-outcome.js";

export const TASK_STATE_SCHEMA_VERSION = 2 as const;

export type TaskStateStatus =
  | "active"
  | "waiting_user"
  | "waiting_confirmation"
  | "completed"
  | "blocked";

/**
 * Planning pipeline stages (legal tool order only).
 * idle → day_context → candidates → plan_ready → (preview_write) → awaiting_confirm → completed
 */
export type WorkflowStage =
  | "idle"
  | "day_context"
  | "candidates"
  | "plan_ready"
  | "preview_write"
  | "awaiting_confirm"
  | "completed";

/** Strongly typed non-secret slots the agent may remember across turns. */
export type TaskKnownSlots = {
  dinerIds?: string[];
  mealType?: "lunch" | "dinner";
  recipientLabel?: string;
  serveAt?: string;
};

export type TaskState = {
  schemaVersion: typeof TASK_STATE_SCHEMA_VERSION;
  /** Soft objective for model-visible status; tool choice is primary intent. */
  objective: AgentGoal | null;
  status: TaskStateStatus;
  workflowStage: WorkflowStage;
  unresolvedSlots: MissingField[];
  knownSlots: TaskKnownSlots;
  focusedTemplateId: string | null;
  lastDomainFailureCode: string | null;
  pendingActionId: string | null;
  pendingActionType: string | null;
  candidateSetId: string | null;
  /** JSON versionStamp string or hash for stale checks. */
  candidateSetVersion: string | null;
  serviceDate: string | null;
};

/**
 * Privacy-safe projection for the model. Never includes health tags or tokens.
 */
export type ModelVisibleTaskState = {
  objective: AgentGoal | null;
  status: TaskStateStatus;
  workflowStage: WorkflowStage;
  unresolvedSlots: MissingField[];
  knownSlots: TaskKnownSlots;
  focusedTemplateId: string | null;
  lastDomainFailureCode: string | null;
  hasPendingAction: boolean;
  pendingActionType: string | null;
  candidateSetId: string | null;
  serviceDate: string | null;
  hasActivePlan: boolean;
};

export type TaskTransition =
  | {
      type: "set_objective";
      objective: AgentGoal;
      /** When false, do not force status=active (default true for new work). */
      activate?: boolean;
    }
  | { type: "replace_objective"; objective: AgentGoal }
  | {
      type: "ask_user";
      missingFields: readonly string[];
      known?: TaskKnownSlots;
      objective?: AgentGoal;
    }
  | { type: "resolve_slots"; slots: TaskKnownSlots }
  | {
      type: "tool_succeeded";
      tool: AgentToolName;
      focusedTemplateId?: string | null;
      pendingActionId?: string | null;
      pendingActionType?: string | null;
      clearFocus?: boolean;
      objective?: AgentGoal;
      candidateSetId?: string | null | undefined;
      candidateSetVersion?: string | null | undefined;
      serviceDate?: string | null | undefined;
      data?: Record<string, unknown> | undefined;
    }
  | { type: "tool_failed"; code: string }
  | { type: "refuse"; reasonCode: string }
  | { type: "block_task"; reasonCode: string; keepSlots?: boolean }
  /** End this user turn without completing the underlying business task. */
  | { type: "turn_finished" }
  /** Mark the confirmation-gated business action as committed. */
  | { type: "commit_completed" }
  | { type: "finish" }
  | { type: "clear_pending_action" }
  | { type: "set_focus"; templateId: string | null }
  | { type: "set_workflow_stage"; stage: WorkflowStage };

export type AvailableActions = {
  domainTools: AgentToolName[];
  controlDecisions: ControlDecisionName[];
};

export type TurnToolResult = {
  tool: AgentToolName;
  ok: boolean;
  code?: string;
  data?: Record<string, unknown> | null;
};

export function createEmptyTaskState(): TaskState {
  return {
    schemaVersion: TASK_STATE_SCHEMA_VERSION,
    objective: null,
    status: "active",
    workflowStage: "idle",
    unresolvedSlots: [],
    knownSlots: {},
    focusedTemplateId: null,
    lastDomainFailureCode: null,
    pendingActionId: null,
    pendingActionType: null,
    candidateSetId: null,
    candidateSetVersion: null,
    serviceDate: null
  };
}

/**
 * Start of a new user message. Keep waiting_user/waiting_confirmation;
 * otherwise clear the soft objective and transient failure so the model
 * re-declares via tool choice. Preserve candidate set / plan-ready stage for
 * multi-turn revision until a different objective is chosen.
 */
export function beginUserTurnTaskState(current: TaskState): TaskState {
  if (
    current.status === "waiting_user" &&
    current.unresolvedSlots.length > 0
  ) {
    return current;
  }
  if (current.status === "waiting_confirmation") {
    return current;
  }
  return {
    ...current,
    objective: null,
    status: "active",
    unresolvedSlots: [],
    lastDomainFailureCode: null
  };
}

export function toModelVisibleTaskState(
  taskState: TaskState,
  agentState?: Pick<AgentState, "activePlanId">
): ModelVisibleTaskState {
  return {
    objective: taskState.objective,
    status: taskState.status,
    workflowStage: taskState.workflowStage,
    unresolvedSlots: [...taskState.unresolvedSlots],
    knownSlots: { ...taskState.knownSlots },
    focusedTemplateId: taskState.focusedTemplateId,
    lastDomainFailureCode: taskState.lastDomainFailureCode,
    hasPendingAction: taskState.pendingActionId != null,
    pendingActionType: taskState.pendingActionType,
    candidateSetId: taskState.candidateSetId,
    serviceDate: taskState.serviceDate,
    hasActivePlan: Boolean(agentState?.activePlanId)
  };
}

export function applyTaskTransition(
  current: TaskState,
  event: TaskTransition
): TaskState {
  switch (event.type) {
    case "set_objective": {
      const next = { ...current, objective: event.objective };
      if (event.activate !== false && current.status !== "waiting_confirmation") {
        next.status = "active";
      }
      // Enter planning pipeline when objective is compose/revise.
      if (
        event.objective === "compose_meal" ||
        event.objective === "revise_meal"
      ) {
        if (current.workflowStage === "idle" || current.workflowStage === "completed") {
          next.workflowStage = "idle";
        }
      }
      return next;
    }
    case "replace_objective":
      if (current.pendingActionId !== null) return current;
      return {
        ...current,
        objective: event.objective,
        status: "active",
        unresolvedSlots: [],
        knownSlots: {},
        focusedTemplateId: null,
        lastDomainFailureCode: null,
        candidateSetId: null,
        candidateSetVersion: null,
        workflowStage: "idle"
      };
    case "ask_user": {
      const known = mergeKnownSlots(current.knownSlots, event.known ?? {});
      return {
        ...current,
        status: "waiting_user",
        unresolvedSlots: normalizeMissingFields(event.missingFields),
        knownSlots: known,
        ...(event.objective !== undefined ? { objective: event.objective } : {})
      };
    }
    case "resolve_slots":
      return {
        ...current,
        knownSlots: mergeKnownSlots(current.knownSlots, event.slots),
        unresolvedSlots: current.unresolvedSlots.filter((slot) => {
          if (slot === "dinerIds") return !event.slots.dinerIds?.length;
          if (slot === "mealType") return event.slots.mealType == null;
          if (slot === "recipientLabel") return !event.slots.recipientLabel;
          return true;
        }),
        status:
          current.status === "waiting_user" ? "active" : current.status
      };
    case "tool_succeeded": {
      const next: TaskState = {
        ...current,
        lastDomainFailureCode: null,
        status:
          current.status === "waiting_user" ? "active" : current.status
      };
      if (event.objective !== undefined) next.objective = event.objective;
      if (event.clearFocus) next.focusedTemplateId = null;
      if (event.focusedTemplateId !== undefined) {
        next.focusedTemplateId = event.focusedTemplateId;
      }
      if (event.serviceDate) next.serviceDate = event.serviceDate;
      if (event.candidateSetId !== undefined) {
        next.candidateSetId = event.candidateSetId;
      }
      if (event.candidateSetVersion !== undefined) {
        next.candidateSetVersion = event.candidateSetVersion;
      }

      if (
        event.tool === "preview_caregiver_task" ||
        event.tool === "preview_meal_completion" ||
        event.tool === "preview_inventory_change" ||
        event.tool === "preview_member_memory_change"
      ) {
        next.pendingActionId = event.pendingActionId ?? next.pendingActionId;
        next.pendingActionType =
          event.pendingActionType ??
          (event.tool === "preview_meal_completion"
            ? "meal_completion"
            : event.tool === "preview_inventory_change"
              ? "inventory_restock"
              : event.tool === "preview_member_memory_change"
                ? "member_memory_change"
                : "caregiver_task_send");
        next.status = "waiting_confirmation";
        next.workflowStage = "awaiting_confirm";
      } else if (event.tool === "get_day_context") {
        if (
          next.objective === "compose_meal" ||
          next.objective === "revise_meal" ||
          next.workflowStage === "idle" ||
          next.workflowStage === "day_context"
        ) {
          next.workflowStage = "day_context";
        }
        if (event.data?.serviceDate && typeof event.data.serviceDate === "string") {
          next.serviceDate = event.data.serviceDate;
        }
      } else if (event.tool === "find_dish_candidates") {
        next.workflowStage = "candidates";
        const id =
          event.candidateSetId ??
          (typeof event.data?.candidateSetId === "string"
            ? event.data.candidateSetId
            : null);
        next.candidateSetId = id;
        if (event.data?.versionStamp) {
          next.candidateSetVersion = JSON.stringify(event.data.versionStamp);
        }
      } else if (event.tool === "finalize_meal_plan") {
        next.workflowStage = "plan_ready";
        next.status = "active";
      }
      return next;
    }
    case "tool_failed":
      return {
        ...current,
        lastDomainFailureCode: event.code,
        status:
          current.status === "waiting_confirmation" ||
          current.status === "waiting_user"
            ? current.status
            : current.status
      };
    case "refuse":
      return {
        ...current,
        status: "blocked",
        lastDomainFailureCode: event.reasonCode
      };
    case "block_task":
      return {
        ...current,
        status: "blocked",
        lastDomainFailureCode: event.reasonCode,
        unresolvedSlots: event.keepSlots ? current.unresolvedSlots : []
      };
    case "turn_finished":
      return {
        ...current,
        unresolvedSlots: []
      };
    case "commit_completed":
      return {
        ...current,
        status: "completed",
        workflowStage: "completed",
        unresolvedSlots: [],
        pendingActionId: null,
        pendingActionType: null
      };
    case "finish":
      // A preview is the end of this turn, not the end of the business task.
      // Keep the confirmation gate until the UI/CLI side channel commits it.
      if (
        current.status === "waiting_confirmation" ||
        current.workflowStage === "awaiting_confirm"
      ) {
        return {
          ...current,
          unresolvedSlots: []
        };
      }
      return {
        ...current,
        status: "completed",
        workflowStage:
          current.workflowStage === "plan_ready" ? "plan_ready" : "completed",
        unresolvedSlots: []
      };
    case "clear_pending_action":
      return {
        ...current,
        pendingActionId: null,
        pendingActionType: null,
        status:
          current.status === "waiting_confirmation" ? "active" : current.status,
        workflowStage:
          current.workflowStage === "awaiting_confirm"
            ? "plan_ready"
            : current.workflowStage
      };
    case "set_focus":
      return { ...current, focusedTemplateId: event.templateId };
    case "set_workflow_stage":
      return { ...current, workflowStage: event.stage };
    default:
      return current;
  }
}

function mergeKnownSlots(
  base: TaskKnownSlots,
  patch: TaskKnownSlots
): TaskKnownSlots {
  const next = { ...base };
  if (patch.dinerIds !== undefined) next.dinerIds = patch.dinerIds;
  if (patch.mealType !== undefined) next.mealType = patch.mealType;
  if (patch.recipientLabel !== undefined) {
    next.recipientLabel = patch.recipientLabel;
  }
  if (patch.serveAt !== undefined) next.serveAt = patch.serveAt;
  return next;
}

/**
 * Single action calculator for Provider tool exposure and Gateway enforcement.
 *
 * Planning order (when objective is compose/revise or stage in pipeline):
 *   get_day_context → find_dish_candidates → finalize_meal_plan → finish_turn
 * Other tools (RAG, inventory, memory, handoff) available outside strict pipeline
 * or after plan_ready.
 */
export function computeAvailableActions(
  agentState: AgentState,
  taskState: TaskState,
  mode: AgentLoopMode,
  turnToolResults: readonly TurnToolResult[] = []
): AvailableActions {
  const domainTools = projectDomainToolsForTurn(
    computeDomainTools(agentState, taskState, mode),
    agentState,
    taskState,
    turnToolResults
  );
  const controlDecisions = computeControlDecisions(mode, taskState);
  return { domainTools, controlDecisions };
}

function isPlanningObjective(objective: AgentGoal | null): boolean {
  return objective === "compose_meal" || objective === "revise_meal";
}

function computeDomainTools(
  agentState: AgentState,
  taskState: TaskState,
  mode: AgentLoopMode
): AgentToolName[] {
  if (mode !== "ACTION_ALLOWED") return [];
  if (
    agentState.phase === "SAFE_STOP" ||
    agentState.phase === "COMPLETED" ||
    taskState.status === "blocked"
  ) {
    return [];
  }

  if (
    taskState.status === "waiting_confirmation" ||
    agentState.phase === "AWAITING_CONFIRMATION" ||
    taskState.workflowStage === "awaiting_confirm"
  ) {
    // A new preview can replace the old one when the user corrects its
    // object/arguments. The old pending action is cancelled before the new
    // preview is created; confirmation itself remains UI-only.
    return [
      "get_day_context",
      "get_inventory",
      "retrieve_local_knowledge",
      "preview_inventory_change",
      "preview_member_memory_change",
      "preview_caregiver_task",
      "preview_meal_completion"
    ];
  }

  // A new user turn starts with no declared objective. Keep the old plan and
  // domain facts, but expose safe entry tools until the model chooses the new
  // objective. The chosen non-planning objective will clear old pipeline refs
  // before its first Domain call.
  if (
    taskState.objective === null ||
    (taskState.status === "waiting_user" && taskState.pendingActionId === null)
  ) {
    const tools = new Set<AgentToolName>([
      "get_day_context",
      "get_inventory",
      "retrieve_local_knowledge",
      "preview_inventory_change",
      "preview_member_memory_change"
    ]);
    if (
      taskState.workflowStage === "day_context" ||
      taskState.workflowStage === "candidates" ||
      agentState.activePlanId
    ) {
      tools.add("find_dish_candidates");
    }
    if (taskState.workflowStage === "candidates") {
      tools.add("finalize_meal_plan");
    }
    if (taskState.workflowStage === "plan_ready" || agentState.activePlanId) {
      tools.add("preview_meal_completion");
      tools.add("preview_caregiver_task");
      tools.add("finalize_meal_plan");
    }
    return [...tools];
  }

  const stage = taskState.workflowStage;
  const planning =
    isPlanningObjective(taskState.objective) ||
    stage === "day_context" ||
    stage === "candidates" ||
    stage === "plan_ready";

  // Strict planning pipeline: only next legal domain tools.
  if (planning && stage !== "plan_ready") {
    if (stage === "idle") {
      return ["get_day_context"];
    }
    if (stage === "day_context") {
      return ["find_dish_candidates", "get_day_context"];
    }
    if (stage === "candidates") {
      // Re-select after failed finalize stays here.
      return ["finalize_meal_plan", "find_dish_candidates", "get_day_context"];
    }
  }

  // After plan ready: handoff, meal complete preview, memory, inventory, replan.
  const tools = new Set<AgentToolName>([
    "get_day_context",
    "get_inventory",
    "retrieve_local_knowledge",
    "preview_inventory_change",
    "preview_member_memory_change"
  ]);

  if (stage === "plan_ready" || agentState.activePlanId) {
    tools.add("preview_meal_completion");
    tools.add("preview_caregiver_task");
    // Revision path: new full selection — reset via candidates.
    tools.add("find_dish_candidates");
    tools.add("finalize_meal_plan");
  }

  // Non-planning intents (inspect, RAG, restock) from idle.
  if (!planning || stage === "idle") {
    tools.add("get_day_context");
    tools.add("get_inventory");
  }

  return [...tools];
}

function projectDomainToolsForTurn(
  domainTools: AgentToolName[],
  agentState: AgentState,
  taskState: TaskState,
  turnToolResults: readonly TurnToolResult[]
): AgentToolName[] {
  if (turnToolResults.length === 0) return domainTools;

  const successfulTools = new Set(
    turnToolResults
      .filter(isSuccessfulToolOutcome)
      .map((result) => result.tool)
  );
  const lastResult = turnToolResults.at(-1);
  let staleFailureIndex = -1;
  for (let index = turnToolResults.length - 1; index >= 0; index -= 1) {
    if (isStalePlanningFailure(taskState, turnToolResults[index])) {
      staleFailureIndex = index;
      break;
    }
  }

  if (staleFailureIndex >= 0) {
    const recoveredResults = turnToolResults.slice(staleFailureIndex + 1);
    const recoveredSuccess = recoveredResults
      .slice()
      .reverse()
      .find(isSuccessfulToolOutcome);
    if (recoveredSuccess?.tool === "find_dish_candidates") {
      return domainTools.includes("finalize_meal_plan")
        ? ["finalize_meal_plan"]
        : domainTools;
    }
    if (recoveredSuccess?.tool === "get_day_context") {
      return domainTools.includes("find_dish_candidates")
        ? ["find_dish_candidates"]
        : domainTools;
    }
    return domainTools.includes("get_day_context")
      ? ["get_day_context"]
      : domainTools;
  }

  if (isReselectableFinalizeFailure(taskState, lastResult)) {
    return domainTools.includes("finalize_meal_plan")
      ? ["finalize_meal_plan"]
      : domainTools;
  }

  if (successfulTools.has("find_dish_candidates")) {
    return domainTools.includes("finalize_meal_plan")
      ? ["finalize_meal_plan"]
      : domainTools.filter((tool) => tool !== "find_dish_candidates");
  }

  if (successfulTools.has("retrieve_local_knowledge")) {
    if (taskState.objective === "retrieve_guidance") {
      return agentState.activePlanId &&
        domainTools.includes("preview_caregiver_task")
        ? ["preview_caregiver_task"]
        : [];
    }
    return domainTools.filter((tool) => tool !== "retrieve_local_knowledge");
  }

  if (successfulTools.has("get_inventory")) {
    if (taskState.objective === "inspect_inventory") return [];
    return domainTools.filter((tool) => tool !== "get_inventory");
  }

  if (successfulTools.has("get_day_context")) {
    if (taskState.objective === "inspect_context") return [];
    return domainTools.filter((tool) => tool !== "get_day_context");
  }

  return domainTools;
}

function isStalePlanningFailure(
  taskState: TaskState,
  result: TurnToolResult | undefined
): boolean {
  if (!result || !isPlanningObjective(taskState.objective)) return false;
  if (
    result.tool !== "finalize_meal_plan" &&
    result.tool !== "get_day_context"
  ) {
    return false;
  }
  const classification = classifyToolOutcome(result);
  const code =
    classification.kind === "succeeded" ? null : classification.code;
  return (
    code === "STALE_CONTEXT" ||
    code === "STALE_CANDIDATE_SET" ||
    code === "CANDIDATE_SET_MISMATCH" ||
    code === "UNKNOWN_CANDIDATE_SET" ||
    code === "MISSING_CANDIDATE_SET"
  );
}

function isReselectableFinalizeFailure(
  taskState: TaskState,
  result: TurnToolResult | undefined
): boolean {
  if (!result || result.tool !== "finalize_meal_plan") {
    return false;
  }
  if (!isPlanningObjective(taskState.objective)) return false;
  const classification = classifyToolOutcome(result);
  if (classification.kind !== "business_rejected") return false;
  const details =
    result.data && typeof result.data === "object"
      ? ((result.data.recovery as Record<string, unknown> | undefined) ??
          (result.data.details as Record<string, unknown> | undefined) ??
          {})
      : {};
  if (details.reselectAllowed === true) return true;
  return (
    classification.code === "NUTRITION_GUARDRAIL" ||
    classification.code === "NUTRITION_BUDGET" ||
    classification.code === "INSUFFICIENT_REMAINING_BUDGET" ||
    classification.code === "MEAL_STRUCTURE_INCOMPLETE" ||
    classification.code === "ONE_POT_DISH_COUNT_EXCEEDED"
  );
}

function computeControlDecisions(
  mode: AgentLoopMode,
  taskState: TaskState
): ControlDecisionName[] {
  if (mode === "ACTION_ALLOWED") {
    return [...CONTROL_DECISION_NAMES];
  }
  if (mode === "FINAL_ONLY") {
    return ["finish_turn", "ask_user"];
  }
  if (taskState.status === "blocked") {
    return ["finish_turn", "refuse_request", "ask_user"];
  }
  return ["finish_turn", "ask_user", "refuse_request"];
}

export function isDomainToolInAvailableActions(
  actions: AvailableActions,
  tool: string
): tool is AgentToolName {
  return (
    (AGENT_TOOL_ALLOWLIST as readonly string[]).includes(tool) &&
    actions.domainTools.includes(tool as AgentToolName)
  );
}

export function phaseAfterToolFailure(
  priorPhase: GraphPhase,
  agentState: AgentState
): GraphPhase {
  if (priorPhase === "CLASSIFYING" || priorPhase === "IDLE") {
    return agentState.activePlanId ? "PRESENTING_PLAN" : "AWAITING_USER";
  }
  if (priorPhase === "ERROR" || priorPhase === "SAFE_STOP") {
    return agentState.activePlanId ? "PRESENTING_PLAN" : "AWAITING_USER";
  }
  return priorPhase;
}

export function successfulToolCallKey(
  tool: string,
  effectiveArguments: Record<string, unknown> | null | undefined
): string {
  return `${tool}:${stableJson(effectiveArguments ?? {})}`;
}

function stableJson(value: unknown): string {
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableJson(item)).join(",")}]`;
  }
  const record = value as Record<string, unknown>;
  const keys = Object.keys(record).sort();
  return `{${keys
    .map((key) => `${JSON.stringify(key)}:${stableJson(record[key])}`)
    .join(",")}}`;
}
