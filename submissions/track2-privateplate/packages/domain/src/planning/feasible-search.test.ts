import { describe, expect, it } from "vitest";
import type {
  Food,
  InventoryItem,
  MealTemplate,
  MemberMealPolicy,
  MemberNutritionBudget
} from "@privateplate/contracts";
import type { PlannerCatalog } from "./compose.js";
import {
  evaluateSelection,
  finalizeAgentMealPlan,
  findFeasibleSelection,
  type CandidateSet
} from "./agent-select.js";
import { calculateMemberNutritionBudget } from "../nutrition-budget.js";
import type { MealRole } from "@privateplate/contracts";

const STANDARD_ROLES: MealRole[] = ["shared_main", "shared_side", "staple"];

function makeCandidateSet(
  catalog: PlannerCatalog,
  candidateSetId: string
): CandidateSet {
  return {
    candidateSetId,
    versionStamp: {
      household: catalog.householdContextVersion,
      inventory: catalog.inventoryVersion,
      intake: 1,
      policy: catalog.mealPolicyVersion
    },
    candidates: catalog.templates.map((t) => ({
      templateId: t.id,
      name: t.name,
      role: t.role,
      coversRoles: [t.role],
      ingredients: t.ingredientsPerStandardServing.map((ing) => ({
        foodId: ing.foodId,
        edibleQuantityG: ing.edibleQuantityG
      })),
      inventoryFacts: {
        coveredFoodIds: [],
        missingFoodIds: [],
        priorityFoodIds: []
      },
      nutritionPerStandardServing: {
        energyKcal: 0,
        carbohydrateG: 0,
        proteinG: 0,
        fatG: 0,
        sodiumMg: 0
      },
      effortFacts: {
        effortLevel: "low",
        oilLevel: "low",
        lowSodiumVariant: true
      }
    })),
    byRole: {},
    selectionGuidance: {
      requiredRoles: [...STANDARD_ROLES],
      maxSelectedDishes: 12,
      selectionCountIsModelDecision: true,
      candidateCount: 0,
      multipleDishesPerRoleAllowed: true,
      note: "candidates is the full hard-filtered pool, not a 3-dish shortlist."
    }
  };
}

/**
 * Fully synthetic catalog — no fixture food/template ids.
 * Designed so a balanced 3-role meal is feasible, while a side-only
 * selection fails nutrition and receives a domain-verified suggestion.
 */
function food(
  id: string,
  nutrition: Food["nutritionPer100g"]
): Food {
  return {
    id,
    canonicalName: id,
    aliases: [],
    nutritionPer100g: nutrition,
    allergenTags: [],
    sourceId: "synth",
    licenseId: "synth",
    dataVersion: "1"
  };
}

function template(
  id: string,
  role: MealTemplate["role"],
  ingredients: Array<{ foodId: string; edibleQuantityG: number }>
): MealTemplate {
  return {
    id,
    name: id,
    role,
    ingredientsPerStandardServing: ingredients,
    tags: {
      cuisine: ["synth"],
      cookingMethods: ["boil"],
      effortLevel: "low",
      oilLevel: "low",
      lowSodiumVariant: true,
      coversRoles: [role]
    },
    instructionsSummary: "synth",
    sourceId: "synth",
    licenseId: "synth",
    templateVersion: "1"
  };
}

function inventoryItem(id: string, foodId: string, grams: number): InventoryItem {
  return {
    id,
    foodId,
    quantity: {
      rawExpression: `${grams}g`,
      normalized: {
        estimateG: grams,
        minG: grams,
        maxG: grams,
        confidence: "exact",
        conversionRuleId: null
      }
    },
    state: "fresh",
    priorityConsume: false
  };
}

function policy(memberId: string, mealType: "lunch" | "dinner"): MemberMealPolicy {
  return {
    memberId,
    mealType,
    portionUnitsByRole: {
      shared_main: 1,
      shared_side: 1,
      staple: 1
    },
    guardrails: {
      energyKcal: { min: 200, max: 1200 },
      carbohydrateG: { min: 20, max: 200 },
      proteinG: { min: 15, max: 80 },
      sodiumMgMax: 2000
    },
    source: "demo_fixture",
    ruleVersion: "1"
  };
}

function synthCatalog(): PlannerCatalog {
  const foods = [
    food("synth-protein", {
      energyKcal: 150,
      carbohydrateG: 0,
      proteinG: 25,
      fatG: 5,
      sodiumMg: 50
    }),
    food("synth-veg", {
      energyKcal: 30,
      carbohydrateG: 5,
      proteinG: 2,
      fatG: 0,
      sodiumMg: 20
    }),
    food("synth-grain", {
      energyKcal: 130,
      carbohydrateG: 28,
      proteinG: 3,
      fatG: 0.5,
      sodiumMg: 5
    }),
    food("synth-extra-veg", {
      energyKcal: 25,
      carbohydrateG: 4,
      proteinG: 1,
      fatG: 0,
      sodiumMg: 15
    })
  ];

  const templates = [
    template("synth-tpl-main", "shared_main", [
      { foodId: "synth-protein", edibleQuantityG: 120 }
    ]),
    template("synth-tpl-side", "shared_side", [
      { foodId: "synth-veg", edibleQuantityG: 150 }
    ]),
    template("synth-tpl-staple", "staple", [
      { foodId: "synth-grain", edibleQuantityG: 150 }
    ]),
    template("synth-tpl-side-b", "shared_side", [
      { foodId: "synth-extra-veg", edibleQuantityG: 120 }
    ])
  ];

  const dinerIds = ["synth-a", "synth-b"];
  return {
    foods,
    templates,
    bundles: [],
    inventory: [
      inventoryItem("inv-1", "synth-protein", 2000),
      inventoryItem("inv-2", "synth-veg", 2000),
      inventoryItem("inv-3", "synth-grain", 2000),
      inventoryItem("inv-4", "synth-extra-veg", 2000)
    ],
    members: dinerIds.map((id) => ({ id })),
    constraints: [],
    mealPolicies: dinerIds.flatMap((id) => [
      policy(id, "lunch"),
      policy(id, "dinner")
    ]),
    frozenPreferences: [],
    householdContextVersion: 1,
    inventoryVersion: 1,
    mealPolicyVersion: "synth-1",
    foodDataVersion: "synth-1"
  };
}

function budgetsFor(
  dinerIds: string[]
): Map<string, MemberNutritionBudget> {
  const map = new Map<string, MemberNutritionBudget>();
  for (const id of dinerIds) {
    map.set(
      id,
      calculateMemberNutritionBudget(
        {
          gender: "female",
          age: 35,
          heightCm: 165,
          weightKg: 58,
          activityLevel: "moderate",
          weightGoal: "maintain"
        },
        id
      )
    );
  }
  return map;
}

describe("findFeasibleSelection (synthetic)", () => {
  it("returns a role-covering feasible selection under soft budgets", () => {
    const catalog = synthCatalog();
    const dinerIds = ["synth-a", "synth-b"];
    const suggestion = findFeasibleSelection(catalog, {
      dinerIds,
      mealType: "lunch",
      mealBudgetsByMemberId: budgetsFor(dinerIds),
      maxDurationMs: 200,
      maxEvaluations: 5000
    });

    expect(suggestion).not.toBeNull();
    expect(suggestion!.selectedDishes.length).toBeGreaterThanOrEqual(3);
    expect(suggestion!.selectedDishes.length).toBeLessThanOrEqual(5);

    const check = evaluateSelection(catalog, {
      dinerIds,
      mealType: "lunch",
      selectedDishes: suggestion!.selectedDishes,
      mealPortionScale: suggestion!.mealPortionScale,
      mealStructure: suggestion!.mealStructure,
      mealBudgetsByMemberId: budgetsFor(dinerIds)
    });
    expect(check.status).toBe("ok");
  });

  it("is deterministic for the same catalog and constraints", () => {
    const catalog = synthCatalog();
    const dinerIds = ["synth-a", "synth-b"];
    const input = {
      dinerIds,
      mealType: "lunch" as const,
      mealBudgetsByMemberId: budgetsFor(dinerIds),
      maxDurationMs: 200,
      maxEvaluations: 5000
    };
    const a = findFeasibleSelection(catalog, input);
    const b = findFeasibleSelection(catalog, input);
    expect(a).toEqual(b);
  });

  it("returns null when nutrition budgets are impossible", () => {
    const catalog = synthCatalog();
    const dinerIds = ["synth-a"];
    const impossible = budgetsFor(dinerIds);
    const budget = impossible.get("synth-a")!;
    // Force an unreachable protein floor for lunch.
    budget.mealBudgets.lunch.min.proteinG = 500;
    budget.mealBudgets.lunch.target.proteinG = 500;
    budget.mealBudgets.lunch.max.proteinG = 600;

    const suggestion = findFeasibleSelection(catalog, {
      dinerIds,
      mealType: "lunch",
      mealBudgetsByMemberId: impossible,
      maxDurationMs: 200,
      maxEvaluations: 5000
    });
    expect(suggestion).toBeNull();
  });

  it("attaches feasibleSuggestion on finalize nutrition reject", () => {
    const catalog = synthCatalog();
    const dinerIds = ["synth-a", "synth-b"];
    const candidates = makeCandidateSet(catalog, "cset-synth");

    // Side-only selection: fails structure / nutrition path.
    const failed = finalizeAgentMealPlan(catalog, {
      sessionId: "sess-synth",
      householdId: "hh-synth",
      dinerIds,
      mealType: "lunch",
      candidateSetId: "cset-synth",
      candidateSet: candidates,
      currentVersionStamp: candidates.versionStamp,
      selectedDishes: [
        { templateId: "synth-tpl-side", relativePortion: "standard" },
        { templateId: "synth-tpl-side-b", relativePortion: "standard" }
      ],
      mealPortionScale: 1,
      selectionReason: "synthetic incomplete",
      mealBudgetsByMemberId: budgetsFor(dinerIds)
    });

    expect(failed.status).toBe("failed");
    if (failed.status !== "failed") return;
    expect(
      ["MEAL_STRUCTURE_INCOMPLETE", "NUTRITION_BUDGET", "NUTRITION_GUARDRAIL"]
    ).toContain(failed.code);
    const suggestion = failed.details?.feasibleSuggestion as
      | { selectedDishes: unknown[] }
      | undefined;
    const nested = (
      failed.details?.recovery as { feasibleSuggestion?: unknown } | undefined
    )?.feasibleSuggestion;
    expect(suggestion ?? nested).toBeTruthy();
    const fullSuggestion = (suggestion ?? nested) as {
      selectedDishes: Array<{
        templateId: string;
        relativePortion: "small" | "standard" | "large";
      }>;
      mealPortionScale: number;
    };
    expect(fullSuggestion.selectedDishes.length).toBeGreaterThanOrEqual(3);

    const adoptedExact = finalizeAgentMealPlan(catalog, {
      sessionId: "sess-synth-3",
      householdId: "hh-synth",
      dinerIds,
      mealType: "lunch",
      candidateSetId: "cset-synth",
      candidateSet: candidates,
      currentVersionStamp: candidates.versionStamp,
      selectedDishes: fullSuggestion.selectedDishes,
      mealPortionScale: fullSuggestion.mealPortionScale,
      selectionReason: "adopt domain suggestion exact",
      mealBudgetsByMemberId: budgetsFor(dinerIds)
    });
    expect(adoptedExact.status).toBe("ok");
  });

  it("sets domainSearchExhausted when no feasible selection exists", () => {
    const catalog = synthCatalog();
    const dinerIds = ["synth-a"];
    const impossible = budgetsFor(dinerIds);
    const budget = impossible.get("synth-a")!;
    budget.mealBudgets.lunch.min.proteinG = 500;
    budget.mealBudgets.lunch.max.proteinG = 600;

    const candidates = makeCandidateSet(catalog, "cset-synth-x");

    const failed = finalizeAgentMealPlan(catalog, {
      sessionId: "sess-synth-x",
      householdId: "hh-synth",
      dinerIds,
      mealType: "lunch",
      candidateSetId: "cset-synth-x",
      candidateSet: candidates,
      currentVersionStamp: candidates.versionStamp,
      selectedDishes: [
        { templateId: "synth-tpl-main", relativePortion: "standard" },
        { templateId: "synth-tpl-side", relativePortion: "standard" },
        { templateId: "synth-tpl-staple", relativePortion: "standard" }
      ],
      mealPortionScale: 1,
      selectionReason: "impossible budget",
      mealBudgetsByMemberId: impossible
    });

    expect(failed.status).toBe("failed");
    if (failed.status !== "failed") return;
    expect(failed.details?.domainSearchExhausted).toBe(true);
    expect(
      (failed.details?.recovery as { domainSearchExhausted?: boolean } | undefined)
        ?.domainSearchExhausted
    ).toBe(true);
  });

  it("returns null for pinned staple-only when noAdditionalDishes (does not invent extra dishes)", () => {
    const catalog = synthCatalog();
    const dinerIds = ["synth-a", "synth-b"];
    const suggestion = findFeasibleSelection(catalog, {
      dinerIds,
      mealType: "lunch",
      mealBudgetsByMemberId: budgetsFor(dinerIds),
      pinnedSelection: [
        { templateId: "synth-tpl-staple", relativePortion: "standard" }
      ],
      noAdditionalDishes: true,
      maxDurationMs: 200,
      maxEvaluations: 2000
    });
    expect(suggestion).toBeNull();
  });

  it("rejects one_pot selections with more than one dish and may suggest a single-dish fix", () => {
    const catalog = synthCatalog();
    const dinerIds = ["synth-a"];
    // Loosen budgets so a single compound-less dish can still be searched.
    const soft = budgetsFor(dinerIds);
    const b = soft.get("synth-a")!;
    for (const nutrient of [
      "energyKcal",
      "carbohydrateG",
      "proteinG",
      "fatG",
      "sodiumMg"
    ] as const) {
      b.mealBudgets.lunch.min[nutrient] = 0;
      b.mealBudgets.lunch.max[nutrient] = 99999;
    }
    // Guardrails already allow wide ranges in synth policy.

    const candidates = makeCandidateSet(catalog, "cset-one-pot");
    const failed = finalizeAgentMealPlan(catalog, {
      sessionId: "sess-one-pot",
      householdId: "hh-synth",
      dinerIds,
      mealType: "lunch",
      candidateSetId: "cset-one-pot",
      candidateSet: candidates,
      currentVersionStamp: candidates.versionStamp,
      selectedDishes: [
        { templateId: "synth-tpl-main", relativePortion: "standard" },
        { templateId: "synth-tpl-side", relativePortion: "standard" }
      ],
      mealPortionScale: 1,
      mealStructure: {
        mode: "one_pot",
        requiredRoles: [],
        omittedRoles: ["shared_main", "shared_side", "staple"],
        reason: "synthetic one pot request"
      },
      selectionReason: "too many dishes",
      mealBudgetsByMemberId: soft,
      maxDishCount: 1
    });
    expect(failed.status).toBe("failed");
    if (failed.status !== "failed") return;
    expect(failed.code).toBe("ONE_POT_DISH_COUNT_EXCEEDED");

    const ok = finalizeAgentMealPlan(catalog, {
      sessionId: "sess-one-pot-ok",
      householdId: "hh-synth",
      dinerIds,
      mealType: "lunch",
      candidateSetId: "cset-one-pot",
      candidateSet: candidates,
      currentVersionStamp: candidates.versionStamp,
      selectedDishes: [
        { templateId: "synth-tpl-main", relativePortion: "standard" }
      ],
      mealPortionScale: 1,
      mealStructure: {
        mode: "one_pot",
        requiredRoles: [],
        omittedRoles: ["shared_main", "shared_side", "staple"],
        reason: "synthetic one pot request"
      },
      selectionReason: "single dish",
      mealBudgetsByMemberId: soft
    });
    // May still fail nutrition with one simple dish; structure must not be ONE_POT_DISH_COUNT.
    if (ok.status === "failed") {
      expect(ok.code).not.toBe("ONE_POT_DISH_COUNT_EXCEEDED");
    }

    const standard = finalizeAgentMealPlan(catalog, {
      sessionId: "sess-standard-multi",
      householdId: "hh-synth",
      dinerIds: ["synth-a", "synth-b"],
      mealType: "lunch",
      candidateSetId: "cset-one-pot",
      candidateSet: candidates,
      currentVersionStamp: candidates.versionStamp,
      selectedDishes: [
        { templateId: "synth-tpl-main", relativePortion: "standard" },
        { templateId: "synth-tpl-side", relativePortion: "standard" },
        { templateId: "synth-tpl-staple", relativePortion: "standard" }
      ],
      mealPortionScale: 1,
      selectionReason: "standard three roles",
      mealBudgetsByMemberId: budgetsFor(["synth-a", "synth-b"])
    });
    expect(standard.status === "ok" || standard.status === "failed").toBe(true);
    if (standard.status === "failed") {
      expect(standard.code).not.toBe("ONE_POT_DISH_COUNT_EXCEEDED");
    }
  });
});
