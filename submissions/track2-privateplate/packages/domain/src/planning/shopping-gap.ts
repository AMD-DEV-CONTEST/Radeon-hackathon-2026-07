import type {
  GramRange,
  InventoryItem,
  ShoppingGapItem
} from "@privateplate/contracts";
import type { BatchIngredient } from "./scale.js";
import { round3 } from "../nutrition.js";

function exactRange(g: number): GramRange {
  return {
    estimateG: g,
    minG: g,
    maxG: g,
    confidence: "exact",
    conversionRuleId: null
  };
}

function mergeRequired(
  items: BatchIngredient[]
): Map<string, { quantityG: number; templateIds: Set<string> }> {
  const map = new Map<string, { quantityG: number; templateIds: Set<string> }>();
  for (const item of items) {
    const current = map.get(item.foodId) ?? {
      quantityG: 0,
      templateIds: new Set<string>()
    };
    current.quantityG = round3(current.quantityG + item.quantityG);
    current.templateIds.add(item.templateId);
    map.set(item.foodId, current);
  }
  return map;
}

function availableForFood(
  inventory: InventoryItem[],
  foodId: string
): GramRange {
  const matches = inventory.filter((item) => item.foodId === foodId);
  if (matches.length === 0) {
    return {
      estimateG: 0,
      minG: 0,
      maxG: 0,
      confidence: "exact",
      conversionRuleId: null
    };
  }

  let minG = 0;
  let maxG = 0;
  let estimateG = 0;
  let hasUnknown = false;
  let hasUnknownMaximum = false;
  let hasApprox = false;
  let conversionRuleId: string | null = null;

  for (const item of matches) {
    const n = item.quantity.normalized;
    if (n.confidence === "unknown") {
      hasUnknown = true;
      minG += n.minG ?? 0;
      if (n.maxG == null) {
        hasUnknownMaximum = true;
      } else {
        maxG += n.maxG;
      }
      conversionRuleId = n.conversionRuleId ?? conversionRuleId;
      continue;
    }
    if (n.confidence === "approximate") hasApprox = true;
    minG += n.minG ?? 0;
    maxG += n.maxG ?? n.minG ?? 0;
    estimateG += n.estimateG ?? ((n.minG ?? 0) + (n.maxG ?? 0)) / 2;
    conversionRuleId = n.conversionRuleId ?? conversionRuleId;
  }

  if (hasUnknown) {
    return {
      estimateG: null,
      minG: round3(minG),
      maxG: hasUnknownMaximum ? null : round3(maxG),
      confidence: "unknown",
      conversionRuleId
    };
  }

  return {
    estimateG: round3(estimateG),
    minG: round3(minG),
    maxG: round3(maxG),
    confidence: hasApprox ? "approximate" : "exact",
    conversionRuleId
  };
}

export function computeShoppingGap(input: {
  batchIngredients: BatchIngredient[];
  inventory: InventoryItem[];
}): ShoppingGapItem[] {
  const required = mergeRequired(input.batchIngredients);
  const gaps: ShoppingGapItem[] = [];

  for (const [foodId, req] of [...required.entries()].sort((a, b) =>
    a[0].localeCompare(b[0])
  )) {
    const available = availableForFood(input.inventory, foodId);
    const requiredRange = exactRange(req.quantityG);
    const templateIds = [...req.templateIds].sort();

    if (available.confidence === "unknown") {
      gaps.push({
        foodId,
        required: requiredRange,
        available,
        purchase: {
          estimateG: null,
          minG: null,
          maxG: null,
          confidence: "unknown",
          conversionRuleId: null
        },
        status: "needs_confirmation",
        usedByTemplateIds: templateIds
      });
      continue;
    }

    const availableMin = available.minG ?? 0;
    const availableMax = available.maxG ?? 0;

    if (available.confidence === "exact") {
      const purchaseG = round3(Math.max(req.quantityG - (available.estimateG ?? 0), 0));
      gaps.push({
        foodId,
        required: requiredRange,
        available,
        purchase: exactRange(purchaseG),
        status: purchaseG > 0 ? "needed" : "not_needed",
        usedByTemplateIds: templateIds
      });
      continue;
    }

    const purchaseMinG = round3(Math.max(req.quantityG - availableMax, 0));
    const purchaseMaxG = round3(Math.max(req.quantityG - availableMin, 0));
    const estimate = round3((purchaseMinG + purchaseMaxG) / 2);
    const needed = purchaseMaxG > 0;
    gaps.push({
      foodId,
      required: requiredRange,
      available,
      purchase: {
        estimateG: estimate,
        minG: purchaseMinG,
        maxG: purchaseMaxG,
        confidence: "approximate",
        conversionRuleId: available.conversionRuleId
      },
      status: needed ? "needed" : "not_needed",
      usedByTemplateIds: templateIds
    });
  }

  return gaps;
}
