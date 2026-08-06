/**
 * Deterministic feasible meal-selection searcher.
 * Catalog-driven only — never hardcodes template/food names or ids.
 */
import type { MealRole, MealStructure, MealTemplate } from "@privateplate/contracts";
import type { PlannerCatalog } from "./compose.js";
import {
  coveredRoles,
  evaluateSelection,
  hardExcludedTemplateIds,
  mealStructureFailure,
  normalizedMealStructure,
  type EvaluateSelectionInput,
  type SelectedDish
} from "./evaluate-selection.js";
import type { RelativePortion } from "./scale-selected.js";
import type { NutritionSnapshot } from "../ledger/types.js";
import type { MemberNutritionBudget } from "@privateplate/contracts";

export type FeasibleSuggestion = {
  selectedDishes: SelectedDish[];
  mealPortionScale: number;
  mealStructure: MealStructure;
};

export type FindFeasibleSelectionInput = {
  dinerIds: string[];
  mealType: "lunch" | "dinner";
  mealStructure?: MealStructure;
  /** When set, search only within these template ids (typically the open candidate set). */
  candidateTemplateIds?: string[];
  remainingNutritionByMember?: Map<string, NutritionSnapshot>;
  mealBudgetsByMemberId?: Map<string, MemberNutritionBudget>;
  prepBuffer?: number;
  /** Explicit caller bans (merged with catalog hard exclusions). */
  bannedFoodIds?: string[];
  bannedTemplateIds?: string[];
  /** Legacy aliases accepted as bans. */
  rejectedFoodIds?: string[];
  rejectedTemplateIds?: string[];
  /**
   * When set with noAdditionalDishes, search only this exact dish set
   * (portion/scale may still vary). Never expands with other catalog dishes.
   */
  pinnedSelection?: SelectedDish[];
  noAdditionalDishes?: boolean;
  /** Upper bound on dish count (one_pot defaults to 1 when unset). */
  maxDishCount?: number;
  /** Optional household energy ceiling for the meal (kcal). */
  maxHouseholdEnergyKcal?: number;
  maxEvaluations?: number;
  maxDurationMs?: number;
};

const MEAL_PORTION_SCALES = [1.0, 0.9, 0.8, 1.1] as const;
const DISH_COUNTS = [3, 4, 5] as const;
const DEFAULT_MAX_EVALUATIONS = 20_000;
const DEFAULT_MAX_DURATION_MS = 50;

function resolveMaxDishCount(
  structure: MealStructure,
  explicit?: number
): number | undefined {
  if (typeof explicit === "number" && Number.isFinite(explicit) && explicit > 0) {
    return Math.trunc(explicit);
  }
  if (structure.mode === "one_pot") return 1;
  return undefined;
}

function mergeIdLists(...lists: Array<string[] | undefined>): string[] {
  const out = new Set<string>();
  for (const list of lists) {
    for (const id of list ?? []) out.add(id);
  }
  return [...out];
}

function compareIds(a: string, b: string): number {
  return a.localeCompare(b);
}

function* combinations(ids: string[], k: number): Generator<string[]> {
  const n = ids.length;
  if (k <= 0 || k > n) return;
  const indices = Array.from({ length: k }, (_, i) => i);
  while (true) {
    yield indices.map((i) => ids[i]!);
    let pivot = k - 1;
    while (pivot >= 0 && indices[pivot] === n - k + pivot) pivot -= 1;
    if (pivot < 0) return;
    indices[pivot]! += 1;
    for (let j = pivot + 1; j < k; j += 1) {
      indices[j] = indices[j - 1]! + 1;
    }
  }
}

function coversStructure(
  templates: MealTemplate[],
  structure: MealStructure
): boolean {
  return mealStructureFailure(templates, structure) === null;
}

type DeficitBias = "lower" | "upper" | "mixed" | "none";

function deficitBiasFromDetails(
  details: Record<string, unknown> | undefined
): DeficitBias {
  const deficits = Array.isArray(details?.deficits)
    ? (details!.deficits as Array<Record<string, unknown>>)
    : [];
  const hasLower = deficits.some(
    (d) => typeof d.deficit === "number" && d.deficit > 0
  );
  const hasUpper = deficits.some(
    (d) => typeof d.excess === "number" && d.excess > 0
  );
  if (hasLower && hasUpper) return "mixed";
  if (hasLower) return "lower";
  if (hasUpper) return "upper";
  const kind = details?.failureKind;
  if (kind === "lower_bound_composition_deficit") return "lower";
  if (kind === "upper_bound_excess") return "upper";
  if (kind === "mixed_guardrail_violation") return "mixed";
  return "none";
}

/**
 * Deterministic relativePortion patterns: all-standard first, then single-dish
 * deviations in the deficit direction, then mild multi-dish adjustments.
 */
function portionPatterns(
  dishCount: number,
  bias: DeficitBias
): RelativePortion[][] {
  const allStandard: RelativePortion[] = Array.from(
    { length: dishCount },
    () => "standard"
  );
  const patterns: RelativePortion[][] = [allStandard];
  const seen = new Set<string>([allStandard.join(",")]);

  const push = (pattern: RelativePortion[]) => {
    const key = pattern.join(",");
    if (seen.has(key)) return;
    seen.add(key);
    patterns.push(pattern);
  };

  const raiseTargets: RelativePortion[] =
    bias === "upper" ? [] : bias === "mixed" ? ["large", "small"] : ["large"];
  const lowerTargets: RelativePortion[] =
    bias === "lower" ? [] : bias === "mixed" ? ["small", "large"] : ["small"];

  for (const portion of [...raiseTargets, ...lowerTargets]) {
    for (let i = 0; i < dishCount; i += 1) {
      const next: RelativePortion[] = [...allStandard];
      next[i] = portion;
      push(next);
    }
  }

  if (bias === "lower" || bias === "mixed") {
    push(Array.from({ length: dishCount }, () => "large" as const));
  }
  if (bias === "upper" || bias === "mixed") {
    push(Array.from({ length: dishCount }, () => "small" as const));
  }

  return patterns;
}

function toSelectedDishes(
  templateIds: string[],
  portions: RelativePortion[]
): SelectedDish[] {
  return templateIds.map((templateId, index) => ({
    templateId,
    relativePortion: portions[index] ?? "standard"
  }));
}

/**
 * Search for the first catalog-feasible selection under the same hard constraints
 * as finalize. Deterministic order; bounded by evaluation count and wall time.
 */
export function findFeasibleSelection(
  catalog: PlannerCatalog,
  input: FindFeasibleSelectionInput
): FeasibleSuggestion | null {
  const started = Date.now();
  const maxEvaluations = input.maxEvaluations ?? DEFAULT_MAX_EVALUATIONS;
  const maxDurationMs = input.maxDurationMs ?? DEFAULT_MAX_DURATION_MS;
  let evaluations = 0;

  const mealStructure = normalizedMealStructure(input.mealStructure);
  const maxDishCount = resolveMaxDishCount(mealStructure, input.maxDishCount);
  const bannedFoodIds = mergeIdLists(input.bannedFoodIds, input.rejectedFoodIds);
  const bannedTemplateIds = mergeIdLists(
    input.bannedTemplateIds,
    input.rejectedTemplateIds
  );
  const hard = hardExcludedTemplateIds(
    catalog.constraints,
    input.dinerIds,
    bannedFoodIds,
    bannedTemplateIds
  );

  const allowed =
    input.candidateTemplateIds && input.candidateTemplateIds.length > 0
      ? new Set(input.candidateTemplateIds)
      : null;

  const templatesById = new Map(catalog.templates.map((t) => [t.id, t]));
  const candidateIds = catalog.templates
    .map((t) => t.id)
    .filter((id) => {
      if (allowed && !allowed.has(id)) return false;
      if (hard.templateIds.has(id)) return false;
      if (bannedTemplateIds.includes(id)) return false;
      const template = templatesById.get(id);
      if (!template) return false;
      if (templateContainsExcludedFoodLocal(template, hard.foodIds)) return false;
      if (
        bannedFoodIds.length > 0 &&
        template.ingredientsPerStandardServing.some((ing) =>
          bannedFoodIds.includes(ing.foodId)
        )
      ) {
        return false;
      }
      return true;
    })
    .sort(compareIds);

  const baseEval: Omit<EvaluateSelectionInput, "selectedDishes" | "mealPortionScale"> =
    {
      dinerIds: input.dinerIds,
      mealType: input.mealType,
      mealStructure,
      ...(input.remainingNutritionByMember
        ? { remainingNutritionByMember: input.remainingNutritionByMember }
        : {}),
      ...(input.mealBudgetsByMemberId
        ? { mealBudgetsByMemberId: input.mealBudgetsByMemberId }
        : {}),
      ...(input.prepBuffer === undefined ? {} : { prepBuffer: input.prepBuffer }),
      ...(bannedFoodIds.length ? { rejectedFoodIds: bannedFoodIds } : {}),
      ...(bannedTemplateIds.length
        ? { rejectedTemplateIds: bannedTemplateIds }
        : {})
    };

  const budgetExceeded = () =>
    evaluations >= maxEvaluations || Date.now() - started >= maxDurationMs;

  const acceptIfOk = (
    result: ReturnType<typeof evaluateSelection>,
    selectedDishes: SelectedDish[],
    mealPortionScale: number
  ): FeasibleSuggestion | null => {
    if (result.status !== "ok") return null;
    if (
      typeof input.maxHouseholdEnergyKcal === "number" &&
      Number.isFinite(input.maxHouseholdEnergyKcal)
    ) {
      const energy = result.memberAllocations.reduce(
        (sum, row) => sum + row.nutrition.energyKcal,
        0
      );
      if (energy > input.maxHouseholdEnergyKcal + 0.5) return null;
    }
    return {
      selectedDishes,
      mealPortionScale,
      mealStructure: result.mealStructure
    };
  };

  const dishCounts = ((): number[] => {
    if (input.noAdditionalDishes && input.pinnedSelection?.length) {
      return [input.pinnedSelection.length];
    }
    if (maxDishCount != null) {
      return DISH_COUNTS.filter((n) => n <= maxDishCount).length
        ? DISH_COUNTS.filter((n) => n <= maxDishCount)
        : maxDishCount >= 1
          ? [maxDishCount]
          : [];
    }
    return [...DISH_COUNTS];
  })();

  if (dishCounts.length === 0) return null;

  // Pinned / no-additional path: only vary portions and scales.
  if (input.noAdditionalDishes && input.pinnedSelection?.length) {
    const pinnedIds = input.pinnedSelection.map((d) => d.templateId);
    if (new Set(pinnedIds).size !== pinnedIds.length) return null;
    if (pinnedIds.some((id) => !candidateIds.includes(id) && !templatesById.has(id))) {
      return null;
    }
    if (maxDishCount != null && pinnedIds.length > maxDishCount) return null;
    const dishCount = pinnedIds.length;
    let lastBias: DeficitBias = "none";
    for (const scale of MEAL_PORTION_SCALES) {
      if (budgetExceeded()) return null;
      evaluations += 1;
      const selectedDishes = input.pinnedSelection.map((d) => ({
        templateId: d.templateId,
        relativePortion: d.relativePortion
      }));
      const result = evaluateSelection(catalog, {
        ...baseEval,
        selectedDishes,
        mealPortionScale: scale
      });
      const accepted = acceptIfOk(result, selectedDishes, scale);
      if (accepted) return accepted;
      if (result.status === "failed") lastBias = deficitBiasFromDetails(result.details);
    }
    for (const pattern of portionPatterns(dishCount, lastBias)) {
      for (const scale of MEAL_PORTION_SCALES) {
        if (budgetExceeded()) return null;
        evaluations += 1;
        const selectedDishes = toSelectedDishes(pinnedIds, pattern);
        const result = evaluateSelection(catalog, {
          ...baseEval,
          selectedDishes,
          mealPortionScale: scale
        });
        const accepted = acceptIfOk(result, selectedDishes, scale);
        if (accepted) return accepted;
      }
    }
    return null;
  }

  for (const dishCount of dishCounts) {
    if (budgetExceeded()) return null;
    for (const combo of combinations(candidateIds, dishCount)) {
      if (budgetExceeded()) return null;
      const templates = combo.map((id) => templatesById.get(id)!);
      if (mealStructure.mode === "standard" && !coversStructure(templates, mealStructure)) {
        continue;
      }
      if (mealStructure.mode === "one_pot" && combo.length !== 1) continue;

      let lastBias: DeficitBias = "none";
      for (const scale of MEAL_PORTION_SCALES) {
        if (budgetExceeded()) return null;
        evaluations += 1;
        const selectedDishes = toSelectedDishes(
          combo,
          Array.from({ length: dishCount }, () => "standard" as const)
        );
        const result = evaluateSelection(catalog, {
          ...baseEval,
          selectedDishes,
          mealPortionScale: scale
        });
        const accepted = acceptIfOk(result, selectedDishes, scale);
        if (accepted) return accepted;
        if (result.status === "failed") {
          lastBias = deficitBiasFromDetails(result.details);
        }
      }

      const patterns = portionPatterns(dishCount, lastBias).filter(
        (pattern) => !pattern.every((p) => p === "standard")
      );
      for (const pattern of patterns) {
        for (const scale of MEAL_PORTION_SCALES) {
          if (budgetExceeded()) return null;
          evaluations += 1;
          const selectedDishes = toSelectedDishes(combo, pattern);
          const result = evaluateSelection(catalog, {
            ...baseEval,
            selectedDishes,
            mealPortionScale: scale
          });
          const accepted = acceptIfOk(result, selectedDishes, scale);
          if (accepted) return accepted;
        }
      }
    }
  }

  return null;
}

function templateContainsExcludedFoodLocal(
  template: MealTemplate,
  foodIds: Set<string>
): boolean {
  return template.ingredientsPerStandardServing.some((ing) =>
    foodIds.has(ing.foodId)
  );
}

/** Test/helper: role coverage check without evaluating nutrition. */
export function selectionCoversRequiredRoles(
  templates: MealTemplate[],
  requiredRoles: MealRole[]
): boolean {
  const covered = new Set<MealRole>();
  for (const template of templates) {
    for (const role of coveredRoles(template)) covered.add(role);
  }
  return requiredRoles.every((role) => covered.has(role));
}
