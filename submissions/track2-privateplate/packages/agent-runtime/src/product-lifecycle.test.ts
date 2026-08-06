import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { PrivatePlateDomain } from "@privateplate/domain";
import { PrivatePlateAgent } from "./graph.js";
import { ScriptedProductProvider } from "./model/scripted-provider.js";

describe("product lifecycle v2", () => {
  let domain: PrivatePlateDomain;

  beforeAll(async () => {
    domain = await PrivatePlateDomain.create(":memory:");
  });

  afterAll(() => domain.close());

  it("plan then complete-meal preview path", async () => {
    const agent = new PrivatePlateAgent(
      domain,
      "life-1",
      new ScriptedProductProvider()
    );
    const plan = await agent.handleUserMessage("规划午餐，不要鸡腿。");
    expect(plan.toolTrace.some((t) => t.tool === "finalize_meal_plan")).toBe(
      true
    );
    expect(agent.state.activePlanId).toBeTruthy();

    const preview = await agent.handleUserMessage("记录本餐已按计划吃完");
    // intent may classify as plan or handoff; either stays model_routed
    expect(preview.routingEvidenceKind).toMatch(/model_/);
  });

  it("refuses write-out-of-scope without domain tools", async () => {
    const agent = new PrivatePlateAgent(
      domain,
      "life-2",
      new ScriptedProductProvider()
    );
    const turn = await agent.handleUserMessage("帮我更新库存并真实下单");
    expect(turn.toolTrace).toEqual([]);
  });
});
