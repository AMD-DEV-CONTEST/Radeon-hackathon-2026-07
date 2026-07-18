export const HEADER_GRADIENT = "bg-gradient-to-r from-indigo-600 to-purple-600";

export const TYPE_TAG_COLORS = {
  finding: "text-red-500",
  insight: "text-blue-500",
  warning: "text-yellow-500",
  precedent: "text-violet-500",
  procedure: "text-green-500",
} as const;

export type ArticleType = keyof typeof TYPE_TAG_COLORS;

export function trustColor(pct: number): string {
  if (pct >= 70) return "text-green-500";
  if (pct >= 40) return "text-yellow-500";
  return "text-red-500";
}
