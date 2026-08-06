import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { PrivatePlateDomain } from "@privateplate/domain";
import { PrivatePlateAgent } from "./graph.js";
import { ScriptedProductProvider } from "./model/scripted-provider.js";

describe("agent loop v2", () => {
  let domain: PrivatePlateDomain;

  beforeAll(async () => {
    domain = await PrivatePlateDomain.create(":memory:");
  });

  afterAll(() => domain.close());

  it("runs multi-tool plan turn without v1 tools", async () => {
    const agent = new PrivatePlateAgent(
      domain,
      "loop-1",
      new ScriptedProductProvider()
    );
    const turn = await agent.handleUserMessage("规划午餐，优先豆腐，不要鸡腿。");
    const tools = turn.toolTrace.map((t) => t.tool);
    expect(tools[0]).toBe("get_day_context");
    expect(tools).toContain("find_dish_candidates");
    expect(tools).toContain("finalize_meal_plan");
    expect(turn.phase).toBe("PRESENTING_PLAN");
  });

  it("stops medical risk before tools", async () => {
    const agent = new PrivatePlateAgent(
      domain,
      "loop-2",
      new ScriptedProductProvider()
    );
    const turn = await agent.handleUserMessage("帮我调整降糖药");
    expect(turn.phase).toBe("SAFE_STOP");
    expect(turn.toolTrace).toEqual([]);
  });
});
