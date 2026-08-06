import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { PrivatePlateDomain } from "@privateplate/domain";
import { PrivatePlateAgent } from "./graph.js";
import { ScriptedProductProvider } from "./model/scripted-provider.js";

describe("product boundary v2", () => {
  let domain: PrivatePlateDomain;

  beforeAll(async () => {
    domain = await PrivatePlateDomain.create(":memory:");
  });

  afterAll(() => domain.close());

  it("never exposes compose_family_meal on the product path", async () => {
    const agent = new PrivatePlateAgent(
      domain,
      "boundary-1",
      new ScriptedProductProvider()
    );
    const turn = await agent.handleUserMessage(
      "中午我们三个人吃什么？不要鸡腿。"
    );
    const tools = turn.toolTrace.map((t) => t.tool);
    expect(tools).not.toContain("compose_family_meal");
    expect(tools).not.toContain("revise_family_meal");
    expect(tools.some((t) => t === "finalize_meal_plan")).toBe(true);
  });

  it("exposes caregiver handoff preview after a plan exists", async () => {
    const agent = new PrivatePlateAgent(
      domain,
      "boundary-handoff",
      new ScriptedProductProvider()
    );
    await agent.handleUserMessage("中午我们三个人吃什么？不要鸡腿。");
    const handoff = await agent.handleUserMessage("发给保姆");
    const tools = handoff.toolTrace.map((t) => t.tool);
    expect(tools).toContain("preview_caregiver_task");
    expect(tools).not.toContain("compose_family_meal");
  });
});
