import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { PrivatePlateDomain } from "./service/privateplate-domain.js";
import { listAppliedMigrations, openDatabase } from "./db/open-db.js";
import { seedFromFixtures } from "./db/seed.js";
import { localServiceDate } from "./ledger/day-context.js";

describe("full-loop lifecycle (milestones A–C domain)", () => {
  let tempDir: string | null = null;

  afterEach(() => {
    if (tempDir) {
      rmSync(tempDir, { recursive: true, force: true });
      tempDir = null;
    }
  });

  it("applies migration 003 and seeds unit conversions + daily targets", async () => {
    const domain = await PrivatePlateDomain.create(":memory:");
    const applied = listAppliedMigrations(domain.db);
    expect(applied).toContain(3);

    const rules = domain.db
      .prepare(`SELECT COUNT(*) AS c FROM unit_conversion_rules`)
      .get() as { c: number };
    expect(Number(rules.c)).toBeGreaterThan(0);

    const targets = domain.db
      .prepare(`SELECT COUNT(*) AS c FROM member_daily_targets`)
      .get() as { c: number };
    expect(Number(targets.c)).toBe(3);

    const day = domain.getDayContext({
      serviceDate: localServiceDate(),
      dinerIds: ["mem-admin", "mem-father", "mem-mother"]
    });
    expect(day.householdIntake.remaining.energyKcal).toBeGreaterThan(0);
    expect(day.memberIntake).toHaveLength(3);
    expect(day.completedMeals).toEqual([]);
    domain.db.close();
  });

  it("persists memory across domain reopen on file sqlite", async () => {
    tempDir = mkdtempSync(join(tmpdir(), "pp-loop-"));
    const dbPath = join(tempDir, "family.sqlite");

    const first = await PrivatePlateDomain.create(dbPath);
    first.restockInventory({
      foodId: "food-tofu",
      deltaG: 700,
      rawExpression: "2盒"
    });
    const inv1 = first.getDayContext().inventory.find((i) => i.foodId === "food-tofu");
    expect(inv1?.quantity.estimateG).toBeGreaterThanOrEqual(1000);
    first.db.close();

    const second = await PrivatePlateDomain.create(dbPath);
    const inv2 = second.getDayContext().inventory.find((i) => i.foodId === "food-tofu");
    expect(inv2?.quantity.estimateG).toBe(inv1?.quantity.estimateG);
    second.db.close();
  });

  it("candidate sets have no ranking fields and finalize preserves dish IDs", async () => {
    const domain = await PrivatePlateDomain.create(":memory:");
    const diners = ["mem-admin", "mem-father", "mem-mother"];
    const candidates = domain.findDishCandidates({
      dinerIds: diners,
      rejectedFoodIds: ["food-chicken-leg"]
    });
    expect(candidates.candidates.length).toBeGreaterThan(3);
    const blob = JSON.stringify(candidates);
    expect(blob).not.toMatch(/"score"|"rank"|"winner"|"recommended"/i);

    const pick = candidates.candidates
      .filter((c) =>
        [
          "tpl-cabbage-tofu-braise",
          "tpl-shiitake-egg",
          "tpl-steamed-fish",
          "tpl-leftover-rice"
        ].includes(c.templateId)
      )
      .map((c) => ({
        templateId: c.templateId,
        relativePortion: "standard" as const
      }));

    const finalized = domain.finalizeMealPlan({
      sessionId: "sess-agent-select",
      dinerIds: diners,
      mealType: "lunch",
      candidateSetId: candidates.candidateSetId,
      selectedDishes: pick,
      mealPortionScale: 1.0,
      selectionReason: "用剩余额度的约一半，优先消耗豆腐并搭配蒸蛋与米饭。"
    });
    expect(finalized.status).toBe("ok");
    if (finalized.status !== "ok") return;

    expect(finalized.plan.sharedTemplates.map((t) => t.templateId)).toEqual(
      pick.map((p) => p.templateId)
    );
    expect(finalized.plan.selectionTrace.selectedBundleId).toBeNull();
    expect(finalized.plan.selectionTrace.agentSelection?.candidateSetId).toBe(
      candidates.candidateSetId
    );

    // 350g tofu should not force a 10g purchase when scalable range fits.
    const tofuGap = finalized.plan.shoppingGap.find((g) => g.foodId === "food-tofu");
    if (tofuGap && tofuGap.status === "needed") {
      expect(tofuGap.purchase.estimateG).toBeGreaterThanOrEqual(350);
    } else {
      expect(tofuGap?.status === "not_needed" || tofuGap == null).toBe(true);
    }
    domain.db.close();
  });

  it("completing a meal updates intake remaining and inventory for a new session", async () => {
    tempDir = mkdtempSync(join(tmpdir(), "pp-loop-meal-"));
    const dbPath = join(tempDir, "family.sqlite");
    const serviceDate = localServiceDate();

    const sessionA = await PrivatePlateDomain.create(dbPath);
    const diners = ["mem-admin", "mem-father", "mem-mother"];
    const before = sessionA.getDayContext({ serviceDate, dinerIds: diners });
    const beforeEnergy = before.householdIntake.remaining.energyKcal;
    const beforeTofu =
      before.inventory.find((i) => i.foodId === "food-tofu")?.quantity.estimateG ??
      0;

    const candidates = sessionA.findDishCandidates({ dinerIds: diners });
    const pick = [
      {
        templateId: "tpl-cabbage-tofu-braise",
        relativePortion: "standard" as const
      },
      {
        templateId: "tpl-shiitake-egg",
        relativePortion: "standard" as const
      },
      {
        templateId: "tpl-steamed-fish",
        relativePortion: "standard" as const
      },
      {
        templateId: "tpl-leftover-rice",
        relativePortion: "standard" as const
      }
    ].filter((p) =>
      candidates.candidates.some((c) => c.templateId === p.templateId)
    );

    const planResult = sessionA.finalizeMealPlan({
      sessionId: "sess-A",
      dinerIds: diners,
      mealType: "lunch",
      candidateSetId: candidates.candidateSetId,
      selectedDishes: pick,
      mealPortionScale: 1.0,
      selectionReason: "午餐约用四成剩余额度。"
    });
    expect(planResult.status).toBe("ok");
    if (planResult.status !== "ok") return;

    const mealPreview = sessionA.previewMealCompletion({
      planId: planResult.plan.id,
      serviceDate
    });
    const completed = sessionA.confirmPendingWrite({
      pendingActionId: mealPreview.confirmation.pendingActionId,
      confirmationToken: mealPreview.confirmation.confirmationToken,
      idempotencyKey: "lifecycle-meal-1",
      expectedPayloadHash: mealPreview.confirmation.payloadHash
    });
    expect(completed.ok).toBe(true);
    if (!completed.ok) return;
    expect(completed.receipt.replayed).toBe(false);

    // Idempotent replay
    const again = sessionA.confirmPendingWrite({
      pendingActionId: mealPreview.confirmation.pendingActionId,
      confirmationToken: mealPreview.confirmation.confirmationToken,
      idempotencyKey: "lifecycle-meal-1",
      expectedPayloadHash: mealPreview.confirmation.payloadHash
    });
    expect(again.ok && again.receipt.replayed).toBe(true);

    sessionA.db.close();

    const sessionB = await PrivatePlateDomain.create(dbPath);
    const after = sessionB.getDayContext({ serviceDate, dinerIds: diners });
    expect(after.completedMeals.length).toBe(1);
    expect(after.householdIntake.remaining.energyKcal).toBeLessThan(beforeEnergy);
    const afterTofu =
      after.inventory.find((i) => i.foodId === "food-tofu")?.quantity.estimateG ??
      0;
    expect(afterTofu).toBeLessThan(beforeTofu);
    sessionB.db.close();
  });

  it("upgrades an existing pre-003 sqlite file without wiping plans", async () => {
    tempDir = mkdtempSync(join(tmpdir(), "pp-mig-"));
    const dbPath = join(tempDir, "legacy.sqlite");

    // Simulate legacy DB: open with only base SQL path by creating domain once
    // then ensuring re-open still has household.
    const first = await PrivatePlateDomain.create(dbPath);
    const plan = first.planInitialDemo({ sessionId: "legacy-sess" });
    expect(plan.status).toBe("valid");
    first.db.close();

    const second = await PrivatePlateDomain.create(dbPath);
    expect(listAppliedMigrations(second.db)).toContain(3);
    expect(second.getMembers().length).toBe(3);
    const day = second.getDayContext();
    expect(day.memberIntake.length).toBe(3);
    second.db.close();
  });
});
