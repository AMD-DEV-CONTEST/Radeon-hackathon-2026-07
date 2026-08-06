import type {
  MemberAllocation,
  MemberMealPolicy,
  NutritionPer100g
} from "@privateplate/contracts";

export type GuardrailMemberResult = {
  memberId: string;
  pass: boolean;
  failures: string[];
};

export function evaluateMemberGuardrails(
  allocation: MemberAllocation,
  policy: MemberMealPolicy
): GuardrailMemberResult {
  const failures: string[] = [];
  const n = allocation.nutrition;
  const g = policy.guardrails;

  if (n.energyKcal < g.energyKcal.min || n.energyKcal > g.energyKcal.max) {
    failures.push(
      `energyKcal ${n.energyKcal} outside [${g.energyKcal.min}, ${g.energyKcal.max}]`
    );
  }
  if (
    n.carbohydrateG < g.carbohydrateG.min ||
    n.carbohydrateG > g.carbohydrateG.max
  ) {
    failures.push(
      `carbohydrateG ${n.carbohydrateG} outside [${g.carbohydrateG.min}, ${g.carbohydrateG.max}]`
    );
  }
  if (
    g.proteinG &&
    (n.proteinG < g.proteinG.min || n.proteinG > g.proteinG.max)
  ) {
    failures.push(
      `proteinG ${n.proteinG} outside [${g.proteinG.min}, ${g.proteinG.max}]`
    );
  }
  if (n.sodiumMg > g.sodiumMgMax) {
    failures.push(`sodiumMg ${n.sodiumMg} > ${g.sodiumMgMax}`);
  }

  return {
    memberId: allocation.memberId,
    pass: failures.length === 0,
    failures
  };
}

export function sumNutrition(items: NutritionPer100g[]): NutritionPer100g {
  return items.reduce(
    (acc, n) => ({
      energyKcal: acc.energyKcal + n.energyKcal,
      carbohydrateG: acc.carbohydrateG + n.carbohydrateG,
      proteinG: acc.proteinG + n.proteinG,
      fatG: acc.fatG + n.fatG,
      sodiumMg: acc.sodiumMg + n.sodiumMg
    }),
    { energyKcal: 0, carbohydrateG: 0, proteinG: 0, fatG: 0, sodiumMg: 0 }
  );
}
