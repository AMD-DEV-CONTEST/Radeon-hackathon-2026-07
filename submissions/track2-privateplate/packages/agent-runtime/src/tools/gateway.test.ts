import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { PrivatePlateDomain } from "@privateplate/domain";
import { createInitialState } from "../state.js";
import { ToolGateway } from "./gateway.js";

describe("ToolGateway get_inventory", () => {
  let domain: PrivatePlateDomain;
  let gateway: ToolGateway;

  beforeEach(async () => {
    domain = await PrivatePlateDomain.create(":memory:");
    gateway = new ToolGateway(domain);
  });

  afterEach(() => {
    domain.close();
  });

  it("returns inventory items without member healthFacts", async () => {
    const state = createInitialState({
      sessionId: "gateway-inventory",
      householdId: domain.householdId,
      dinerIds: ["mem-admin", "mem-father", "mem-mother"]
    });
    const outcome = await gateway.invoke(
      state,
      "get_inventory",
      { goal: "inspect_inventory" },
      "只查看库存",
      ["get_inventory"]
    );

    expect(outcome.result.ok).toBe(true);
    if (!outcome.result.ok) return;
    const data = outcome.result.data as Record<string, unknown>;
    expect(Array.isArray(data.inventory)).toBe(true);
    expect((data.inventory as unknown[]).length).toBeGreaterThan(0);
    expect(data.inventoryVersion).toEqual(expect.any(Number));
    expect(data.householdContextVersion).toEqual(expect.any(Number));
    expect(data.members).toBeUndefined();
    expect(data.memberIntake).toBeUndefined();
    expect(data.householdIntake).toBeUndefined();
    expect(JSON.stringify(data)).not.toMatch(/healthFacts/);
  });
});
