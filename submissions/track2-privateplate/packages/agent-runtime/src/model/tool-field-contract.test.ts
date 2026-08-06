import { describe, expect, it } from "vitest";
import { applyInterfaceDefaults } from "./tool-field-contract.js";
import { parseModelToolArguments } from "./tool-definitions.js";

describe("v2 tool field contract", () => {
  it("defaults empty rejection lists on find_dish_candidates", () => {
    const raw = applyInterfaceDefaults("find_dish_candidates", {
      goal: "compose_meal",
      dinerIds: ["mem-admin"]
    });
    expect(raw).toMatchObject({
      rejectedFoodIds: [],
      rejectedTemplateIds: []
    });
  });

  it("defaults preview mode", () => {
    const raw = applyInterfaceDefaults("preview_meal_completion", {
      goal: "preview_meal_completion"
    });
    expect(raw).toMatchObject({ mode: "as_planned" });
  });

  it("requires mealType for finalize", () => {
    expect(() =>
      parseModelToolArguments("finalize_meal_plan", {
        goal: "compose_meal",
        dinerIds: ["mem-admin"],
        candidateSetId: "cset",
        selectedDishes: [
          { templateId: "tpl-leftover-rice", relativePortion: "standard" }
        ],
        mealPortionScale: 1.0,
        selectionReason: "x"
      })
    ).toThrow();
  });
});
