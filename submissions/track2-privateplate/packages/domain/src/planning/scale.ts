import type { MealRole, MealTemplate, MemberMealPolicy } from "@privateplate/contracts";
import { round3 } from "../nutrition.js";

export type BatchIngredient = {
  templateId: string;
  foodId: string;
  quantityG: number;
};

export type MemberIngredientShare = {
  memberId: string;
  templateId: string;
  role: MealRole;
  foodId: string;
  quantityG: number;
};

export function totalPortionUnits(
  policies: MemberMealPolicy[],
  role: MealRole
): number {
  return policies.reduce((sum, policy) => sum + (policy.portionUnitsByRole[role] ?? 0), 0);
}

/**
 * Scale template ingredients to the active diner batch and allocate conservatively
 * so sum(member) == batch within 0.001g.
 */
export function scaleAndAllocate(input: {
  templates: MealTemplate[];
  policiesByMemberId: Map<string, MemberMealPolicy>;
  dinerIds: string[];
}): {
  batchIngredients: BatchIngredient[];
  memberShares: MemberIngredientShare[];
  portionUnitsByMember: Map<string, Record<MealRole, number>>;
} {
  const dinerPolicies = input.dinerIds.map((id) => {
    const policy = input.policiesByMemberId.get(id);
    if (!policy) {
      throw new Error(`GUARD_CONFIG_MISSING:${id}`);
    }
    return policy;
  });

  const portionUnitsByMember = new Map<string, Record<MealRole, number>>();
  for (const policy of dinerPolicies) {
    portionUnitsByMember.set(policy.memberId, {
      shared_main: policy.portionUnitsByRole.shared_main ?? 0,
      shared_side: policy.portionUnitsByRole.shared_side ?? 0,
      staple: policy.portionUnitsByRole.staple ?? 0
    });
  }

  const batchIngredients: BatchIngredient[] = [];
  const memberShares: MemberIngredientShare[] = [];
  const sortedMemberIds = [...input.dinerIds].sort();

  for (const template of input.templates) {
    const role = template.role;
    const totalUnits = totalPortionUnits(dinerPolicies, role);
    if (totalUnits <= 0) {
      throw new Error(`GUARD_CONFIG_MISSING:zero_units:${role}`);
    }

    for (const ingredient of template.ingredientsPerStandardServing) {
      const batchG = round3(ingredient.edibleQuantityG * totalUnits);
      batchIngredients.push({
        templateId: template.id,
        foodId: ingredient.foodId,
        quantityG: batchG
      });

      const rawShares = sortedMemberIds.map((memberId) => {
        const units = portionUnitsByMember.get(memberId)?.[role] ?? 0;
        return {
          memberId,
          raw: (batchG * units) / totalUnits
        };
      });

      // Floor to 0.001g then distribute remainder for conservation.
      const floored = rawShares.map((share) => ({
        memberId: share.memberId,
        quantityG: Math.floor(share.raw * 1000) / 1000
      }));
      let assigned = round3(floored.reduce((s, x) => s + x.quantityG, 0));
      let remainderUnits = Math.round((batchG - assigned) * 1000);
      let idx = 0;
      while (remainderUnits > 0) {
        const target = floored[idx % floored.length]!;
        target.quantityG = round3(target.quantityG + 0.001);
        remainderUnits -= 1;
        idx += 1;
      }

      for (const share of floored) {
        memberShares.push({
          memberId: share.memberId,
          templateId: template.id,
          role,
          foodId: ingredient.foodId,
          quantityG: share.quantityG
        });
      }

      const memberSum = round3(
        floored.reduce((s, x) => s + x.quantityG, 0)
      );
      if (Math.abs(memberSum - batchG) > 0.001) {
        throw new Error(
          `ALLOCATION_CONSERVATION_FAILED:${template.id}:${ingredient.foodId}:${batchG}!=${memberSum}`
        );
      }
    }
  }

  return { batchIngredients, memberShares, portionUnitsByMember };
}
