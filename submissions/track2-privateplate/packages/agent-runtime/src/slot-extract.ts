/**
 * Lightweight Chinese slot helpers for scripted mock / coarse argument fill.
 * Maps natural phrases onto fixture ids without inventing free-form recipes.
 * Not a product business router for the real model path.
 */
import type { HouseholdMember } from "@privateplate/contracts";

export type DinerSelection =
  | { kind: "unspecified" }
  | { kind: "resolved"; dinerIds: string[] }
  | { kind: "needs_clarification"; reason: "empty" | "unknown" | "ambiguous" };

const ROLE_ALIASES: Record<HouseholdMember["roleLabel"], readonly string[]> = {
  admin: ["我", "本人", "管理员"],
  father: ["爸爸", "父亲", "老爸"],
  mother: ["妈妈", "母亲", "老妈"],
  member: []
};

const UNKNOWN_FAMILY_TERMS =
  /弟弟|妹妹|哥哥|姐姐|儿子|女儿|孩子|爷爷|奶奶|外公|外婆|丈夫|妻子|老公|老婆/;

function aliasesFor(member: HouseholdMember): string[] {
  return [...new Set([member.displayName, ...ROLE_ALIASES[member.roleLabel]])];
}

function membersMentioned(
  text: string,
  members: HouseholdMember[]
): HouseholdMember[] {
  return members.filter((member) =>
    aliasesFor(member).some((alias) => text.includes(alias))
  );
}

/**
 * Resolve an explicitly stated diner subset. Ordinary planning requests without
 * a diner phrase keep the current selection.
 */
export function extractDinerSelection(
  text: string,
  members: HouseholdMember[]
): DinerSelection {
  if (/没有人|没人|都不吃|无人(?:吃饭|用餐|就餐)/.test(text)) {
    return { kind: "needs_clarification", reason: "empty" };
  }

  if (/全家|一家三口|所有人|大家|我们三个人/.test(text)) {
    return { kind: "resolved", dinerIds: members.map((member) => member.id) };
  }

  const numericCount = text.match(/(?:我们)?([一二两三123])个?人/);
  if (numericCount) {
    const countByLabel: Record<string, number> = {
      一: 1,
      "1": 1,
      二: 2,
      两: 2,
      "2": 2,
      三: 3,
      "3": 3
    };
    const count = countByLabel[numericCount[1] ?? ""];
    if (count === members.length) {
      return { kind: "resolved", dinerIds: members.map((member) => member.id) };
    }
    return { kind: "needs_clarification", reason: "ambiguous" };
  }

  // Require non-empty content between 就/只有 and 吃 so ordinary “就吃…” is not a diner subset.
  const explicitSubset =
    text.match(/(?:只有|仅有|仅|就)([^。！？，,]+?)(?:吃|用餐|就餐)/)?.[1] ??
    text.match(/([^。！？，,]+?)(?:一起)?吃(?:午饭|晚饭|午餐|晚餐)/)?.[1];

  if (explicitSubset == null) {
    return { kind: "unspecified" };
  }

  const selected = membersMentioned(explicitSubset, members);
  if (selected.length === 0 || UNKNOWN_FAMILY_TERMS.test(explicitSubset)) {
    return { kind: "needs_clarification", reason: "unknown" };
  }

  return {
    kind: "resolved",
    dinerIds: selected.map((member) => member.id)
  };
}

export function extractRejectedFoodIds(text: string): string[] {
  const ids: string[] = [];
  if (/鸡腿|鸡肉/.test(text) && /不要|不想|别|拒绝|别做|不吃/.test(text)) {
    ids.push("food-chicken-leg");
  }
  if (/花生/.test(text) && /不要|避开|过敏|拒绝/.test(text)) {
    ids.push("food-peanut");
  }
  if (/牛肉/.test(text) && /不要|不吃|拒绝/.test(text)) {
    ids.push("food-beef");
  }
  return [...new Set(ids)];
}

export function extractPriorityFoodIds(text: string): string[] {
  const ids: string[] = [];
  if (/豆腐/.test(text) && /优先|最好|快坏|吃掉|用掉|先用/.test(text)) {
    ids.push("food-tofu");
  }
  if (/米饭|昨日米饭/.test(text) && /优先|先用|吃掉/.test(text)) {
    ids.push("food-rice-cooked");
  }
  return [...new Set(ids)];
}

export function extractRejectedTemplateIds(text: string): string[] {
  const ids: string[] = [];
  if (/蒸蛋|香菇蒸蛋/.test(text) && /不要|不想|换|拒绝|别/.test(text)) {
    ids.push("tpl-shiitake-egg");
  }
  if (/鸡腿/.test(text) && /土豆|炖/.test(text) && /不要|不想|换/.test(text)) {
    ids.push("tpl-potato-chicken");
  }
  return [...new Set(ids)];
}

/**
 * @deprecated Prefer resolveMealTypeSlot from product-semantics (no silent lunch).
 * Kept for callers that still expect a non-null value; returns lunch only when
 * lunch cues present, dinner when dinner cues present, else lunch for legacy
 * unit tests that pass explicit 午餐 phrases.
 */
export function extractMealType(text: string): "lunch" | "dinner" {
  if (/晚|晚饭|晚餐|今晚/.test(text) && !/午|午饭|午餐|中午/.test(text)) {
    return "dinner";
  }
  if (/午|午饭|午餐|中午/.test(text)) return "lunch";
  // Legacy fallback — new product paths must call resolveMealTypeSlot instead.
  return "lunch";
}

export function extractPreferLowEffort(text: string): boolean {
  return /更省事|尽量省事|省事一点|简单一点|简单点|少折腾|快手/.test(text);
}
