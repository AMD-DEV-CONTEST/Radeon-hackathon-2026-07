import { describe, expect, it } from "vitest";
import type { InventoryItem } from "@privateplate/contracts";
import {
  computePriorityConsumeScore,
  computeRequestedPriorityScore
} from "./priority-score.js";

function inventoryItem(input: {
  id: string;
  foodId: string;
  estimateG: number | null;
  priorityConsume?: boolean;
}): InventoryItem {
  const confidence = input.estimateG == null ? "unknown" : "exact";
  return {
    id: input.id,
    foodId: input.foodId,
    priorityConsume: input.priorityConsume ?? true,
    state: "fresh",
    quantity: {
      rawExpression:
        input.estimateG == null ? "数量不明" : `${input.estimateG}克`,
      normalized: {
        estimateG: input.estimateG,
        minG: input.estimateG,
        maxG: input.estimateG,
        confidence,
        conversionRuleId: null
      }
    }
  };
}

describe("computePriorityConsumeScore", () => {
  it("scores the actual share of known priority inventory consumed", () => {
    const score = computePriorityConsumeScore({
      inventory: [
        inventoryItem({ id: "tofu-1", foodId: "tofu", estimateG: 300 }),
        inventoryItem({ id: "cabbage-1", foodId: "cabbage", estimateG: 100 })
      ],
      batchIngredients: [
        { foodId: "tofu", quantityG: 150 },
        { foodId: "cabbage", quantityG: 100 }
      ]
    });

    expect(score).toBe(0.625);
  });

  it("aggregates duplicate rows and caps consumption at available quantity", () => {
    const score = computePriorityConsumeScore({
      inventory: [
        inventoryItem({ id: "tofu-1", foodId: "tofu", estimateG: 100 }),
        inventoryItem({ id: "tofu-2", foodId: "tofu", estimateG: 50 }),
        inventoryItem({ id: "unknown", foodId: "cabbage", estimateG: null })
      ],
      batchIngredients: [
        { foodId: "tofu", quantityG: 100 },
        { foodId: "tofu", quantityG: 100 },
        { foodId: "cabbage", quantityG: 500 }
      ]
    });

    expect(score).toBe(1);
  });

  it("returns zero when no priority inventory has a usable estimate", () => {
    expect(
      computePriorityConsumeScore({
        inventory: [
          inventoryItem({ id: "unknown", foodId: "tofu", estimateG: null })
        ],
        batchIngredients: [{ foodId: "tofu", quantityG: 100 }]
      })
    ).toBe(0);
  });
});

describe("computeRequestedPriorityScore", () => {
  it("keeps explicit user priority separate from inventory consumption", () => {
    expect(
      computeRequestedPriorityScore({
        requestedFoodIds: ["tofu", "tofu", "cabbage"],
        batchIngredients: [{ foodId: "tofu", quantityG: 100 }]
      })
    ).toBe(0.5);
  });
});
