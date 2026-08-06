import { describe, expect, it } from "vitest";
import type { MealTemplate, MemberMealPolicy } from "@privateplate/contracts";
import { scaleAndAllocate } from "./scale.js";
import { round3 } from "../nutrition.js";

const template: MealTemplate = {
  id: "tpl-test",
  name: "测试主菜",
  role: "shared_main",
  ingredientsPerStandardServing: [
    { foodId: "food-a", edibleQuantityG: 100 },
    { foodId: "food-b", edibleQuantityG: 50 }
  ],
  tags: {
    cuisine: ["home"],
    cookingMethods: ["steam"],
    effortLevel: "low",
    oilLevel: "low",
    lowSodiumVariant: true
  },
  instructionsSummary: "test",
  sourceId: "src",
  licenseId: "lic",
  templateVersion: "1"
};

function policy(memberId: string, main: number): MemberMealPolicy {
  return {
    memberId,
    mealType: "lunch",
    portionUnitsByRole: {
      shared_main: main,
      shared_side: 1,
      staple: 1
    },
    guardrails: {
      energyKcal: { min: 0, max: 9999 },
      carbohydrateG: { min: 0, max: 9999 },
      sodiumMgMax: 9999
    },
    source: "demo_fixture",
    ruleVersion: "1"
  };
}

describe("scaleAndAllocate conservation", () => {
  it("keeps member sum equal to batch within 0.001g", () => {
    const policiesByMemberId = new Map([
      ["m1", policy("m1", 1)],
      ["m2", policy("m2", 0.7)],
      ["m3", policy("m3", 0.9)]
    ]);

    const { batchIngredients, memberShares } = scaleAndAllocate({
      templates: [template],
      policiesByMemberId,
      dinerIds: ["m1", "m2", "m3"]
    });

    for (const batch of batchIngredients) {
      const sum = round3(
        memberShares
          .filter(
            (s) => s.templateId === batch.templateId && s.foodId === batch.foodId
          )
          .reduce((acc, s) => acc + s.quantityG, 0)
      );
      expect(Math.abs(sum - batch.quantityG)).toBeLessThanOrEqual(0.001);
    }
  });
});
