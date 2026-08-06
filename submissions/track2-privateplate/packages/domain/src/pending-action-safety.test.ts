import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { PrivatePlateDomain } from "./service/privateplate-domain.js";

describe("pending caregiver action safety", () => {
  let domain: PrivatePlateDomain;

  beforeEach(async () => {
    domain = await PrivatePlateDomain.create(":memory:");
  });

  afterEach(() => {
    domain.close();
  });

  it("does not commit a cancelled pending action", () => {
    const initial = domain.planInitialDemo();
    if (initial.status !== "valid") throw new Error("expected valid plan");
    const preview = domain.previewCaregiverSend({
      planId: initial.plan.id,
      recipientLabel: "家庭保姆"
    });

    const cancelled = domain.cancelCaregiverSend({
      pendingActionId: preview.confirmation.pendingActionId
    });
    expect(cancelled).toEqual({ ok: true, status: "cancelled" });

    const confirmed = domain.confirmCaregiverSend({
      pendingActionId: preview.confirmation.pendingActionId,
      confirmationToken: preview.confirmation.confirmationToken,
      idempotencyKey: "cancelled-action-confirm",
      expectedPayloadHash: preview.confirmation.payloadHash
    });

    expect(confirmed).toMatchObject({ ok: false, code: "STALE_CONTEXT" });
    expect(caregiverTaskCount(domain)).toBe(0);
  });

  it("does not commit a preview after its plan is superseded", () => {
    const initial = domain.planInitialDemo();
    if (initial.status !== "valid") throw new Error("expected valid plan");
    const preview = domain.previewCaregiverSend({
      planId: initial.plan.id,
      recipientLabel: "家庭保姆"
    });

    const revised = domain.replanRejectTemplate({
      sessionId: initial.sessionId,
      parentPlanId: initial.plan.id,
      rejectedTemplateId: "tpl-shiitake-egg",
      sourceUtterance: "蒸蛋换一道"
    });
    expect(revised.status).toBe("valid");

    const confirmed = domain.confirmCaregiverSend({
      pendingActionId: preview.confirmation.pendingActionId,
      confirmationToken: preview.confirmation.confirmationToken,
      idempotencyKey: "superseded-plan-confirm",
      expectedPayloadHash: preview.confirmation.payloadHash
    });

    expect(confirmed).toMatchObject({ ok: false, code: "STALE_CONTEXT" });
    expect(caregiverTaskCount(domain)).toBe(0);
  });

  it("does not replay one action's idempotency receipt for another action", () => {
    const firstPlan = domain.planInitialDemo({ sessionId: "first-action-plan" });
    const secondPlan = domain.planInitialDemo({ sessionId: "second-action-plan" });
    if (firstPlan.status !== "valid" || secondPlan.status !== "valid") {
      throw new Error("expected valid plans");
    }
    const firstPreview = domain.previewCaregiverSend({
      planId: firstPlan.plan.id,
      recipientLabel: "家庭保姆"
    });
    const secondPreview = domain.previewCaregiverSend({
      planId: secondPlan.plan.id,
      recipientLabel: "家庭保姆"
    });
    const idempotencyKey = "action-bound-replay";
    const firstCommit = domain.confirmCaregiverSend({
      pendingActionId: firstPreview.confirmation.pendingActionId,
      confirmationToken: firstPreview.confirmation.confirmationToken,
      idempotencyKey,
      expectedPayloadHash: firstPreview.confirmation.payloadHash
    });
    expect(firstCommit.ok).toBe(true);

    const crossActionReplay = domain.confirmCaregiverSend({
      pendingActionId: secondPreview.confirmation.pendingActionId,
      confirmationToken: "wrong-token",
      idempotencyKey,
      expectedPayloadHash: firstPreview.confirmation.payloadHash
    });

    expect(crossActionReplay).toMatchObject({
      ok: false,
      code: "PAYLOAD_HASH_MISMATCH"
    });
    expect(caregiverTaskCount(domain)).toBe(1);
    const secondRow = domain.db
      .prepare(`SELECT status FROM pending_actions WHERE id = ?`)
      .get(secondPreview.confirmation.pendingActionId) as { status: string };
    expect(secondRow.status).toBe("pending");
  });

  it("rejects an expired confirmation token without writing an inbox task", () => {
    const initial = domain.planInitialDemo({ sessionId: "expired-preview" });
    if (initial.status !== "valid") throw new Error("expected valid plan");
    const preview = domain.previewCaregiverSend({
      planId: initial.plan.id,
      recipientLabel: "家庭保姆",
      ttlMs: -1
    });

    const confirmed = domain.confirmCaregiverSend({
      pendingActionId: preview.confirmation.pendingActionId,
      confirmationToken: preview.confirmation.confirmationToken,
      idempotencyKey: "expired-confirm",
      expectedPayloadHash: preview.confirmation.payloadHash
    });

    expect(confirmed).toMatchObject({ ok: false, code: "TOKEN_EXPIRED" });
    expect(caregiverTaskCount(domain)).toBe(0);
  });

  it("rejects health labels in every user-controlled task-card field", () => {
    const initial = domain.planInitialDemo();
    if (initial.status !== "valid") throw new Error("expected valid plan");

    expect(() =>
      domain.previewCaregiverSend({
        planId: initial.plan.id,
        recipientLabel: "糖尿病患者的保姆"
      })
    ).toThrow(/DISCLOSURE_VIOLATION/);
    expect(() =>
      domain.previewCaregiverSend({
        planId: initial.plan.id,
        recipientLabel: "家庭保姆",
        serveAt: "高血压用餐时间"
      })
    ).toThrow(/DISCLOSURE_VIOLATION/);
    expect(() =>
      domain.previewCaregiverSend({
        planId: initial.plan.id,
        recipientLabel: "需要控血糖的爸爸"
      })
    ).toThrow(/DISCLOSURE_VIOLATION/);
  });
});

function caregiverTaskCount(domain: PrivatePlateDomain): number {
  const row = domain.db
    .prepare(`SELECT COUNT(*) AS count FROM caregiver_tasks`)
    .get() as { count: number };
  return Number(row.count);
}
