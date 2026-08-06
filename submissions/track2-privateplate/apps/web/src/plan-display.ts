import type {
  MealPlan,
  MealMemberAllocation,
  NutritionSnapshot,
  PreparedBatchItem
} from "./api";
import { mealRoleName } from "./formatters";

export type PlanDishDisplay = {
  templateId: string;
  name: string;
  role: string;
  coversRoles: string[];
  roleLabel: string;
  plannedByMember: Array<{ memberId: string; quantityG: number }>;
  plannedTotalG: number | null;
  preparedTotalG: number | null;
};

export type PlanQuantitySummary = {
  plannedTotalG: number | null;
  preparedTotalG: number | null;
  bufferG: number | null;
};

function intakeAllocations(plan: MealPlan): MealMemberAllocation[] {
  return plan.plannedIntake?.byMember ?? plan.memberAllocations;
}

function preparedItems(plan: MealPlan): PreparedBatchItem[] {
  return plan.preparedBatch ?? plan.batchIngredients ?? [];
}

function sumQuantities(values: Array<number | undefined>): number | null {
  const valid = values.filter(
    (value): value is number => value != null && Number.isFinite(value)
  );
  return valid.length > 0
    ? valid.reduce((total, value) => total + value, 0)
    : null;
}

function plannedItemsForTemplate(plan: MealPlan, templateId: string) {
  // One dish template can expand to multiple food lines (e.g. cabbage + tofu).
  // The drawer shows per-person planned grams, so aggregate by member.
  const totals = new Map<string, number>();
  const order: string[] = [];
  for (const allocation of intakeAllocations(plan)) {
    for (const item of allocation.items ?? []) {
      if (item.templateId !== templateId) continue;
      if (item.quantityG == null || !Number.isFinite(item.quantityG)) continue;
      if (!totals.has(allocation.memberId)) order.push(allocation.memberId);
      totals.set(
        allocation.memberId,
        (totals.get(allocation.memberId) ?? 0) + item.quantityG
      );
    }
  }
  return order.map((memberId) => ({
    memberId,
    quantityG: totals.get(memberId)!
  }));
}

function preparedQuantityForTemplate(
  plan: MealPlan,
  templateId: string
): number | null {
  return sumQuantities(
    preparedItems(plan)
      .filter((item) => item.templateId === templateId)
      .map((item) => item.quantityG)
  );
}

function roleLabel(role: string, coversRoles: string[]): string {
  const roles = coversRoles.length > 0 ? coversRoles : [role];
  return roles.map((item) => mealRoleName(item)).join(" · ");
}

export function buildPlanDishDisplays(plan: MealPlan): PlanDishDisplay[] {
  return plan.sharedTemplates.map((template) => {
    const plannedByMember = plannedItemsForTemplate(plan, template.templateId);
    const coversRoles = template.coversRoles ?? [template.role];
    return {
      templateId: template.templateId,
      name: template.name,
      role: template.role,
      coversRoles,
      roleLabel: roleLabel(template.role, coversRoles),
      plannedByMember,
      plannedTotalG: sumQuantities(plannedByMember.map((item) => item.quantityG)),
      preparedTotalG: preparedQuantityForTemplate(plan, template.templateId)
    };
  });
}

export function planMemberNutrition(
  plan: MealPlan
): Array<{ memberId: string; nutrition: NutritionSnapshot }> {
  return intakeAllocations(plan).map((allocation) => ({
    memberId: allocation.memberId,
    nutrition: allocation.nutrition
  }));
}

export function planHouseholdNutrition(plan: MealPlan): NutritionSnapshot | null {
  if (plan.plannedIntake?.householdTotal) return plan.plannedIntake.householdTotal;
  if (plan.nutritionSummary?.householdTotal) return plan.nutritionSummary.householdTotal;
  if (planMemberNutrition(plan).length === 0) return null;
  return planMemberNutrition(plan).reduce(
    (total, member) => ({
      energyKcal: total.energyKcal + member.nutrition.energyKcal,
      carbohydrateG: total.carbohydrateG + member.nutrition.carbohydrateG,
      proteinG: total.proteinG + member.nutrition.proteinG,
      fatG: total.fatG + member.nutrition.fatG,
      sodiumMg: total.sodiumMg + member.nutrition.sodiumMg
    }),
    { energyKcal: 0, carbohydrateG: 0, proteinG: 0, fatG: 0, sodiumMg: 0 }
  );
}

export function planQuantitySummary(plan: MealPlan): PlanQuantitySummary {
  const dishes = buildPlanDishDisplays(plan);
  const plannedTotalG = sumQuantities(dishes.map((dish) => dish.plannedTotalG ?? undefined));
  const preparedTotalG = sumQuantities(
    preparedItems(plan).map((item) => item.quantityG)
  );
  return {
    plannedTotalG,
    preparedTotalG,
    bufferG:
      plannedTotalG != null && preparedTotalG != null
        ? Math.max(0, preparedTotalG - plannedTotalG)
        : null
  };
}

export function planPreparedFoodSummary(
  plan: MealPlan
): Array<{ foodId: string; quantityG: number }> {
  const totals = new Map<string, number>();
  for (const item of preparedItems(plan)) {
    if (item.quantityG == null || !Number.isFinite(item.quantityG)) continue;
    totals.set(item.foodId, (totals.get(item.foodId) ?? 0) + item.quantityG);
  }
  return [...totals.entries()].map(([foodId, quantityG]) => ({
    foodId,
    quantityG
  }));
}
