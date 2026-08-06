import { describe, expect, it } from "vitest";
import { PrivatePlateDomain } from "@privateplate/domain";
import { PrivatePlateAgent } from "./graph.js";
import { ScriptedProductProvider } from "./model/scripted-provider.js";

describe("preference no pin (v2)", () => {
  it("plans without requiring pin tools", async () => {
    const domain = await PrivatePlateDomain.create(":memory:");
    const agent = new PrivatePlateAgent(
      domain,
      "pref-1",
      new ScriptedProductProvider()
    );
    const turn = await agent.handleUserMessage("规划午餐，不要鸡腿。");
    expect(turn.toolTrace.some((t) => t.tool === "finalize_meal_plan")).toBe(
      true
    );
    domain.close();
  });
});
