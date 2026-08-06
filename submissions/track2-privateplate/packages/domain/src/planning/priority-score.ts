import type { InventoryItem } from "@privateplate/contracts";

type BatchIngredient = {
  foodId: string;
  quantityG: number;
};

/**
 * Returns the share of known, priority inventory that this batch consumes.
 * Quantities are aggregated by food and capped at the available estimate.
 */
export function computePriorityConsumeScore(input: {
  inventory: InventoryItem[];
  batchIngredients: BatchIngredient[];
}): number {
  const availableByFood = new Map<string, number>();
  for (const item of input.inventory) {
    if (!item.priorityConsume) continue;
    const estimateG = item.quantity.normalized.estimateG;
    if (estimateG == null || estimateG <= 0) continue;
    availableByFood.set(
      item.foodId,
      (availableByFood.get(item.foodId) ?? 0) + estimateG
    );
  }

  const totalAvailableG = [...availableByFood.values()].reduce(
    (sum, quantityG) => sum + quantityG,
    0
  );
  if (totalAvailableG === 0) return 0;

  const usedByFood = new Map<string, number>();
  for (const ingredient of input.batchIngredients) {
    if (!availableByFood.has(ingredient.foodId) || ingredient.quantityG <= 0) {
      continue;
    }
    usedByFood.set(
      ingredient.foodId,
      (usedByFood.get(ingredient.foodId) ?? 0) + ingredient.quantityG
    );
  }

  const consumedG = [...availableByFood].reduce(
    (sum, [foodId, availableG]) =>
      sum + Math.min(usedByFood.get(foodId) ?? 0, availableG),
    0
  );
  return consumedG / totalAvailableG;
}

export function computeRequestedPriorityScore(input: {
  requestedFoodIds: string[];
  batchIngredients: BatchIngredient[];
}): number {
  const requestedFoodIds = [...new Set(input.requestedFoodIds)];
  if (requestedFoodIds.length === 0) return 0;

  const batchFoodIds = new Set(
    input.batchIngredients
      .filter((ingredient) => ingredient.quantityG > 0)
      .map((ingredient) => ingredient.foodId)
  );
  const includedCount = requestedFoodIds.filter((foodId) =>
    batchFoodIds.has(foodId)
  ).length;
  return includedCount / requestedFoodIds.length;
}
