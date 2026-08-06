/**
 * Scale the dishes selected by the Agent and keep intake separate from
 * prepared batch quantity. The Domain does not choose or replace dishes.
 */
import type { MealRole, MealTemplate, MemberMealPolicy } from "@privateplate/contracts";
import { DEFAULT_PREP_BUFFER } from "../nutrition-budget.js";
import { round3 } from "../nutrition.js";
import { type BatchIngredient, type MemberIngredientShare } from "./scale.js";

export type RelativePortion = "small" | "standard" | "large";

const PORTION_WEIGHT: Record<RelativePortion, number> = {
  small: 0.75,
  standard: 1,
  large: 1.25
};

export type ScaledSelectedMeal = {
  plannedBatch: BatchIngredient[];
  preparedBatch: BatchIngredient[];
  /** Compatibility alias; new callers should use preparedBatch. */
  batchIngredients: BatchIngredient[];
  memberShares: MemberIngredientShare[];
  portionUnitsByMember: Map<string, Record<MealRole, number>>;
  mealPortionScale: number;
  prepBuffer: number;
};

function resolveMealPortionScale(value: number | undefined): number {
  const scale = value ?? 1;
  if (!Number.isFinite(scale) || scale <= 0 || scale > 1.5) {
    throw new Error("INVALID_MEAL_PORTION_SCALE");
  }
  return round3(scale);
}

function resolvePrepBuffer(value: number | undefined): number {
  const buffer = value ?? DEFAULT_PREP_BUFFER;
  if (!Number.isFinite(buffer) || buffer < 0.05 || buffer > 0.1) {
    throw new Error("INVALID_PREP_BUFFER");
  }
  return round3(buffer);
}

function prepareBatch(plannedBatch: BatchIngredient[], prepBuffer: number): BatchIngredient[] {
  return plannedBatch.map((item) => ({
    ...item,
    quantityG: round3(item.quantityG * (1 + prepBuffer))
  }));
}

function allocateShares(
  batchG: number,
  role: MealRole,
  templateId: string,
  foodId: string,
  dinerIds: string[],
  portionUnitsByMember: Map<string, Record<MealRole, number>>,
  totalUnits: number,
  memberShares: MemberIngredientShare[]
): void {
  const sortedMemberIds = [...dinerIds].sort();
  const rawShares = sortedMemberIds.map((memberId) => {
    const units = portionUnitsByMember.get(memberId)?.[role] ?? 0;
    return { memberId, raw: (batchG * units) / totalUnits };
  });
  const floored = rawShares.map((share) => ({
    memberId: share.memberId,
    quantityG: Math.floor(share.raw * 1000) / 1000
  }));
  let assigned = round3(floored.reduce((sum, share) => sum + share.quantityG, 0));
  let remainderUnits = Math.round((batchG - assigned) * 1000);
  let index = 0;
  while (remainderUnits > 0) {
    const target = floored[index % floored.length]!;
    target.quantityG = round3(target.quantityG + 0.001);
    remainderUnits -= 1;
    index += 1;
  }
  for (const share of floored) {
    memberShares.push({
      memberId: share.memberId,
      templateId,
      role,
      foodId,
      quantityG: share.quantityG
    });
  }
}

export function scaleAndAllocateSelected(input: {
  selectedDishes: Array<{ template: MealTemplate; relativePortion: RelativePortion }>;
  policiesByMemberId: Map<string, MemberMealPolicy>;
  dinerIds: string[];
  mealPortionScale?: number;
  prepBuffer?: number;
}): ScaledSelectedMeal {
  const mealPortionScale = resolveMealPortionScale(input.mealPortionScale);
  const prepBuffer = resolvePrepBuffer(input.prepBuffer);
  const dinerPolicies = input.dinerIds.map((id) => {
    const policy = input.policiesByMemberId.get(id);
    if (!policy) throw new Error(`GUARD_CONFIG_MISSING:${id}`);
    return policy;
  });

  const portionUnitsByMember = new Map<string, Record<MealRole, number>>();
  for (const policy of dinerPolicies) {
    const scaleRole = (units: number | undefined) =>
      round3((units ?? 0) * mealPortionScale);
    portionUnitsByMember.set(policy.memberId, {
      shared_main: scaleRole(policy.portionUnitsByRole.shared_main),
      shared_side: scaleRole(policy.portionUnitsByRole.shared_side),
      staple: scaleRole(policy.portionUnitsByRole.staple)
    });
  }

  const byRole = new Map<MealRole, Array<{ template: MealTemplate; relativePortion: RelativePortion }>>();
  for (const dish of input.selectedDishes) {
    const list = byRole.get(dish.template.role) ?? [];
    list.push(dish);
    byRole.set(dish.template.role, list);
  }

  const plannedBatch: BatchIngredient[] = [];
  const memberShares: MemberIngredientShare[] = [];
  for (const [role, dishes] of byRole) {
    const totalUnits = input.dinerIds.reduce(
      (sum, memberId) => sum + (portionUnitsByMember.get(memberId)?.[role] ?? 0),
      0
    );
    if (totalUnits <= 0) {
      throw new Error(`GUARD_CONFIG_MISSING:zero_units:${role}`);
    }
    const weightSum = dishes.reduce(
      (sum, dish) => sum + PORTION_WEIGHT[dish.relativePortion],
      0
    );
    const roleUnits = totalUnits * (weightSum / dishes.length);
    for (const dish of dishes) {
      const dishUnits =
        (roleUnits * PORTION_WEIGHT[dish.relativePortion]) / weightSum;
      for (const ingredient of dish.template.ingredientsPerStandardServing) {
        let perUnit = ingredient.edibleQuantityG;
        if (
          ingredient.edibleQuantityGMin != null &&
          ingredient.edibleQuantityGMax != null
        ) {
          perUnit = Math.min(
            ingredient.edibleQuantityGMax,
            Math.max(ingredient.edibleQuantityGMin, perUnit)
          );
        }
        const batchG = round3(perUnit * dishUnits);
        plannedBatch.push({
          templateId: dish.template.id,
          foodId: ingredient.foodId,
          quantityG: batchG
        });
        allocateShares(
          batchG,
          role,
          dish.template.id,
          ingredient.foodId,
          input.dinerIds,
          portionUnitsByMember,
          totalUnits,
          memberShares
        );
      }
    }
  }

  const preparedBatch = prepareBatch(plannedBatch, prepBuffer);
  return {
    plannedBatch,
    preparedBatch,
    batchIngredients: preparedBatch,
    memberShares,
    portionUnitsByMember,
    mealPortionScale,
    prepBuffer
  };
}

function batchNeed(batch: BatchIngredient[]): Map<string, number> {
  const need = new Map<string, number>();
  for (const item of batch) {
    need.set(item.foodId, round3((need.get(item.foodId) ?? 0) + item.quantityG));
  }
  return need;
}

function fitsInventory(
  batch: BatchIngredient[],
  availableByFoodId: Map<string, number>
): boolean {
  for (const [foodId, quantityG] of batchNeed(batch)) {
    if (quantityG > (availableByFoodId.get(foodId) ?? 0) + 1e-6) return false;
  }
  return true;
}

/**
 * Fit the prepared batch to known inventory only when scalable ranges allow it.
 * If the batch still needs shopping, the caller keeps the normal plan and
 * exposes the gap instead of silently shrinking intake.
 */
export function tryFitScalableBatch(input: {
  selectedDishes: Array<{ template: MealTemplate; relativePortion: RelativePortion }>;
  policiesByMemberId: Map<string, MemberMealPolicy>;
  dinerIds: string[];
  availableByFoodId: Map<string, number>;
  mealPortionScale?: number;
  prepBuffer?: number;
}): ScaledSelectedMeal | null {
  const base = scaleAndAllocateSelected(input);
  if (fitsInventory(base.preparedBatch, input.availableByFoodId)) return base;

  const shrunk = input.selectedDishes.map((dish) => ({
    ...dish,
    template: {
      ...dish.template,
      ingredientsPerStandardServing: dish.template.ingredientsPerStandardServing.map(
        (ingredient) =>
          ingredient.edibleQuantityGMin != null &&
          ingredient.edibleQuantityGMax != null
            ? { ...ingredient, edibleQuantityG: ingredient.edibleQuantityGMin }
            : ingredient
      )
    }
  }));
  const minScale = scaleAndAllocateSelected({
    ...input,
    selectedDishes: shrunk
  });
  return fitsInventory(minScale.preparedBatch, input.availableByFoodId)
    ? minScale
    : null;
}
