/**
 * Behavior coverage: workflow, goal inference, finalize reselect, checkpoint,
 * and layered L1–L5 structured assertions (structure, not live model).
 */
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { PrivatePlateDomain } from "@privateplate/domain";
import {
  applyTaskTransition,
  computeAvailableActions,
  createEmptyTaskState
} from "./task-state.js";
import { createInitialState } from "./state.js";
import {
  buildCheckpointV2,
  parseCheckpointPayload
} from "./checkpoint-v2.js";
import { resolveLoopTransition } from "./loop-mode.js";
import { PRIVATEPLATE_MODEL_TOOLS } from "./model/tool-definitions.js";
import { PrivatePlateAgent } from "./graph.js";
import { ScriptedProductProvider } from "./model/scripted-provider.js";

function pickBalanced(
  candidates: { candidates: Array<{ role: string; templateId: string }> }
) {
  const preferred = {
    shared_main: "tpl-potato-chicken",
    shared_side: "tpl-garlic-spinach",
    staple: "tpl-leftover-rice"
  } as const;
  return (["shared_main", "shared_side", "staple"] as const)
    .map(
      (role) =>
        candidates.candidates.find((c) => c.templateId === preferred[role])?.templateId ??
        candidates.candidates.find((c) => c.role === role)?.templateId
    )
    .filter(Boolean)
    .map((templateId) => ({
      templateId: templateId!,
      relativePortion: "standard" as const
    }));
}

describe("behavior coverage v2", () => {
  let domain: PrivatePlateDomain;

  beforeAll(async () => {
    domain = await PrivatePlateDomain.create(":memory:");
  });

  afterAll(() => domain.close());

  it("model tool schemas expose optional semantic goals", () => {
    const getContext = PRIVATEPLATE_MODEL_TOOLS.find(
      (t) => t.function.name === "get_day_context"
    );
    const inventory = PRIVATEPLATE_MODEL_TOOLS.find(
      (t) => t.function.name === "preview_inventory_change"
    );
    expect(getContext?.function.parameters.properties).toHaveProperty(
      "serviceDate"
    );
    const getGoal = getContext?.function.parameters.properties.goal as
      | { enum?: string[] }
      | undefined;
    const inventoryGoal = inventory?.function.parameters.properties.goal as
      | { enum?: string[] }
      | undefined;
    expect(getGoal?.enum).toContain("inspect_context");
    expect(inventoryGoal?.enum).toContain("update_inventory");
    for (const t of PRIVATEPLATE_MODEL_TOOLS) {
      expect(t.function.parameters.required).not.toContain("goal");
    }
  });

  it("first plan objective is compose not revise when no active plan", () => {
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
    // Stage gate: only get_day_context
    const actions = computeAvailableActions(agent, task, "ACTION_ALLOWED");
    expect(actions.domainTools).toEqual(["get_day_context"]);
  });

  it("finalize domain reject stays ACTION_ALLOWED for reselect", () => {
    const transition = resolveLoopTransition({
      goal: "compose_meal",
      tool: "finalize_meal_plan",
      result: {
        ok: true,
        tool: "finalize_meal_plan",
        data: {
          status: "failed",
          code: "NUTRITION_GUARDRAIL",
          details: { reselectAllowed: true, deficits: [{ deficit: 40 }] }
        },
        auditRef: "t"
      } as never
    });
    expect(transition.mode).toBe("ACTION_ALLOWED");
    expect(transition.reason).toBe("finalize_failed_reselect");
  });

  it("rejected food does not reappear in candidates", () => {
    const open = domain.findDishCandidates({
      dinerIds: ["mem-admin", "mem-father", "mem-mother"]
    });
    const hadChicken = open.candidates.some((c) =>
      c.ingredients.some((i) => i.foodId === "food-chicken-leg")
    );
    // Seed may or may not include chicken dishes; if present, reject filters it.
    const filtered = domain.findDishCandidates({
      dinerIds: ["mem-admin", "mem-father", "mem-mother"],
      rejectedFoodIds: ["food-chicken-leg"]
    });
    expect(
      filtered.candidates.some((c) =>
        c.ingredients.some((i) => i.foodId === "food-chicken-leg")
      )
    ).toBe(false);
    if (hadChicken) {
      expect(filtered.candidates.length).toBeLessThan(open.candidates.length);
    }
  });

  it("revision version+1 supersedes parent only after success", () => {
    const diners = ["mem-admin", "mem-father", "mem-mother"];
    const c1 = domain.findDishCandidates({ dinerIds: diners });
    const first = domain.finalizeMealPlan({
      sessionId: "cov-rev",
      dinerIds: diners,
      mealType: "lunch",
      candidateSetId: c1.candidateSetId,
      selectedDishes: pickBalanced(c1),
      mealPortionScale: 1.0,
      selectionReason: "v1"
    });
    expect(first.status).toBe("ok");
    if (first.status !== "ok") return;
    expect(first.plan.version).toBe(1);

    const c2 = domain.findDishCandidates({ dinerIds: diners });
    const second = domain.finalizeMealPlan({
      sessionId: "cov-rev",
      dinerIds: diners,
      mealType: "lunch",
      candidateSetId: c2.candidateSetId,
      selectedDishes: pickBalanced(c2),
      mealPortionScale: 1.0,
      selectionReason: "v2",
      parentPlan: { id: first.plan.id, version: first.plan.version }
    });
    expect(second.status).toBe("ok");
    if (second.status !== "ok") return;
    expect(second.plan.version).toBe(2);
    expect(domain.getPlanById(first.plan.id)?.status).toBe("superseded");
  });

  it("0.2 份量倍率不会绕过绝对下限", () => {
    const diners = ["mem-admin", "mem-father", "mem-mother"];
    const c = domain.findDishCandidates({ dinerIds: diners });
    const pick = pickBalanced(c);
    const low = domain.finalizeMealPlan({
      sessionId: "cov-low",
      dinerIds: diners,
      mealType: "lunch",
      candidateSetId: c.candidateSetId,
      selectedDishes: pick,
      mealPortionScale: 0.2,
      selectionReason: "low"
    });
    const high = domain.finalizeMealPlan({
      sessionId: "cov-high",
      dinerIds: diners,
      mealType: "lunch",
      candidateSetId: c.candidateSetId,
      selectedDishes: pick,
      mealPortionScale: 1.0,
      selectionReason: "high"
    });
    expect(low.status).toBe("failed");
    expect(high.status).toBe("ok");
    if (low.status !== "failed") return;
    expect(low.details?.mealPortionScale).toBe(0.2);
    expect(low.details?.shareOnlyAdjustmentEffective).toBe(false);
  });

  it("meal completion preview creates pending with token+hash", () => {
    const diners = ["mem-admin", "mem-father", "mem-mother"];
    const c = domain.findDishCandidates({ dinerIds: diners });
    const plan = domain.finalizeMealPlan({
      sessionId: "cov-meal",
      dinerIds: diners,
      mealType: "lunch",
      candidateSetId: c.candidateSetId,
      selectedDishes: pickBalanced(c),
      mealPortionScale: 1.0,
      selectionReason: "p"
    });
    expect(plan.status).toBe("ok");
    if (plan.status !== "ok") return;
    const preview = domain.previewMealCompletion({ planId: plan.plan.id });
    expect(preview.actionType).toBe("meal_completion");
    expect(preview.confirmation.pendingActionId).toMatch(/\w/);
    expect(preview.confirmation.confirmationToken).toMatch(/\w/);
    expect(preview.confirmation.payloadHash).toMatch(/\w/);
  });

  it("checkpoint v2 round-trip restores workflow fields", () => {
    const agentState = createInitialState({
      sessionId: "ckpt-s",
      householdId: "hh",
      dinerIds: ["mem-admin"]
    });
    agentState.activePlanId = "plan-1";
    agentState.activePlanVersion = 2;
    let task = createEmptyTaskState();
    task = applyTaskTransition(task, {
      type: "set_objective",
      objective: "revise_meal"
    });
    task = applyTaskTransition(task, {
      type: "tool_succeeded",
      tool: "get_day_context",
      data: { serviceDate: "2026-08-02" }
    });
    task = applyTaskTransition(task, {
      type: "tool_succeeded",
      tool: "find_dish_candidates",
      data: {
        candidateSetId: "cset-restore",
        versionStamp: { household: 1, inventory: 2, intake: 1, policy: "p1" }
      }
    });
    const ckpt = buildCheckpointV2(agentState, task);
    expect(ckpt.schemaVersion).toBe(2);
    expect(ckpt.taskState.workflowStage).toBe("candidates");
    expect(ckpt.taskState.candidateSetId).toBe("cset-restore");
    expect(ckpt.taskState.serviceDate).toBe("2026-08-02");

    const restored = parseCheckpointPayload(JSON.parse(JSON.stringify(ckpt)));
    expect(restored.fromVersion).toBe(2);
    expect(restored.taskState.workflowStage).toBe("candidates");
    expect(restored.taskState.candidateSetId).toBe("cset-restore");
    expect(restored.taskState.candidateSetVersion).toContain("inventory");
    expect(restored.agentState.activePlanId).toBe("plan-1");
    expect(restored.agentState.activePlanVersion).toBe(2);
  });

  it("scripted agent first plan is not revise and exposes stage pipeline", async () => {
    const agent = new PrivatePlateAgent(
      domain,
      "cov-agent-1",
      new ScriptedProductProvider()
    );
    const turn = await agent.handleUserMessage("规划午餐，不要鸡腿。");
    const tools = (turn.toolTrace ?? []).map((t) => t.tool);
    expect(tools).toContain("finalize_meal_plan");
    expect(tools).not.toContain("compose_family_meal");
    expect(tools).not.toContain("revise_family_meal");
    // No revise objective on first successful plan path.
    const ckpt = agent.exportCheckpoint();
    expect(ckpt.taskState.objective).not.toBe("revise_meal");
    expect(ckpt.agentState.activePlanId).toBeTruthy();
    expect(ckpt.taskState.workflowStage).toBe("plan_ready");
  });

  it("rich-meal request can select multiple dishes in one role", async () => {
    const agent = new PrivatePlateAgent(
      domain,
      "cov-rich-meal",
      new ScriptedProductProvider()
    );
    const turn = await agent.handleUserMessage(
      "规划午餐，丰富一点，多一道蔬菜，三个人一起吃。"
    );
    const plan = domain.getPlanById(agent.state.activePlanId ?? "");
    expect(turn.validationOk).toBe(true);
    expect(plan?.sharedTemplates.length).toBeGreaterThan(3);
    expect(
      plan?.sharedTemplates.filter((item) => item.role === "shared_side").length
    ).toBeGreaterThan(1);
    expect(plan?.selectionTrace.agentSelection?.selectedDishes.length).toBe(
      plan?.sharedTemplates.length
    );
  });

  /**
   * L1–L5 structured layer assertions (protocol tools only; no live LLM).
   * Mirrors layered-diag-2.0 case ids for offline structure coverage.
   */
  it("L1–L5 layered structure: v2 tools and stage gates", async () => {
    const cases = [
      {
        id: "L1-plan-no-chicken",
        text: "规划午餐，不要鸡腿。我们三个人一起吃。",
        expectTools: ["finalize_meal_plan"]
      },
      {
        id: "L2-inspect-day",
        text: "查看今天的家庭额度、库存和成员情况。",
        expectTools: ["get_day_context"]
      },
      {
        id: "L5-restock-tofu",
        text: "刚买了两盒豆腐，帮我记入库。",
        expectTools: ["preview_inventory_change"]
      }
    ] as const;

    for (const c of cases) {
      const agent = new PrivatePlateAgent(
        domain,
        `cov-${c.id}`,
        new ScriptedProductProvider()
      );
      const turn = await agent.handleUserMessage(c.text);
      const executed = (turn.toolTrace ?? [])
        .filter((t) => t.ok)
        .map((t) => t.tool);
      for (const t of c.expectTools) {
        expect(executed, c.id).toContain(t);
      }
      // Layer protocol: never v1 tool names
      expect(executed.some((t) => t.includes("family_meal")), c.id).toBe(false);
      expect(turn.phase).not.toBe("ERROR");
      expect(turn.phase).not.toBe("SAFE_STOP");
    }
  });
});
