import type { InventoryItem } from "@privateplate/contracts";
import { describe, expect, it } from "vitest";
import { computeShoppingGap } from "./shopping-gap.js";

describe("shopping gap uncertainty", () => {
  it("keeps availability unknown when known and unknown stock are mixed", () => {
    const inventory: InventoryItem[] = [
      {
        id: "known-tofu",
        foodId: "food-tofu",
        quantity: {
          rawExpression: "100 克",
          normalized: {
            estimateG: 100,
            minG: 100,
            maxG: 100,
            confidence: "exact",
            conversionRuleId: null
          }
        },
        state: "unopened",
        priorityConsume: false
      },
      {
        id: "unknown-tofu",
        foodId: "food-tofu",
        quantity: {
          rawExpression: "还有一些",
          normalized: {
            estimateG: null,
            minG: null,
            maxG: null,
            confidence: "unknown",
            conversionRuleId: null
          }
        },
        state: "opened",
        priorityConsume: false
      }
    ];

    const [gap] = computeShoppingGap({
      batchIngredients: [
        { templateId: "tpl-tofu", foodId: "food-tofu", quantityG: 180 }
      ],
      inventory
    });

    expect(gap?.available).toEqual({
      estimateG: null,
      minG: 100,
      maxG: null,
      confidence: "unknown",
      conversionRuleId: null
    });
    expect(gap?.purchase.confidence).toBe("unknown");
    expect(gap?.status).toBe("needs_confirmation");
  });
});
