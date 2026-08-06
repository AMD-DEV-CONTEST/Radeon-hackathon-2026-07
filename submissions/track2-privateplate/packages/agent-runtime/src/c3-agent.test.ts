import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { PrivatePlateDomain } from "@privateplate/domain";
import { PrivatePlateAgent } from "./graph.js";
import { ScriptedProductProvider } from "./model/scripted-provider.js";
import { classifyIntent } from "./policy.js";

function mockAgent(domain: PrivatePlateDomain, sessionId: string) {
  return new PrivatePlateAgent(
    domain,
    sessionId,
    new ScriptedProductProvider()
  );
}

describe("C3 policy basics", () => {
  it("classifies core intents", () => {
    expect(classifyIntent("规划午餐，不要鸡腿").intent).toBe("plan_meal");
    expect(classifyIntent("请帮我调胰岛素剂量").safeStop).toBe(true);
  });
});

describe("C3 agent v2 product path", () => {
  let domain: PrivatePlateDomain;

  beforeAll(async () => {
    domain = await PrivatePlateDomain.create(":memory:");
  });

  afterAll(() => {
    domain.close();
  });

  it("plans via get_day_context → candidates → finalize", async () => {
    const agent = mockAgent(domain, "v2-plan");
    const turn = await agent.handleUserMessage(
      "中午我们三个人吃什么？豆腐今天最好吃掉，但我不想再吃鸡腿了。"
    );
    expect(turn.routingEvidenceKind).toBe("model_routed");
    expect(turn.validationOk).toBe(true);
    const tools = turn.toolTrace.map((t) => t.tool);
    expect(tools).toContain("get_day_context");
    expect(tools).toContain("find_dish_candidates");
    expect(tools).toContain("finalize_meal_plan");
    expect(tools).not.toContain("compose_family_meal");
    expect(agent.state.activePlanId).toBeTruthy();
    expect(agent.state.phase).toBe("PRESENTING_PLAN");
  });

  it("safe-stops medical risk without tools", async () => {
    const agent = mockAgent(domain, "medical");
    const turn = await agent.handleUserMessage("请根据我的情况调整降糖药剂量");
    expect(turn.phase).toBe("SAFE_STOP");
    expect(turn.toolTrace).toEqual([]);
  });

  it("previews caregiver task card when plan exists", async () => {
    const agent = mockAgent(domain, "complete");
    await agent.handleUserMessage("规划午餐，不要鸡腿。");
    const preview = await agent.handleUserMessage("发给保姆");
    const tools = preview.toolTrace.map((t) => t.tool);
    expect(tools).toContain("preview_caregiver_task");
    expect(tools).not.toContain("compose_family_meal");
  });

  it("inspects via get_day_context", async () => {
    const agent = mockAgent(domain, "inspect");
    const turn = await agent.handleUserMessage("查看家庭库存和成员");
    expect(turn.toolTrace.map((t) => t.tool)).toEqual(["get_day_context"]);
  });
});
