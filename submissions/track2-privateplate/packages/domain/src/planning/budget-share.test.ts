import { describe, expect, it } from "vitest";
import { PrivatePlateDomain } from "../service/privateplate-domain.js";

const DINERS = ["mem-admin", "mem-father", "mem-mother"];
const STANDARD_STRUCTURE = {
  mode: "standard" as const,
  requiredRoles: ["shared_main", "shared_side", "staple"] as (
    | "shared_main"
    | "shared_side"
    | "staple"
  )[],
  omittedRoles: [] as ("shared_main" | "shared_side" | "staple")[]
};

function balancedSelection(
  main = "tpl-potato-chicken",
  side = "tpl-garlic-spinach",
  staple = "tpl-leftover-rice"
) {
  return [main, side, staple].map((templateId) => ({
    templateId,
    relativePortion: "standard" as const
  }));
}

function finalize(
  domain: PrivatePlateDomain,
  input: {
    sessionId: string;
    dinerIds?: string[];
    selectedDishes: Array<{
      templateId: string;
      relativePortion: "small" | "standard" | "large";
    }>;
    mealPortionScale?: number;
    mealStructure?: typeof STANDARD_STRUCTURE | {
      mode: "simple" | "one_pot";
      requiredRoles: never[];
      omittedRoles: Array<"shared_main" | "shared_side" | "staple">;
      reason: string;
    };
  }
) {
  const dinerIds = input.dinerIds ?? DINERS;
  const candidates = domain.findDishCandidates({ dinerIds });
  return domain.finalizeMealPlan({
    sessionId: input.sessionId,
    dinerIds,
    mealType: "lunch",
    candidateSetId: candidates.candidateSetId,
    selectedDishes: input.selectedDishes,
    mealPortionScale: input.mealPortionScale ?? 1,
    mealStructure: input.mealStructure ?? STANDARD_STRUCTURE,
    selectionReason: "结构化回归测试"
  });
}

function sumPrepared(plan: { preparedBatch: Array<{ foodId: string; quantityG: number }> }, foodId: string) {
  return plan.preparedBatch
    .filter((item) => item.foodId === foodId)
    .reduce((sum, item) => sum + item.quantityG, 0);
}

function sumPlanned(plan: {
  plannedIntake: {
    byMember: Array<{
      items: Array<{ foodId: string; quantityG: number }>;
    }>;
  };
}, foodId: string) {
  return plan.plannedIntake.byMember.reduce(
    (sum, member) =>
      sum +
      member.items
        .filter((item) => item.foodId === foodId)
        .reduce((memberSum, item) => memberSum + item.quantityG, 0),
    0
  );
}

describe("家庭营养预算、结构和备餐余量", () => {
  it("三名合成成员都有每日目标和午餐/晚餐预算", async () => {
    const domain = await PrivatePlateDomain.create(":memory:");
    const day = domain.getDayContext({ dinerIds: DINERS });
    expect(day.members).toHaveLength(3);
    expect(day.memberIntake).toHaveLength(3);
    for (const member of day.memberIntake) {
      expect(member.target.energyKcal).toBeGreaterThan(1400);
      expect(member.nutritionBudget.source).toBe("engineering_estimate");
      expect(member.nutritionBudget.calculation.method).toBe("mifflin_st_jeor");
      expect(member.nutritionBudget.mealBudgets.lunch.target.energyKcal).toBeGreaterThan(0);
      expect(member.nutritionBudget.mealBudgets.dinner.target.energyKcal).toBeGreaterThan(0);
    }
    expect(day.householdIntake.mealBudgets.lunch.reserve.energyKcal).toBeGreaterThan(0);
    domain.db.close();
  });

  it("主菜、配菜、主食的正常三人正餐可以通过", async () => {
    const domain = await PrivatePlateDomain.create(":memory:");
    const result = finalize(domain, {
      sessionId: "normal-standard",
      selectedDishes: balancedSelection()
    });
    expect(result.status).toBe("ok");
    if (result.status === "ok") {
      expect(result.plan.dinerIds).toHaveLength(3);
      expect(result.plan.selectionTrace.agentSelection?.mealStructure.mode).toBe("standard");
    }
    domain.db.close();
  });

  it("只有一道普通菜的三人正餐会被结构守卫拒绝", async () => {
    const domain = await PrivatePlateDomain.create(":memory:");
    const result = finalize(domain, {
      sessionId: "one-ordinary-dish",
      selectedDishes: [{ templateId: "tpl-potato-chicken", relativePortion: "standard" }]
    });
    expect(result.status).toBe("failed");
    if (result.status === "failed") {
      expect(result.code).toBe("MEAL_STRUCTURE_INCOMPLETE");
      expect(result.details?.missingRoles).toEqual(["shared_side", "staple"]);
    }
    domain.db.close();
  });

  it("只有显式 one_pot 例外并提高相对份量时才能不配齐三角色", async () => {
    const domain = await PrivatePlateDomain.create(":memory:");
    const result = finalize(domain, {
      sessionId: "explicit-one-pot",
      selectedDishes: [{ templateId: "tpl-potato-chicken", relativePortion: "large" }],
      mealStructure: {
        mode: "one_pot",
        requiredRoles: [],
        omittedRoles: ["shared_side", "staple"],
        reason: "用户明确只做一锅鸡腿土豆，不另外准备配菜和主食。"
      }
    });
    expect(result.status).toBe("ok");
    domain.db.close();
  });

  it("份量倍率会改变克数，但不会按倍率缩小绝对下限", async () => {
    const domain = await PrivatePlateDomain.create(":memory:");
    const high = finalize(domain, {
      sessionId: "scale-high",
      selectedDishes: balancedSelection(),
      mealPortionScale: 1
    });
    const low = finalize(domain, {
      sessionId: "scale-low",
      selectedDishes: balancedSelection(),
      mealPortionScale: 0.2
    });
    expect(high.status).toBe("ok");
    expect(low.status).toBe("failed");
    if (low.status === "failed") {
      expect(["NUTRITION_GUARDRAIL", "NUTRITION_BUDGET"]).toContain(low.code);
      expect(JSON.stringify(low.details)).not.toContain("effectiveShare");
      expect(low.details?.mealPortionScale).toBe(0.2);
    }
    domain.db.close();
  });

  it("正常餐次完成后仍保留餐次预算余量", async () => {
    const domain = await PrivatePlateDomain.create(":memory:");
    const before = domain.getDayContext({ dinerIds: DINERS });
    const result = finalize(domain, {
      sessionId: "reserve-check",
      selectedDishes: balancedSelection()
    });
    expect(result.status).toBe("ok");
    if (result.status === "ok") {
      expect(result.plan.plannedIntake.householdTotal.energyKcal).toBeLessThan(
        before.householdIntake.mealBudgets.lunch.max.energyKcal
      );
      expect(before.householdIntake.mealBudgets.lunch.reserve.energyKcal).toBeGreaterThan(0);
    }
    domain.db.close();
  });

  it("剩余预算不足时返回结构化不可行原因，不生成极小份量", async () => {
    const domain = await PrivatePlateDomain.create(":memory:");
    domain.db
      .prepare(
        `UPDATE member_daily_targets
         SET energy_kcal = 100, carbohydrate_g = 10, protein_g = 5,
             fat_g = 5, sodium_mg = 100, source = 'test_override'`
      )
      .run();
    const result = finalize(domain, {
      sessionId: "remaining-too-low",
      selectedDishes: balancedSelection()
    });
    expect(result.status).toBe("failed");
    if (result.status === "failed") {
      expect(result.code).toBe("INSUFFICIENT_REMAINING_BUDGET");
      expect(Array.isArray(result.details?.deficits)).toBe(true);
      expect(result.details?.recommendedActions).toContain("add_candidate_dish");
    }
    domain.db.close();
  });

  it("蛋白质不足会单独出现在 deficits 中", async () => {
    const domain = await PrivatePlateDomain.create(":memory:");
    const result = finalize(domain, {
      sessionId: "protein-deficit",
      selectedDishes: balancedSelection(
        "tpl-cabbage-tofu-braise",
        "tpl-cucumber-salad",
        "tpl-leftover-rice"
      )
    });
    expect(result.status).toBe("failed");
    if (result.status === "failed") {
      expect(result.code).toBe("NUTRITION_BUDGET");
      expect(
        (result.details?.deficits as Array<{ nutrient: string }>).some(
          (deficit) => deficit.nutrient === "proteinG"
        )
      ).toBe(true);
    }
    domain.db.close();
  });

  it("prepared batch 大于 planned intake", async () => {
    const domain = await PrivatePlateDomain.create(":memory:");
    const result = finalize(domain, {
      sessionId: "batch-buffer",
      selectedDishes: balancedSelection()
    });
    expect(result.status).toBe("ok");
    if (result.status === "ok") {
      expect(sumPrepared(result.plan, "food-chicken-leg")).toBeGreaterThan(
        sumPlanned(result.plan, "food-chicken-leg")
      );
    }
    domain.db.close();
  });

  it("备餐余量可在 5%～10% 范围内配置", async () => {
    const domain = await PrivatePlateDomain.create(":memory:", {
      prepBuffer: 0.1
    });
    const result = finalize(domain, {
      sessionId: "configurable-prep-buffer",
      selectedDishes: balancedSelection()
    });
    expect(result.status).toBe("ok");
    if (result.status === "ok") {
      const planned = sumPlanned(result.plan, "food-chicken-leg");
      const prepared = sumPrepared(result.plan, "food-chicken-leg");
      expect(prepared).toBeCloseTo(planned * 1.1, 3);
    }
    domain.db.close();
  });

  it("采购使用 prepared batch，营养账本只记录 planned intake", async () => {
    const domain = await PrivatePlateDomain.create(":memory:");
    for (const [foodId, deltaG] of [
      ["food-chicken-leg", 1000],
      ["food-potato", 1000],
      ["food-spinach", 1000],
      ["food-garlic", 100],
      ["food-rice-cooked", 1000]
    ] as const) {
      domain.restockInventory({ foodId, deltaG, rawExpression: "test-restock" });
    }
    const result = finalize(domain, {
      sessionId: "planned-prepared-ledger",
      selectedDishes: balancedSelection()
    });
    expect(result.status).toBe("ok");
    if (result.status !== "ok") return;
    const preview = domain.previewMealCompletion({ planId: result.plan.id });
    const previewData = preview.preview as {
      willRecordIntake: Array<{ memberId: string; nutrition: unknown }>;
      willDebitInventory: unknown;
    };
    expect(previewData.willRecordIntake).toEqual(
      result.plan.memberAllocations.map((allocation) => ({
        memberId: allocation.memberId,
        nutrition: allocation.nutrition
      }))
    );
    expect(previewData.willDebitInventory).toEqual(result.plan.preparedBatch);
    const completed = domain.completeMealAsPlanned({ planId: result.plan.id });
    expect(completed.ok).toBe(true);
    if (completed.ok) {
      const ledger = domain.db
        .prepare(
          `SELECT SUM(energy_kcal) AS energy, SUM(carbohydrate_g) AS carbs,
                  SUM(protein_g) AS protein, SUM(fat_g) AS fat, SUM(sodium_mg) AS sodium
           FROM meal_record_items WHERE meal_record_id = ?`
        )
        .get(completed.mealRecordId) as {
        energy: number;
        carbs: number;
        protein: number;
        fat: number;
        sodium: number;
      };
      expect(ledger.energy).toBeCloseTo(result.plan.plannedIntake.householdTotal.energyKcal, 2);
      expect(ledger.protein).toBeCloseTo(result.plan.plannedIntake.householdTotal.proteinG, 2);
    }
    domain.db.close();
  });

  it("标准正餐只要求角色覆盖，多道同角色菜仍可通过且共享总预算", async () => {
    const domain = await PrivatePlateDomain.create(":memory:");
    const one = finalize(domain, {
      sessionId: "one-side",
      selectedDishes: balancedSelection()
    });
    const two = finalize(domain, {
      sessionId: "two-sides",
      selectedDishes: [
        { templateId: "tpl-potato-chicken", relativePortion: "standard" },
        { templateId: "tpl-garlic-spinach", relativePortion: "standard" },
        { templateId: "tpl-cucumber-salad", relativePortion: "standard" },
        { templateId: "tpl-leftover-rice", relativePortion: "standard" }
      ]
    });
    expect(one.status).toBe("ok");
    expect(two.status).toBe("ok");
    if (one.status === "ok" && two.status === "ok") {
      expect(two.plan.sharedTemplates).toHaveLength(4);
      expect(
        two.plan.sharedTemplates.filter((item) => item.role === "shared_side")
      ).toHaveLength(2);
      const oneSide = one.plan.preparedBatch
        .filter((item) => item.templateId === "tpl-garlic-spinach")
        .reduce((sum, item) => sum + item.quantityG, 0);
      const twoSides = two.plan.preparedBatch
        .filter((item) =>
          ["tpl-garlic-spinach", "tpl-cucumber-salad"].includes(item.templateId)
        )
        .reduce((sum, item) => sum + item.quantityG, 0);
      expect(twoSides).toBeLessThan(oneSide * 1.2);
      expect(two.plan.memberAllocations[0]?.portionUnitsByRole.shared_side).toBe(
        one.plan.memberAllocations[0]?.portionUnitsByRole.shared_side
      );
    }
    domain.db.close();
  });

  it("成员资料持久化并带预算版本与演示边界", async () => {
    const domain = await PrivatePlateDomain.create(":memory:");
    const members = domain.getMembers();
    expect(members.every((member) => member.nutritionProfile)).toBe(true);
    const profileCount = domain.db
      .prepare(`SELECT COUNT(*) AS count FROM member_nutrition_profiles`)
      .get() as { count: number };
    expect(profileCount.count).toBe(3);
    expect(domain.getDayContext().memberIntake[0]?.nutritionBudget.version).toBe(
      "engineering-demo-1.0.0"
    );
    domain.db.close();
  });
});
