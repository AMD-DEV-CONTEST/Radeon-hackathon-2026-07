import type {
  ComposeFamilyMealInput,
  ConstraintDelta,
  MealPlan,
  PlanDiff,
  ReplanFamilyMealInput
} from "@privateplate/contracts";
import { composeFamilyMeal, type PlannerCatalog } from "./compose.js";

export type ReplanResult =
  | {
      status: "valid";
      plan: MealPlan;
      diff: PlanDiff;
      shoppingGap: MealPlan["shoppingGap"];
    }
  | {
      status: "infeasible";
      code: "NO_FEASIBLE_PLAN";
      parentPlan: MealPlan;
      result: ReturnType<typeof composeFamilyMeal>;
    };

function applyDeltas(
  parent: MealPlan,
  deltas: ConstraintDelta[]
): Pick<
  ComposeFamilyMealInput,
  | "rejectedTemplateIds"
  | "rejectedFoodIds"
  | "pinnedTemplateIds"
  | "preferLowEffort"
  | "requestedPriorityFoodIds"
> {
  const rejectedTemplateIds = new Set(parent.rejectedTemplateIds);
  const rejectedFoodIds = new Set(parent.rejectedFoodIds);
  const pinnedTemplateIds = new Set(
    parent.sharedTemplates.map((t) => t.templateId)
  );
  let preferLowEffort = parent.preferLowEffort;

  for (const delta of deltas) {
    if (delta.kind === "reject_template") {
      if (delta.operation === "add") {
        rejectedTemplateIds.add(delta.targetId);
        pinnedTemplateIds.delete(delta.targetId);
      } else {
        rejectedTemplateIds.delete(delta.targetId);
      }
    }
    if (delta.kind === "reject_food") {
      if (delta.operation === "add") rejectedFoodIds.add(delta.targetId);
      else rejectedFoodIds.delete(delta.targetId);
    }
    if (delta.kind === "pin_template") {
      if (delta.operation === "add") pinnedTemplateIds.add(delta.targetId);
      else pinnedTemplateIds.delete(delta.targetId);
    }
    if (delta.kind === "prefer_low_effort") {
      preferLowEffort = delta.operation === "add";
    }
  }

  // Drop pins that conflict with new rejects.
  for (const id of [...pinnedTemplateIds]) {
    if (rejectedTemplateIds.has(id)) pinnedTemplateIds.delete(id);
  }

  return {
    rejectedTemplateIds: [...rejectedTemplateIds],
    rejectedFoodIds: [...rejectedFoodIds],
    pinnedTemplateIds: [...pinnedTemplateIds],
    preferLowEffort,
    requestedPriorityFoodIds: [...parent.requestedPriorityFoodIds]
  };
}

export function buildPlanDiff(parent: MealPlan, next: MealPlan): PlanDiff {
  const parentTemplates = new Set(parent.sharedTemplates.map((t) => t.templateId));
  const nextTemplates = new Set(next.sharedTemplates.map((t) => t.templateId));

  const retainedTemplateIds = [...parentTemplates].filter((id) => nextTemplates.has(id)).sort();
  const removedTemplateIds = [...parentTemplates].filter((id) => !nextTemplates.has(id)).sort();
  const addedTemplateIds = [...nextTemplates].filter((id) => !parentTemplates.has(id)).sort();

  const parentAlloc = new Map<string, number>();
  for (const member of parent.memberAllocations) {
    for (const item of member.items) {
      parentAlloc.set(`${member.memberId}:${item.templateId}:${item.foodId}`, item.quantityG);
    }
  }

  const changedAllocations: PlanDiff["changedAllocations"] = [];
  for (const member of next.memberAllocations) {
    for (const item of member.items) {
      const key = `${member.memberId}:${item.templateId}:${item.foodId}`;
      const before = parentAlloc.get(key);
      if (before == null || before !== item.quantityG) {
        changedAllocations.push({
          memberId: member.memberId,
          itemId: `${item.templateId}:${item.foodId}`,
          before: before ?? 0,
          after: item.quantityG,
          unit: "g"
        });
      }
    }
  }

  const parentGap = JSON.stringify(parent.shoppingGap);
  const nextGap = JSON.stringify(next.shoppingGap);

  return {
    retainedTemplateIds,
    removedTemplateIds,
    addedTemplateIds,
    changedAllocations,
    shoppingGapChanged: parentGap !== nextGap,
    preservedConstraintIds: parent.activeConstraintIds.filter((id) =>
      next.activeConstraintIds.includes(id)
    ),
    addedConstraintIds: next.activeConstraintIds.filter(
      (id) => !parent.activeConstraintIds.includes(id)
    )
  };
}

export function replanFamilyMeal(
  catalog: PlannerCatalog,
  parent: MealPlan,
  input: ReplanFamilyMealInput
): ReplanResult {
  if (parent.id !== input.parentPlanId || parent.version !== input.parentPlanVersion) {
    throw Object.assign(new Error("STALE_CONTEXT"), { code: "STALE_CONTEXT" });
  }
  if (parent.sessionId !== input.mealSessionId) {
    throw Object.assign(new Error("STALE_CONTEXT"), { code: "STALE_CONTEXT" });
  }

  const nextState = applyDeltas(parent, input.constraintDelta);
  const composeInput: ComposeFamilyMealInput = {
    householdId: parent.householdId,
    mealSessionId: parent.sessionId,
    dinerIds: parent.dinerIds,
    mealType: parent.mealType,
    householdContextVersion: input.householdContextVersion,
    inventoryVersion: input.inventoryVersion,
    mealPolicyVersion: input.mealPolicyVersion,
    constraints: [],
    pinnedTemplateIds: nextState.pinnedTemplateIds,
    rejectedTemplateIds: nextState.rejectedTemplateIds,
    rejectedFoodIds: nextState.rejectedFoodIds,
    requestedPriorityFoodIds: nextState.requestedPriorityFoodIds,
    preferLowEffort: nextState.preferLowEffort
  };

  const result = composeFamilyMeal(catalog, composeInput, {
    version: parent.version + 1,
    parentPlanId: parent.id
  });

  if (result.status === "infeasible") {
    return {
      status: "infeasible",
      code: "NO_FEASIBLE_PLAN",
      parentPlan: parent,
      result
    };
  }

  return {
    status: "valid",
    plan: result.plan,
    shoppingGap: result.shoppingGap,
    diff: buildPlanDiff(parent, result.plan)
  };
}
