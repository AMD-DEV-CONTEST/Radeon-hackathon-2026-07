import { describe, expect, it } from "vitest";
import { renderDeterministicFinal } from "./deterministic-final.js";

describe("deterministic final v2", () => {
  it("renders finalize plan", () => {
    const text = renderDeterministicFinal({
      goal: "compose_meal",
      toolResults: [
        {
          tool: "finalize_meal_plan",
          ok: true,
          goal: "compose_meal",
          data: {
            status: "ok",
            plan: {
              sharedTemplates: [{ name: "白菜豆腐煲" }],
              version: 1
            }
          }
        } as never
      ]
    });
    expect(text).toBeTruthy();
  });
});
