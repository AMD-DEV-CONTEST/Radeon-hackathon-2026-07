import { describe, expect, it } from "vitest";
import { resolveLoopTransition } from "./loop-mode.js";

describe("loop mode v2", () => {
  it("finalizes after successful finalize_meal_plan", () => {
    const t = resolveLoopTransition({
      goal: "compose_meal",
      tool: "finalize_meal_plan",
      result: {
        tool: "finalize_meal_plan",
        ok: true,
        data: { status: "ok" },
        auditRef: "a",
        schemaVersion: 1
      } as never
    });
    expect(t.mode).toBe("FINAL_ONLY");
  });

  it("keeps action after candidates", () => {
    const t = resolveLoopTransition({
      goal: "compose_meal",
      tool: "find_dish_candidates",
      result: {
        tool: "find_dish_candidates",
        ok: true,
        data: { candidates: [] },
        auditRef: "a",
        schemaVersion: 1
      } as never
    });
    expect(t.mode).toBe("ACTION_ALLOWED");
  });

  it("domain finalize reject stays ACTION_ALLOWED for reselect", () => {
    const t = resolveLoopTransition({
      goal: "compose_meal",
      tool: "finalize_meal_plan",
      result: {
        tool: "finalize_meal_plan",
        ok: true,
        data: {
          status: "failed",
          code: "NUTRITION_GUARDRAIL",
          details: { reselectAllowed: true, deficits: [{ deficit: 12 }] }
        },
        auditRef: "a",
        schemaVersion: 1
      } as never
    });
    expect(t.mode).toBe("ACTION_ALLOWED");
    expect(t.reason).toBe("finalize_failed_reselect");
  });

  it("keeps action after local retrieval for grounded follow-up work", () => {
    const t = resolveLoopTransition({
      goal: "retrieve_guidance",
      tool: "retrieve_local_knowledge",
      result: {
        tool: "retrieve_local_knowledge",
        ok: true,
        data: { cards: [{ sourceId: "src-rule-1" }] },
        auditRef: "a",
        schemaVersion: 1
      } as never
    });
    expect(t.mode).toBe("ACTION_ALLOWED");
  });
});
