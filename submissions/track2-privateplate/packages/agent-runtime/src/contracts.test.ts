import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { PrivatePlateDomain } from "@privateplate/domain";
import { PrivatePlateAgent } from "./graph.js";
import { ScriptedProductProvider } from "./model/scripted-provider.js";
import { goalForTool } from "./contracts.js";

describe("contracts v2", () => {
  let domain: PrivatePlateDomain;

  beforeAll(async () => {
    domain = await PrivatePlateDomain.create(":memory:");
  });

  afterAll(() => domain.close());

  it("maps tools to goals", () => {
    expect(goalForTool("get_day_context")).toBe("inspect_context");
    expect(goalForTool("finalize_meal_plan")).toBe("compose_meal");
    expect(goalForTool("preview_caregiver_task")).toBe("preview_handoff");
    expect(goalForTool("preview_inventory_change")).toBe("update_inventory");
    expect(goalForTool("preview_member_memory_change")).toBe(
      "update_member_memory"
    );
    expect(goalForTool("preview_meal_completion")).toBe(
      "complete_meal"
    );
  });

  it("records model steps on plan", async () => {
    const agent = new PrivatePlateAgent(
      domain,
      "contracts-1",
      new ScriptedProductProvider()
    );
    const turn = await agent.handleUserMessage("规划午餐，不要鸡腿。");
    expect(turn.modelSteps.length).toBeGreaterThan(0);
    expect(turn.routingEvidenceKind).toBe("model_routed");
  });
});
