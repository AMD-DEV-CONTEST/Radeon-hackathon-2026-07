/**
 * Planning pipeline: get_day_context must not freeze inspect_context + FINAL_ONLY
 * when the user is asking to plan a meal (stage gate requires context first).
 */
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { PrivatePlateDomain } from "@privateplate/domain";
import { PrivatePlateAgent } from "./graph.js";
import { ScriptedProductProvider } from "./model/scripted-provider.js";
import { resolveLoopTransition } from "./loop-mode.js";

describe("planning pipeline goal lock", () => {
  let domain: PrivatePlateDomain;

  beforeAll(async () => {
    domain = await PrivatePlateDomain.create(":memory:");
  });

  afterAll(() => domain.close());

  it("compose_meal is not satisfied by get_day_context alone", () => {
    const t = resolveLoopTransition({
      goal: "compose_meal",
      tool: "get_day_context",
      result: {
        tool: "get_day_context",
        ok: true,
        data: { serviceDate: "2026-08-03" },
        auditRef: "a",
        schemaVersion: 1
      } as never
    });
    expect(t.mode).toBe("ACTION_ALLOWED");
    expect(t.reason).toBe("context_observed_choose_next_action");
  });

  it("scripted plan reaches finalize_meal_plan after day context", async () => {
    const agent = new PrivatePlateAgent(
      domain,
      "pipe-plan-1",
      new ScriptedProductProvider()
    );
    const turn = await agent.handleUserMessage(
      "规划午餐，不要鸡腿。我们三个人一起吃。"
    );
    const tools = (turn.toolTrace ?? []).filter((t) => t.ok).map((t) => t.tool);
    expect(tools).toContain("get_day_context");
    expect(tools).toContain("find_dish_candidates");
    expect(tools).toContain("finalize_meal_plan");
    expect(turn.answer).not.toMatch(/改变了目标/);
    expect(turn.phase).not.toBe("SAFE_STOP");
    expect(turn.phase).not.toBe("ERROR");
    const ckpt = agent.exportCheckpoint();
    expect(ckpt.taskState.objective).not.toBe("inspect_context");
    expect(ckpt.agentState.activePlanId).toBeTruthy();
  });

  it("pure inspect still completes on get_day_context only", async () => {
    const agent = new PrivatePlateAgent(
      domain,
      "pipe-inspect-1",
      new ScriptedProductProvider()
    );
    const turn = await agent.handleUserMessage(
      "查看今天的家庭额度、库存和成员情况。"
    );
    const tools = (turn.toolTrace ?? []).filter((t) => t.ok).map((t) => t.tool);
    expect(tools).toEqual(["get_day_context"]);
    expect(tools).not.toContain("finalize_meal_plan");
  });
});
