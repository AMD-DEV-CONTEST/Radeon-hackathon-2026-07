/**
 * Shopping gap with realistic purchase units (round up to unit_conversion_rules).
 * Never report "buy 10g tofu" when one box is 350g.
 */
import type { GramRange, InventoryItem, ShoppingGapItem } from "@privateplate/contracts";
import type { BatchIngredient } from "./scale.js";
import { round3 } from "../nutrition.js";

export type UnitRule = {
  id: string;
  foodId: string;
  rawUnit: string;
  gramsPerUnit: number;
};

function exactRange(g: number, conversionRuleId: string | null = null): GramRange {
  return {
    estimateG: g,
    minG: g,
    maxG: g,
    confidence: "exact",
    conversionRuleId
  };
}

function availableForFood(inventory: InventoryItem[], foodId: string): GramRange {
  const matches = inventory.filter((item) => item.foodId === foodId);
  if (matches.length === 0) {
    return exactRange(0);
  }
  let estimateG = 0;
  let minG = 0;
  let maxG = 0;
  let conversionRuleId: string | null = null;
  let confidence: GramRange["confidence"] = "exact";
  for (const item of matches) {
    const n = item.quantity.normalized;
    estimateG += n.estimateG ?? 0;
    minG += n.minG ?? n.estimateG ?? 0;
    maxG += n.maxG ?? n.estimateG ?? 0;
    conversionRuleId = n.conversionRuleId ?? conversionRuleId;
    if (n.confidence === "approximate") confidence = "approximate";
  }
  return {
    estimateG: round3(estimateG),
    minG: round3(minG),
    maxG: round3(maxG),
    confidence,
    conversionRuleId
  };
}

function roundUpToUnit(
  neededG: number,
  rule: UnitRule | undefined
): { purchaseG: number; conversionRuleId: string | null } {
  if (!rule || rule.gramsPerUnit <= 0) {
    return { purchaseG: round3(neededG), conversionRuleId: null };
  }
  const units = Math.ceil(neededG / rule.gramsPerUnit - 1e-9);
  return {
    purchaseG: round3(units * rule.gramsPerUnit),
    conversionRuleId: rule.id
  };
}

export function computeShoppingGapWithUnits(input: {
  preparedBatch?: BatchIngredient[];
  /** Legacy input alias; new planning uses preparedBatch. */
  batchIngredients?: BatchIngredient[];
  inventory: InventoryItem[];
  unitRules: UnitRule[];
}): ShoppingGapItem[] {
  const preparedBatch = input.preparedBatch ?? input.batchIngredients ?? [];
  const required = new Map<string, { quantityG: number; templateIds: Set<string> }>();
  for (const item of preparedBatch) {
    const cur = required.get(item.foodId) ?? {
      quantityG: 0,
      templateIds: new Set<string>()
    };
    cur.quantityG = round3(cur.quantityG + item.quantityG);
    cur.templateIds.add(item.templateId);
    required.set(item.foodId, cur);
  }

  const rulesByFood = new Map<string, UnitRule>();
  for (const rule of input.unitRules) {
    if (!rulesByFood.has(rule.foodId)) rulesByFood.set(rule.foodId, rule);
  }

  const gaps: ShoppingGapItem[] = [];
  for (const [foodId, need] of required) {
    const available = availableForFood(input.inventory, foodId);
    const availEst = available.estimateG ?? 0;
    const shortfall = round3(Math.max(0, need.quantityG - availEst));
    if (shortfall <= 0.05) {
      // Treat sub-gram / tiny residual as covered (scalable range fit).
      gaps.push({
        foodId,
        required: exactRange(need.quantityG),
        available,
        purchase: exactRange(0),
        status: "not_needed",
        usedByTemplateIds: [...need.templateIds]
      });
      continue;
    }
    const rounded = roundUpToUnit(shortfall, rulesByFood.get(foodId));
    gaps.push({
      foodId,
      required: exactRange(need.quantityG),
      available,
      purchase: exactRange(rounded.purchaseG, rounded.conversionRuleId),
      status: "needed",
      usedByTemplateIds: [...need.templateIds]
    });
  }
  return gaps.sort((a, b) => a.foodId.localeCompare(b.foodId));
}
