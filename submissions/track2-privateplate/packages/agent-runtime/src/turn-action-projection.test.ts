import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { PrivatePlateDomain } from "@privateplate/domain";
import { PrivatePlateAgent } from "./graph.js";
import type {
  AgentModelProvider,
  ModelRouteDecision,
  ModelRouteInput
} from "./model/provider.js";
import type { AgentGoal } from "./contracts.js";
import { toolFailure } from "./tools/types.js";

type Candidate = {
  templateId: string;
  role: string;
};

function toolDecision(
  tool: Extract<ModelRouteDecision, { kind: "tool" }>['tool'],
  goal: AgentGoal,
  args: Record<string, unknown>,
  model: string
): Extract<ModelRouteDecision, { kind: "tool" }> {
  return {
    kind: "tool",
    goal,
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
    model,
    format_retry_count: 0,
    format_retry_reasons: []
  };
}

function finalDecision(
  goal: Exclude<AgentGoal, "unsupported">,
  message: string,
  model: string
): Extract<ModelRouteDecision, { kind: "final" }> {
  return {
    kind: "final",
    goal,
    message,
    reasonCode: null,
    transport: "native_function",
    model,
    privacy_violation: false,
    format_retry_count: 0,
    format_retry_reasons: []
  };
}

function chooseDishes(
  data: Record<string, unknown> | null | undefined,
  useLastCandidate: boolean
) {
  const candidates = Array.isArray(data?.candidates)
    ? (data.candidates as Candidate[])
    : [];
  const preferred = useLastCandidate
    ? {
        shared_main: "tpl-steamed-fish",
        shared_side: "tpl-shiitake-egg",
        staple: "tpl-leftover-rice"
      }
    : {
        shared_main: "tpl-potato-chicken",
        shared_side: "tpl-garlic-spinach",
        staple: "tpl-leftover-rice"
      };
  const selected = (["shared_main", "shared_side", "staple"] as const)
    .map((role) => {
      return (
        candidates.find(
          (candidate) => candidate.templateId === preferred[role]
        ) ?? candidates.find((candidate) => candidate.role === role)
      );
    })
    .filter((candidate): candidate is Candidate => Boolean(candidate));
  return selected.map((candidate) => ({
    templateId: candidate.templateId,
    relativePortion: "standard" as const
  }));
}

function finalizeDecisionFromCandidates(
  input: ModelRouteInput,
  goal: AgentGoal,
  useLastCandidate: boolean,
  model: string
) {
  const candidateResult = input.currentTurn.toolResults
    .slice()
    .reverse()
    .find((result) => result.tool === "find_dish_candidates");
  const args = {
    dinerIds: input.state.dinerIds,
    mealType: "lunch",
    candidateSetId: String(candidateResult?.data?.candidateSetId),
    selectedDishes: chooseDishes(candidateResult?.data, useLastCandidate),
    mealPortionScale: 1.0,
    selectionReason: "根据当前候选集提交完整菜单。"
  };
  return toolDecision("finalize_meal_plan", goal, args, model);
}

class RevisionProjectionProvider implements AgentModelProvider {
  readonly mode = "scripted_mock" as const;
  readonly model = "revision-projection-provider";
  readonly availableActionsAfterCandidates: string[] = [];
  revisionFindArguments: Record<string, unknown> | null = null;
  revisionSelections: Record<string, unknown>[] = [];
  private userTurn = -1;

  async route(input: ModelRouteInput): Promise<ModelRouteDecision> {
    if (input.currentTurn.decisionIndex === 0) this.userTurn += 1;
    const isRevision = this.userTurn === 1;
    const goal: AgentGoal = isRevision ? "revise_meal" : "compose_meal";
    const last = input.currentTurn.toolResults.at(-1);

    if (!last) {
      return toolDecision("get_day_context", goal, {
        dinerIds: input.state.dinerIds
      }, this.model);
    }
    if (last.tool === "get_day_context") {
      const args = {
        dinerIds: input.state.dinerIds,
        rejectedFoodIds: isRevision ? ["food-chicken-leg"] : [],
        rejectedTemplateIds: []
      };
      if (isRevision) this.revisionFindArguments = args;
      return toolDecision("find_dish_candidates", goal, args, this.model);
    }
    if (last.tool === "find_dish_candidates") {
      if (isRevision) {
        this.availableActionsAfterCandidates.push(
          ...(input.availableActions?.domainTools ?? [])
        );
      }
      const failedAttempts = input.currentTurn.toolResults.filter(
        (result) =>
          result.tool === "finalize_meal_plan" &&
          result.data?.status !== "ok" &&
          result.data?.status !== "valid"
      ).length;
      return finalizeDecisionFromCandidates(
        input,
        goal,
        isRevision || failedAttempts > 0,
        this.model
      );
    }
    if (last.tool === "finalize_meal_plan") {
      if (last.data?.status !== "ok" && last.data?.status !== "valid") {
        return finalizeDecisionFromCandidates(input, goal, true, this.model);
      }
      const selected = last.data?.plan;
      if (isRevision && selected && typeof selected === "object") {
        this.revisionSelections.push(
          (input.currentTurn.toolResults.at(-1)?.data ?? {}) as Record<
            string,
            unknown
          >
        );
      }
      return finalDecision(goal, "计划已生成，确认后才会执行。", this.model);
    }
    return finalDecision(goal, "本轮已完成。", this.model);
  }
}

class HandoffProjectionProvider implements AgentModelProvider {
  readonly mode = "scripted_mock" as const;
  readonly model = "handoff-projection-provider";
  readonly availableActionsAfterRetrieval: string[] = [];
  private userTurn = -1;

  async route(input: ModelRouteInput): Promise<ModelRouteDecision> {
    if (input.currentTurn.decisionIndex === 0) this.userTurn += 1;
    const last = input.currentTurn.toolResults.at(-1);

    if (this.userTurn === 0) {
      if (!last) {
        return toolDecision("get_day_context", "compose_meal", {
          dinerIds: input.state.dinerIds
        }, this.model);
      }
      if (last.tool === "get_day_context") {
        return toolDecision("find_dish_candidates", "compose_meal", {
          dinerIds: input.state.dinerIds,
          rejectedFoodIds: [],
          rejectedTemplateIds: []
        }, this.model);
      }
      if (last.tool === "find_dish_candidates") {
        return finalizeDecisionFromCandidates(input, "compose_meal", false, this.model);
      }
      return finalDecision("compose_meal", "计划已生成，确认后才会执行。", this.model);
    }

    if (!last && input.state.hasPendingAction) {
      return this.previewDecision(input);
    }
    if (!last) {
      return toolDecision("retrieve_local_knowledge", "retrieve_guidance", {
        query: "本地晚餐准备规则",
        topK: 3
      }, this.model);
    }
    if (last.tool === "retrieve_local_knowledge") {
      this.availableActionsAfterRetrieval.push(
        ...(input.availableActions?.domainTools ?? [])
      );
      return this.previewDecision(input);
    }
    return finalDecision(
      "preview_handoff",
      "任务卡预览已生成，确认前不会发送。",
      this.model
    );
  }

  private previewDecision(input: ModelRouteInput) {
    const recipient = input.requestContext?.handoffRecipient;
    const recipientLabel = recipient?.status === "ok" ? recipient.value : "保姆";
    return toolDecision("preview_caregiver_task", "preview_handoff", {
      recipientLabel,
      serveAt: "unspecified"
    }, this.model);
  }
}

describe("same-turn available action projection", () => {
  let domain: PrivatePlateDomain;

  beforeEach(async () => {
    domain = await PrivatePlateDomain.create(":memory:");
  });

  afterEach(() => domain.close());

  it("lets a revision submit a real new plan after candidate lookup", async () => {
    const provider = new RevisionProjectionProvider();
    const agent = new PrivatePlateAgent(domain, "projection-revision", provider);

    const initial = await agent.handleUserMessage("规划一顿午餐");
    const firstPlanId = agent.state.activePlanId;
    expect(initial.validationOk).toBe(true);
    expect(firstPlanId).toBeTruthy();

    const revised = await agent.handleUserMessage("排除一种食材后重新规划");
    expect(provider.revisionFindArguments?.rejectedFoodIds).toEqual([
      "food-chicken-leg"
    ]);
    expect(provider.availableActionsAfterCandidates).toContain(
      "finalize_meal_plan"
    );
    expect(provider.availableActionsAfterCandidates).not.toContain(
      "find_dish_candidates"
    );
    expect(revised.validationOk).toBe(true);
    expect(
      revised.taskOutcome.evidence.filter(
        (evidence) => evidence.kind === "deterministic_fallback"
      )
    ).toHaveLength(0);

    const secondPlanId = agent.state.activePlanId;
    expect(secondPlanId).toBeTruthy();
    expect(secondPlanId).not.toBe(firstPlanId);
    const firstPlan = domain.getPlanById(firstPlanId!);
    const secondPlan = domain.getPlanById(secondPlanId!);
    expect(firstPlan?.status).toBe("superseded");
    expect(secondPlan).toMatchObject({
      version: 2,
      parentPlanId: firstPlanId,
      status: "valid"
    });
    expect(secondPlan?.selectionTrace.agentSelection?.selectedDishes).not.toEqual(
      firstPlan?.selectionTrace.agentSelection?.selectedDishes
    );

    const finalStep = revised.modelSteps
      .slice()
      .reverse()
      .find(
        (step) =>
          step.decision === "tool" && step.tool === "finalize_meal_plan"
      );
    expect(finalStep?.rawArguments?.selectedDishes).toEqual(
      secondPlan?.selectionTrace.agentSelection?.selectedDishes
    );
    expect(finalStep?.effectiveArguments?.selectedDishes).toEqual(
      secondPlan?.selectionTrace.agentSelection?.selectedDishes
    );
  });

  it("moves from real retrieval to preview and replaces an unconfirmed card", async () => {
    const provider = new HandoffProjectionProvider();
    const agent = new PrivatePlateAgent(domain, "projection-handoff", provider);

    await agent.handleUserMessage("规划一顿午餐");
    const firstPreview = await agent.handleUserMessage(
      "查本地晚餐规则并生成给保姆的任务卡，先不要发送"
    );
    expect(firstPreview.toolTrace).toEqual([
      expect.objectContaining({ tool: "retrieve_local_knowledge", ok: true }),
      expect.objectContaining({ tool: "preview_caregiver_task", ok: true })
    ]);
    expect(provider.availableActionsAfterRetrieval).toContain(
      "preview_caregiver_task"
    );
    expect(provider.availableActionsAfterRetrieval).not.toContain(
      "retrieve_local_knowledge"
    );
    expect(agent.getTaskState().status).toBe("waiting_confirmation");
    expect(
      domain.db.prepare("SELECT COUNT(*) AS count FROM caregiver_tasks").get()
    ).toMatchObject({ count: 0 });

    const oldPendingId = firstPreview.uiOnly?.pendingActionId;
    if (!oldPendingId) throw new Error("expected a pending caregiver preview");
    const corrected = await agent.handleUserMessage(
      "收件人改成阿姨，确认前不要发送"
    );
    expect(corrected.toolTrace).toContainEqual(
      expect.objectContaining({ tool: "preview_caregiver_task", ok: true })
    );
    expect(corrected.uiOnly?.taskCard?.recipientLabel).toBe("阿姨");
    expect(JSON.stringify(corrected.uiOnly?.taskCard)).not.toMatch(
      /糖尿病|高血压|token|confirmation/i
    );
    expect(
      domain.db.prepare("SELECT COUNT(*) AS count FROM caregiver_tasks").get()
    ).toMatchObject({ count: 0 });
    expect(
      domain.db
        .prepare("SELECT status FROM pending_actions WHERE id = ?")
        .get(oldPendingId)
    ).toMatchObject({ status: "cancelled" });
    expect(agent.getTaskState().status).toBe("waiting_confirmation");
  });

  it("keeps the current pending card when its replacement preview fails", async () => {
    const provider = new HandoffProjectionProvider();
    const agent = new PrivatePlateAgent(
      domain,
      "projection-handoff-failed-replacement",
      provider
    );

    await agent.handleUserMessage("规划一顿午餐");
    const firstPreview = await agent.handleUserMessage(
      "查本地晚餐规则并生成给保姆的任务卡，先不要发送"
    );
    const oldPendingId = firstPreview.uiOnly?.pendingActionId;
    if (!oldPendingId) throw new Error("expected a pending caregiver preview");

    const invoke = agent.gateway.invoke.bind(agent.gateway);
    agent.gateway.invoke = async (state, tool, args, source, available) => {
      if (tool !== "preview_caregiver_task") {
        return invoke(state, tool, args, source, available);
      }
      return {
        result: toolFailure(
          tool,
          "INTERNAL_ERROR",
          "新任务卡预览失败。",
          "failed-replacement-preview"
        ),
        statePatch: {
          lastToolStatus: "failure",
          errorCode: "INTERNAL_ERROR"
        },
        durationMs: 0
      };
    };

    await agent.handleUserMessage("收件人改成阿姨，确认前不要发送");

    expect(agent.state.pendingActionId).toBe(oldPendingId);
    expect(agent.getTaskState()).toMatchObject({
      status: "waiting_confirmation",
      pendingActionId: oldPendingId
    });
    expect(
      domain.db
        .prepare("SELECT status FROM pending_actions WHERE id = ?")
        .get(oldPendingId)
    ).toMatchObject({ status: "pending" });
  });
});
