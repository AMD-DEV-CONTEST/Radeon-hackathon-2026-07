import type { Food } from "@privateplate/contracts";

export function buildFoodAliasIndex(foods: Food[]): Map<string, string> {
  const index = new Map<string, string>();
  for (const food of foods) {
    index.set(normalizeAlias(food.canonicalName), food.id);
    for (const alias of food.aliases) {
      index.set(normalizeAlias(alias), food.id);
    }
  }
  return index;
}

export function resolveFoodId(
  aliasIndex: Map<string, string>,
  text: string
): string | null {
  return aliasIndex.get(normalizeAlias(text)) ?? null;
}

export function normalizeAlias(value: string): string {
  return value.trim().toLowerCase().replace(/\s+/g, "");
}
