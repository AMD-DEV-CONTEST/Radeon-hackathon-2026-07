import type { OutcomeCandidate, OutcomeType } from "./types.js";

export function touchSummaryBlob(o: OutcomeCandidate): void {
  const nFiles = o.scope.paths.length;
  const nTests = o.verification_anchors.filter((a) => a.kind === "test").length;
  const parts = [
    `${o.type} ${o.title}: ${o.status}`,
    nFiles > 0 ? `(+${nFiles} files)` : null,
    nTests > 0 ? `(${nTests} verify anchors)` : null,
  ].filter(Boolean);
  o.summary_blob = parts.join(" ").slice(0, 1000);
}

export function titleFromClaim(
  text: string,
  hint?: string,
  max = 120,
): string {
  if (hint && hint.trim()) return hint.trim().slice(0, 200);
  const t = text.replace(/\s+/g, " ").trim();
  if (t.length <= max) return t || "Untitled claim";
  return t.slice(0, max - 1) + "…";
}

export function typeFromClaimHints(
  claim_kind: string,
  type_hint?: OutcomeType,
): OutcomeType {
  if (type_hint) return type_hint;
  switch (claim_kind) {
    case "fixed":
      return "bugfix";
    case "implemented":
    case "completed":
    case "works_now":
      return "feature";
    default:
      return "chore";
  }
}

export function jaccard(a: string[], b: string[]): number {
  if (a.length === 0 && b.length === 0) return 1;
  if (a.length === 0 || b.length === 0) return 0;
  const A = new Set(a.map((p) => p.replace(/\\/g, "/")));
  const B = new Set(b.map((p) => p.replace(/\\/g, "/")));
  let inter = 0;
  for (const x of A) if (B.has(x)) inter += 1;
  const union = A.size + B.size - inter;
  return union === 0 ? 0 : inter / union;
}

/** Types that may auto-merge (R-M1). */
export function typesCompatible(a: OutcomeType, b: OutcomeType): boolean {
  if (a === b) return true;
  const soft: Record<string, OutcomeType[]> = {
    bugfix: ["problem"],
    problem: ["bugfix"],
    feature: ["refactor"],
    refactor: ["feature", "chore"],
    chore: ["refactor", "docs"],
    docs: ["chore"],
    spike: ["investigation"],
    investigation: ["spike"],
  };
  return soft[a]?.includes(b) ?? false;
}

export function titleSimilarity(a: string, b: string): number {
  const tok = (s: string) =>
    new Set(
      s
        .toLowerCase()
        .replace(/[^a-z0-9一-鿿]+/g, " ")
        .split(/\s+/)
        .filter(Boolean),
    );
  const A = tok(a);
  const B = tok(b);
  if (A.size === 0 || B.size === 0) return 0;
  let inter = 0;
  for (const x of A) if (B.has(x)) inter += 1;
  return inter / Math.max(A.size, B.size);
}
