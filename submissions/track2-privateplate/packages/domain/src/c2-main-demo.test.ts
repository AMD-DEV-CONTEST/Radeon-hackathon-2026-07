import { describe, expect, it, beforeAll, afterAll } from "vitest";
import { PrivatePlateDomain } from "./service/privateplate-domain.js";
import { hashToken } from "./actions/canonical.js";

describe("C2 main demo via direct function calls", () => {
  let domain: PrivatePlateDomain;

  beforeAll(async () => {
    domain = await PrivatePlateDomain.create(":memory:");
  });

  afterAll(() => {
    domain.close();
  });

  it("runs plan → replan → preview → confirm → readback without hard-coded answers", async () => {
    // 1) Initial plan: three diners, priority tofu, reject chicken.
    const initial = domain.planInitialDemo();
    expect(initial.status).toBe("valid");
    if (initial.status !== "valid") return;

    const plan1 = initial.plan;
    expect(plan1.version).toBe(1);
    expect(plan1.dinerIds).toHaveLength(3);
    expect(plan1.rejectedFoodIds).toContain("food-chicken-leg");
    expect(plan1.sharedTemplates.map((t) => t.templateId).join(",")).not.toContain(
      "tpl-potato-chicken"
    );
    // Priority tofu should surface in a tofu-containing selection when feasible.
    const usesTofu = plan1.batchIngredients.some((b) => b.foodId === "food-tofu");
    expect(usesTofu).toBe(true);
    expect(plan1.validationSummary.guardrailsPass).toBe(true);
    expect(plan1.shoppingGap.length).toBeGreaterThan(0);

    // Allocation conservation
    for (const batch of plan1.batchIngredients) {
      const sum = plan1.memberAllocations
        .flatMap((m) => m.items)
        .filter((i) => i.templateId === batch.templateId && i.foodId === batch.foodId)
        .reduce((acc, i) => acc + i.quantityG, 0);
      expect(Math.abs(sum - batch.quantityG)).toBeLessThanOrEqual(0.001);
    }

    // 2) Replan: reject steamed egg side.
    const replan = domain.replanRejectTemplate({
      sessionId: initial.sessionId,
      parentPlanId: plan1.id,
      rejectedTemplateId: "tpl-shiitake-egg",
      sourceUtterance: "蒸蛋今天也不想吃，换一道，其他都保留。"
    });
    expect(replan.status).toBe("valid");
    if (replan.status !== "valid") return;

    expect(replan.plan.version).toBe(2);
    expect(replan.plan.parentPlanId).toBe(plan1.id);
    expect(replan.plan.rejectedTemplateIds).toContain("tpl-shiitake-egg");
    expect(replan.plan.sharedTemplates.map((t) => t.templateId)).not.toContain(
      "tpl-shiitake-egg"
    );
    expect(replan.diff.removedTemplateIds).toContain("tpl-shiitake-egg");
    // Chicken reject still preserved.
    expect(replan.plan.rejectedFoodIds).toContain("food-chicken-leg");

    const parent = domain.db
      .prepare(`SELECT status FROM meal_plans WHERE id = ?`)
      .get(plan1.id) as { status: string };
    expect(parent.status).toBe("superseded");

    // 3) Preview send — must not create caregiver task yet.
    const preview = domain.previewCaregiverSend({
      planId: replan.plan.id,
      recipientLabel: "家庭保姆",
      serveAt: "今天 12:30"
    });
    expect(preview.preview.menu.length).toBe(3);
    expect(preview.preview.executionNotes.some((n) => /糖尿病|高血压/.test(n))).toBe(
      false
    );
    expect(preview.confirmation.confirmationToken.length).toBeGreaterThan(20);
    const cabbageUsage = preview.preview.useFromInventory.find(
      (item) => item.foodId === "food-cabbage"
    );
    expect(cabbageUsage?.quantity.maxG).toBe(450);

    const tasksBefore = domain.db
      .prepare(`SELECT COUNT(*) AS c FROM caregiver_tasks`)
      .get() as { c: number };
    expect(Number(tasksBefore.c)).toBe(0);

    // Token is hashed at rest.
    const pendingRow = domain.db
      .prepare(`SELECT confirmation_token_hash, status FROM pending_actions WHERE id = ?`)
      .get(preview.confirmation.pendingActionId) as {
      confirmation_token_hash: string;
      status: string;
    };
    expect(pendingRow.status).toBe("pending");
    expect(pendingRow.confirmation_token_hash).toBe(
      hashToken(preview.confirmation.confirmationToken)
    );
    expect(pendingRow.confirmation_token_hash).not.toBe(
      preview.confirmation.confirmationToken
    );

    // 4) Confirm with idempotency.
    const idempotencyKey = "demo-confirm-1";
    const first = domain.confirmCaregiverSend({
      pendingActionId: preview.confirmation.pendingActionId,
      confirmationToken: preview.confirmation.confirmationToken,
      idempotencyKey,
      expectedPayloadHash: preview.confirmation.payloadHash
    });
    expect(first.ok).toBe(true);
    if (!first.ok) return;
    expect(first.receipt.replayed).toBe(false);
    expect(first.task?.status).toBe("queued");
    expect(first.task?.channel).toBe("simulated_local_inbox");

    // 5) Replay same key → same receipt, no duplicate task.
    const second = domain.confirmCaregiverSend({
      pendingActionId: preview.confirmation.pendingActionId,
      confirmationToken: preview.confirmation.confirmationToken,
      idempotencyKey,
      expectedPayloadHash: preview.confirmation.payloadHash
    });
    expect(second.ok).toBe(true);
    if (!second.ok) return;
    expect(second.receipt.replayed).toBe(true);
    expect(second.receipt.result.caregiverTaskId).toBe(
      first.receipt.result.caregiverTaskId
    );

    const taskCount = domain.db
      .prepare(`SELECT COUNT(*) AS c FROM caregiver_tasks`)
      .get() as { c: number };
    expect(Number(taskCount.c)).toBe(1);

    // 6) Readback real business object.
    const readback = domain.readCaregiverTask(first.receipt.result.caregiverTaskId);
    expect(readback).toBeTruthy();
    const card = JSON.parse(readback!.task_card_json);
    expect(card.planVersion).toBe(2);
    expect(card.menu.map((m: { displayName: string }) => m.displayName).join("+")).not.toBe(
      ""
    );
  });

  it("rejects invalid confirmation token", async () => {
    const initial = domain.planInitialDemo({ sessionId: `session-bad-token` });
    if (initial.status !== "valid") throw new Error("expected valid plan");
    const preview = domain.previewCaregiverSend({
      planId: initial.plan.id,
      recipientLabel: "保姆"
    });
    const result = domain.confirmCaregiverSend({
      pendingActionId: preview.confirmation.pendingActionId,
      confirmationToken: "not-the-real-token",
      idempotencyKey: "bad-token-key",
      expectedPayloadHash: preview.confirmation.payloadHash
    });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.code).toBe("TOKEN_INVALID");
  });

  it("replaces a dish when one of its ingredients is rejected", () => {
    const initial = domain.composeMeal({
      sessionId: "session-replace-rejected-ingredient",
      mealType: "lunch",
      pinnedTemplateIds: ["tpl-potato-chicken"]
    });
    expect(initial.status).toBe("valid");
    if (initial.status !== "valid") return;

    const initialMenu = initial.plan.sharedTemplates.map(
      (item) => item.templateId
    );
    expect(initialMenu).toContain("tpl-potato-chicken");

    const revised = domain.reviseMeal({
      sessionId: initial.sessionId,
      parentPlanId: initial.plan.id,
      constraintDelta: [
        {
          operation: "add",
          kind: "reject_food",
          targetId: "food-chicken-leg",
          sourceUtterance: "不要鸡腿，换一道菜。"
        }
      ]
    });
    expect(revised.status).toBe("valid");
    if (revised.status !== "valid") return;

    const revisedMenu = revised.plan.sharedTemplates.map(
      (item) => item.templateId
    );
    expect(revisedMenu).toHaveLength(initialMenu.length);
    expect(revisedMenu).not.toContain("tpl-potato-chicken");
    expect(revised.diff.removedTemplateIds).toContain("tpl-potato-chicken");
    expect(revised.diff.addedTemplateIds).toHaveLength(1);
    expect(revisedMenu).toContain(revised.diff.addedTemplateIds[0]);
    expect(
      revised.plan.batchIngredients.some(
        (item) => item.foodId === "food-chicken-leg"
      )
    ).toBe(false);
  });

  it("keeps an explicitly requested dish when it remains feasible", () => {
    const result = domain.composeMeal({
      sessionId: "session-keep-requested-dish",
      mealType: "lunch",
      rejectedFoodIds: ["food-tofu"],
      pinnedTemplateIds: ["tpl-tomato-egg"]
    });
    expect(result.status).toBe("valid");
    if (result.status !== "valid") return;

    expect(
      result.plan.sharedTemplates.map((item) => item.templateId)
    ).toContain("tpl-tomato-egg");
    expect(result.plan.pinnedTemplateIds).toContain("tpl-tomato-egg");
  });

  it("does not silently replace an infeasible requested dish", () => {
    const result = domain.composeMeal({
      sessionId: "session-conflicting-requested-dish",
      mealType: "lunch",
      rejectedFoodIds: ["food-chicken-leg"],
      pinnedTemplateIds: ["tpl-potato-chicken"]
    });

    expect(result.status).toBe("infeasible");
  });
});
