import { describe, expect, it } from "vitest";
import {
  applyTaskTransition,
  computeAvailableActions,
  createEmptyTaskState
} from "./task-state.js";
import { createInitialState } from "./state.js";

describe("v2 workflow stage tool gating", () => {
  it("planning pipeline only exposes next legal tools", () => {
    const agent = createInitialState({
      sessionId: "s",
      householdId: "h",
      dinerIds: ["mem-admin"]
    });
    let task = createEmptyTaskState();
    task = applyTaskTransition(task, {
      type: "set_objective",
      objective: "compose_meal"
    });
    expect(task.workflowStage).toBe("idle");
    let actions = computeAvailableActions(agent, task, "ACTION_ALLOWED");
    expect(actions.domainTools).toEqual(["get_day_context"]);
    expect(actions.domainTools).not.toContain("finalize_meal_plan");

    task = applyTaskTransition(task, {
      type: "tool_succeeded",
      tool: "get_day_context",
      data: { serviceDate: "2026-08-02" }
    });
    expect(task.workflowStage).toBe("day_context");
    actions = computeAvailableActions(agent, task, "ACTION_ALLOWED");
    expect(actions.domainTools).toContain("find_dish_candidates");
    expect(actions.domainTools).not.toContain("finalize_meal_plan");

    task = applyTaskTransition(task, {
      type: "tool_succeeded",
      tool: "find_dish_candidates",
      data: {
        candidateSetId: "cset-1",
        versionStamp: { household: 1, inventory: 1, intake: 1, policy: "p" }
      }
    });
    expect(task.workflowStage).toBe("candidates");
    expect(task.candidateSetId).toBe("cset-1");
    actions = computeAvailableActions(agent, task, "ACTION_ALLOWED");
    expect(actions.domainTools).toContain("finalize_meal_plan");

    task = applyTaskTransition(task, {
      type: "tool_failed",
      code: "NUTRITION_GUARDRAIL"
    });
    // Stay candidates for reselect — not blocked.
    expect(task.workflowStage).toBe("candidates");
    expect(task.status).toBe("active");
    actions = computeAvailableActions(agent, task, "ACTION_ALLOWED");
    expect(actions.domainTools).toContain("finalize_meal_plan");
    expect(actions.domainTools).toContain("find_dish_candidates");

    task = applyTaskTransition(task, {
      type: "tool_succeeded",
      tool: "finalize_meal_plan",
      data: { status: "ok" }
    });
    expect(task.workflowStage).toBe("plan_ready");
  });

  it("initial plan path is compose not revise when no active plan", () => {
    const agent = createInitialState({
      sessionId: "s",
      householdId: "h",
      dinerIds: ["mem-admin"]
    });
    expect(agent.activePlanId).toBeNull();
    let task = createEmptyTaskState();
    task = applyTaskTransition(task, {
      type: "set_objective",
      objective: "compose_meal"
    });
    expect(task.objective).toBe("compose_meal");
    expect(task.objective).not.toBe("revise_meal");
  });
});
