import { describe, expect, it } from "vitest";
import { assertToolAllowed } from "./policy.js";
import { computeAvailableActions, createEmptyTaskState } from "./task-state.js";
import { createInitialState } from "./state.js";

describe("allowed actions v2", () => {
  it("rejects unknown tools", () => {
    const blocked = assertToolAllowed("PLANNING", "compose_family_meal" as never);
    expect(blocked.ok).toBe(false);
  });

  it("allows finalize when stage is candidates", () => {
    const state = createInitialState({
      sessionId: "s",
      householdId: "h",
      dinerIds: ["mem-admin"]
    });
    const task = {
      ...createEmptyTaskState(),
      objective: "compose_meal" as const,
      workflowStage: "candidates" as const,
      candidateSetId: "cset-1"
    };
    const actions = computeAvailableActions(state, task, "ACTION_ALLOWED");
    expect(actions.domainTools).toContain("finalize_meal_plan");
    const ok = assertToolAllowed(
      "PLANNING",
      "finalize_meal_plan",
      actions.domainTools
    );
    expect(ok.ok).toBe(true);
    // Idle planning only exposes get_day_context.
    const idle = computeAvailableActions(
      state,
      { ...createEmptyTaskState(), objective: "compose_meal" },
      "ACTION_ALLOWED"
    );
    expect(idle.domainTools).toEqual(["get_day_context"]);
  });
});
