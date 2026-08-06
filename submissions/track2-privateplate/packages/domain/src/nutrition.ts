import type { Food, MealTemplate, NutritionPer100g } from "@privateplate/contracts";

export function emptyNutrition(): NutritionPer100g {
  return {
    energyKcal: 0,
    carbohydrateG: 0,
    proteinG: 0,
    fatG: 0,
    sodiumMg: 0
  };
}

export function scaleNutrition(n: NutritionPer100g, factor: number): NutritionPer100g {
  return {
    energyKcal: round3(n.energyKcal * factor),
    carbohydrateG: round3(n.carbohydrateG * factor),
    proteinG: round3(n.proteinG * factor),
    fatG: round3(n.fatG * factor),
    sodiumMg: round3(n.sodiumMg * factor)
  };
}

export function addNutrition(a: NutritionPer100g, b: NutritionPer100g): NutritionPer100g {
  return {
    energyKcal: round3(a.energyKcal + b.energyKcal),
    carbohydrateG: round3(a.carbohydrateG + b.carbohydrateG),
    proteinG: round3(a.proteinG + b.proteinG),
    fatG: round3(a.fatG + b.fatG),
    sodiumMg: round3(a.sodiumMg + b.sodiumMg)
  };
}

/** Nutrition for grams of a food using per-100g values. */
export function nutritionForGrams(food: Food, grams: number): NutritionPer100g {
  return scaleNutrition(food.nutritionPer100g, grams / 100);
}

/**
 * Deterministic template nutrition from ingredients × food table.
 * Templates must not store a separate hand-filled nutrition total.
 */
export function computeTemplateNutrition(
  template: MealTemplate,
  foodsById: Map<string, Food>
): NutritionPer100g {
  let total = emptyNutrition();
  for (const ingredient of template.ingredientsPerStandardServing) {
    const food = foodsById.get(ingredient.foodId);
    if (!food) {
      throw new Error(`UNKNOWN_FOOD: ${ingredient.foodId} in template ${template.id}`);
    }
    total = addNutrition(total, nutritionForGrams(food, ingredient.edibleQuantityG));
  }
  return total;
}

export function round3(value: number): number {
  return Math.round(value * 1000) / 1000;
}
