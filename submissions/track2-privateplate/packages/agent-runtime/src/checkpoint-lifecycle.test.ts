import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { PrivatePlateDomain } from "@privateplate/domain";
import { PrivatePlateAgent } from "./graph.js";
import { ScriptedProductProvider } from "./model/scripted-provider.js";

describe("checkpoint lifecycle v2", () => {
  let domain: PrivatePlateDomain;

  beforeAll(async () => {
    domain = await PrivatePlateDomain.create(":memory:");
  });

  afterAll(() => domain.close());

  it("exports checkpoint after plan without tokens", async () => {
    const agent = new PrivatePlateAgent(
      domain,
      "ckpt-1",
      new ScriptedProductProvider()
    );
    await agent.handleUserMessage("规划午餐，不要鸡腿。");
    const ckpt = agent.exportCheckpoint();
    expect(ckpt.schemaVersion).toBe(2);
    expect(ckpt.agentState.activePlanId).toBeTruthy();
    const blob = JSON.stringify(ckpt);
    expect(blob).not.toMatch(/confirmationToken|payloadHash/);
  });
});
