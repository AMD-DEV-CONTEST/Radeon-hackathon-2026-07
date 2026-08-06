/**
 * Protocol v2: Domain matches candidates and finalizes Agent-selected dishes.
 * No ranking, no winner, no silent substitution.
 */
import { randomUUID } from "node:crypto";
import type {
  InventoryItem,
  MealRole,
  MealPlan,
  MealTemplate,
  MealStructure,
  ShoppingGapItem
} from "@privateplate/contracts";
import {
  collectHardExclusions,
  templateContainsExcludedFood
} from "../bundle-filter.js";
import {
  addNutrition,
  computeTemplateNutrition,
  round3
} from "../nutrition.js";
import type { PlannerCatalog } from "./compose.js";
import { computeShoppingGapWithUnits } from "./shopping-gap-units.js";
import type { NutritionSnapshot } from "../ledger/types.js";
import {
  coveredRoles,
  evaluateSelection,
  normalizedMealStructure,
  type SelectedDish
} from "./evaluate-selection.js";
import {
  findFeasibleSelection,
  type FeasibleSuggestion
} from "./feasible-search.js";
import type { MemberNutritionBudget } from "@privateplate/contracts";

export type { SelectedDish } from "./evaluate-selection.js";
export {
  evaluateSelection,
  normalizedMealStructure,
  coveredRoles
} from "./evaluate-selection.js";
export {
  findFeasibleSelection,
  type FeasibleSuggestion,
  type FindFeasibleSelectionInput
} from "./feasible-search.js";

export type DishCandidate = {
  templateId: string;
  name: string;
  role: string;
  coversRoles: MealRole[];
  ingredients: Array<{
    foodId: string;
    edibleQuantityG: number;
    edibleQuantityGMin?: number;
    edibleQuantityGMax?: number;
  }>;
  inventoryFacts: {
    coveredFoodIds: string[];
    missingFoodIds: string[];
    priorityFoodIds: string[];
  };
  nutritionPerStandardServing: {
    energyKcal: number;
    carbohydrateG: number;
    proteinG: number;
    fatG: number;
    sodiumMg: number;
  };
  effortFacts: {
    effortLevel: string;
    oilLevel: string;
    lowSodiumVariant: boolean;
  };
};

export type CandidateSet = {
  candidateSetId: string;
  versionStamp: {
    household: number;
    inventory: number;
    intake: number;
    policy: string;
  };
  candidates: DishCandidate[];
  /** Grouped by role for model readability — still unordered within role. */
  byRole: Record<string, string[]>;
  selectionGuidance: {
    requiredRoles: MealRole[];
    maxSelectedDishes: number;
    selectionCountIsModelDecision: true;
    /** Full hard-filtered pool size; not a shortlist length. */
    candidateCount: number;
    multipleDishesPerRoleAllowed: true;
    note: string;
  };
};

export type FinalizeMealInput = {
  sessionId: string;
  dinerIds: string[];
  mealType: "lunch" | "dinner";
  candidateSetId: string;
  selectedDishes: SelectedDish[];
  mealPortionScale: number;
  mealStructure?: MealStructure;
  selectionReason: string;
  parentPlan?: { id: string; version: number };
  intakeVersion?: number;
  /** Loaded candidate set for subset/version checks. */
  candidateSet?: CandidateSet;
  currentVersionStamp?: CandidateSet["versionStamp"];
  /** Remaining is an upper cap for this meal, never a gram multiplier. */
  remainingNutritionByMember?: Map<string, NutritionSnapshot>;
  mealBudgetsByMemberId?: Map<string, MemberNutritionBudget>;
  prepBuffer?: number;
  /** Explicit bans / pins for feasible search (caller-structured; no NL parsing). */
  rejectedFoodIds?: string[];
  rejectedTemplateIds?: string[];
  bannedFoodIds?: string[];
  bannedTemplateIds?: string[];
  pinnedSelection?: SelectedDish[];
  noAdditionalDishes?: boolean;
  maxDishCount?: number;
  maxHouseholdEnergyKcal?: number;
};

export type FinalizeMealResult =
  | {
      status: "ok";
      plan: MealPlan;
      shoppingGap: ShoppingGapItem[];
      selectionReason: string;
      mealPortionScale: number;
    }
  | {
      status: "failed";
      code: string;
      message: string;
      details?: Record<string, unknown>;
    };

const STANDARD_MEAL_ROLES: MealRole[] = ["shared_main", "shared_side", "staple"];

const RESELECT_CODES = new Set([
  "NUTRITION_BUDGET",
  "NUTRITION_GUARDRAIL",
  "MEAL_STRUCTURE_INCOMPLETE",
  "ONE_POT_DISH_COUNT_EXCEEDED"
]);

function inventoryCoverage(
  template: MealTemplate,
  inventory: InventoryItem[]
): DishCandidate["inventoryFacts"] {
  const covered: string[] = [];
  const missing: string[] = [];
  const priority: string[] = [];
  for (const ing of template.ingredientsPerStandardServing) {
    const items = inventory.filter((i) => i.foodId === ing.foodId);
    const estimate = items.reduce(
      (sum, item) => sum + (item.quantity.normalized.estimateG ?? 0),
      0
    );
    if (estimate > 0) covered.push(ing.foodId);
    else missing.push(ing.foodId);
    if (items.some((i) => i.priorityConsume)) priority.push(ing.foodId);
  }
  return {
    coveredFoodIds: covered,
    missingFoodIds: missing,
    priorityFoodIds: priority
  };
}

function attachFeasibleRecovery(
  catalog: PlannerCatalog,
  input: FinalizeMealInput & {
    householdId: string;
    unitRules?: Array<{
      foodId: string;
      rawUnit: string;
      gramsPerUnit: number;
      id: string;
    }>;
  },
  failure: Extract<FinalizeMealResult, { status: "failed" }>
): FinalizeMealResult {
  if (!RESELECT_CODES.has(failure.code)) return failure;

  const suggestion: FeasibleSuggestion | null = findFeasibleSelection(catalog, {
    dinerIds: input.dinerIds,
    mealType: input.mealType,
    ...(input.mealStructure ? { mealStructure: input.mealStructure } : {}),
    ...(input.candidateSet
      ? {
          candidateTemplateIds: input.candidateSet.candidates.map(
            (c) => c.templateId
          )
        }
      : {}),
    ...(input.remainingNutritionByMember
      ? { remainingNutritionByMember: input.remainingNutritionByMember }
      : {}),
    ...(input.mealBudgetsByMemberId
      ? { mealBudgetsByMemberId: input.mealBudgetsByMemberId }
      : {}),
    ...(input.prepBuffer === undefined ? {} : { prepBuffer: input.prepBuffer }),
    ...(input.bannedFoodIds ? { bannedFoodIds: input.bannedFoodIds } : {}),
    ...(input.bannedTemplateIds
      ? { bannedTemplateIds: input.bannedTemplateIds }
      : {}),
    ...(input.rejectedFoodIds ? { rejectedFoodIds: input.rejectedFoodIds } : {}),
    ...(input.rejectedTemplateIds
      ? { rejectedTemplateIds: input.rejectedTemplateIds }
      : {}),
    ...(input.pinnedSelection ? { pinnedSelection: input.pinnedSelection } : {}),
    ...(input.noAdditionalDishes ? { noAdditionalDishes: true } : {}),
    ...(input.maxDishCount !== undefined
      ? { maxDishCount: input.maxDishCount }
      : {}),
    ...(input.maxHouseholdEnergyKcal !== undefined
      ? { maxHouseholdEnergyKcal: input.maxHouseholdEnergyKcal }
      : {})
  });

  const baseDetails = { ...(failure.details ?? {}) };
  const priorRecovery =
    typeof baseDetails.recovery === "object" && baseDetails.recovery !== null
      ? (baseDetails.recovery as Record<string, unknown>)
      : {};

  if (suggestion) {
    const recovery = {
      ...priorRecovery,
      feasibleSuggestion: suggestion
    };
    return {
      ...failure,
      details: {
        ...baseDetails,
        feasibleSuggestion: suggestion,
        recovery
      }
    };
  }

  const recovery = {
    ...priorRecovery,
    domainSearchExhausted: true
  };
  return {
    ...failure,
    details: {
      ...baseDetails,
      domainSearchExhausted: true,
      recovery
    }
  };
}

export function findDishCandidates(
  catalog: PlannerCatalog,
  input: {
    dinerIds: string[];
    rejectedFoodIds?: string[];
    rejectedTemplateIds?: string[];
    intakeVersion?: number;
  }
): CandidateSet {
  const hard = collectHardExclusions(
    catalog.constraints.filter((c) => input.dinerIds.includes(c.memberId)),
    input.rejectedFoodIds ?? [],
    input.rejectedTemplateIds ?? []
  );

  const foodsById = new Map(catalog.foods.map((f) => [f.id, f]));
  const candidates: DishCandidate[] = [];
  for (const template of catalog.templates) {
    if (hard.templateIds.has(template.id)) continue;
    if (templateContainsExcludedFood(template, hard.foodIds)) continue;

    const nutrition = computeTemplateNutrition(template, foodsById);
    candidates.push({
      templateId: template.id,
      name: template.name,
      role: template.role,
      coversRoles: coveredRoles(template),
      ingredients: template.ingredientsPerStandardServing.map((ing) => ({
        foodId: ing.foodId,
        edibleQuantityG: ing.edibleQuantityG,
        ...(ing.edibleQuantityGMin != null
          ? { edibleQuantityGMin: ing.edibleQuantityGMin }
          : {}),
        ...(ing.edibleQuantityGMax != null
          ? { edibleQuantityGMax: ing.edibleQuantityGMax }
          : {})
      })),
      inventoryFacts: inventoryCoverage(template, catalog.inventory),
      nutritionPerStandardServing: {
        energyKcal: round3(nutrition.energyKcal),
        carbohydrateG: round3(nutrition.carbohydrateG),
        proteinG: round3(nutrition.proteinG),
        fatG: round3(nutrition.fatG),
        sodiumMg: round3(nutrition.sodiumMg)
      },
      effortFacts: {
        effortLevel: template.tags.effortLevel,
        oilLevel: template.tags.oilLevel,
        lowSodiumVariant: template.tags.lowSodiumVariant
      }
    });
  }

  // Stable ID order only — never score/rank.
  candidates.sort((a, b) => a.templateId.localeCompare(b.templateId));

  const byRole: Record<string, string[]> = {};
  for (const c of candidates) {
    for (const role of c.coversRoles) {
      byRole[role] = byRole[role] ?? [];
      byRole[role]!.push(c.templateId);
    }
  }

  return {
    candidateSetId: `cset-${randomUUID()}`,
    versionStamp: {
      household: catalog.householdContextVersion,
      inventory: catalog.inventoryVersion,
      intake: input.intakeVersion ?? 1,
      policy: catalog.mealPolicyVersion
    },
    candidates,
    byRole,
    selectionGuidance: {
      requiredRoles: STANDARD_MEAL_ROLES,
      maxSelectedDishes: 12,
      selectionCountIsModelDecision: true,
      candidateCount: candidates.length,
      multipleDishesPerRoleAllowed: true,
      note: "candidates is the full hard-filtered pool, not a 3-dish shortlist. Cover requiredRoles; each role may include multiple dishes. byRole only groups ids for readability."
    }
  };
}

export function finalizeAgentMealPlan(
  catalog: PlannerCatalog,
  input: FinalizeMealInput & {
    planId?: string;
    householdId: string;
    unitRules?: Array<{
      foodId: string;
      rawUnit: string;
      gramsPerUnit: number;
      id: string;
    }>;
  }
): FinalizeMealResult {
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

  const candidateSet = input.candidateSet;
  const currentStamp = input.currentVersionStamp;

  if (candidateSet) {
    if (candidateSet.candidateSetId !== input.candidateSetId) {
      return {
        status: "failed",
        code: "CANDIDATE_SET_MISMATCH",
        message: "candidateSetId 与预加载候选集不一致。"
      };
    }
    if (currentStamp) {
      const vs = candidateSet.versionStamp;
      if (
        vs.household !== currentStamp.household ||
        vs.inventory !== currentStamp.inventory ||
        vs.intake !== currentStamp.intake ||
        vs.policy !== currentStamp.policy
      ) {
        return {
          status: "failed",
          code: "STALE_CANDIDATE_SET",
          message: "候选集版本已过期，请重新 find_dish_candidates。",
          details: { candidate: vs, current: currentStamp }
        };
      }
    }
    const allowed = new Set(candidateSet.candidates.map((c) => c.templateId));
    for (const dish of input.selectedDishes) {
      if (!allowed.has(dish.templateId)) {
        return {
          status: "failed",
          code: "SELECTION_NOT_IN_CANDIDATES",
          message: `选中的菜 ${dish.templateId} 不在候选集中。`,
          details: { templateId: dish.templateId, candidateSetId: input.candidateSetId }
        };
      }
    }
  } else if (!input.candidateSetId) {
    return {
      status: "failed",
      code: "MISSING_CANDIDATE_SET",
      message: "缺少 candidateSetId。"
    };
  }

  const evaluated = evaluateSelection(catalog, {
    dinerIds: input.dinerIds,
    mealType: input.mealType,
    selectedDishes: input.selectedDishes,
    mealPortionScale: input.mealPortionScale,
    ...(input.mealStructure ? { mealStructure: input.mealStructure } : {}),
    ...(input.remainingNutritionByMember
      ? { remainingNutritionByMember: input.remainingNutritionByMember }
      : {}),
    ...(input.mealBudgetsByMemberId
      ? { mealBudgetsByMemberId: input.mealBudgetsByMemberId }
      : {}),
    ...(input.prepBuffer === undefined ? {} : { prepBuffer: input.prepBuffer }),
    rejectedFoodIds: [
      ...new Set([
        ...(input.rejectedFoodIds ?? []),
        ...(input.bannedFoodIds ?? [])
      ])
    ],
    rejectedTemplateIds: [
      ...new Set([
        ...(input.rejectedTemplateIds ?? []),
        ...(input.bannedTemplateIds ?? [])
      ])
    ]
  });

  if (evaluated.status === "failed") {
    return attachFeasibleRecovery(catalog, input, evaluated);
  }

  const { mealStructure, selectedTemplates, scaled, memberAllocations, memberResults } =
    evaluated;

  const shoppingGap = computeShoppingGapWithUnits({
    preparedBatch: scaled.preparedBatch,
    inventory: catalog.inventory,
    unitRules: input.unitRules ?? []
  });

  const byMember: Record<string, (typeof memberAllocations)[0]["nutrition"]> =
    {};
  for (const allocation of memberAllocations) {
    byMember[allocation.memberId] = allocation.nutrition;
  }
  const householdTotal = memberAllocations.reduce(
    (acc, a) => addNutrition(acc, a.nutrition),
    {
      energyKcal: 0,
      carbohydrateG: 0,
      proteinG: 0,
      fatG: 0,
      sodiumMg: 0
    }
  );

  const plan: MealPlan = {
    id: input.planId ?? `plan-${randomUUID()}`,
    sessionId: input.sessionId,
    version: input.parentPlan ? input.parentPlan.version + 1 : 1,
    parentPlanId: input.parentPlan?.id ?? null,
    status: "valid",
    householdId: input.householdId,
    mealType: input.mealType,
    dinerIds: [...input.dinerIds],
    householdContextVersion: catalog.householdContextVersion,
    inventoryVersion: catalog.inventoryVersion,
    mealPolicyVersion: catalog.mealPolicyVersion,
    bundleId: `agent-selection:${input.candidateSetId}`,
    sharedTemplates: selectedTemplates.map((t) => ({
      templateId: t.id,
      name: t.name,
      role: t.role,
      coversRoles: coveredRoles(t),
      templateVersion: t.templateVersion
    })),
    memberAllocations,
    plannedIntake: {
      byMember: memberAllocations,
      householdTotal: {
        energyKcal: round3(householdTotal.energyKcal),
        carbohydrateG: round3(householdTotal.carbohydrateG),
        proteinG: round3(householdTotal.proteinG),
        fatG: round3(householdTotal.fatG),
        sodiumMg: round3(householdTotal.sodiumMg)
      }
    },
    preparedBatch: scaled.preparedBatch,
    batchIngredients: scaled.preparedBatch,
    prepBuffer: scaled.prepBuffer,
    nutritionSummary: {
      byMember,
      householdTotal: {
        energyKcal: round3(householdTotal.energyKcal),
        carbohydrateG: round3(householdTotal.carbohydrateG),
        proteinG: round3(householdTotal.proteinG),
        fatG: round3(householdTotal.fatG),
        sodiumMg: round3(householdTotal.sodiumMg)
      }
    },
    validationSummary: {
      guardrailsPass: true,
      memberResults
    },
    selectionTrace: {
      candidateBundleIds: [],
      eliminatedBundleIds: [],
      ranking: [],
      selectedBundleId: null,
      foodDataVersion: catalog.foodDataVersion,
      templateVersions: selectedTemplates.map(
        (t) => `${t.id}@${t.templateVersion}`
      ),
      mealPolicyVersion: catalog.mealPolicyVersion,
      agentSelection: {
        candidateSetId: input.candidateSetId,
        selectedDishes: input.selectedDishes,
        mealPortionScale: input.mealPortionScale,
        mealStructure,
        selectionReason: input.selectionReason
      }
    },
    shoppingGap,
    activeConstraintIds: catalog.constraints
      .filter((c) => input.dinerIds.includes(c.memberId))
      .map((c) => c.id),
    rejectedTemplateIds: [],
    rejectedFoodIds: [],
    pinnedTemplateIds: [],
    requestedPriorityFoodIds: [],
    preferLowEffort: false,
    createdAt: new Date().toISOString()
  };

  const planIds = plan.sharedTemplates.map((t) => t.templateId);
  const agentIds = input.selectedDishes.map((d) => d.templateId);
  if (JSON.stringify(planIds) !== JSON.stringify(agentIds)) {
    return {
      status: "failed",
      code: "SELECTION_MUTATED",
      message: "Domain 不得改写 Agent 选定的菜品 ID。"
    };
  }

  return {
    status: "ok",
    plan,
    shoppingGap,
    selectionReason: input.selectionReason,
    mealPortionScale: input.mealPortionScale
  };
}
