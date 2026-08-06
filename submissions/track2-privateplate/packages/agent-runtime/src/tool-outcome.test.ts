import { describe, expect, it } from "vitest";
import { classifyToolOutcome } from "./tool-outcome.js";

describe("tool outcome classification", () => {
  it("distinguishes a Domain rejection from a successful plan", () => {
    expect(
      classifyToolOutcome({
        tool: "finalize_meal_plan",
        ok: true,
        data: { status: "failed", code: "NUTRITION_GUARDRAIL" }
      })
    ).toEqual({
      kind: "business_rejected",
      code: "NUTRITION_GUARDRAIL"
    });

    expect(
      classifyToolOutcome({
        tool: "finalize_meal_plan",
        ok: true,
        data: { status: "ok" }
      })
    ).toEqual({ kind: "succeeded", code: null });
  });

  it("keeps gateway failures separate from Domain feedback", () => {
    expect(
      classifyToolOutcome({
        tool: "finalize_meal_plan",
        ok: false,
        code: "STALE_CONTEXT"
      })
    ).toEqual({ kind: "invocation_failed", code: "STALE_CONTEXT" });
  });
});
