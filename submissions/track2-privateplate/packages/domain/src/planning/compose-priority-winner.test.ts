import { describe, expect, it } from "vitest";
import {
  compareMealRankingRows,
  type MealRankingRow
} from "./compose.js";
import { computePriorityConsumeScore } from "./priority-score.js";
import type { InventoryItem } from "@privateplate/contracts";

function baseRow(overrides: Partial<MealRankingRow> & { tieBreakId: string }): MealRankingRow {
  return {
    hardConstraintsPass: true,
    pinRetentionScore: 0,
    requestedPriorityScore: 1,
    priorityConsumeScore: 0,
    inventoryCoverageScore: 0.5,
    distinctPurchaseCount: 1,
    softPreferenceScore: 0,
    effortScore: 1,
    ...overrides
  };
}

function inventoryItem(input: {
  id: string;
  foodId: string;
  estimateG: number;
}): InventoryItem {
  return {
    id: input.id,
    foodId: input.foodId,
    priorityConsume: true,
    state: "fresh",
    quantity: {
      rawExpression: `${input.estimateG}克`,
      normalized: {
        estimateG: input.estimateG,
        minG: input.estimateG,
        maxG: input.estimateG,
        confidence: "exact",
        conversionRuleId: null
      }
    }
  };
}

/**
 * Controlled: equal hard-pass and requestedPriority; higher priorityConsume
 * wins even when inventoryCoverage is worse.
 */
describe("compose priority consume winner", () => {
  it("ranks higher priorityConsume ahead of better inventoryCoverage", () => {
    const highConsumeLowCoverage = baseRow({
      tieBreakId: "bundle-high-consume",
      priorityConsumeScore: 0.9,
      inventoryCoverageScore: 0.2
    });
    const lowConsumeHighCoverage = baseRow({
      tieBreakId: "bundle-low-consume",
      priorityConsumeScore: 0.3,
      inventoryCoverageScore: 0.95
    });

    const ordered = [lowConsumeHighCoverage, highConsumeLowCoverage].sort(
      (a, b) => compareMealRankingRows(a, b, { preferLowEffort: false })
    );
    expect(ordered[0]?.tieBreakId).toBe("bundle-high-consume");
    expect(
      compareMealRankingRows(highConsumeLowCoverage, lowConsumeHighCoverage, {
        preferLowEffort: false
      })
    ).toBeLessThan(0);
  });

  it("computePriorityConsumeScore prefers the batch that actually uses more priority stock", () => {
    const inventory = [
      inventoryItem({ id: "tofu-1", foodId: "food-tofu", estimateG: 400 })
    ];
    const high = computePriorityConsumeScore({
      inventory,
      batchIngredients: [{ foodId: "food-tofu", quantityG: 300 }]
    });
    const low = computePriorityConsumeScore({
      inventory,
      batchIngredients: [{ foodId: "food-tofu", quantityG: 50 }]
    });
    expect(high).toBeGreaterThan(low);
    expect(high).toBeCloseTo(0.75, 5);
    expect(low).toBeCloseTo(0.125, 5);
  });
});
