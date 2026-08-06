import { describe, expect, it } from "vitest";
import { renderStructuredInfeasible } from "./deterministic-final.js";

describe("renderStructuredInfeasible", () => {
  it("includes NO_FEASIBLE_PLAN and recovery facts", () => {
    const text = renderStructuredInfeasible({
      priorFailureCode: "NUTRITION_BUDGET",
      failureKind: "lower_bound_composition_deficit",
      deficits: [
        { memberId: "mem-father", nutrient: "proteinG", deficit: 9.4 },
        { nutrient: "energyKcal", excess: 12 }
      ],
      recommendedActions: [
        "add_candidate_dish",
        "replace_with_more_suitable_candidate"
      ],
      allowedRelaxations: [
        {
          constraintId: "soft_preference_or_portion",
          userFacingQuestion: "是否愿意调整软偏好后再试？"
        }
      ]
    });

    expect(text).toContain("NO_FEASIBLE_PLAN");
    expect(text).toContain("NUTRITION_BUDGET");
    expect(text).toContain("proteinG");
    expect(text).toContain("add_candidate_dish");
    expect(text).toContain("是否愿意调整软偏好后再试？");
  });
});
