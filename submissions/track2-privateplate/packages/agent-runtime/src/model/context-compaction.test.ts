import { describe, expect, it } from "vitest";
import { toolSuccess } from "../tools/types.js";
import {
  projectModelToolResultsForNextDecision,
  toModelVisibleToolResult
} from "./tool-result.js";

function modelResult(
  tool: "get_day_context" | "find_dish_candidates" | "finalize_meal_plan",
  data: Record<string, unknown>
) {
  return toModelVisibleToolResult({
    step: 0,
    goal: "compose_meal",
    tool,
    outcome: {
      result: toolSuccess(tool, data, "audit-1"),
      statePatch: {},
      durationMs: 1
    }
  });
}

describe("model tool-result context compaction", () => {
  it("keeps next-decision facts without carrying full domain payloads", () => {
    const context = modelResult("get_day_context", {
      serviceDate: "2026-08-03",
      householdContextVersion: 4,
      inventoryVersion: 7,
      intakeVersion: 5,
      householdIntake: {
        remaining: { energyKcal: 4200, proteinG: 180 }
      },
      memberIntake: [
        {
          memberId: "mem-a",
          remaining: { energyKcal: 1400, proteinG: 60 },
          nutritionBudget: {
            dailyTarget: { energyKcal: 1800, proteinG: 80 },
            mealBudgets: {
              lunch: {
                target: { energyKcal: 720, proteinG: 36 },
                min: { energyKcal: 288, proteinG: 18 },
                max: { energyKcal: 634, proteinG: 32 },
                reserve: { energyKcal: 86, proteinG: 4 }
              }
            },
            source: "engineering_estimate",
            version: "engineering-demo-1.0.0"
          }
        }
      ],
      inventory: [
        {
          id: "inv-tofu",
          foodId: "food-tofu",
          quantity: { estimateG: 350, minG: 350, maxG: 350 }
        }
      ],
      members: [
        {
          id: "mem-a",
          displayName: "成员甲",
          hardConstraints: [{ targetId: "food-beef", kind: "avoid_ingredient" }],
          healthFacts: [{ summary: "private-health-data-".repeat(200) }]
        }
      ],
      completedMeals: [],
      unitConversionRules: []
    });
    const candidates = modelResult("find_dish_candidates", {
      candidateSetId: "cset-current",
      versionStamp: { household: 4, inventory: 7, intake: 5 },
      candidates: Array.from({ length: 12 }, (_, index) => ({
        templateId: `tpl-${index}`,
        name: `菜${index}`,
        role: "shared_main",
        coversRoles: ["shared_main"],
        ingredients: [{ foodId: "food-tofu", edibleQuantityG: 100 }],
        inventoryFacts: {
          coveredFoodIds: ["food-tofu"],
          missingFoodIds: [],
          priorityFoodIds: ["food-tofu"]
        },
        nutritionPerStandardServing: { energyKcal: 120, proteinG: 10 },
        effortFacts: { effortLevel: "low", oilLevel: "low" }
      })),
      byRole: { shared_main: Array.from({ length: 12 }, (_, i) => `tpl-${i}`) },
      selectionGuidance: {
        requiredRoles: ["shared_main", "shared_side", "staple"],
        maxSelectedDishes: 12,
        selectionCountIsModelDecision: true,
        candidateCount: 12,
        multipleDishesPerRoleAllowed: true,
        note: "candidates is the full hard-filtered pool, not a 3-dish shortlist."
      }
    });
    const plan = modelResult("finalize_meal_plan", {
      status: "ok",
      selectionReason: "优先使用当前库存",
      plan: {
        id: "plan-current",
        version: 2,
        status: "valid",
        dinerIds: ["mem-a"],
        menu: [{ templateId: "tpl-1", name: "菜1", role: "shared_main" }],
        memberNutrition: [{ memberId: "mem-a", energyKcal: 120 }]
      },
      shoppingGap: []
    });

    const visible = [context, candidates, plan];
    const serialized = JSON.stringify(visible);
    expect(serialized.length).toBeLessThan(12_000);
    expect(serialized).not.toContain("private-health-data");
    expect(context.data?.inventory).toEqual([
      expect.objectContaining({
        foodId: "food-tofu",
        quantity: expect.objectContaining({ estimateG: 350 })
      })
    ]);
    expect(context.data?.members).toEqual([
      expect.objectContaining({
        id: "mem-a",
        hardConstraints: [
          expect.objectContaining({ targetId: "food-beef" })
        ]
      })
    ]);
    expect(
      (context.data?.memberIntake as Array<Record<string, unknown>>)[0]
        ?.nutritionBudget
    ).toMatchObject({
      source: "engineering_estimate",
      mealBudgets: { lunch: { min: { energyKcal: 288 } } }
    });
    expect(candidates.data?.candidateSetId).toBe("cset-current");
    expect(
      (candidates.data?.candidates as Array<Record<string, unknown>>).map(
        (candidate) => candidate.templateId
      )
    ).toContain("tpl-1");
    expect(
      (candidates.data?.candidates as Array<Record<string, unknown>>)[0]
    ).toMatchObject({ coversRoles: ["shared_main"] });
    expect(candidates.data?.selectionGuidance).toMatchObject({
      selectionCountIsModelDecision: true,
      maxSelectedDishes: 12
    });
    expect(
      (plan.data?.plan as Record<string, unknown>).menu
    ).toEqual([
      expect.objectContaining({ templateId: "tpl-1", name: "菜1" })
    ]);
    expect(projectModelToolResultsForNextDecision(visible)).toEqual([plan]);
    expect(projectModelToolResultsForNextDecision([context, candidates])).toEqual([
      context,
      candidates
    ]);
  });

  it("keeps compact recovery facts after a nutrition guard failure", () => {
    const fullFailure = {
      status: "failed",
      code: "NUTRITION_GUARDRAIL",
      message: "成员营养守卫未通过。请根据差额调整菜品。",
      details: {
        memberResults: [
          {
            memberId: "mem-father",
            pass: false,
            failures: ["energyKcal 98.824 outside [100, 720]"]
          }
        ],
        deficits: [
          {
            memberId: "mem-father",
            nutrient: "energyKcal",
            actual: 98.824,
            min: 100,
            max: 720,
            deficit: 1.176
          }
        ],
        mealPortionScale: 1.0,
        reselectAllowed: true,
        failureKind: "lower_bound_composition_deficit",
        shareOnlyAdjustmentEffective: false,
        recommendedActions: [
          "add_candidate_dish",
          "replace_with_more_suitable_candidate",
          "increase_relative_portion"
        ],
        oversizedDomainPayload: "private-domain-detail-".repeat(500)
      },
      oversizedPlanPayload: "private-domain-detail-".repeat(500)
    };
    const failed = modelResult("finalize_meal_plan", fullFailure);
    const recovery = failed.data?.recovery as Record<string, unknown>;
    const deficit = (recovery.deficits as Array<Record<string, unknown>>)[0];

    expect(recovery).toMatchObject({
        mealPortionScale: 1.0,
      reselectAllowed: true,
      failureKind: "lower_bound_composition_deficit",
      shareOnlyAdjustmentEffective: false,
      recommendedActions: [
        "add_candidate_dish",
        "replace_with_more_suitable_candidate",
        "increase_relative_portion"
      ]
    });
    expect(failed).toMatchObject({
      ok: false,
      code: "NUTRITION_GUARDRAIL",
      retryable: true
    });
    expect(recovery.memberResults).toEqual([
      expect.objectContaining({ memberId: "mem-father", pass: false })
    ]);
    expect(deficit).toMatchObject({
      memberId: "mem-father",
      nutrient: "energyKcal",
      actual: 98.824,
      min: 100,
      max: 720,
      deficit: 1.176
    });
    expect(JSON.stringify(failed).length).toBeLessThan(
      JSON.stringify(fullFailure).length / 10
    );
    expect(JSON.stringify(failed)).not.toContain("oversizedDomainPayload");
  });

  it("keeps successful finalize output focused on the final plan", () => {
    const plan = modelResult("finalize_meal_plan", {
      status: "ok",
      plan: {
        id: "plan-1",
        version: 1,
        status: "valid",
        dinerIds: ["mem-father"],
        menu: [{ templateId: "tpl-tofu", name: "豆腐菜" }],
        memberNutrition: [{ memberId: "mem-father", energyKcal: 120 }]
      },
      details: { oversizedDomainPayload: "should-not-be-visible" }
    });

    expect(plan.data).toMatchObject({
      status: "ok",
      plan: expect.objectContaining({
        id: "plan-1",
        menu: [expect.objectContaining({ templateId: "tpl-tofu" })]
      })
    });
    expect(plan.data).not.toHaveProperty("recovery");
    expect(JSON.stringify(plan)).not.toContain("oversizedDomainPayload");
  });
});
