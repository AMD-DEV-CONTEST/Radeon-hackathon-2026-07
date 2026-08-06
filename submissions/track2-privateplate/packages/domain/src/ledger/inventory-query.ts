import type { Db } from "../db/open-db.js";
import type { DayContext } from "./types.js";

export type InventoryQuery = {
  inventoryVersion: number;
  householdContextVersion: number;
  inventory: DayContext["inventory"];
};

/**
 * Read-only household inventory snapshot. Excludes nutrition, intake, and member memory.
 */
export function getInventory(
  db: Db,
  householdId: string
): InventoryQuery {
  const household = db
    .prepare(
      `SELECT version, inventory_version
       FROM households WHERE id = ?`
    )
    .get(householdId) as
    | { version: number; inventory_version: number }
    | undefined;
  if (!household) {
    throw new Error(`HOUSEHOLD_NOT_FOUND:${householdId}`);
  }

  const inventoryRows = db
    .prepare(
      `SELECT id, food_id, raw_name, priority_use, normalized_gram_range_json
       FROM inventory_items
       WHERE household_id = ?
       ORDER BY id`
    )
    .all(householdId) as Array<{
    id: string;
    food_id: string | null;
    raw_name: string;
    priority_use: number;
    normalized_gram_range_json: string;
  }>;

  const inventory = inventoryRows.map((row) => {
    const qty = JSON.parse(row.normalized_gram_range_json) as {
      estimateG: number | null;
      minG: number | null;
      maxG: number | null;
      confidence: string;
    };
    return {
      id: row.id,
      foodId: row.food_id,
      rawName: row.raw_name,
      priorityUse: row.priority_use === 1,
      quantity: {
        estimateG: qty.estimateG,
        minG: qty.minG,
        maxG: qty.maxG,
        confidence: qty.confidence
      }
    };
  });

  return {
    inventoryVersion: household.inventory_version,
    householdContextVersion: household.version,
    inventory
  };
}
