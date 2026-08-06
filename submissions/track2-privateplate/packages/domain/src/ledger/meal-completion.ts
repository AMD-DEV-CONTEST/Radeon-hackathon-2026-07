/**
 * Atomic meal completion: intake + inventory debit + ledger + plan status.
 */
import { randomUUID } from "node:crypto";
import type { MealPlan } from "@privateplate/contracts";
import type { Db } from "../db/open-db.js";
import { round3 } from "../nutrition.js";

export type CompleteMealAsPlannedResult =
  | {
      ok: true;
      mealRecordId: string;
      inventoryVersion: number;
      intakeVersion: number;
      replayed: boolean;
    }
  | { ok: false; code: string; message: string };

/**
 * Mark plan completed and write intake/inventory once.
 * Idempotent on (householdId, planId, planVersion, status=completed).
 */
export function completeMealAsPlanned(
  db: Db,
  input: {
    householdId: string;
    plan: MealPlan;
    serviceDate: string;
    completedAt?: string;
  }
): CompleteMealAsPlannedResult {
  const completedAt = input.completedAt ?? new Date().toISOString();
  const existing = db
    .prepare(
      `SELECT id FROM meal_records
       WHERE household_id = ? AND plan_id = ? AND plan_version = ?
         AND status = 'completed'
       LIMIT 1`
    )
    .get(input.householdId, input.plan.id, input.plan.version) as
    | { id: string }
    | undefined;

  if (existing) {
    const inv = db
      .prepare(`SELECT inventory_version FROM households WHERE id = ?`)
      .get(input.householdId) as { inventory_version: number };
    const intake = db
      .prepare(
        `SELECT intake_version FROM household_intake_versions WHERE household_id = ?`
      )
      .get(input.householdId) as { intake_version: number } | undefined;
    return {
      ok: true,
      mealRecordId: existing.id,
      inventoryVersion: inv.inventory_version,
      intakeVersion: intake?.intake_version ?? 1,
      replayed: true
    };
  }

  db.exec("BEGIN IMMEDIATE");
  try {
    const mealRecordId = `meal-${randomUUID()}`;
    db.prepare(
      `INSERT INTO meal_records
       (id, household_id, service_date, meal_type, status, plan_id, plan_version, source, diner_ids_json, completed_at, created_at)
       VALUES (?, ?, ?, ?, 'completed', ?, ?, 'as_planned', ?, ?, ?)`
    ).run(
      mealRecordId,
      input.householdId,
      input.serviceDate,
      input.plan.mealType,
      input.plan.id,
      input.plan.version,
      JSON.stringify(input.plan.dinerIds),
      completedAt,
      completedAt
    );

    for (const allocation of input.plan.memberAllocations) {
      for (const item of allocation.items) {
        const foodShare = item.quantityG;
        // Approximate item nutrition by share of member total if multi-item.
        const memberTotalG = allocation.items.reduce(
          (s, i) => s + i.quantityG,
          0
        );
        const ratio = memberTotalG > 0 ? foodShare / memberTotalG : 0;
        db.prepare(
          `INSERT INTO meal_record_items
           (id, meal_record_id, member_id, template_id, food_id, quantity_g,
            energy_kcal, carbohydrate_g, protein_g, fat_g, sodium_mg)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
        ).run(
          `mri-${randomUUID()}`,
          mealRecordId,
          allocation.memberId,
          item.templateId,
          item.foodId,
          foodShare,
          round3(allocation.nutrition.energyKcal * ratio),
          round3(allocation.nutrition.carbohydrateG * ratio),
          round3(allocation.nutrition.proteinG * ratio),
          round3(allocation.nutrition.fatG * ratio),
          round3(allocation.nutrition.sodiumMg * ratio)
        );
      }
    }

    // Debit inventory by prepared batch; the meal record above stays planned intake.
    for (const batch of input.plan.preparedBatch ?? input.plan.batchIngredients ?? []) {
      const invRows = db
        .prepare(
          `SELECT id, normalized_gram_range_json FROM inventory_items
           WHERE household_id = ? AND food_id = ?
           ORDER BY id`
        )
        .all(input.householdId, batch.foodId) as Array<{
        id: string;
        normalized_gram_range_json: string;
      }>;
      let remaining = batch.quantityG;
      for (const row of invRows) {
        if (remaining <= 0) break;
        const qty = JSON.parse(row.normalized_gram_range_json) as {
          estimateG: number | null;
          minG: number | null;
          maxG: number | null;
          confidence: string;
          conversionRuleId: string | null;
        };
        const before = qty.estimateG ?? 0;
        const debit = Math.min(before, remaining);
        const after = round3(before - debit);
        remaining = round3(remaining - debit);
        const next = {
          ...qty,
          estimateG: after,
          minG: qty.minG == null ? null : Math.max(0, round3((qty.minG ?? 0) - debit)),
          maxG: qty.maxG == null ? null : Math.max(0, round3((qty.maxG ?? 0) - debit))
        };
        db.prepare(
          `UPDATE inventory_items
           SET normalized_gram_range_json = ?, updated_at = ?
           WHERE id = ?`
        ).run(JSON.stringify(next), completedAt, row.id);
        db.prepare(
          `INSERT INTO inventory_ledger
           (id, household_id, inventory_item_id, food_id, reason, before_estimate_g, delta_g, after_estimate_g, related_meal_record_id, related_pending_action_id, created_at)
           VALUES (?, ?, ?, ?, 'meal_complete_debit', ?, ?, ?, ?, NULL, ?)`
        ).run(
          `led-${randomUUID()}`,
          input.householdId,
          row.id,
          batch.foodId,
          before,
          -debit,
          after,
          mealRecordId,
          completedAt
        );
      }
    }

    db.prepare(
      `UPDATE households
       SET inventory_version = inventory_version + 1, updated_at = ?
       WHERE id = ?`
    ).run(completedAt, input.householdId);

    db.prepare(
      `INSERT INTO household_intake_versions (household_id, intake_version, updated_at)
       VALUES (?, 1, ?)
       ON CONFLICT(household_id) DO UPDATE SET
         intake_version = intake_version + 1,
         updated_at = excluded.updated_at`
    ).run(input.householdId, completedAt);

    // PlanStatus enum has no "completed"; supersede is used after consume so
    // the plan cannot be re-finalized as active, while meal_records is source of truth.
    db.prepare(
      `UPDATE meal_plans SET status = 'superseded' WHERE id = ?`
    ).run(input.plan.id);

    db.exec("COMMIT");

    const inv = db
      .prepare(`SELECT inventory_version FROM households WHERE id = ?`)
      .get(input.householdId) as { inventory_version: number };
    const intake = db
      .prepare(
        `SELECT intake_version FROM household_intake_versions WHERE household_id = ?`
      )
      .get(input.householdId) as { intake_version: number };

    return {
      ok: true,
      mealRecordId,
      inventoryVersion: inv.inventory_version,
      intakeVersion: intake.intake_version,
      replayed: false
    };
  } catch (error) {
    db.exec("ROLLBACK");
    return {
      ok: false,
      code: "MEAL_COMPLETE_FAILED",
      message: error instanceof Error ? error.message : String(error)
    };
  }
}

export function applyInventoryRestock(
  db: Db,
  input: {
    householdId: string;
    foodId: string;
    deltaG: number;
    rawExpression: string;
    reason?: string;
    relatedPendingActionId?: string | null;
  }
): { ok: true; inventoryVersion: number } | { ok: false; code: string; message: string } {
  const now = new Date().toISOString();
  db.exec("BEGIN IMMEDIATE");
  try {
    const existing = db
      .prepare(
        `SELECT id, normalized_gram_range_json FROM inventory_items
         WHERE household_id = ? AND food_id = ?
         ORDER BY id LIMIT 1`
      )
      .get(input.householdId, input.foodId) as
      | { id: string; normalized_gram_range_json: string }
      | undefined;

    let itemId: string;
    let before = 0;
    if (existing) {
      itemId = existing.id;
      const qty = JSON.parse(existing.normalized_gram_range_json) as {
        estimateG: number | null;
        minG: number | null;
        maxG: number | null;
        confidence: string;
        conversionRuleId: string | null;
      };
      before = qty.estimateG ?? 0;
      const after = round3(before + input.deltaG);
      const next = {
        ...qty,
        estimateG: after,
        minG: after,
        maxG: after,
        confidence: "exact" as const
      };
      db.prepare(
        `UPDATE inventory_items
         SET normalized_gram_range_json = ?, raw_quantity_expression = ?, updated_at = ?
         WHERE id = ?`
      ).run(JSON.stringify(next), input.rawExpression, now, itemId);
    } else {
      itemId = `inv-${randomUUID()}`;
      before = 0;
      const after = round3(input.deltaG);
      db.prepare(
        `INSERT INTO inventory_items
         (id, household_id, food_id, raw_name, raw_quantity_expression, normalized_gram_range_json, state, priority_use, notes, updated_at)
         VALUES (?, ?, ?, ?, ?, ?, 'sealed', 0, NULL, ?)`
      ).run(
        itemId,
        input.householdId,
        input.foodId,
        input.foodId,
        input.rawExpression,
        JSON.stringify({
          estimateG: after,
          minG: after,
          maxG: after,
          confidence: "exact",
          conversionRuleId: null
        }),
        now
      );
    }

    const after = round3(before + input.deltaG);
    db.prepare(
      `INSERT INTO inventory_ledger
       (id, household_id, inventory_item_id, food_id, reason, before_estimate_g, delta_g, after_estimate_g, related_meal_record_id, related_pending_action_id, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)`
    ).run(
      `led-${randomUUID()}`,
      input.householdId,
      itemId,
      input.foodId,
      input.reason ?? "restock",
      before,
      input.deltaG,
      after,
      input.relatedPendingActionId ?? null,
      now
    );

    db.prepare(
      `UPDATE households
       SET inventory_version = inventory_version + 1, updated_at = ?
       WHERE id = ?`
    ).run(now, input.householdId);

    db.exec("COMMIT");
    const inv = db
      .prepare(`SELECT inventory_version FROM households WHERE id = ?`)
      .get(input.householdId) as { inventory_version: number };
    return { ok: true, inventoryVersion: inv.inventory_version };
  } catch (error) {
    db.exec("ROLLBACK");
    return {
      ok: false,
      code: "RESTOCK_FAILED",
      message: error instanceof Error ? error.message : String(error)
    };
  }
}
