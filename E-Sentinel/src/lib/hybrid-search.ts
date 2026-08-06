// ============================================================================
// Hybrid Search — BM25 (PostgreSQL tsvector) + Vector (pgvector) + RRF merge
// ============================================================================
// 当前 knowledge_entries 表已有 embedding vector(1536) + ivfflat 索引
// 新增: tsvector 列 + GIN 索引 → 实现 BM25 风格全文检索
// RRF (Reciprocal Rank Fusion) 融合两路结果, 一致性排名
// ============================================================================

import { supabaseAdmin } from "./supabase";
import { textToEmbedding, embeddingToPgVector } from "./embedding";

export interface HybridMatch {
  id: string;
  title: string;
  content: string;
  category: string;
  keywords: string[];
  similarity: number;
  rank: number;
}

export interface HybridSearchResult {
  matches: HybridMatch[];
  method: "hybrid" | "vector_only" | "keyword_only" | "none";
  total: number;
}

const RRF_K = 60;          // RRF 常数, 控制顶部结果权重
const RRF_TOPK = 20;       // 每路召回数
const RESULT_LIMIT = 10;   // 最终返回数
const VECTOR_WEIGHT = 0.5; // 加权融合时向量权重
const KEYWORD_WEIGHT = 0.5;

/**
 * RRF merge: 1/(k + rank) for both result lists
 * 降序排列并取前 N
 */
function rrfMerge(
  vecIds: string[],
  kwIds: string[],
  limit: number,
): string[] {
  const scores = new Map<string, number>();

  for (let i = 0; i < vecIds.length; i++) {
    const rank = i + 1;
    scores.set(vecIds[i], (scores.get(vecIds[i]) || 0) + 1.0 / (RRF_K + rank));
  }
  for (let i = 0; i < kwIds.length; i++) {
    const rank = i + 1;
    scores.set(kwIds[i], (scores.get(kwIds[i]) || 0) + 1.0 / (RRF_K + rank));
  }

  return [...scores.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit)
    .map(([id]) => id);
}

/**
 * 加权融合: vector_score * WEIGHT + keyword_score * WEIGHT
 */
function weightedMerge(
  vecScores: Map<string, number>,
  kwScores: Map<string, number>,
  limit: number,
): string[] {
  const allIds = new Set([...vecScores.keys(), ...kwScores.keys()]);
  const fused = [...allIds].map((id) => ({
    id,
    score:
      (vecScores.get(id) || 0) * VECTOR_WEIGHT +
      (kwScores.get(id) || 0) * KEYWORD_WEIGHT,
  }));
  return fused.sort((a, b) => b.score - a.score).slice(0, limit).map((r) => r.id);
}

/**
 * 混合检索: 向量 + BM25 双路 → RRF 融合 → 返回完整条目
 *
 * @param query  - 原始用户查询
 * @param options.threshold - 向量相似度阈值 (默认0)
 * @param options.limit     - 返回条数 (默认10)
 * @param options.mode      - "rrf" | "weighted" | "vector_only" (默认"rrf")
 */
export async function hybridSearch(
  query: string,
  options?: {
    threshold?: number;
    limit?: number;
    mode?: "rrf" | "weighted" | "vector_only";
    matchCount?: number;
    tenantId?: string;
  },
): Promise<HybridSearchResult> {
  const threshold = options?.threshold ?? 0;
  const limit = options?.limit ?? RESULT_LIMIT;
  const mode = options?.mode ?? "rrf";
  const matchCount = options?.matchCount ?? RRF_TOPK;
  const tenantId = options?.tenantId?.trim();

  if (!supabaseAdmin) {
    return { matches: [], method: "none", total: 0 };
  }

  // A service-role client bypasses RLS. Refuse to query without an explicit
  // tenant so internal callers cannot accidentally perform a cross-tenant scan.
  if (!query || !query.trim() || !tenantId) {
    return { matches: [], method: "none", total: 0 };
  }

  // ── 1. 向量检索 ──
  const embedding = textToEmbedding(query);
  const vecStr = embeddingToPgVector(embedding);

  const { data: vecResults, error: vecError } = await supabaseAdmin.rpc(
    "hybrid_search_vector",
    {
      query_embedding: vecStr,
      match_count: matchCount,
      tenant_id: tenantId,
    },
  );

  if (vecError) {
    console.warn("[HybridSearch] vector RPC failed:", vecError.message);
  }

  // ── 2. 关键词检索 (tsquery) ──
  const { data: kwResults, error: kwError } = await supabaseAdmin.rpc(
    "hybrid_search_keyword",
    {
      query_text: query,
      match_count: matchCount,
      tenant_id: tenantId,
    },
  );

  if (kwError) {
    console.warn("[HybridSearch] keyword RPC failed:", kwError.message);
  }

  // ── 3. 融合 ──
  const vecRows = await filterRowsByTenant(
    (vecResults || []) as Array<Record<string, unknown>>,
    tenantId,
  );
  const kwRows = await filterRowsByTenant(
    (kwResults || []) as Array<Record<string, unknown>>,
    tenantId,
  );
  const scopedVecRows = vecRows.filter((row) => Number(row.similarity || 0) >= threshold);
  const scopedKwRows = kwRows.filter((row) => Number(row.similarity || 0) >= threshold);

  // 只有一路有结果时的兜底
  if (scopedVecRows.length === 0 && scopedKwRows.length === 0) {
    return { matches: [], method: "none", total: 0 };
  }
  if (scopedVecRows.length === 0) {
    return formatResults(scopedKwRows, threshold, limit, "keyword_only");
  }
  if (scopedKwRows.length === 0 || mode === "vector_only") {
    return formatResults(scopedVecRows, threshold, limit, "vector_only");
  }

  const vecIds = scopedVecRows.map((r) => String(r.id));
  const kwIds = scopedKwRows.map((r) => String(r.id));
  const similarityById = new Map<string, number>();
  for (const row of [...scopedVecRows, ...scopedKwRows]) {
    const id = String(row.id);
    const similarity = Number(row.similarity || 0);
    similarityById.set(id, Math.max(similarityById.get(id) || 0, similarity));
  }

  let fusedIds: string[];
  if (mode === "weighted") {
    const vecScores = new Map(scopedVecRows.map((r) => [String(r.id), Number(r.similarity || 0)]));
    const kwScores = new Map(scopedKwRows.map((r) => [String(r.id), Number(r.similarity || 0)]));
    fusedIds = weightedMerge(vecScores, kwScores, limit);
  } else {
    fusedIds = rrfMerge(vecIds, kwIds, limit);
  }

  // ── 4. 回查完整条目 ──
  if (fusedIds.length === 0) {
    return { matches: [], method: "none", total: 0 };
  }

  const { data: entries, error: fetchError } = await supabaseAdmin
    .from("knowledge_entries")
    .select("id, title, content, category, keywords")
    .eq("tenant_id", tenantId)
    .eq("status", "published")
    .in("id", fusedIds);

  if (fetchError) {
    console.error("[HybridSearch] fetch failed:", fetchError.message);
    // fallback: 只用向量结果
    return formatResults(scopedVecRows, threshold, limit, "vector_only");
  }

  const entryMap = new Map(
    ((entries || []) as Array<Record<string, unknown>>).map((e) => [String(e.id), e]),
  );

  const matches: HybridMatch[] = fusedIds
    .map((id, idx) => {
      const entry = entryMap.get(id);
      if (!entry) return null;
      return {
        id: String(entry.id),
        title: String(entry.title || ""),
        content: String(entry.content || ""),
        category: String(entry.category || ""),
        keywords: Array.isArray(entry.keywords) ? (entry.keywords as string[]) : [],
        similarity: similarityById.get(id) || 0,
        rank: idx + 1,
      };
    })
    .filter((m): m is HybridMatch => m !== null);

  return { matches, method: "hybrid", total: matches.length };
}

async function filterRowsByTenant(
  rows: Array<Record<string, unknown>>,
  tenantId?: string,
): Promise<Array<Record<string, unknown>>> {
  if (!tenantId || rows.length === 0 || !supabaseAdmin) return [];
  const ids = rows.map((row) => String(row.id)).filter(Boolean);
  const { data, error } = await supabaseAdmin
    .from("knowledge_entries")
    .select("id")
    .eq("tenant_id", tenantId)
    .in("id", ids);
  if (error) {
    console.warn("[HybridSearch] tenant scope failed:", error.message);
    return [];
  }
  const allowed = new Set((data || []).map((row) => String(row.id)));
  return rows.filter((row) => allowed.has(String(row.id)));
}

function formatResults(
  rows: Array<Record<string, unknown>>,
  threshold: number,
  limit: number,
  method: HybridSearchResult["method"],
): HybridSearchResult {
  const matches: HybridMatch[] = rows
    .filter((r) => Number(r.similarity || 0) >= threshold)
    .slice(0, limit)
    .map((r, idx) => ({
      id: String(r.id),
      title: String(r.title || ""),
      content: String(r.content || ""),
      category: String(r.category || ""),
      keywords: Array.isArray(r.keywords) ? (r.keywords as string[]) : [],
      similarity: Number(r.similarity || 0),
      rank: idx + 1,
    }));
  return { matches, method, total: matches.length };
}
