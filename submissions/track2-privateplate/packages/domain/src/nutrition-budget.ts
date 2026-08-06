import type {
  MealBudgetBounds,
  MemberNutritionBudget,
  MemberNutritionProfile,
  NutritionSnapshot
} from "@privateplate/contracts";

export const NUTRITION_BUDGET_VERSION = "engineering-demo-1.0.0";
export const DEFAULT_PREP_BUFFER = 0.08;

const ACTIVITY_FACTORS = {
  low: 1.2,
  moderate: 1.4,
  high: 1.6
} as const;

const MEAL_RATIOS = {
  energy: { breakfast: 0.15, lunch: 0.4, dinner: 0.4, snack: 0.05 },
  carbohydrate: { breakfast: 0.15, lunch: 0.4, dinner: 0.4, snack: 0.05 },
  protein: { breakfast: 0.05, lunch: 0.45, dinner: 0.45, snack: 0.05 },
  fat: { breakfast: 0.15, lunch: 0.4, dinner: 0.4, snack: 0.05 },
  sodium: { breakfast: 0.15, lunch: 0.4, dinner: 0.4, snack: 0.05 }
} as const;

type MealSlot = keyof typeof MEAL_RATIOS.energy;

function round1(value: number): number {
  return Math.round(value * 10) / 10;
}

function round10(value: number): number {
  return Math.round(value / 10) * 10;
}

function ageOf(profile: MemberNutritionProfile, currentYear: number): number | null {
  if (profile.age != null) return profile.age;
  if (profile.birthYear != null) return Math.max(1, currentYear - profile.birthYear);
  return null;
}

function emptyNutrition(): NutritionSnapshot {
  return {
    energyKcal: 0,
    carbohydrateG: 0,
    proteinG: 0,
    fatG: 0,
    sodiumMg: 0
  };
}

function scaleNutrition(
  daily: NutritionSnapshot,
  slot: MealSlot,
  reserveRate: number
): MealBudgetBounds {
  const energyTarget = daily.energyKcal * MEAL_RATIOS.energy[slot];
  const carbohydrateTarget =
    daily.carbohydrateG * MEAL_RATIOS.carbohydrate[slot];
  const proteinTarget = daily.proteinG * MEAL_RATIOS.protein[slot];
  const fatTarget = daily.fatG * MEAL_RATIOS.fat[slot];
  const sodiumTarget = daily.sodiumMg * MEAL_RATIOS.sodium[slot];
  const target: NutritionSnapshot = {
    energyKcal: round1(energyTarget),
    carbohydrateG: round1(carbohydrateTarget),
    proteinG: round1(proteinTarget),
    fatG: round1(fatTarget),
    sodiumMg: round1(sodiumTarget)
  };
  const reserve: NutritionSnapshot = {
    energyKcal: round1(energyTarget * reserveRate),
    carbohydrateG: round1(carbohydrateTarget * reserveRate),
    proteinG: round1(proteinTarget * reserveRate),
    fatG: round1(fatTarget * reserveRate),
    sodiumMg: round1(sodiumTarget * reserveRate)
  };
  return {
    target,
    min: {
      energyKcal: round1(energyTarget * 0.4),
      carbohydrateG: round1(carbohydrateTarget * 0.2),
      proteinG: round1(proteinTarget * 0.5),
      fatG: round1(fatTarget * 0.25),
      sodiumMg: 0
    },
    max: {
      energyKcal: round1(Math.max(0, energyTarget - reserve.energyKcal)),
      carbohydrateG: round1(Math.max(0, carbohydrateTarget - reserve.carbohydrateG)),
      proteinG: round1(Math.max(0, proteinTarget - reserve.proteinG)),
      fatG: round1(Math.max(0, fatTarget - reserve.fatG)),
      sodiumMg: round1(Math.max(0, sodiumTarget - reserve.sodiumMg))
    },
    reserve
  };
}

export function calculateMemberNutritionBudget(
  profile: MemberNutritionProfile | undefined,
  memberId: string,
  options: { currentYear?: number; reserveRate?: number } = {}
): MemberNutritionBudget {
  const reserveRate = options.reserveRate ?? 0.12;
  const currentYear = options.currentYear ?? new Date().getFullYear();
  const normalizedReserveRate = Math.min(0.15, Math.max(0.1, reserveRate));

  if (!profile) {
    const dailyTarget: NutritionSnapshot = {
      energyKcal: 1800,
      carbohydrateG: 200,
      proteinG: 80,
      fatG: 55,
      sodiumMg: 2000
    };
    return {
      memberId,
      dailyTarget,
      mealBudgets: {
        breakfast: scaleNutrition(dailyTarget, "breakfast", normalizedReserveRate),
        lunch: scaleNutrition(dailyTarget, "lunch", normalizedReserveRate),
        dinner: scaleNutrition(dailyTarget, "dinner", normalizedReserveRate),
        snack: scaleNutrition(dailyTarget, "snack", normalizedReserveRate)
      },
      calculation: {
        method: "fallback_demo_estimate",
        bmrKcal: 1600,
        tdeeKcal: 1800,
        activityFactor: 1.2,
        goalAdjustment: 1
      },
      source: "engineering_estimate",
      version: NUTRITION_BUDGET_VERSION,
      applicability: {
        fullySupportedMealTypes: ["lunch", "dinner"],
        extensionMealSlots: ["breakfast", "snack"],
        boundary:
          "仅用于 PrivatePlate 合成演示；不是医疗诊断、治疗建议或个体化处方。"
      }
    };
  }

  const age = ageOf(profile, currentYear);
  const activityFactor = ACTIVITY_FACTORS[profile.activityLevel];
  const genderOffset =
    profile.gender === "male" ? 5 : profile.gender === "female" ? -161 : -78;
  const bmr =
    age == null
      ? 1600
      : 10 * profile.weightKg +
        6.25 * profile.heightCm -
        5 * age +
        genderOffset;
  const goalAdjustment =
    profile.weightGoal === "loss"
      ? 0.9
      : profile.weightGoal === "gain"
        ? 1.05
        : 1;
  const tdee = Math.max(1400, bmr * activityFactor);
  const energyKcal = round10(Math.max(1400, tdee * goalAdjustment));
  const dailyTarget: NutritionSnapshot = {
    energyKcal,
    carbohydrateG: round1((energyKcal * 0.45) / 4),
    proteinG: round1(Math.max(75, profile.weightKg * 1.6)),
    fatG: round1(Math.max(40, (energyKcal * 0.28) / 9)),
    sodiumMg: 2000
  };

  return {
    memberId,
    dailyTarget,
    mealBudgets: {
      breakfast: scaleNutrition(dailyTarget, "breakfast", normalizedReserveRate),
      lunch: scaleNutrition(dailyTarget, "lunch", normalizedReserveRate),
      dinner: scaleNutrition(dailyTarget, "dinner", normalizedReserveRate),
      snack: scaleNutrition(dailyTarget, "snack", normalizedReserveRate)
    },
    calculation: {
      method: "mifflin_st_jeor",
      bmrKcal: round1(Math.max(0, bmr)),
      tdeeKcal: round1(tdee),
      activityFactor,
      goalAdjustment
    },
    source: "engineering_estimate",
    version: NUTRITION_BUDGET_VERSION,
    applicability: {
      fullySupportedMealTypes: ["lunch", "dinner"],
      extensionMealSlots: ["breakfast", "snack"],
      boundary:
        "依据合成成员资料和工程公式估算；不替代医生、营养师或权威食物数据库。"
    }
  };
}

export function calculateHouseholdNutritionBudget(
  profiles: Array<{ memberId: string; profile?: MemberNutritionProfile }>,
  options: { currentYear?: number; reserveRate?: number } = {}
) {
  const members = profiles.map(({ memberId, profile }) =>
    calculateMemberNutritionBudget(profile, memberId, options)
  );
  const dailyTarget = members.reduce<NutritionSnapshot>(
    (total, member) => ({
      energyKcal: round1(total.energyKcal + member.dailyTarget.energyKcal),
      carbohydrateG: round1(total.carbohydrateG + member.dailyTarget.carbohydrateG),
      proteinG: round1(total.proteinG + member.dailyTarget.proteinG),
      fatG: round1(total.fatG + member.dailyTarget.fatG),
      sodiumMg: round1(total.sodiumMg + member.dailyTarget.sodiumMg)
    }),
    emptyNutrition()
  );
  return { members, dailyTarget };
}
