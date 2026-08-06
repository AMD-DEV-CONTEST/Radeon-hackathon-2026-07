import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { PrivatePlateDomain } from "@privateplate/domain";
import { PrivatePlateAgent } from "./graph.js";
import type {
  AgentModelProvider,
  ModelRouteDecision,
  ModelRouteInput
} from "./model/provider.js";
import { toolSuccess } from "./tools/types.js";

class RecoveryProvider implements AgentModelProvider {
  readonly mode = "scripted_mock" as const;
  readonly model = "recovery-test-provider";

  constructor(private readonly succeedOnThirdAttempt: boolean) {}

  async route(input: ModelRouteInput): Promise<ModelRouteDecision> {
    const last = input.currentTurn.toolResults.at(-1);
    if (!last) {
      return toolDecision("get_day_context", {
        dinerIds: input.state.dinerIds
      });
    }
    if (last.tool === "get_day_context") {
      return toolDecision("find_dish_candidates", {
        dinerIds: input.state.dinerIds,
        rejectedFoodIds: [],
        rejectedTemplateIds: []
      });
    }
    if (last.tool === "find_dish_candidates") {
      return finalizeDecision(input, 0);
    }
    if (last.tool === "finalize_meal_plan") {
      if (last.data?.status === "ok" || last.data?.status === "valid") {
        return {
          kind: "final",
          goal: "compose_meal",
          message: "计划已生成，确认后才会执行。",
          reasonCode: null,
          transport: "native_function",
          model: this.model,
          privacy_violation: false,
          format_retry_count: 0,
          format_retry_reasons: []
        };
      }
      const failedAttempts = input.currentTurn.toolResults.filter(
        (result) =>
          result.tool === "finalize_meal_plan" &&
          result.data?.status !== "ok" &&
          result.data?.status !== "valid"
      ).length;
      return finalizeDecision(input, failedAttempts);
    }
    return finalizeDecision(input, 0);
  }

  shouldSucceed(attempt: number): boolean {
    return this.succeedOnThirdAttempt && attempt >= 2;
  }
}

class ContentFinalRecoveryProvider extends RecoveryProvider {
  async route(input: ModelRouteInput): Promise<ModelRouteDecision> {
    const decision = await super.route(input);
    if (decision.kind === "final") {
      return {
        ...decision,
        transport: "content_final",
        message: "计划已生成，确认后才会执行。"
      };
    }
    return decision;
  }
}

function toolDecision(
  tool: "get_day_context" | "find_dish_candidates",
  args: Record<string, unknown>
): Extract<ModelRouteDecision, { kind: "tool" }> {
  return {
    kind: "tool",
    goal: "compose_meal",
    tool,
    arguments: args,
    raw_model_arguments: args,
    normalized_model_arguments: args,
    effective_arguments: args,
    policy: {
      status: "ok",
      effective: args,
      privacy_violation: false,
      reasons: []
    },
    privacy_violation: false,
    model: "recovery-test-provider",
    format_retry_count: 0,
    format_retry_reasons: []
  };
}

function finalizeDecision(
  input: ModelRouteInput,
  attempt: number
): ModelRouteDecision {
  const candidateResult = [...input.currentTurn.toolResults]
    .reverse()
    .find((result) => result.tool === "find_dish_candidates");
  const candidates = Array.isArray(candidateResult?.data?.candidates)
    ? (candidateResult.data.candidates as Array<{
        templateId: string;
      }>)
    : [];
  const selected = candidates
    .slice(0, Math.min(candidates.length, attempt + 1))
    .map((candidate) => ({
      templateId: candidate.templateId,
      relativePortion: "standard"
    }));
  return {
    ...toolDecision("find_dish_candidates", {}),
    tool: "finalize_meal_plan",
    arguments: {
      dinerIds: input.state.dinerIds,
      mealType: "lunch",
      candidateSetId: String(candidateResult?.data?.candidateSetId),
      selectedDishes: selected,
      mealPortionScale: 1.0,
      selectionReason: `第 ${attempt + 1} 次候选选择`
    },
    raw_model_arguments: {
      dinerIds: input.state.dinerIds,
      mealType: "lunch",
      candidateSetId: String(candidateResult?.data?.candidateSetId),
      selectedDishes: selected,
      mealPortionScale: 1.0,
      selectionReason: `第 ${attempt + 1} 次候选选择`
    },
    normalized_model_arguments: {
      dinerIds: input.state.dinerIds,
      mealType: "lunch",
      candidateSetId: String(candidateResult?.data?.candidateSetId),
      selectedDishes: selected,
      mealPortionScale: 1.0,
      selectionReason: `第 ${attempt + 1} 次候选选择`
    },
    effective_arguments: {
      dinerIds: input.state.dinerIds,
      mealType: "lunch",
      candidateSetId: String(candidateResult?.data?.candidateSetId),
      selectedDishes: selected,
      mealPortionScale: 1.0,
      selectionReason: `第 ${attempt + 1} 次候选选择`
    }
  };
}

function attachPlanningGateway(
  agent: PrivatePlateAgent,
  domain: PrivatePlateDomain,
  provider: RecoveryProvider
): { finalizeCalls: () => number } {
  let finalizeCalls = 0;
  const templates = domain.getMealContext({ dinerIds: agent.state.dinerIds }).templates;
  agent.gateway.invoke = async (state, tool, args) => {
    if (tool === "get_day_context") {
      return {
        result: toolSuccess(
          "get_day_context",
          { serviceDate: "2026-08-03" },
          "test-context"
        ),
        statePatch: {
          lastToolStatus: "success",
          errorCode: null,
          toolSteps: state.toolSteps + 1
        },
        durationMs: 0
      };
    }
    if (tool === "find_dish_candidates") {
      return {
        result: toolSuccess(
          "find_dish_candidates",
          {
            candidateSetId: "cset-recovery-test",
            candidates: templates.map((template, index) => ({
              templateId: template.id,
              name: template.name,
              role: index === 0 ? "shared_main" : "shared_side"
            }))
          },
          "test-candidates"
        ),
        statePatch: {
          lastToolStatus: "success",
          errorCode: null,
          toolSteps: state.toolSteps + 1
        },
        durationMs: 0
      };
    }

    if (tool === "finalize_meal_plan") {
      finalizeCalls += 1;
      const selectedDishes = Array.isArray(args.selectedDishes)
        ? (args.selectedDishes as Array<{ templateId: string }>)
        : [];
      if (!provider.shouldSucceed(finalizeCalls - 1)) {
        return {
          result: toolSuccess(
            "finalize_meal_plan",
            {
              status: "failed",
              code: "NUTRITION_GUARDRAIL",
              details: {
                deficits: [
                  {
                    memberId: state.dinerIds[0],
                    nutrient: "energyKcal",
                    actual: 99,
                    min: 100,
                    max: 720,
                    deficit: 1,
                    reselectAllowed: true
                  }
                ],
                reselectAllowed: true
              }
            },
            "test-finalize-failed"
          ),
          statePatch: {
            lastToolStatus: "success",
            errorCode: "NUTRITION_GUARDRAIL",
            toolSteps: state.toolSteps + 1
          },
          durationMs: 0
        };
      }
      const menu = selectedDishes.map((dish) => ({
        templateId: dish.templateId,
        name:
          templates.find((template) => template.id === dish.templateId)
            ?.name ?? dish.templateId
      }));
      return {
        result: toolSuccess(
          "finalize_meal_plan",
          {
            status: "ok",
            plan: {
              id: "plan-recovery-test",
              version: 1,
              status: "valid",
              dinerIds: state.dinerIds,
              menu
            },
            shoppingGap: []
          },
          "test-finalize-success"
        ),
        statePatch: {
          lastToolStatus: "success",
          errorCode: null,
          toolSteps: state.toolSteps + 1,
          phase: "PRESENTING_PLAN",
          activePlanId: "plan-recovery-test",
          activePlanVersion: 1
        },
        durationMs: 0
      };
    }
    throw new Error(`Unexpected test tool: ${tool}`);
  };
  return { finalizeCalls: () => finalizeCalls };
}

describe("bounded finalize recovery", () => {
  let domain: PrivatePlateDomain;

  beforeEach(async () => {
    domain = await PrivatePlateDomain.create(":memory:");
  });

  afterEach(() => domain.close());

  it("executes a genuinely changed third selection", async () => {
    const provider = new RecoveryProvider(true);
    const agent = new PrivatePlateAgent(domain, "recovery-success", provider);
    const counters = attachPlanningGateway(agent, domain, provider);

    const turn = await agent.handleUserMessage("开始规划午餐");
    const finalizes = turn.modelSteps.filter(
      (step) => step.decision === "tool" && step.tool === "finalize_meal_plan"
    );

    expect(counters.finalizeCalls()).toBe(3);
    expect(finalizes).toHaveLength(3);
    expect(finalizes[2]?.effectiveArguments?.selectedDishes).not.toEqual(
      finalizes[1]?.effectiveArguments?.selectedDishes
    );
    expect(agent.state.activePlanId).toBe("plan-recovery-test");
    expect(turn.taskOutcome.reasons).not.toContain("plan_retry_limit_reached");
  });

  it("stops safely after three failed finalize attempts", async () => {
    const provider = new RecoveryProvider(false);
    const agent = new PrivatePlateAgent(domain, "recovery-stop", provider);
    const counters = attachPlanningGateway(agent, domain, provider);

    const turn = await agent.handleUserMessage("开始规划午餐");
    expect(counters.finalizeCalls()).toBe(3);
    expect(turn.answer).toContain("NO_FEASIBLE_PLAN");
    expect(turn.phase).toBe("PRESENTING_INFEASIBLE");
    expect(agent.state.errorCode).toBe("NO_FEASIBLE_PLAN");
    expect(turn.taskOutcome.reasons).toContain("plan_retry_limit_reached");
    expect(turn.taskOutcome.reasons).toContain("NO_FEASIBLE_PLAN");
    expect(turn.taskOutcome.status).toBe("BLOCKED");
    expect(agent.state.activePlanId).toBeNull();
  });

  it("preserves the current plan state when every replacement is rejected", async () => {
    const provider = new RecoveryProvider(false);
    const agent = new PrivatePlateAgent(
      domain,
      "recovery-preserve-current-plan",
      provider
    );
    agent.state = {
      ...agent.state,
      phase: "PRESENTING_PLAN",
      mealSessionId: "meal-existing",
      activePlanId: "plan-existing",
      activePlanVersion: 3,
      activeConstraintIds: ["constraint-existing"],
      rejectedFoodIds: ["food-beef"],
      rejectedTemplateIds: ["tpl-existing-rejected"],
      requestedPriorityFoodIds: ["food-tofu"],
      preferLowEffort: true
    };
    attachPlanningGateway(agent, domain, provider);

    const turn = await agent.handleUserMessage("重新规划午餐");

    expect(turn.taskOutcome.reasons).toContain("plan_retry_limit_reached");
    expect(turn.taskOutcome.reasons).toContain("NO_FEASIBLE_PLAN");
    expect(turn.phase).toBe("PRESENTING_INFEASIBLE");
    expect(agent.state).toMatchObject({
      activePlanId: "plan-existing",
      activePlanVersion: 3,
      activeConstraintIds: ["constraint-existing"],
      rejectedFoodIds: ["food-beef"],
      rejectedTemplateIds: ["tpl-existing-rejected"],
      requestedPriorityFoodIds: ["food-tofu"],
      preferLowEffort: true,
      errorCode: "NO_FEASIBLE_PLAN"
    });
  });

  it("records content_final only for the final answer after a successful tool", async () => {
    const provider = new ContentFinalRecoveryProvider(true);
    const agent = new PrivatePlateAgent(domain, "recovery-content-final", provider);
    attachPlanningGateway(agent, domain, provider);

    const turn = await agent.handleUserMessage("开始规划午餐");
    const finalStep = turn.modelSteps.find((step) => step.decision === "final");

    expect(turn.validationOk).toBe(true);
    expect(finalStep).toMatchObject({
      transport: "content_final",
      tool: null
    });
    expect(turn.modelTrace).toMatchObject({
      decisionKind: "final",
      transport: "content_final"
    });
    expect(
      turn.modelSteps.some(
        (step) => step.transport === "content_final" && step.decision === "tool"
      )
    ).toBe(false);
  });
});
