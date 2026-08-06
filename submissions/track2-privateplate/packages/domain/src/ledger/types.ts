import type {
  MealBudgetBounds,
  MemberNutritionBudget,
  MemberNutritionProfile
} from "@privateplate/contracts";

export type NutritionSnapshot = {
  energyKcal: number;
  carbohydrateG: number;
  proteinG: number;
  fatG: number;
  sodiumMg: number;
};

export type MemberDailyTarget = {
  memberId: string;
  energyKcal: number;
  carbohydrateG: number;
  proteinG: number;
  fatG: number;
  sodiumMg: number;
  source: string;
  version: number;
};

export type MemberIntakeSummary = {
  memberId: string;
  target: NutritionSnapshot;
  consumed: NutritionSnapshot;
  remaining: NutritionSnapshot;
  nutritionBudget: MemberNutritionBudget;
};

export type DayContext = {
  householdId: string;
  serviceDate: string;
  timeZone: string;
  householdContextVersion: number;
  inventoryVersion: number;
  intakeVersion: number;
  mealPolicyVersion: string;
  members: Array<{
    id: string;
    displayName: string;
    roleLabel: string | null;
    nutritionProfile?: MemberNutritionProfile;
    healthFacts: Array<{
      id: string;
      kind: string;
      summary: string;
      source: string;
    }>;
    preferences: Array<{
      id: string;
      kind: string;
      note: string;
      polarity: string;
      targetType: string;
      targetId: string | null;
    }>;
    hardConstraints: Array<{
      id: string;
      kind: string;
      targetId: string;
    }>;
    nutritionBudget: MemberNutritionBudget;
  }>;
  inventory: Array<{
    id: string;
    foodId: string | null;
    rawName: string;
    priorityUse: boolean;
    quantity: {
      estimateG: number | null;
      minG: number | null;
      maxG: number | null;
      confidence: string;
    };
  }>;
  unitConversionRules: Array<{
    id: string;
    foodId: string;
    rawUnit: string;
    gramsPerUnit: number;
    confidence: string;
  }>;
  completedMeals: Array<{
    id: string;
    mealType: string;
    planId: string | null;
    planVersion: number | null;
    completedAt: string | null;
    dinerIds: string[];
  }>;
  memberIntake: MemberIntakeSummary[];
  householdIntake: {
    target: NutritionSnapshot;
    consumed: NutritionSnapshot;
    remaining: NutritionSnapshot;
    mealBudgets: Record<"breakfast" | "lunch" | "dinner" | "snack", MealBudgetBounds>;
  };
};

export function emptyNutritionSnapshot(): NutritionSnapshot {
  return {
    energyKcal: 0,
    carbohydrateG: 0,
    proteinG: 0,
    fatG: 0,
    sodiumMg: 0
  };
}

export function addNutritionSnapshots(
  a: NutritionSnapshot,
  b: NutritionSnapshot
): NutritionSnapshot {
  return {
    energyKcal: a.energyKcal + b.energyKcal,
    carbohydrateG: a.carbohydrateG + b.carbohydrateG,
    proteinG: a.proteinG + b.proteinG,
    fatG: a.fatG + b.fatG,
    sodiumMg: a.sodiumMg + b.sodiumMg
  };
}

export function remainingNutrition(
  target: NutritionSnapshot,
  consumed: NutritionSnapshot
): NutritionSnapshot {
  return {
    energyKcal: Math.max(0, target.energyKcal - consumed.energyKcal),
    carbohydrateG: Math.max(0, target.carbohydrateG - consumed.carbohydrateG),
    proteinG: Math.max(0, target.proteinG - consumed.proteinG),
    fatG: Math.max(0, target.fatG - consumed.fatG),
    sodiumMg: Math.max(0, target.sodiumMg - consumed.sodiumMg)
  };
}

/** Default demo daily targets derived from meal-policy guardrail midpoints × 2 meals. */
export const DEMO_DAILY_TARGETS: Record<string, NutritionSnapshot> = {
  "mem-admin": {
    energyKcal: 1900,
    carbohydrateG: 230,
    proteinG: 80,
    fatG: 60,
    sodiumMg: 2000
  },
  "mem-father": {
    energyKcal: 1800,
    carbohydrateG: 180,
    proteinG: 85,
    fatG: 55,
    sodiumMg: 2000
  },
  "mem-mother": {
    energyKcal: 1700,
    carbohydrateG: 200,
    proteinG: 75,
    fatG: 50,
    sodiumMg: 1800
  }
};
