import type { GraphPhase } from "./state.js";
import type { MissingField, ReasonCode } from "./model/tool-field-contract.js";

export type { MissingField, ReasonCode } from "./model/tool-field-contract.js";
export {
  MISSING_FIELDS,
  REASON_CODES,
  INTERFACE_DEFAULTS,
  normalizeMissingFields,
  normalizeReasonCode,
  applyInterfaceDefaults,
  missingFieldsFromPolicyReasons,
  toolFieldSpecs
} from "./model/tool-field-contract.js";

export type AgentGoal =
  | "inspect_context"
  | "inspect_inventory"
  | "compose_meal"
  | "revise_meal"
  | "retrieve_guidance"
  | "preview_handoff"
  | "send_handoff"
  | "preview_inventory"
  | "update_inventory"
  | "preview_member_memory"
  | "update_member_memory"
  | "preview_meal_completion"
  | "complete_meal"
  | "no_action"
  | "unsupported";

/**
 * Structured action status for irreversible writes.
 * Replaces regex-based "已发送" detection in answer validation.
 */
export type ActionStatus =
  | "not_started"
  | "previewed"
  | "confirmation_required"
  | "committed"
  | "cancelled"
  | "failed";

export type ModelDecisionKind = "tool" | "ask_user" | "final" | "refuse";
export type ModelDecisionTransport = "native_function" | "content_final";
export type AgentModelStepDecision =
  | ModelDecisionKind
  | "retry"
  | "deterministic_fallback";

export type AgentModelStep = {
  index: number;
  providerMode: string;
  model: string;
  decision: AgentModelStepDecision;
  transport?: ModelDecisionTransport;
  goal: AgentGoal;
  tool: string | null;
  rawArguments: Record<string, unknown> | null;
  normalizedArguments: Record<string, unknown> | null;
  effectiveArguments: Record<string, unknown> | null;
  policy: {
    status: "ok" | "needs_clarification" | "not_applicable";
    reasons: string[];
    privacyViolation: boolean;
  };
  missingFields: MissingField[];
  toolResult?: {
    tool: string;
    ok: boolean;
    code?: string;
    status?: string;
  };
  answerValidation?: {
    ok: boolean;
    reasons: string[];
  };
};

export type TaskOutcomeStatus = "COMPLETE" | "PARTIAL" | "BLOCKED" | "FAILED";

export type TaskOutcome = {
  goal: AgentGoal;
  status: TaskOutcomeStatus;
  phase: GraphPhase;
  verification: {
    passed: boolean;
  };
  reasons: string[];
  evidence: Array<{
    kind:
      | "tool_result"
      | "answer_validation"
      | "policy"
      | "domain_error"
      | "deterministic_fallback";
    tool?: string;
    ok: boolean;
    code?: string;
  }>;
};

export function goalForTool(tool: string): AgentGoal {
  switch (tool) {
    case "get_day_context":
      return "inspect_context";
    case "get_inventory":
      return "inspect_inventory";
    case "find_dish_candidates":
    case "finalize_meal_plan":
      return "compose_meal";
    case "preview_meal_completion":
      return "complete_meal";
    case "preview_caregiver_task":
      return "preview_handoff";
    case "retrieve_local_knowledge":
      return "retrieve_guidance";
    case "preview_inventory_change":
      return "update_inventory";
    case "preview_member_memory_change":
      return "update_member_memory";
    default:
      return "unsupported";
  }
}

export function buildTaskOutcome(input: {
  goal: AgentGoal;
  phase: GraphPhase;
  toolTrace: Array<{ tool: string; ok: boolean; code?: string }>;
  validationOk: boolean;
  blockingReasons?: string[];
  decision?: ModelDecisionKind;
  deterministicFallbackCodes?: string[];
}): TaskOutcome {
  const evidence: TaskOutcome["evidence"] = input.toolTrace.map((item) => ({
    kind: "tool_result",
    tool: item.tool,
    ok: item.ok,
    ...(item.code ? { code: item.code } : {})
  }));
  evidence.push({
    kind: "answer_validation",
    ok: input.validationOk,
    ...(!input.validationOk ? { code: "ANSWER_VALIDATION_FAILED" } : {})
  });
  for (const item of input.toolTrace.filter((tool) => !tool.ok)) {
    evidence.push({
      kind: "domain_error",
      tool: item.tool,
      ok: false,
      code: "DOMAIN_TOOL_FAILED"
    });
  }
  if (input.decision === "ask_user" || input.decision === "refuse") {
    evidence.push({
      kind: "policy",
      ok: false,
      code: "POLICY_BLOCKED"
    });
  }
  for (const code of input.deterministicFallbackCodes ?? []) {
    evidence.push({
      kind: "deterministic_fallback",
      ok: true,
      code
    });
  }

  const reasons = [...(input.blockingReasons ?? [])];
  const successfulTools = new Set(
    input.toolTrace.filter((item) => item.ok).map((item) => item.tool)
  );
  const failedTools = input.toolTrace.filter((item) => !item.ok);

  if (!input.validationOk) {
    return outcome("FAILED", false, ["answer_validation_failed", ...reasons]);
  }
  // Caregiver handoff preview: product goal decides COMPLETE vs confirmation BLOCKED.
  // preview_handoff = preview work done. send_handoff = still needs UI confirm.
  if (successfulTools.has("preview_caregiver_task")) {
    if (input.goal === "send_handoff") {
      return outcome("BLOCKED", true, ["confirmation_required"]);
    }
    return outcome("COMPLETE", true, []);
  }
  if (successfulTools.has("preview_meal_completion")) {
    return input.goal === "preview_meal_completion"
      ? outcome("COMPLETE", true, [])
      : outcome("BLOCKED", true, ["confirmation_required"]);
  }
  if (successfulTools.has("preview_inventory_change")) {
    return input.goal === "preview_inventory"
      ? outcome("COMPLETE", true, [])
      : outcome("BLOCKED", true, ["confirmation_required"]);
  }
  if (successfulTools.has("preview_member_memory_change")) {
    return input.goal === "preview_member_memory"
      ? outcome("COMPLETE", true, [])
      : outcome("BLOCKED", true, ["confirmation_required"]);
  }
  if (input.decision === "refuse" || input.goal === "unsupported") {
    return outcome("BLOCKED", true, reasons.length ? reasons : ["unsupported"]);
  }
  if (input.decision === "ask_user" || reasons.length > 0) {
    if (input.phase === "ERROR") {
      return successfulTools.size > 0
        ? outcome("PARTIAL", false, reasons)
        : outcome("FAILED", false, reasons);
    }
    return outcome("BLOCKED", true, reasons);
  }
  if (input.goal === "no_action" && input.decision === "final") {
    return outcome("COMPLETE", true, []);
  }
  // send_handoff without a new preview this turn still needs UI confirmation.
  if (
    input.goal === "send_handoff" &&
    (input.phase === "AWAITING_CONFIRMATION" ||
      input.phase === "AWAITING_USER" ||
      input.decision === "final")
  ) {
    return outcome("BLOCKED", true, ["confirmation_required"]);
  }

  const requiredTool = requiredToolForGoal(input.goal);
  if (requiredTool && successfulTools.has(requiredTool)) {
    return outcome("COMPLETE", true, []);
  }
  if (failedTools.length > 0 && successfulTools.size === 0) {
    return outcome(
      "FAILED",
      false,
      failedTools.map((item) => item.code ?? `${item.tool}_failed`)
    );
  }
  if (successfulTools.size > 0) {
    return outcome("PARTIAL", true, reasons);
  }

  // Grounded final without new tools this turn: plan summary, revision noop,
  // or acknowledge-in-place. Must not leave COMPLETE work as goal_not_verified.
  if (
    input.decision === "final" &&
    failedTools.length === 0 &&
    input.goal !== "send_handoff" &&
    (input.phase === "PRESENTING_PLAN" ||
      input.phase === "COMPLETED" ||
      input.phase === "PRESENTING_INFEASIBLE" ||
      input.phase === "IDLE" ||
      input.phase === "AWAITING_USER")
  ) {
    return outcome("COMPLETE", true, []);
  }

  return outcome(
    input.phase === "ERROR" ? "FAILED" : "BLOCKED",
    input.phase !== "ERROR",
    reasons.length ? reasons : ["goal_not_verified"]
  );

  function outcome(
    status: TaskOutcomeStatus,
    passed: boolean,
    outcomeReasons: string[]
  ): TaskOutcome {
    return {
      goal: input.goal,
      status,
      phase: input.phase,
      verification: { passed },
      reasons: [...new Set(outcomeReasons)],
      evidence
    };
  }
}

function requiredToolForGoal(goal: AgentGoal): string | undefined {
  switch (goal) {
    case "inspect_context":
      return "get_day_context";
    case "inspect_inventory":
      return "get_inventory";
    case "compose_meal":
      return "finalize_meal_plan";
    case "revise_meal":
      return "finalize_meal_plan";
    case "retrieve_guidance":
      return "retrieve_local_knowledge";
    case "preview_handoff":
      return "preview_caregiver_task";
    case "send_handoff":
      return "preview_caregiver_task";
    case "preview_inventory":
    case "update_inventory":
      return "preview_inventory_change";
    case "preview_member_memory":
    case "update_member_memory":
      return "preview_member_memory_change";
    case "preview_meal_completion":
    case "complete_meal":
      return "preview_meal_completion";
    case "no_action":
    case "unsupported":
      return undefined;
  }
}
