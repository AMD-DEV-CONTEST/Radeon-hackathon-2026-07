import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { PrivatePlateDomain } from "../service/privateplate-domain.js";
import {
  resolveAvoidedFoodId,
  applyMemberMemoryChange
} from "./memory-writes.js";
import { evaluateSelection } from "../planning/evaluate-selection.js";

describe("resolveAvoidedFoodId", () => {
  const catalog = [
    { foodId: "food-egg", labels: ["鸡蛋", "蛋", "整蛋"] },
    { foodId: "food-beef", labels: ["牛肉"] },
    { foodId: "food-peanut", labels: ["花生"] }
  ];

  it("maps an allergy summary to exactly one food", () => {
    expect(
      resolveAvoidedFoodId("父亲对鸡蛋过敏，禁止安排含鸡蛋的菜", catalog)
    ).toBe("food-egg");
  });

  it("returns null when the summary has no avoid wording", () => {
    expect(resolveAvoidedFoodId("父亲喜欢鸡蛋", catalog)).toBeNull();
  });

  it("returns null when zero or multiple foods match", () => {
    expect(resolveAvoidedFoodId("父亲对海鲜过敏", catalog)).toBeNull();
    expect(
      resolveAvoidedFoodId("父亲对鸡蛋和花生都过敏", catalog)
    ).toBeNull();
  });
});

describe("member memory avoid → hard constraint", () => {
  let domain: PrivatePlateDomain;

  beforeEach(async () => {
    domain = await PrivatePlateDomain.create(":memory:");
  });

  afterEach(() => {
    domain.close();
  });

  it("writes member_constraints for a confirmed egg allergy and rejects egg dishes", () => {
    const preview = domain.previewMemberMemoryChange({
      memberId: "mem-father",
      kind: "health_fact",
      summary: "父亲对鸡蛋过敏，别再给他安排含鸡蛋的菜。"
    });
    const confirmed = domain.confirmPendingWrite({
      pendingActionId: preview.confirmation.pendingActionId,
      confirmationToken: preview.confirmation.confirmationToken,
      idempotencyKey: "mem-egg-allergy-1",
      expectedPayloadHash: preview.confirmation.payloadHash
    });
    expect(confirmed.ok).toBe(true);
    if (!confirmed.ok) return;

    const receipt = confirmed.result as {
      enforcedConstraintId?: string;
      memberId: string;
    };
    expect(receipt.enforcedConstraintId).toBe(
      "cst-mem-father-avoid-food-egg"
    );

    const row = domain.db
      .prepare(
        `SELECT id, member_id, kind, target_id, source FROM member_constraints
         WHERE member_id = ? AND target_id = ?`
      )
      .get("mem-father", "food-egg") as
      | {
          id: string;
          member_id: string;
          kind: string;
          target_id: string;
          source: string;
        }
      | undefined;
    expect(row).toEqual({
      id: "cst-mem-father-avoid-food-egg",
      member_id: "mem-father",
      kind: "avoid_ingredient",
      target_id: "food-egg",
      source: "session_input"
    });

    // Re-confirm is idempotent: no duplicate constraint rows.
    const preview2 = domain.previewMemberMemoryChange({
      memberId: "mem-father",
      kind: "health_fact",
      summary: "父亲对鸡蛋过敏。"
    });
    const confirmed2 = domain.confirmPendingWrite({
      pendingActionId: preview2.confirmation.pendingActionId,
      confirmationToken: preview2.confirmation.confirmationToken,
      idempotencyKey: "mem-egg-allergy-2",
      expectedPayloadHash: preview2.confirmation.payloadHash
    });
    expect(confirmed2.ok).toBe(true);
    const count = (
      domain.db
        .prepare(
          `SELECT COUNT(*) AS n FROM member_constraints
           WHERE member_id = ? AND target_id = ?`
        )
        .get("mem-father", "food-egg") as { n: number }
    ).n;
    expect(count).toBe(1);

    const catalog = domain.getCatalog();
    const rejected = evaluateSelection(catalog, {
      dinerIds: ["mem-admin", "mem-father", "mem-mother"],
      mealType: "dinner",
      selectedDishes: [
        { templateId: "tpl-cabbage-tofu-braise", relativePortion: "standard" },
        { templateId: "tpl-shiitake-egg", relativePortion: "standard" },
        { templateId: "tpl-leftover-rice", relativePortion: "standard" }
      ],
      mealPortionScale: 1
    });
    expect(rejected.status).toBe("failed");
    if (rejected.status === "failed") {
      expect(rejected.code).toBe("HARD_CONSTRAINT_VIOLATION");
      expect(rejected.details).toMatchObject({
        templateId: "tpl-shiitake-egg"
      });
    }
  });

  it("saves memory without a constraint when no single food can be resolved", () => {
    const applied = applyMemberMemoryChange(domain.db, {
      householdId: domain.householdId,
      change: {
        memberId: "mem-father",
        kind: "health_fact",
        summary: "父亲最近血压偏高，少油少盐。",
        source: "user_confirmed"
      }
    });
    expect(applied.ok).toBe(true);
    if (!applied.ok) return;
    expect(applied.enforcedConstraintId).toBeUndefined();

    const count = (
      domain.db
        .prepare(
          `SELECT COUNT(*) AS n FROM member_constraints
           WHERE member_id = ? AND source = 'session_input'`
        )
        .get("mem-father") as { n: number }
    ).n;
    expect(count).toBe(0);
  });
});
