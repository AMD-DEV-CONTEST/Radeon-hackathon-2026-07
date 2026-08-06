import { describe, expect, it } from "vitest";
import {
  applyTaskTransition,
  beginUserTurnTaskState,
  computeAvailableActions,
  createEmptyTaskState,
  type TurnToolResult
} from "./task-state.js";
import { createInitialState } from "./state.js";

describe("task-state v2 available actions", () => {
  it("exposes only v2 tools", () => {
    const state = createInitialState({
      sessionId: "s",
      householdId: "h",
      dinerIds: ["mem-admin"]
    });
    const actions = computeAvailableActions(
      state,
      createEmptyTaskState(),
      "ACTION_ALLOWED"
    );
    // Idle non-planning: context + side tools, not finalize.
    expect(actions.domainTools).toContain("get_day_context");
    expect(actions.domainTools).not.toContain("compose_family_meal");
  });

  it("adds meal completion when plan active", () => {
    const state = createInitialState({
      sessionId: "s",
      householdId: "h",
      dinerIds: ["mem-admin"]
    });
    state.activePlanId = "plan-1";
    state.activePlanVersion = 1;
    const task = createEmptyTaskState();
    task.workflowStage = "plan_ready";
    const actions = computeAvailableActions(state, task, "ACTION_ALLOWED");
    expect(actions.domainTools).toContain("preview_meal_completion");
    expect(actions.domainTools).toContain("preview_caregiver_task");
  });

  it("transitions on finalize success", () => {
    const next = applyTaskTransition(createEmptyTaskState(), {
      type: "tool_succeeded",
      tool: "finalize_meal_plan",
      clearFocus: true
    });
    expect(next.status).toBe("active");
    expect(next.pendingActionId).toBeNull();
  });

  it("ends a preview turn without completing the confirmation-gated task", () => {
    let task = applyTaskTransition(createEmptyTaskState(), {
      type: "tool_succeeded",
      tool: "preview_inventory_change",
      pendingActionId: "pending-1",
      pendingActionType: "inventory_restock"
    });

    task = applyTaskTransition(task, { type: "turn_finished" });
    expect(task.status).toBe("waiting_confirmation");
    expect(task.workflowStage).toBe("awaiting_confirm");
    expect(task.pendingActionId).toBe("pending-1");
    expect(task.pendingActionType).toBe("inventory_restock");

    const guardedFinish = applyTaskTransition(task, { type: "finish" });
    expect(guardedFinish.status).toBe("waiting_confirmation");
    expect(guardedFinish.workflowStage).toBe("awaiting_confirm");
  });

  it("opens safe entry tools after a blocked planning lifecycle", () => {
    const state = createInitialState({
      sessionId: "s",
      householdId: "h",
      dinerIds: ["mem-admin"]
    });
    const blocked = {
      ...createEmptyTaskState(),
      objective: "revise_meal" as const,
      status: "blocked" as const,
      workflowStage: "candidates" as const,
      candidateSetId: "old-candidates",
      lastDomainFailureCode: "NO_FEASIBLE_PLAN"
    };
    const nextTurn = beginUserTurnTaskState(blocked);
    const actions = computeAvailableActions(state, nextTurn, "ACTION_ALLOWED");

    expect(nextTurn).toMatchObject({
      objective: null,
      status: "active",
      workflowStage: "candidates",
      candidateSetId: "old-candidates",
      lastDomainFailureCode: null
    });
    expect(actions.domainTools).toContain("retrieve_local_knowledge");
    expect(actions.domainTools).toContain("find_dish_candidates");
  });

  it("clears transient planning refs only when a new objective is chosen", () => {
    const planning = {
      ...createEmptyTaskState(),
      objective: null,
      workflowStage: "candidates" as const,
      candidateSetId: "old-candidates",
      candidateSetVersion: "old-version",
      lastDomainFailureCode: "NO_FEASIBLE_PLAN"
    };
    const next = applyTaskTransition(planning, {
      type: "replace_objective",
      objective: "retrieve_guidance"
    });
    expect(next).toMatchObject({
      objective: "retrieve_guidance",
      workflowStage: "idle",
      candidateSetId: null,
      candidateSetVersion: null,
      lastDomainFailureCode: null
    });

    const waiting = applyTaskTransition(createEmptyTaskState(), {
      type: "tool_succeeded",
      tool: "preview_inventory_change",
      pendingActionId: "pending-action",
      pendingActionType: "inventory_restock"
    });
    expect(
      applyTaskTransition(waiting, {
        type: "replace_objective",
        objective: "retrieve_guidance"
      })
    ).toEqual(waiting);
  });

  it("projects the next planning tool after same-turn successes", () => {
    const state = createInitialState({
      sessionId: "same-turn-planning",
      householdId: "h",
      dinerIds: ["mem-admin"]
    });
    let task = applyTaskTransition(createEmptyTaskState(), {
      type: "set_objective",
      objective: "revise_meal"
    });
    const context: TurnToolResult = {
      tool: "get_day_context",
      ok: true,
      data: { serviceDate: "2026-08-03" }
    };
    const candidates: TurnToolResult = {
      tool: "find_dish_candidates",
      ok: true,
      data: {
        candidateSetId: "cset-1",
        versionStamp: { household: 1 },
        candidates: []
      }
    };

    task = applyTaskTransition(task, {
      type: "tool_succeeded",
      tool: "get_day_context",
      data: context.data ?? undefined
    });
    expect(
      computeAvailableActions(state, task, "ACTION_ALLOWED", [context])
        .domainTools
    ).toEqual(["find_dish_candidates"]);

    task = applyTaskTransition(task, {
      type: "tool_succeeded",
      tool: "find_dish_candidates",
      data: candidates.data ?? undefined,
      candidateSetId: "cset-1"
    });
    expect(
      computeAvailableActions(state, task, "ACTION_ALLOWED", [
        context,
        candidates
      ]).domainTools
    ).toEqual(["finalize_meal_plan"]);
  });

  it("keeps finalize for nutrition recovery and reopens context for stale candidates", () => {
    const state = createInitialState({
      sessionId: "same-turn-recovery",
      householdId: "h",
      dinerIds: ["mem-admin"]
    });
    let task = applyTaskTransition(createEmptyTaskState(), {
      type: "set_objective",
      objective: "compose_meal"
    });
    task = applyTaskTransition(task, {
      type: "tool_succeeded",
      tool: "get_day_context",
      data: { serviceDate: "2026-08-03" }
    });
    task = applyTaskTransition(task, {
      type: "tool_succeeded",
      tool: "find_dish_candidates",
      data: {
        candidateSetId: "cset-1",
        versionStamp: { household: 1 },
        candidates: []
      }
    });

    const nutritionFailure: TurnToolResult = {
      tool: "finalize_meal_plan",
      ok: false,
      code: "NUTRITION_GUARDRAIL",
      data: {
        status: "failed",
        code: "NUTRITION_GUARDRAIL",
        details: { reselectAllowed: true }
      }
    };
    expect(
      computeAvailableActions(state, task, "ACTION_ALLOWED", [nutritionFailure])
        .domainTools
    ).toEqual(["finalize_meal_plan"]);

    const staleFailure: TurnToolResult = {
      tool: "finalize_meal_plan",
      ok: false,
      code: "STALE_CANDIDATE_SET",
      data: { status: "failed", code: "STALE_CANDIDATE_SET" }
    };
    expect(
      computeAvailableActions(state, task, "ACTION_ALLOWED", [staleFailure])
        .domainTools
    ).toEqual(["get_day_context"]);

    const refreshedContext: TurnToolResult = {
      tool: "get_day_context",
      ok: true,
      data: { serviceDate: "2026-08-03" }
    };
    expect(
      computeAvailableActions(state, task, "ACTION_ALLOWED", [
        staleFailure,
        refreshedContext
      ]).domainTools
    ).toEqual(["find_dish_candidates"]);
  });

  it("moves from successful retrieval to caregiver preview without retrieval again", () => {
    const state = createInitialState({
      sessionId: "same-turn-rag",
      householdId: "h",
      dinerIds: ["mem-admin"]
    });
    state.activePlanId = "plan-1";
    const task = {
      ...createEmptyTaskState(),
      objective: "retrieve_guidance" as const,
      workflowStage: "plan_ready" as const
    };
    const retrieval: TurnToolResult = {
      tool: "retrieve_local_knowledge",
      ok: true,
      data: { hits: [{ sourcePath: "rules.md" }] }
    };

    const actions = computeAvailableActions(
      state,
      task,
      "ACTION_ALLOWED",
      [retrieval]
    );
    expect(actions.domainTools).toEqual(["preview_caregiver_task"]);
    expect(actions.domainTools).not.toContain("retrieve_local_knowledge");
  });
});
