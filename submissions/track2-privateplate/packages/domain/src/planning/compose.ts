import { randomUUID } from "node:crypto";
import type {
  ComposeFamilyMealInput,
  ComposeFamilyMealResult,
  Food,
  FrozenPreference,
  InventoryItem,
  MealBundleTemplate,
  MealPlan,
  MealTemplate,
  MemberAllocation,
  MemberConstraint,
  MemberMealPolicy,
  NutritionPer100g,
  SelectionTrace,
  ShoppingGapItem
} from "@privateplate/contracts";
import {
  collectHardExclusions,
  filterFeasibleBundles,
  resolveBundleTemplates,
  templateContainsExcludedFood
} from "../bundle-filter.js";
import {
  addNutrition,
  computeTemplateNutrition,
  emptyNutrition,
  nutritionForGrams,
  round3
} from "../nutrition.js";
import { evaluateMemberGuardrails } from "./guardrails.js";
import {
  computePriorityConsumeScore,
  computeRequestedPriorityScore
} from "./priority-score.js";
import { scaleAndAllocate } from "./scale.js";
import { computeShoppingGap } from "./shopping-gap.js";

export type PlannerCatalog = {
  foods: Food[];
  templates: MealTemplate[];
  bundles: MealBundleTemplate[];
  inventory: InventoryItem[];
  members: Array<{ id: string }>;
  constraints: MemberConstraint[];
  mealPolicies: MemberMealPolicy[];
  frozenPreferences: FrozenPreference[];
  householdContextVersion: number;
  inventoryVersion: number;
  mealPolicyVersion: string;
  foodDataVersion: string;
};

function effortRank(templates: MealTemplate[]): number {
  // lower is better when preferLowEffort
  return templates.reduce((sum, t) => sum + (t.tags.effortLevel === "low" ? 0 : 1), 0);
}

function softPreferenceScore(
  templates: MealTemplate[],
  prefs: FrozenPreference[],
  dinerIds: string[]
): number {
  let score = 0;
  const dinerPref = prefs.filter((p) => dinerIds.includes(p.memberId));
  for (const pref of dinerPref) {
    if (pref.kind === "low_oil_preference") {
      if (templates.every((t) => t.tags.oilLevel === "low")) score += 1;
    }
    if (pref.kind === "low_effort_preference") {
      if (templates.every((t) => t.tags.effortLevel === "low")) score += 1;
    }
  }
  return score;
}

function buildMemberAllocations(input: {
  dinerIds: string[];
  memberShares: ReturnType<typeof scaleAndAllocate>["memberShares"];
  portionUnitsByMember: Map<string, Record<"shared_main" | "shared_side" | "staple", number>>;
  foodsById: Map<string, Food>;
}): MemberAllocation[] {
  return input.dinerIds.map((memberId) => {
    const items = input.memberShares
      .filter((s) => s.memberId === memberId)
      .map((s) => ({
        templateId: s.templateId,
        role: s.role,
        foodId: s.foodId,
        quantityG: s.quantityG
      }));

    let nutrition: NutritionPer100g = emptyNutrition();
    for (const item of items) {
      const food = input.foodsById.get(item.foodId);
      if (!food) throw new Error(`UNKNOWN_FOOD:${item.foodId}`);
      nutrition = addNutrition(nutrition, nutritionForGrams(food, item.quantityG));
    }

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
      portionUnitsByRole: input.portionUnitsByMember.get(memberId) ?? {
        shared_main: 0,
        shared_side: 0,
        staple: 0
      }
    };
  });
}

export function composeFamilyMeal(
  catalog: PlannerCatalog,
  input: ComposeFamilyMealInput,
  options?: {
    planId?: string;
    version?: number;
    parentPlanId?: string | null;
    now?: string;
    requirePins?: boolean;
  }
): ComposeFamilyMealResult {
  if (input.householdContextVersion !== catalog.householdContextVersion) {
    throw Object.assign(new Error("STALE_CONTEXT"), { code: "STALE_CONTEXT" });
  }
  if (input.inventoryVersion !== catalog.inventoryVersion) {
    throw Object.assign(new Error("STALE_CONTEXT"), { code: "STALE_CONTEXT" });
  }
  if (input.mealPolicyVersion !== catalog.mealPolicyVersion) {
    throw Object.assign(new Error("STALE_CONTEXT"), { code: "STALE_CONTEXT" });
  }

  const memberIds = new Set(catalog.members.map((m) => m.id));
  for (const dinerId of input.dinerIds) {
    if (!memberIds.has(dinerId)) {
      throw Object.assign(new Error(`Unknown diner ${dinerId}`), {
        code: "VALIDATION_ERROR"
      });
    }
  }

  const sessionConstraints: MemberConstraint[] = [
    ...catalog.constraints.filter((c) => input.dinerIds.includes(c.memberId)),
    ...input.constraints.filter((c) => input.dinerIds.includes(c.memberId))
  ];

  const exclusions = collectHardExclusions(
    sessionConstraints,
    input.rejectedFoodIds,
    input.rejectedTemplateIds
  );

  const foodsById = new Map(catalog.foods.map((f) => [f.id, f]));
  const templatesById = new Map(catalog.templates.map((t) => [t.id, t]));
  const policiesForMeal = catalog.mealPolicies.filter(
    (p) => p.mealType === input.mealType && input.dinerIds.includes(p.memberId)
  );
  const policiesByMemberId = new Map(policiesForMeal.map((p) => [p.memberId, p]));

  for (const dinerId of input.dinerIds) {
    if (!policiesByMemberId.has(dinerId)) {
      throw Object.assign(new Error(`GUARD_CONFIG_MISSING:${dinerId}`), {
        code: "GUARD_CONFIG_MISSING"
      });
    }
  }

  const baseCandidates = filterFeasibleBundles({
    bundles: catalog.bundles,
    templates: catalog.templates,
    foods: catalog.foods,
    exclusions
  });

  // Replans prefer retained dishes. Initial plans treat user-requested dishes
  // as requirements and ask before substituting them.
  const requestedPins = [...new Set(input.pinnedTemplateIds)];
  const pins = requestedPins.filter((id) => {
    if (exclusions.templateIds.has(id)) return false;
    const template = templatesById.get(id);
    return (
      template != null &&
      !templateContainsExcludedFood(template, exclusions.foodIds)
    );
  });
  const pinnedCandidates =
    pins.length > 0
      ? baseCandidates.filter((b) => pins.every((pin) => b.templateIds.includes(pin)))
      : [];
  const allPinsUsable = pins.length === requestedPins.length;
  const candidates =
    options?.requirePins && input.pinnedTemplateIds.length > 0
      ? allPinsUsable
        ? pinnedCandidates
        : []
      : baseCandidates;

  const eliminated = catalog.bundles
    .map((b) => b.id)
    .filter((id) => !candidates.some((c) => c.id === id));

  type Ranked = {
    bundleId: string;
    hardConstraintsPass: boolean;
    requestedPriorityScore: number;
    priorityConsumeScore: number;
    inventoryCoverageScore: number;
    distinctPurchaseCount: number;
    softPreferenceScore: number;
    effortScore: number;
    pinRetentionScore: number;
    tieBreakId: string;
    planDraft: {
      templates: MealTemplate[];
      batchIngredients: ReturnType<typeof scaleAndAllocate>["batchIngredients"];
      memberAllocations: MemberAllocation[];
      shoppingGap: ShoppingGapItem[];
      validation: MealPlan["validationSummary"];
    } | null;
  };

  const ranking: Ranked[] = [];
  const pinnedIdSet = new Set(pinnedCandidates.map((b) => b.id));

  for (const bundle of candidates) {
    const templates = resolveBundleTemplates(bundle, templatesById);
    if (!templates) continue;

    let draft: Ranked["planDraft"] = null;
    let hardPass = false;

    try {
      const scaled = scaleAndAllocate({
        templates,
        policiesByMemberId,
        dinerIds: input.dinerIds
      });
      const memberAllocations = buildMemberAllocations({
        dinerIds: input.dinerIds,
        memberShares: scaled.memberShares,
        portionUnitsByMember: scaled.portionUnitsByMember,
        foodsById
      });

      const memberResults = memberAllocations.map((allocation) =>
        evaluateMemberGuardrails(allocation, policiesByMemberId.get(allocation.memberId)!)
      );
      hardPass = memberResults.every((r) => r.pass);

      const shoppingGap = computeShoppingGap({
        batchIngredients: scaled.batchIngredients,
        inventory: catalog.inventory
      });

      draft = {
        templates,
        batchIngredients: scaled.batchIngredients,
        memberAllocations,
        shoppingGap,
        validation: {
          guardrailsPass: hardPass,
          memberResults
        }
      };
    } catch {
      hardPass = false;
      draft = null;
    }

    const batchIngredients = draft?.batchIngredients ?? [];
    const requestedPriorityScore = computeRequestedPriorityScore({
      requestedFoodIds: input.requestedPriorityFoodIds,
      batchIngredients
    });
    const priorityConsumeScore = computePriorityConsumeScore({
      inventory: catalog.inventory,
      batchIngredients
    });

    const needed = (draft?.shoppingGap ?? []).filter((g) => g.status === "needed");
    const requiredTotal = (draft?.shoppingGap ?? []).reduce(
      (s, g) => s + (g.required.estimateG ?? 0),
      0
    );
    const purchaseTotal = needed.reduce(
      (s, g) => s + (g.purchase.estimateG ?? g.purchase.maxG ?? 0),
      0
    );
    const inventoryCoverageScore =
      requiredTotal <= 0 ? 1 : Math.max(0, 1 - purchaseTotal / requiredTotal);

    const retainedPins = pins.filter((pin) => bundle.templateIds.includes(pin)).length;
    const pinRetentionScore = pins.length === 0 ? 0 : retainedPins / pins.length;

    ranking.push({
      bundleId: bundle.id,
      hardConstraintsPass: hardPass,
      requestedPriorityScore,
      priorityConsumeScore,
      inventoryCoverageScore,
      distinctPurchaseCount: needed.length,
      softPreferenceScore: softPreferenceScore(
        templates,
        catalog.frozenPreferences,
        input.dinerIds
      ),
      effortScore: effortRank(templates),
      pinRetentionScore: pinnedIdSet.has(bundle.id) ? 1 + pinRetentionScore : pinRetentionScore,
      tieBreakId: bundle.id,
      planDraft: hardPass ? draft : null
    });
  }

  ranking.sort((a, b) =>
    compareMealRankingRows(a, b, { preferLowEffort: input.preferLowEffort })
  );

  const selectionTrace: SelectionTrace = {
    candidateBundleIds: candidates.map((c) => c.id).sort(),
    eliminatedBundleIds: eliminated.sort(),
    ranking: ranking.map((r) => ({
      bundleId: r.bundleId,
      hardConstraintsPass: r.hardConstraintsPass,
      requestedPriorityScore: r.requestedPriorityScore,
      priorityConsumeScore: r.priorityConsumeScore,
      inventoryCoverageScore: r.inventoryCoverageScore,
      distinctPurchaseCount: r.distinctPurchaseCount,
      softPreferenceScore: r.softPreferenceScore,
      effortScore: r.effortScore,
      tieBreakId: r.tieBreakId
    })),
    selectedBundleId: null,
    foodDataVersion: catalog.foodDataVersion,
    templateVersions: catalog.templates.map((t) => `${t.id}@${t.templateVersion}`),
    mealPolicyVersion: catalog.mealPolicyVersion
  };

  const winner = ranking.find((r) => r.hardConstraintsPass && r.planDraft);
  if (!winner || !winner.planDraft) {
    return {
      status: "infeasible",
      code: "NO_FEASIBLE_PLAN",
      conflictingConstraintIds: sessionConstraints.map((c) => c.id),
      exhaustedRoles: ["shared_main", "shared_side", "staple"],
      allowedRelaxations: input.rejectedTemplateIds.map((id) => ({
        constraintId: `reject:${id}`,
        userFacingQuestion: `是否可以取消对 ${id} 的拒绝，以便重新规划？`
      })),
      selectionTrace
    };
  }

  selectionTrace.selectedBundleId = winner.bundleId;
  const draft = winner.planDraft;
  const byMember: Record<string, NutritionPer100g> = {};
  for (const allocation of draft.memberAllocations) {
    byMember[allocation.memberId] = allocation.nutrition;
  }
  const householdTotal = draft.memberAllocations.reduce(
    (acc, a) => addNutrition(acc, a.nutrition),
    emptyNutrition()
  );

  // Sanity: template nutrition path is deterministic for provenance.
  for (const template of draft.templates) {
    computeTemplateNutrition(template, foodsById);
  }

  const plan: MealPlan = {
    id: options?.planId ?? `plan-${randomUUID()}`,
    sessionId: input.mealSessionId,
    version: options?.version ?? 1,
    parentPlanId: options?.parentPlanId ?? null,
    status: "valid",
    householdId: input.householdId,
    mealType: input.mealType,
    dinerIds: [...input.dinerIds],
    householdContextVersion: input.householdContextVersion,
    inventoryVersion: input.inventoryVersion,
    mealPolicyVersion: input.mealPolicyVersion,
    bundleId: winner.bundleId,
    sharedTemplates: draft.templates.map((t) => ({
      templateId: t.id,
      name: t.name,
      role: t.role,
      coversRoles: t.tags.coversRoles ?? [t.role],
      templateVersion: t.templateVersion
    })),
    memberAllocations: draft.memberAllocations,
    plannedIntake: {
      byMember: draft.memberAllocations,
      householdTotal: {
        energyKcal: round3(householdTotal.energyKcal),
        carbohydrateG: round3(householdTotal.carbohydrateG),
        proteinG: round3(householdTotal.proteinG),
        fatG: round3(householdTotal.fatG),
        sodiumMg: round3(householdTotal.sodiumMg)
      }
    },
    preparedBatch: draft.batchIngredients,
    batchIngredients: draft.batchIngredients,
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
    validationSummary: draft.validation,
    selectionTrace,
    shoppingGap: draft.shoppingGap,
    activeConstraintIds: sessionConstraints.map((c) => c.id),
    rejectedTemplateIds: [...input.rejectedTemplateIds].sort(),
    rejectedFoodIds: [...input.rejectedFoodIds].sort(),
    pinnedTemplateIds: [...pins].sort(),
    requestedPriorityFoodIds: [...input.requestedPriorityFoodIds].sort(),
    preferLowEffort: input.preferLowEffort,
    createdAt: options?.now ?? new Date().toISOString()
  };

  return {
    status: "valid",
    plan,
    shoppingGap: draft.shoppingGap
  };
}

/** Exported for controlled ranking tests — keep in sync with compose sort. */
export type MealRankingRow = {
  hardConstraintsPass: boolean;
  pinRetentionScore: number;
  requestedPriorityScore: number;
  priorityConsumeScore: number;
  inventoryCoverageScore: number;
  distinctPurchaseCount: number;
  softPreferenceScore: number;
  effortScore: number;
  tieBreakId: string;
};

export function compareMealRankingRows(
  a: MealRankingRow,
  b: MealRankingRow,
  options: { preferLowEffort: boolean }
): number {
  if (a.hardConstraintsPass !== b.hardConstraintsPass) {
    return a.hardConstraintsPass ? -1 : 1;
  }
  if (b.pinRetentionScore !== a.pinRetentionScore) {
    return b.pinRetentionScore - a.pinRetentionScore;
  }
  if (b.requestedPriorityScore !== a.requestedPriorityScore) {
    return b.requestedPriorityScore - a.requestedPriorityScore;
  }
  if (b.priorityConsumeScore !== a.priorityConsumeScore) {
    return b.priorityConsumeScore - a.priorityConsumeScore;
  }
  if (b.inventoryCoverageScore !== a.inventoryCoverageScore) {
    return b.inventoryCoverageScore - a.inventoryCoverageScore;
  }
  if (a.distinctPurchaseCount !== b.distinctPurchaseCount) {
    return a.distinctPurchaseCount - b.distinctPurchaseCount;
  }
  if (b.softPreferenceScore !== a.softPreferenceScore) {
    return b.softPreferenceScore - a.softPreferenceScore;
  }
  if (options.preferLowEffort && a.effortScore !== b.effortScore) {
    return a.effortScore - b.effortScore;
  }
  return a.tieBreakId.localeCompare(b.tieBreakId);
}
