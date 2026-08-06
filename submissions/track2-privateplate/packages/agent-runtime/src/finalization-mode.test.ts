import { describe, expect, it } from "vitest";
import { HashEmbeddingClient, PrivatePlateDomain } from "@privateplate/domain";
import { PrivatePlateAgent } from "./graph.js";
import type { AgentGoal } from "./contracts.js";
import type {
  AgentModelProvider,
  ModelRouteDecision,
  ModelRouteInput
} from "./model/provider.js";

type TerminalTarget =
  | "plan"
  | "meal_completion"
  | "caregiver"
  | "inventory"
  | "memory";

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

class TerminalProvider implements AgentModelProvider {
  readonly mode = "scripted_mock" as const;
  readonly model = "terminal-presenter-test-provider";
  calls = 0;
  private userTurn = -1;

  constructor(private readonly target: TerminalTarget) {}

  async route(input: ModelRouteInput): Promise<ModelRouteDecision> {
    this.calls += 1;
    if (input.currentTurn.decisionIndex === 0) this.userTurn += 1;

    const last = input.currentTurn.toolResults.at(-1);
    const requiresPlan =
      this.target === "meal_completion" || this.target === "caregiver";
    if (this.target === "plan" || (requiresPlan && this.userTurn === 0)) {
      return this.planDecision(input, last);
    }

    if (!last) {
      return this.targetDecision(input);
    }
    if (
      this.target === "caregiver" &&
      last.tool === "retrieve_local_knowledge"
    ) {
      return this.targetDecision(input);
    }

    return finalDecision(
      this.target === "caregiver" ? "preview_handoff" : this.goalForTarget(),
      this.target === "caregiver"
        ? "任务卡预览已生成，尚未发送。"
        : "本轮预览已生成，确认前不会写入。",
      this.model
    );
  }

  private planDecision(
    input: ModelRouteInput,
    last: ModelRouteInput["currentTurn"]["toolResults"][number] | undefined
  ): ModelRouteDecision {
    if (!last) {
      return toolDecision(
        "get_day_context",
        "compose_meal",
        { dinerIds: input.state.dinerIds },
        this.model
      );
    }
    if (last.tool === "get_day_context") {
      return toolDecision(
        "find_dish_candidates",
        "compose_meal",
        {
          dinerIds: input.state.dinerIds,
          rejectedFoodIds: [],
          rejectedTemplateIds: []
        },
        this.model
      );
    }
    if (last.tool === "find_dish_candidates") {
      const candidates = Array.isArray(last.data?.candidates)
        ? (last.data.candidates as Array<{ templateId: string; role: string }>)
        : [];
      const preferred = {
        shared_main: "tpl-potato-chicken",
        shared_side: "tpl-garlic-spinach",
        staple: "tpl-leftover-rice"
      } as const;
      const selected = (["shared_main", "shared_side", "staple"] as const)
        .map(
          (role) =>
            candidates.find((candidate) => candidate.templateId === preferred[role]) ??
            candidates.find((candidate) => candidate.role === role)
        )
        .filter((candidate): candidate is { templateId: string; role: string } =>
          Boolean(candidate)
        )
        .map((candidate) => ({
          templateId: candidate.templateId,
          relativePortion: "standard"
        }));
      return toolDecision(
        "finalize_meal_plan",
        "compose_meal",
        {
          dinerIds: input.state.dinerIds,
          mealType: "lunch",
          candidateSetId: String(last.data?.candidateSetId),
          selectedDishes: selected,
          mealPortionScale: 1.0,
          selectionReason: "根据当前候选和库存提交完整菜单。"
        },
        this.model
      );
    }
    return finalDecision(
      "compose_meal",
      "计划已生成。",
      this.model
    );
  }

  private targetDecision(input: ModelRouteInput): ModelRouteDecision {
    switch (this.target) {
      case "meal_completion":
        return toolDecision(
          "preview_meal_completion",
          "complete_meal",
          { mode: "as_planned" },
          this.model
        );
      case "caregiver":
        if (!input.currentTurn.toolResults.length) {
          return toolDecision(
            "retrieve_local_knowledge",
            "retrieve_guidance",
            { query: "本地晚餐准备规则", topK: 3 },
            this.model
          );
        }
        return toolDecision(
          "preview_caregiver_task",
          "preview_handoff",
          { recipientLabel: "阿姨", serveAt: "unspecified" },
          this.model
        );
      case "inventory":
        return toolDecision(
          "preview_inventory_change",
          "preview_inventory",
          { foodId: "food-tofu", quantity: 2, unit: "盒" },
          this.model
        );
      case "memory":
        return toolDecision(
          "preview_member_memory_change",
          "preview_member_memory",
          {
            memberId: "mem-admin",
            kind: "preference",
            summary: "少油清淡",
            polarity: "prefer"
          },
          this.model
        );
      case "plan":
        return this.planDecision(input, undefined);
    }
  }

  private goalForTarget(): Exclude<AgentGoal, "unsupported"> {
    switch (this.target) {
      case "meal_completion":
        return "complete_meal";
      case "inventory":
        return "preview_inventory";
      case "memory":
        return "preview_member_memory";
      case "caregiver":
        return "preview_handoff";
      case "plan":
        return "compose_meal";
    }
  }
}

async function createDomain(): Promise<PrivatePlateDomain> {
  return PrivatePlateDomain.create(":memory:", {
    embedding: new HashEmbeddingClient(64)
  });
}

async function runPlan(mode: "model" | "trusted_presenter") {
  const domain = await createDomain();
  const provider = new TerminalProvider("plan");
  const agent = new PrivatePlateAgent(domain, `finalization-${mode}`, provider, {
    finalizationMode: mode
  });
  const turn = await agent.handleUserMessage("规划今天的午餐");
  const plan = domain.getPlanById(agent.state.activePlanId ?? "");
  return { domain, provider, agent, turn, plan };
}

describe("trusted presenter finalization", () => {
  it("removes only the final model call while preserving the model menu", async () => {
    const model = await runPlan("model");
    const trusted = await runPlan("trusted_presenter");

    expect(model.turn.validationOk).toBe(true);
    expect(trusted.turn.validationOk).toBe(true);
    expect(model.provider.calls).toBe(4);
    expect(trusted.provider.calls).toBe(3);
    expect(model.turn.toolTrace.map((item) => item.tool)).toEqual(
      trusted.turn.toolTrace.map((item) => item.tool)
    );
    expect(trusted.turn.finalizationMode).toBe("trusted_presenter");
    expect(trusted.turn.modelSteps.some((step) => step.decision === "deterministic_fallback")).toBe(false);
    expect(trusted.plan?.sharedTemplates.map((item) => item.name)).toEqual(
      model.plan?.sharedTemplates.map((item) => item.name)
    );
    for (const item of trusted.plan?.sharedTemplates ?? []) {
      expect(trusted.turn.answer).toContain(item.name);
    }
    expect(trusted.turn.answer).toContain(
      "选择理由：根据当前候选和库存提交完整菜单。"
    );
    expect(trusted.turn.answer).not.toContain("。。");
    expect(trusted.turn.answer).not.toContain("Domain");

    model.domain.close();
    trusted.domain.close();
  });

  it("does not close the planning pipeline after context or candidates", async () => {
    const domain = await createDomain();
    const provider = new TerminalProvider("plan");
    const agent = new PrivatePlateAgent(domain, "finalization-stage-gate", provider, {
      finalizationMode: "trusted_presenter"
    });

    const turn = await agent.handleUserMessage("规划今天的午餐");

    expect(turn.toolTrace.map((item) => item.tool)).toEqual([
      "get_day_context",
      "find_dish_candidates",
      "finalize_meal_plan"
    ]);
    expect(provider.calls).toBe(3);
    domain.close();
  });

  it("keeps meal completion preview pending and performs no write", async () => {
    const domain = await createDomain();
    const provider = new TerminalProvider("meal_completion");
    const agent = new PrivatePlateAgent(domain, "finalization-meal", provider, {
      finalizationMode: "trusted_presenter"
    });

    await agent.handleUserMessage("规划今天的午餐");
    const before = domain.db.prepare("SELECT COUNT(*) AS count FROM meal_records").get();
    const turn = await agent.handleUserMessage("这顿饭吃完了，先预览餐后记录");
    const after = domain.db.prepare("SELECT COUNT(*) AS count FROM meal_records").get();

    expect(turn.finalizationMode).toBe("trusted_presenter");
    expect(turn.answer).toContain("尚未写入");
    expect(agent.getTaskState().status).toBe("waiting_confirmation");
    expect(before).toEqual({ count: 0 });
    expect(after).toEqual({ count: 0 });
    expect(provider.calls).toBe(4);
    domain.close();
  });

  it("uses the verified caregiver preview and does not send", async () => {
    const domain = await createDomain();
    const provider = new TerminalProvider("caregiver");
    const agent = new PrivatePlateAgent(domain, "finalization-caregiver", provider, {
      finalizationMode: "trusted_presenter"
    });

    await agent.handleUserMessage("规划今天的午餐");
    const turn = await agent.handleUserMessage(
      "查本地晚餐准备规则，再生成给阿姨的任务卡，先不要发送"
    );

    expect(turn.finalizationMode).toBe("trusted_presenter");
    expect(turn.answer).toContain("给阿姨");
    expect(turn.answer).toContain("任务卡最小披露与确认前不发送");
    expect(turn.answer).toContain("尚未发送");
    expect(turn.uiOnly?.taskCard?.recipientLabel).toBe("阿姨");
    expect(domain.db.prepare("SELECT COUNT(*) AS count FROM caregiver_tasks").get()).toEqual({
      count: 0
    });
    expect(provider.calls).toBe(5);
    domain.close();
  });

  it("records presenter rendering failure as deterministic fallback", async () => {
    const domain = await createDomain();
    const provider = new TerminalProvider("plan");
    const agent = new PrivatePlateAgent(domain, "finalization-presenter-failure", provider, {
      finalizationMode: "trusted_presenter"
    });
    const originalInvoke = agent.gateway.invoke.bind(agent.gateway);
    agent.gateway.invoke = async (...invokeArgs) => {
      const outcome = await originalInvoke(...invokeArgs);
      if (invokeArgs[1] !== "finalize_meal_plan" || !outcome.result.ok) {
        return outcome;
      }
      const data = outcome.result.data as Record<string, unknown>;
      const plan =
        data.plan && typeof data.plan === "object"
          ? (data.plan as Record<string, unknown>)
          : {};
      return {
        ...outcome,
        result: {
          ...outcome.result,
          data: {
            ...data,
            plan: { ...plan, menu: [] }
          }
        }
      };
    };

    const turn = await agent.handleUserMessage("规划今天的午餐");

    expect(turn.finalizationMode).toBe("deterministic_fallback");
    expect(turn.modelSteps.at(-1)?.decision).toBe("deterministic_fallback");
    expect(turn.modelSteps.at(-1)?.policy.reasons).toContain(
      "TRUSTED_PRESENTER_INPUT_UNAVAILABLE"
    );
    domain.close();
  });

  it.each([
    ["inventory", "刚买了两盒豆腐，帮我记入库存", "不会修改库存"],
    ["memory", "记住全家喜欢少油清淡", "不会写入家庭记忆"]
  ] as const)("keeps %s confirmation boundary", async (target, input, wording) => {
    const domain = await createDomain();
    const provider = new TerminalProvider(target);
    const agent = new PrivatePlateAgent(domain, `finalization-${target}`, provider, {
      finalizationMode: "trusted_presenter"
    });

    const before = domain.db.prepare(
      target === "inventory"
        ? "SELECT COUNT(*) AS count FROM inventory_ledger"
        : "SELECT COUNT(*) AS count FROM member_preferences"
    ).get();
    const turn = await agent.handleUserMessage(input);
    const after = domain.db.prepare(
      target === "inventory"
        ? "SELECT COUNT(*) AS count FROM inventory_ledger"
        : "SELECT COUNT(*) AS count FROM member_preferences"
    ).get();

    expect(turn.finalizationMode).toBe("trusted_presenter");
    expect(turn.answer).toContain(wording);
    expect(turn.taskOutcome.status).toBe("COMPLETE");
    expect(agent.getTaskState().status).toBe("waiting_confirmation");
    expect(before).toEqual(after);
    expect(provider.calls).toBe(1);
    domain.close();
  });
});
