// ============================================================================
// Tests for Hybrid Search Module
// ============================================================================

import { textToEmbedding, embeddingToPgVector } from "@/lib/embedding";

// ── 测试 RRF 融合算法 ──────────────────────────────────────

const RRF_K = 60;

function rrfMerge(
  vecIds: string[],
  kwIds: string[],
  limit: number,
): string[] {
  const scores = new Map<string, number>();
  for (let i = 0; i < vecIds.length; i++) {
    scores.set(vecIds[i], (scores.get(vecIds[i]) || 0) + 1.0 / (RRF_K + i + 1));
  }
  for (let i = 0; i < kwIds.length; i++) {
    scores.set(kwIds[i], (scores.get(kwIds[i]) || 0) + 1.0 / (RRF_K + i + 1));
  }
  return [...scores.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit)
    .map(([id]) => id);
}

describe("HybridSearch - RRF Merge", () => {
  test("both lists empty returns empty", () => {
    expect(rrfMerge([], [], 10)).toEqual([]);
  });

  test("single list passes through in order", () => {
    const result = rrfMerge(["a", "b", "c"], [], 3);
    expect(result).toEqual(["a", "b", "c"]);
  });

  test("items in both lists rank highest", () => {
    const vec = ["a", "b", "c", "d", "e"];
    const kw = ["x", "b", "y", "a", "z"];
    const result = rrfMerge(vec, kw, 5);
    // a: RRF = 1/(60+1) + 1/(60+4) = 0.01639 + 0.01563 = 0.03202
    // b: RRF = 1/(60+2) + 1/(60+2) = 0.01613 + 0.01613 = 0.03226
    // b 略高于 a
    expect(result.indexOf("b")).toBeLessThan(result.indexOf("c"));
    expect(result.indexOf("a")).toBeLessThan(result.indexOf("c"));
  });

  test("respects limit", () => {
    const result = rrfMerge(["a", "b", "c", "d"], ["e", "f", "g", "h"], 2);
    expect(result.length).toBe(2);
  });

  test("100% overlap - all items match", () => {
    const ids = ["a", "b", "c", "d", "e"];
    const result = rrfMerge(ids, ids, 5);
    expect(result).toEqual(ids);
  });

  test("disjoint sets still produce merged result", () => {
    const result = rrfMerge(["a", "b"], ["c", "d"], 4);
    expect(result.length).toBe(4);
    expect(result).toContain("a");
    expect(result).toContain("c");
  });
});

describe("HybridSearch - Weighted Merge", () => {
  const vecScores = new Map([["a", 0.9], ["b", 0.5], ["c", 0.3]]);
  const kwScores = new Map([["b", 0.8], ["c", 0.7], ["d", 0.9]]);
  const VW = 0.5, KW = 0.5;

  function weightedMerge(limit: number): string[] {
    const allIds = new Set([...vecScores.keys(), ...kwScores.keys()]);
    return [...allIds]
      .map((id) => ({
        id,
        score: (vecScores.get(id) || 0) * VW + (kwScores.get(id) || 0) * KW,
      }))
      .sort((a, b) => b.score - a.score)
      .slice(0, limit)
      .map((r) => r.id);
  }

  test("weighted merge combines scores correctly", () => {
    const result = weightedMerge(4);
    // b: 0.5*0.5 + 0.8*0.5 = 0.65 → 最高
    // c: 0.3*0.5 + 0.7*0.5 = 0.50
    // a: 0.9*0.5 + 0.0*0.5 = 0.45
    // d: 0.0*0.5 + 0.9*0.5 = 0.45
    expect(result[0]).toBe("b");
    expect(result[1]).toBe("c");
  });
});

describe("HybridSearch - Embedding Integration", () => {
  test("textToEmbedding produces 1536-d vector", () => {
    const vec = textToEmbedding("发货物流查询");
    expect(vec.length).toBe(1536);
    expect(vec.every((v) => typeof v === "number")).toBe(true);
  });

  test("same text produces same embedding (deterministic)", () => {
    const a = textToEmbedding("今天天气不错");
    const b = textToEmbedding("今天天气不错");
    expect(a).toEqual(b);
  });

  test("different texts produce different embeddings", () => {
    const a = textToEmbedding("发货");
    const b = textToEmbedding("退款");
    expect(a).not.toEqual(b);
  });

  test("embeddingToPgVector formats correctly", () => {
    const vec = [0.123456, 0.789012, -0.345678];
    const result = embeddingToPgVector(vec);
    expect(result).toBe("[0.123456,0.789012,-0.345678]");
  });

  test("embeddingToPgVector handles full 1536-d vector", () => {
    const vec = new Array(1536).fill(0).map((_, i) => Math.sin(i));
    const result = embeddingToPgVector(vec);
    expect(result.startsWith("[")).toBe(true);
    expect(result.endsWith("]")).toBe(true);
    expect(result.split(",").length).toBe(1536);
  });

  test("empty string produces valid vector", () => {
    const vec = textToEmbedding("");
    expect(vec.length).toBe(1536);
  });
});

describe("HybridSearch - Edge Cases", () => {
  test("RRF handles single item lists", () => {
    expect(rrfMerge(["a"], [], 1)).toEqual(["a"]);
    expect(rrfMerge([], ["a"], 1)).toEqual(["a"]);
  });

  test("RRF with duplicate IDs in same list", () => {
    // 不应该出现, 但如果出现了, 应该去重处理
    const result = rrfMerge(["a", "a", "b"], ["c"], 3);
    expect(new Set(result).size).toBe(result.length); // 无重复
  });
});
