/**
 * Pure selection evaluation shared by finalizeAgentMealPlan and findFeasibleSelection.
 * No I/O, no UUID/clock side effects.
 */
import type {
  MealRole,
  MealTemplate,
  MemberConstraint,
  MemberMealPolicy,
  MemberNutritionBudget,
  MealStructure,
  MealPlan
} from "@privateplate/contracts";
import {
  collectHardExclusions,
  templateContainsExcludedFood
} from "../bundle-filter.js";
import {
  addNutrition,
  emptyNutrition,
  nutritionForGrams,
  round3
} from "../nutrition.js";
import type { PlannerCatalog } from "./compose.js";
import { evaluateMemberGuardrails } from "./guardrails.js";
import {
  scaleAndAllocateSelected,
  tryFitScalableBatch,
  type RelativePortion
} from "./scale-selected.js";
import { calculateMemberNutritionBudget } from "../nutrition-budget.js";
import type { NutritionSnapshot } from "../ledger/types.js";

export type SelectedDish = {
  templateId: string;
  relativePortion: RelativePortion;
};

export type EvaluateSelectionInput = {
  dinerIds: string[];
  mealType: "lunch" | "dinner";
  selectedDishes: SelectedDish[];
  mealPortionScale: number;
  mealStructure?: MealStructure;
  remainingNutritionByMember?: Map<string, NutritionSnapshot>;
  mealBudgetsByMemberId?: Map<string, MemberNutritionBudget>;
  prepBuffer?: number;
  rejectedFoodIds?: string[];
  rejectedTemplateIds?: string[];
};

export type EvaluateSelectionOk = {
  status: "ok";
  mealStructure: MealStructure;
  selectedTemplates: MealTemplate[];
  scaled: NonNullable<ReturnType<typeof scaleAndAllocateSelected>>;
  memberAllocations: MealPlan["memberAllocations"];
  memberResults: ReturnType<typeof evaluateMemberGuardrails>[];
};

export type EvaluateSelectionFailed = {
  status: "failed";
  code: string;
  message: string;
  details?: Record<string, unknown>;
};

export type EvaluateSelectionResult = EvaluateSelectionOk | EvaluateSelectionFailed;

const STANDARD_MEAL_ROLES: MealRole[] = ["shared_main", "shared_side", "staple"];

type NutrientKey = keyof NutritionSnapshot;
const NUTRIENTS: NutrientKey[] = [
  "energyKcal",
  "carbohydrateG",
  "proteinG",
  "fatG",
  "sodiumMg"
];
const NUTRITION_EPSILON = 0.5;

export function normalizedMealStructure(input?: MealStructure): MealStructure {
  if (!input) {
    return {
      mode: "standard",
      requiredRoles: STANDARD_MEAL_ROLES,
      omittedRoles: []
    };
  }
  return {
    ...input,
    requiredRoles:
      input.mode === "standard" ? STANDARD_MEAL_ROLES : input.requiredRoles,
    omittedRoles: input.omittedRoles ?? []
  };
}

export function coveredRoles(template: MealTemplate): MealRole[] {
  return template.tags.coversRoles ?? [template.role];
}

export function mealStructureFailure(
  selectedTemplates: MealTemplate[],
  structure: MealStructure
): { missingRoles: MealRole[] } | null {
  if (structure.mode !== "standard" && !structure.reason?.trim()) {
    return { missingRoles: [] };
  }
  const covered = new Set<MealRole>();
  for (const template of selectedTemplates) {
    for (const role of coveredRoles(template)) covered.add(role);
  }
  const missingRoles = structure.requiredRoles.filter((role) => !covered.has(role));
  return missingRoles.length > 0 ? { missingRoles } : null;
}

function budgetForMember(
  memberId: string,
  budgetsByMemberId: Map<string, MemberNutritionBudget> | undefined
): MemberNutritionBudget {
  return (
    budgetsByMemberId?.get(memberId) ??
    calculateMemberNutritionBudget(undefined, memberId)
  );
}

function sumSnapshots(items: NutritionSnapshot[]): NutritionSnapshot {
  return items.reduce(
    (total, item) => ({
      energyKcal: round3(total.energyKcal + item.energyKcal),
      carbohydrateG: round3(total.carbohydrateG + item.carbohydrateG),
      proteinG: round3(total.proteinG + item.proteinG),
      fatG: round3(total.fatG + item.fatG),
      sodiumMg: round3(total.sodiumMg + item.sodiumMg)
    }),
    emptyNutrition()
  );
}

/**
 * Evaluate whether a concrete dish selection is feasible under catalog constraints.
 * Mirrors the nutrition/structure path used by finalizeAgentMealPlan.
 */
export function evaluateSelection(
  catalog: PlannerCatalog,
  input: EvaluateSelectionInput
): EvaluateSelectionResult {
  if (!input.selectedDishes.length) {
    return {
      status: "failed",
      code: "EMPTY_SELECTION",
      message: "必须至少选择一道菜。"
    };
  }
  const selectedTemplateIds = input.selectedDishes.map((dish) => dish.templateId);
  if (new Set(selectedTemplateIds).size !== selectedTemplateIds.length) {
    return {
      status: "failed",
      code: "DUPLICATE_SELECTED_TEMPLATE",
      message: "selectedDishes 不能重复选择同一 templateId。",
      details: { templateIds: selectedTemplateIds }
    };
  }
  if (
    !Number.isFinite(input.mealPortionScale) ||
    input.mealPortionScale <= 0 ||
    input.mealPortionScale > 1.5
  ) {
    return {
      status: "failed",
      code: "INVALID_MEAL_PORTION_SCALE",
      message: "餐次基础份量倍率必须在 (0, 1.5] 之间。"
    };
  }

  const templatesById = new Map(catalog.templates.map((t) => [t.id, t]));
  const foodsById = new Map(catalog.foods.map((f) => [f.id, f]));
  const selectedTemplates: MealTemplate[] = [];
  for (const dish of input.selectedDishes) {
    const template = templatesById.get(dish.templateId);
    if (!template) {
      return {
        status: "failed",
        code: "UNKNOWN_TEMPLATE",
        message: `未知菜品 ${dish.templateId}`,
        details: { templateId: dish.templateId }
      };
    }
    selectedTemplates.push(template);
  }

  const hard = collectHardExclusions(
    catalog.constraints.filter((c) => input.dinerIds.includes(c.memberId)),
    input.rejectedFoodIds ?? [],
    input.rejectedTemplateIds ?? []
  );
  for (const template of selectedTemplates) {
    if (
      hard.templateIds.has(template.id) ||
      templateContainsExcludedFood(template, hard.foodIds)
    ) {
      return {
        status: "failed",
        code: "HARD_CONSTRAINT_VIOLATION",
        message: `菜品 ${template.name} 触碰硬禁忌。`,
        details: { templateId: template.id }
      };
    }
  }

  const mealStructure = normalizedMealStructure(input.mealStructure);
  if (mealStructure.mode !== "standard" && !mealStructure.reason?.trim()) {
    return {
      status: "failed",
      code: "MEAL_STRUCTURE_EXCEPTION_REASON_MISSING",
      message: "simple 或 one_pot 餐必须由 Agent 明确说明例外原因。",
      details: { mealStructure }
    };
  }
  if (mealStructure.mode === "one_pot" && selectedTemplates.length > 1) {
    return {
      status: "failed",
      code: "ONE_POT_DISH_COUNT_EXCEEDED",
      message: "one_pot 餐只能选择一道菜。",
      details: {
        mealStructure,
        selectedCount: selectedTemplates.length,
        reselectAllowed: true,
        recommendedActions: [
          "keep_single_one_pot_dish",
          "replace_with_compound_dish",
          "declare_standard_meal_structure"
        ]
      }
    };
  }
  const structureFailure = mealStructureFailure(selectedTemplates, mealStructure);
  if (structureFailure) {
    return {
      status: "failed",
      code: "MEAL_STRUCTURE_INCOMPLETE",
      message: "普通家庭正餐至少需要主菜、蔬菜/配菜和主食三个角色。",
      details: {
        mealStructure,
        missingRoles: structureFailure.missingRoles,
        reselectAllowed: true,
        recommendedActions: [
          "add_candidate_dish",
          "replace_with_compound_dish",
          "declare_simple_or_one_pot_exception"
        ]
      }
    };
  }

  const policiesByMemberId = new Map<string, MemberMealPolicy>();
  for (const policy of catalog.mealPolicies) {
    if (
      input.dinerIds.includes(policy.memberId) &&
      policy.mealType === input.mealType
    ) {
      policiesByMemberId.set(policy.memberId, policy);
    }
  }
  for (const dinerId of input.dinerIds) {
    if (!policiesByMemberId.has(dinerId)) {
      return {
        status: "failed",
        code: "GUARD_CONFIG_MISSING",
        message: `缺少成员 ${dinerId} 的餐次策略。`
      };
    }
  }

  const selectedForScale = input.selectedDishes.map((d, index) => ({
    template: selectedTemplates[index]!,
    relativePortion: d.relativePortion
  }));

  const availableByFoodId = new Map<string, number>();
  for (const item of catalog.inventory) {
    if (!item.foodId) continue;
    const est = item.quantity.normalized.estimateG ?? 0;
    availableByFoodId.set(
      item.foodId,
      (availableByFoodId.get(item.foodId) ?? 0) + est
    );
  }

  let scaled: ReturnType<typeof scaleAndAllocateSelected> | null = null;
  try {
    scaled =
      tryFitScalableBatch({
        selectedDishes: selectedForScale,
        policiesByMemberId,
        dinerIds: input.dinerIds,
        availableByFoodId,
        mealPortionScale: input.mealPortionScale,
        ...(input.prepBuffer === undefined
          ? {}
          : { prepBuffer: input.prepBuffer })
      }) ??
      scaleAndAllocateSelected({
        selectedDishes: selectedForScale,
        policiesByMemberId,
        dinerIds: input.dinerIds,
        mealPortionScale: input.mealPortionScale,
        ...(input.prepBuffer === undefined
          ? {}
          : { prepBuffer: input.prepBuffer })
      });
  } catch (error) {
    return {
      status: "failed",
      code: "SCALE_FAILED",
      message: "无法按所选菜品与份量完成克数换算。",
      details: { cause: error instanceof Error ? error.message : String(error) }
    };
  }

  if (!scaled) {
    return {
      status: "failed",
      code: "SCALE_FAILED",
      message: "无法按所选菜品与份量完成克数换算。"
    };
  }

  const memberAllocations = input.dinerIds.map((memberId) => {
    const items = scaled!.memberShares
      .filter((s) => s.memberId === memberId)
      .map((s) => ({
        templateId: s.templateId,
        role: s.role,
        foodId: s.foodId,
        quantityG: s.quantityG
      }));
    let nutrition = emptyNutrition();
    for (const item of items) {
      const food = foodsById.get(item.foodId);
      if (!food) throw new Error(`UNKNOWN_FOOD:${item.foodId}`);
      nutrition = addNutrition(
        nutrition,
        nutritionForGrams(food, item.quantityG)
      );
    }
    const policy = policiesByMemberId.get(memberId)!;
    return {
      memberId,
      items,
      nutrition: {
        energyKcal: round3(nutrition.energyKcal),
        carbohydrateG: round3(nutrition.carbohydrateG),
        proteinG: round3(nutrition.proteinG),
        fatG: round3(nutrition.fatG),
        sodiumMg: round3(nutrition.sodiumMg)
      },
      portionUnitsByRole: {
        shared_main: policy.portionUnitsByRole.shared_main ?? 0,
        shared_side: policy.portionUnitsByRole.shared_side ?? 0,
        staple: policy.portionUnitsByRole.staple ?? 0
      }
    };
  });

  const memberResults = memberAllocations.map((allocation) => {
    const policy = policiesByMemberId.get(allocation.memberId)!;
    return evaluateMemberGuardrails(allocation, policy);
  });
  if (!memberResults.every((r) => r.pass)) {
    const failed = memberResults.filter((result) => !result.pass);
    const deficits = failed.flatMap((result) => {
      const policy = policiesByMemberId.get(result.memberId)!;
      const alloc = memberAllocations.find((a) => a.memberId === result.memberId)!;
      const rows: Array<Record<string, unknown>> = [];
      const g = policy.guardrails;
      if (alloc.nutrition.energyKcal < g.energyKcal.min) {
        rows.push({
          memberId: result.memberId,
          nutrient: "energyKcal",
          actual: alloc.nutrition.energyKcal,
          min: g.energyKcal.min,
          deficit: round3(g.energyKcal.min - alloc.nutrition.energyKcal)
        });
      }
      if (alloc.nutrition.energyKcal > g.energyKcal.max) {
        rows.push({
          memberId: result.memberId,
          nutrient: "energyKcal",
          actual: alloc.nutrition.energyKcal,
          max: g.energyKcal.max,
          excess: round3(alloc.nutrition.energyKcal - g.energyKcal.max)
        });
      }
      if (alloc.nutrition.carbohydrateG < g.carbohydrateG.min) {
        rows.push({
          memberId: result.memberId,
          nutrient: "carbohydrateG",
          actual: alloc.nutrition.carbohydrateG,
          min: g.carbohydrateG.min,
          deficit: round3(g.carbohydrateG.min - alloc.nutrition.carbohydrateG)
        });
      }
      if (alloc.nutrition.carbohydrateG > g.carbohydrateG.max) {
        rows.push({
          memberId: result.memberId,
          nutrient: "carbohydrateG",
          actual: alloc.nutrition.carbohydrateG,
          max: g.carbohydrateG.max,
          excess: round3(alloc.nutrition.carbohydrateG - g.carbohydrateG.max)
        });
      }
      if (g.proteinG && alloc.nutrition.proteinG < g.proteinG.min) {
        rows.push({
          memberId: result.memberId,
          nutrient: "proteinG",
          actual: alloc.nutrition.proteinG,
          min: g.proteinG.min,
          deficit: round3(g.proteinG.min - alloc.nutrition.proteinG)
        });
      }
      if (g.proteinG && alloc.nutrition.proteinG > g.proteinG.max) {
        rows.push({
          memberId: result.memberId,
          nutrient: "proteinG",
          actual: alloc.nutrition.proteinG,
          max: g.proteinG.max,
          excess: round3(alloc.nutrition.proteinG - g.proteinG.max)
        });
      }
      if (alloc.nutrition.sodiumMg > g.sodiumMgMax) {
        rows.push({
          memberId: result.memberId,
          nutrient: "sodiumMg",
          actual: alloc.nutrition.sodiumMg,
          max: g.sodiumMgMax,
          excess: round3(alloc.nutrition.sodiumMg - g.sodiumMgMax)
        });
      }
      return rows;
    });
    const hasLowerBoundDeficit = deficits.some(
      (deficit) =>
        typeof deficit.deficit === "number" && deficit.deficit > 0
    );
    const hasUpperBoundExcess = deficits.some(
      (deficit) => typeof deficit.excess === "number" && deficit.excess > 0
    );
    const recommendedActions = [
      ...(hasLowerBoundDeficit
        ? [
            "add_candidate_dish",
            "replace_with_more_suitable_candidate",
            "increase_relative_portion"
          ]
        : []),
      ...(hasUpperBoundExcess
        ? ["reduce_meal_portion_scale", "reduce_relative_portion", "remove_or_replace_dish"]
        : [])
    ];
    const failureKind =
      hasLowerBoundDeficit && hasUpperBoundExcess
        ? "mixed_guardrail_violation"
        : hasLowerBoundDeficit
          ? "lower_bound_composition_deficit"
          : "upper_bound_excess";
    return {
      status: "failed",
      code: "NUTRITION_GUARDRAIL",
      message: hasLowerBoundDeficit
        ? "成员营养守卫未通过。下限是绝对标准，请改变菜品组合或 relativePortion 后重新 finalize。"
        : "成员营养守卫未通过，请根据差额调整餐次倍率、relativePortion 或替换菜品后重新 finalize。",
      details: {
        memberResults: failed,
        deficits,
        mealPortionScale: input.mealPortionScale,
        reselectAllowed: true,
        failureKind,
        shareOnlyAdjustmentEffective: !hasLowerBoundDeficit,
        recommendedActions
      }
    };
  }

  const nutritionDeficits: Array<Record<string, unknown>> = [];
  let remainingBudgetInsufficient = false;
  const budgets = input.dinerIds.map((memberId) => ({
    memberId,
    budget: budgetForMember(memberId, input.mealBudgetsByMemberId),
    allocation: memberAllocations.find((item) => item.memberId === memberId)!
  }));
  for (const { memberId, budget, allocation } of budgets) {
    const mealBudget = budget.mealBudgets[input.mealType];
    const remaining = input.remainingNutritionByMember?.get(memberId);
    for (const nutrient of NUTRIENTS) {
      const actual = allocation.nutrition[nutrient];
      const min = mealBudget.min[nutrient];
      const max = remaining
        ? Math.min(mealBudget.max[nutrient], remaining[nutrient])
        : mealBudget.max[nutrient];
      if (remaining && remaining[nutrient] + NUTRITION_EPSILON < min) {
        remainingBudgetInsufficient = true;
        nutritionDeficits.push({
          scope: "member",
          memberId,
          nutrient,
          reason: "remaining_budget_below_meal_minimum",
          remaining: remaining[nutrient],
          requiredMinimum: min,
          deficit: round3(min - remaining[nutrient])
        });
        continue;
      }
      if (actual + NUTRITION_EPSILON < min) {
        nutritionDeficits.push({
          scope: "member",
          memberId,
          nutrient,
          actual,
          min,
          deficit: round3(min - actual)
        });
      } else if (actual > max + NUTRITION_EPSILON) {
        nutritionDeficits.push({
          scope: "member",
          memberId,
          nutrient,
          actual,
          max,
          excess: round3(actual - max)
        });
      }
    }
  }

  const householdAllocation = sumSnapshots(memberAllocations.map((item) => item.nutrition));
  const householdBudget = input.dinerIds.reduce(
    (total, memberId) => {
      const meal = budgetForMember(memberId, input.mealBudgetsByMemberId).mealBudgets[
        input.mealType
      ];
      return {
        min: sumSnapshots([total.min, meal.min]),
        max: sumSnapshots([total.max, meal.max]),
        target: sumSnapshots([total.target, meal.target]),
        reserve: sumSnapshots([total.reserve, meal.reserve])
      };
    },
    {
      min: emptyNutrition(),
      max: emptyNutrition(),
      target: emptyNutrition(),
      reserve: emptyNutrition()
    }
  );
  for (const nutrient of NUTRIENTS) {
    if (
      householdAllocation[nutrient] + NUTRITION_EPSILON <
      householdBudget.min[nutrient]
    ) {
      nutritionDeficits.push({
        scope: "household",
        nutrient,
        actual: householdAllocation[nutrient],
        min: householdBudget.min[nutrient],
        deficit: round3(householdBudget.min[nutrient] - householdAllocation[nutrient])
      });
    } else if (
      householdAllocation[nutrient] >
      householdBudget.max[nutrient] + NUTRITION_EPSILON
    ) {
      nutritionDeficits.push({
        scope: "household",
        nutrient,
        actual: householdAllocation[nutrient],
        max: householdBudget.max[nutrient],
        excess: round3(householdAllocation[nutrient] - householdBudget.max[nutrient])
      });
    }
  }
  if (nutritionDeficits.length > 0) {
    const hasLowerBoundDeficit = nutritionDeficits.some(
      (deficit) => typeof deficit.deficit === "number" && deficit.deficit > 0
    );
    const hasUpperBoundExcess = nutritionDeficits.some(
      (deficit) => typeof deficit.excess === "number" && deficit.excess > 0
    );
    return {
      status: "failed",
      code: remainingBudgetInsufficient
        ? "INSUFFICIENT_REMAINING_BUDGET"
        : "NUTRITION_BUDGET",
      message: remainingBudgetInsufficient
        ? "当前剩余预算不足以提供一份合理餐食，不能静默缩成极小份量。"
        : "餐食营养预算未通过，请根据结构化缺口重新选菜或调整份量。",
      details: {
        deficits: nutritionDeficits,
        mealPortionScale: input.mealPortionScale,
        mealStructure,
        reserve: householdBudget.reserve,
        shareOnlyAdjustmentEffective: !hasLowerBoundDeficit,
        reselectAllowed: true,
        recommendedActions: [
          ...(hasLowerBoundDeficit
            ? [
                "add_candidate_dish",
                "replace_with_more_suitable_candidate",
                "increase_relative_portion"
              ]
            : []),
          ...(hasUpperBoundExcess
            ? [
                "reduce_meal_portion_scale",
                "reduce_relative_portion",
                "remove_or_replace_dish"
              ]
            : [])
        ]
      }
    };
  }

  return {
    status: "ok",
    mealStructure,
    selectedTemplates,
    scaled,
    memberAllocations,
    memberResults
  };
}

/** Exposed for search pruning only — not a product ranking signal. */
export function hardExcludedTemplateIds(
  constraints: MemberConstraint[],
  dinerIds: string[],
  rejectedFoodIds: string[] = [],
  rejectedTemplateIds: string[] = []
): { templateIds: Set<string>; foodIds: Set<string> } {
  return collectHardExclusions(
    constraints.filter((c) => dinerIds.includes(c.memberId)),
    rejectedFoodIds,
    rejectedTemplateIds
  );
}
