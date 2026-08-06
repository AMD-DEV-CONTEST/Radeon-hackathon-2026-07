/**
 * Milestone D flagship: session A restock → plan → complete → session B sees SQLite state.
 */
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { PrivatePlateDomain } from "./service/privateplate-domain.js";
import { localServiceDate } from "./ledger/day-context.js";

describe("flagship closed-loop lifecycle (milestone D)", () => {
  let tempDir: string | null = null;

  afterEach(() => {
    if (tempDir) {
      rmSync(tempDir, { recursive: true, force: true });
      tempDir = null;
    }
  });

  it("A restocks tofu, plans, completes meal; B reads new remaining + inventory", async () => {
    tempDir = mkdtempSync(join(tmpdir(), "pp-flagship-"));
    const dbPath = join(tempDir, "family.sqlite");
    const diners = ["mem-admin", "mem-father", "mem-mother"];
    const serviceDate = localServiceDate();

    // --- Session A ---
    const sessionA = await PrivatePlateDomain.create(dbPath);
    const tofuBefore = sessionA
      .getDayContext({ dinerIds: diners, serviceDate })
      .inventory.find((i) => i.foodId === "food-tofu")?.quantity.estimateG;
    expect(tofuBefore).toBe(350);

    const restockPreview = sessionA.previewInventoryChange({
      foodId: "food-tofu",
      quantity: 2,
      unit: "盒"
    });
    expect(restockPreview.preview.deltaG).toBe(700);
    // Preview must not mutate
    expect(
      sessionA
        .getDayContext({ dinerIds: diners })
        .inventory.find((i) => i.foodId === "food-tofu")?.quantity.estimateG
    ).toBe(350);

    const restockConfirm = sessionA.confirmPendingWrite({
      pendingActionId: restockPreview.confirmation.pendingActionId,
      confirmationToken: restockPreview.confirmation.confirmationToken,
      idempotencyKey: "flagship-restock-1",
      expectedPayloadHash: restockPreview.confirmation.payloadHash
    });
    expect(restockConfirm.ok).toBe(true);
    const tofuAfterBuy = sessionA
      .getDayContext({ dinerIds: diners })
      .inventory.find((i) => i.foodId === "food-tofu")?.quantity.estimateG;
    expect(tofuAfterBuy).toBe(1050);

    // Idempotent replay
    const restockReplay = sessionA.confirmPendingWrite({
      pendingActionId: restockPreview.confirmation.pendingActionId,
      confirmationToken: restockPreview.confirmation.confirmationToken,
      idempotencyKey: "flagship-restock-1",
      expectedPayloadHash: restockPreview.confirmation.payloadHash
    });
    expect(restockReplay.ok && restockReplay.receipt.replayed).toBe(true);
    expect(
      sessionA
        .getDayContext({ dinerIds: diners })
        .inventory.find((i) => i.foodId === "food-tofu")?.quantity.estimateG
    ).toBe(1050);

    const dayBefore = sessionA.getDayContext({ dinerIds: diners, serviceDate });
    const remainingBefore = dayBefore.householdIntake.remaining.energyKcal;

    const candidates = sessionA.findDishCandidates({ dinerIds: diners });
    expect(candidates.candidates.length).toBeGreaterThan(0);
    const dishes = [
      "tpl-cabbage-tofu-braise",
      "tpl-shiitake-egg",
      "tpl-steamed-fish",
      "tpl-leftover-rice"
    ].filter((templateId) =>
      candidates.candidates.some((candidate) => candidate.templateId === templateId)
    );

    const planResult = sessionA.finalizeMealPlan({
      sessionId: "session-a-flagship",
      dinerIds: diners,
      mealType: "lunch",
      candidateSetId: candidates.candidateSetId,
      selectedDishes: dishes.map((templateId) => ({
        templateId,
        relativePortion: "standard" as const
      })),
      mealPortionScale: 1.0,
      selectionReason: "flagship lifecycle plan"
    });
    expect(planResult.status).toBe("ok");
    if (planResult.status !== "ok") throw new Error("plan failed");

    const mealPreview = sessionA.previewMealCompletion({
      planId: planResult.plan.id,
      serviceDate
    });
    const completed = sessionA.confirmPendingWrite({
      pendingActionId: mealPreview.confirmation.pendingActionId,
      confirmationToken: mealPreview.confirmation.confirmationToken,
      idempotencyKey: "flagship-meal-1",
      expectedPayloadHash: mealPreview.confirmation.payloadHash
    });
    expect(completed.ok).toBe(true);

    const dayAfterA = sessionA.getDayContext({ dinerIds: diners, serviceDate });
    expect(dayAfterA.completedMeals.length).toBeGreaterThanOrEqual(1);
    expect(dayAfterA.householdIntake.remaining.energyKcal).toBeLessThan(
      remainingBefore
    );
    sessionA.close();

    // --- Session B: new process, same SQLite ---
    const sessionB = await PrivatePlateDomain.create(dbPath);
    const dayB = sessionB.getDayContext({ dinerIds: diners, serviceDate });
    expect(dayB.completedMeals.length).toBeGreaterThanOrEqual(1);
    expect(
      dayB.inventory.find((i) => i.foodId === "food-tofu")?.quantity.estimateG
    ).toBeLessThan(1050); // meal debit reduced stock
    expect(dayB.householdIntake.remaining.energyKcal).toBe(
      dayAfterA.householdIntake.remaining.energyKcal
    );

    // Memory write survives reopen
    const mem = sessionB.previewMemberMemoryChange({
      memberId: "mem-father",
      kind: "preference",
      summary: "少油"
    });
    const memOk = sessionB.confirmPendingWrite({
      pendingActionId: mem.confirmation.pendingActionId,
      confirmationToken: mem.confirmation.confirmationToken,
      idempotencyKey: "flagship-mem-1",
      expectedPayloadHash: mem.confirmation.payloadHash
    });
    expect(memOk.ok).toBe(true);
    sessionB.close();

    const sessionC = await PrivatePlateDomain.create(dbPath);
    const pref = sessionC.db
      .prepare(
        `SELECT note FROM member_preferences WHERE member_id = ? AND note = ? AND active = 1`
      )
      .get("mem-father", "少油") as { note: string } | undefined;
    expect(pref?.note).toBe("少油");
    sessionC.close();
  });
});
