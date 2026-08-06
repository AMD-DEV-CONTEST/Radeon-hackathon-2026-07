import { describe, expect, it } from "vitest";
import type { MealPlan } from "./api";
import {
  buildPlanDishDisplays,
  planQuantitySummary
} from "./plan-display";

function demoPlan(scale: number): MealPlan {
  const planned = (templateId: string, role: string, quantityG: number) => ({
    templateId,
    role,
    foodId: `food-${templateId}`,
    quantityG
  });
  const allocation = {
    memberId: "mem-admin",
    nutrition: {
      energyKcal: 620 * scale,
      carbohydrateG: 48 * scale,
      proteinG: 34 * scale,
      fatG: 20 * scale,
      sodiumMg: 650 * scale
    },
    items: [
      planned("tpl-main", "shared_main", 240 * scale),
      planned("tpl-greens", "shared_side", 180 * scale),
      planned("tpl-cucumber", "shared_side", 120 * scale),
      planned("tpl-rice", "staple", 150 * scale)
    ],
    portionUnitsByRole: {}
  };
  return {
    id: "plan-web",
    version: 2,
    status: "valid",
    bundleId: "agent-selection:test",
    sharedTemplates: [
      { templateId: "tpl-main", name: "鱼片", role: "shared_main" },
      { templateId: "tpl-greens", name: "菠菜", role: "shared_side" },
      { templateId: "tpl-cucumber", name: "黄瓜", role: "shared_side" },
      { templateId: "tpl-rice", name: "米饭", role: "staple" }
    ],
    dinerIds: ["mem-admin"],
    memberAllocations: [allocation],
    plannedIntake: {
      byMember: [allocation],
      householdTotal: allocation.nutrition
    },
    preparedBatch: [
      { templateId: "tpl-main", foodId: "food-tpl-main", quantityG: 259.2 * scale },
      { templateId: "tpl-greens", foodId: "food-tpl-greens", quantityG: 194.4 * scale },
      { templateId: "tpl-cucumber", foodId: "food-tpl-cucumber", quantityG: 129.6 * scale },
      { templateId: "tpl-rice", foodId: "food-tpl-rice", quantityG: 162 * scale }
    ],
    batchIngredients: [],
    prepBuffer: 0.08,
    shoppingGap: [],
    rejectedFoodIds: [],
    rejectedTemplateIds: []
  } as MealPlan;
}

describe("Web meal plan display data", () => {
  it("uses real roles and shows every selected dish", () => {
    const displays = buildPlanDishDisplays(demoPlan(1));
    expect(displays).toHaveLength(4);
    expect(displays[2]?.roleLabel).toBe("蔬菜 / 配菜");
    expect(displays[3]?.roleLabel).toBe("主食 / 碳水");
    expect(displays[0]?.plannedByMember[0]?.quantityG).toBe(240);
    expect(displays[2]?.plannedTotalG).toBe(120);
  });

  it("aggregates multi-ingredient dish lines per member", () => {
    const plan = demoPlan(1);
    const multiIngredient = {
      ...plan.memberAllocations[0]!,
      items: [
        {
          templateId: "tpl-main",
          role: "shared_main",
          foodId: "food-cabbage",
          quantityG: 132
        },
        {
          templateId: "tpl-main",
          role: "shared_main",
          foodId: "food-tofu",
          quantityG: 165
        },
        {
          templateId: "tpl-main",
          role: "shared_main",
          foodId: "food-seasoning",
          quantityG: 8.8
        },
        {
          templateId: "tpl-rice",
          role: "staple",
          foodId: "food-tpl-rice",
          quantityG: 150
        }
      ]
    };
    const withIngredients = {
      ...plan,
      memberAllocations: [multiIngredient],
      plannedIntake: {
        byMember: [multiIngredient],
        householdTotal: multiIngredient.nutrition
      }
    } as MealPlan;

    const displays = buildPlanDishDisplays(withIngredients);
    expect(displays[0]?.plannedByMember).toEqual([
      { memberId: "mem-admin", quantityG: 305.8 }
    ]);
    expect(displays[0]?.plannedTotalG).toBeCloseTo(305.8, 5);
    expect(displays[3]?.plannedByMember).toEqual([
      { memberId: "mem-admin", quantityG: 150 }
    ]);
  });

  it("keeps planned intake and prepared batch separate", () => {
    const plan = demoPlan(1);
    const summary = planQuantitySummary(plan);
    expect(summary.plannedTotalG).toBe(690);
    expect(summary.preparedTotalG).toBe(745.2);
    expect(summary.bufferG).toBeCloseTo(55.2, 5);
  });

  it("reflects a new mealPortionScale through the actual returned grams", () => {
    const normal = buildPlanDishDisplays(demoPlan(1));
    const smaller = buildPlanDishDisplays(demoPlan(0.6));
    expect(smaller[0]?.plannedTotalG).toBeCloseTo(
      (normal[0]?.plannedTotalG ?? 0) * 0.6,
      5
    );
    expect(smaller[0]?.plannedTotalG).not.toBe(normal[0]?.plannedTotalG);
  });

  it("keeps a legacy plan visible without inventing planned grams", () => {
    const current = demoPlan(1);
    const {
      plannedIntake: _plannedIntake,
      preparedBatch: _preparedBatch,
      prepBuffer: _prepBuffer,
      ...legacyFields
    } = current;
    const legacy = {
      ...legacyFields,
      batchIngredients: current.preparedBatch
    } as MealPlan;

    const displays = buildPlanDishDisplays(legacy);
    expect(displays).toHaveLength(4);
    expect(displays[3]?.roleLabel).toBe("主食 / 碳水");
    expect(displays[0]?.plannedTotalG).toBe(240);
    expect(planQuantitySummary(legacy)).toMatchObject({
      plannedTotalG: 690,
      preparedTotalG: 745.2
    });
  });
});
