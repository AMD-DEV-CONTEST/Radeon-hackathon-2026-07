import type { AgentGoal } from "./contracts.js";
import type { AgentToolName } from "./state.js";
import type { ToolResult } from "./tools/types.js";
import { classifyToolOutcome } from "./tool-outcome.js";

export type AgentLoopMode = "ACTION_ALLOWED" | "FINAL_ONLY" | "BLOCKED";

export type LoopTransition = {
  mode: AgentLoopMode;
  reason: string;
};

type ActionableGoal = Exclude<AgentGoal, "no_action" | "unsupported">;

export function resolveLoopTransition(input: {
  goal: ActionableGoal;
  tool: AgentToolName;
  result: ToolResult<unknown>;
}): LoopTransition {
  const { goal, tool, result } = input;
  const outcome = classifyToolOutcome({
    tool,
    ok: result.ok,
    ...(!result.ok ? { code: result.code } : {}),
    ...(result.ok && result.data && typeof result.data === "object"
      ? { data: result.data as Record<string, unknown> }
      : {})
  });
  if (outcome.kind === "invocation_failed") {
    return outcome.code === "NO_FEASIBLE_PLAN"
      ? { mode: "BLOCKED", reason: "plan_infeasible" }
      : { mode: "ACTION_ALLOWED", reason: "tool_failed" };
  }

  // Domain reject of a menu is recoverable: model may re-select from candidates.
  if (outcome.kind === "business_rejected") {
    return { mode: "ACTION_ALLOWED", reason: "finalize_failed_reselect" };
  }

  // Reading context is deliberately neutral. The model may either finish the
  // inspection or choose the next planning action from the updated state.
  if (tool === "get_day_context") {
    return { mode: "ACTION_ALLOWED", reason: "context_observed_choose_next_action" };
  }

  if (tool === "preview_meal_completion") {
    return { mode: "FINAL_ONLY", reason: "goal_satisfied" };
  }

  if (tool === "preview_caregiver_task") {
    // Preview ready; send still needs UI confirmation (BLOCKED at TaskOutcome).
    return { mode: "FINAL_ONLY", reason: "goal_satisfied" };
  }

  if (tool === "retrieve_local_knowledge") {
    // Retrieval is read-only context. The model may finish after it, or use
    // the grounded result for a follow-up preview in the same turn.
    return {
      mode: "ACTION_ALLOWED",
      reason: "guidance_observed_choose_next_action"
    };
  }

  if (
    tool === "preview_inventory_change" ||
    tool === "preview_member_memory_change"
  ) {
    return { mode: "FINAL_ONLY", reason: "goal_satisfied" };
  }

  if (tool === "get_inventory") {
    return { mode: "FINAL_ONLY", reason: "goal_satisfied" };
  }

  if (tool === "finalize_meal_plan") {
    if (goal === "send_handoff" || goal === "preview_handoff") {
      return {
        mode: "ACTION_ALLOWED",
        reason: "goal_requires_more_evidence"
      };
    }
    return { mode: "FINAL_ONLY", reason: "goal_satisfied" };
  }

  if (isGoalSatisfied(goal, tool)) {
    return { mode: "FINAL_ONLY", reason: "goal_satisfied" };
  }

  return { mode: "ACTION_ALLOWED", reason: "goal_requires_more_evidence" };
}

function isGoalSatisfied(goal: ActionableGoal, tool: AgentToolName): boolean {
  switch (goal) {
    case "inspect_context":
      return tool === "get_day_context";
    case "inspect_inventory":
      return tool === "get_inventory";
    case "compose_meal":
      return tool === "finalize_meal_plan";
    case "revise_meal":
      return tool === "finalize_meal_plan";
    case "retrieve_guidance":
      return tool === "retrieve_local_knowledge";
    case "preview_handoff":
    case "send_handoff":
      return tool === "preview_caregiver_task";
    case "preview_inventory":
    case "update_inventory":
      return tool === "preview_inventory_change";
    case "preview_member_memory":
    case "update_member_memory":
      return tool === "preview_member_memory_change";
    case "preview_meal_completion":
    case "complete_meal":
      return tool === "preview_meal_completion";
  }
}
