/**
 * RAG 检索契约（C2，冻结版，零依赖）。
 *
 * 服务级融合的接口契约：E-Sentinel 侧 typed client + 运行时校验 +
 * 引用有效性（grounded）判定。冻结后不改字段语义；服务端富化字段
 * （sourceId/chunkId/contentHash/effectiveAt/rrfScore）缺失时按 null 处理，
 * 不阻塞现有链路。
 */
export const RAG_INTENTS = ["product_qa", "policy_qa", "wiki_tech"] as const;
export type RagIntent = (typeof RAG_INTENTS)[number];

export interface RetrieveRequest {
  query: string;
  /** 缺省按 product_qa 处理（调用方兜底）。 */
  intent?: RagIntent | string;
  tenantId?: string;
  topK?: number;
}

export interface RetrieveSource {
  title: string | null;
  snippet: string | null;
  model_context?: string | null;
  url?: string | null;
  doc_type?: string | null;
  similarity?: number | null;
  /** 服务端富化字段（可选，缺失为 null） */
  sourceId?: string | null;
  chunkId?: string | null;
  contentHash?: string | null;
  effectiveAt?: string | null;
  rrfScore?: number | null;
}

export interface RetrieveResponse {
  ok: boolean;
  retrievalMode: string;
  queryId?: string;
  sources: RetrieveSource[];
  /** 派生：有来源且最佳相似度达阈值（引用有效性） */
  grounded: boolean;
  bestSimilarity: number | null;
  sourceCount: number;
}

export const RAG_ERROR_CODES = {
  NOT_CONFIGURED: "RAG_NOT_CONFIGURED",
  SERVER_ERROR: "RAG_SERVER_ERROR",
  EMPTY_RESULT: "RAG_EMPTY_RESULT",
  INVALID_RESPONSE: "RAG_INVALID_RESPONSE",
} as const;
export type RagErrorCode = (typeof RAG_ERROR_CODES)[keyof typeof RAG_ERROR_CODES];

/** 引用被视为有效的最低相似度（与 RAG 实测 top-1 ~1.0 / top-5 ~0.98 对齐，取宽松阈值） */
export const GROUNDED_SIMILARITY_THRESHOLD = 0.6;

export function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

export function toNullableString(v: unknown): string | null {
  return typeof v === "string" ? v : null;
}

export function toNullableNumber(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/**
 * 校验请求：query 非空、intent 为合法意图（unknown intent 视为 product_qa，不阻塞）。
 */
export function validateRetrieveRequest(req: RetrieveRequest): { ok: boolean; error?: string } {
  if (!req || typeof req.query !== "string" || !req.query.trim()) {
    return { ok: false, error: "RAG request requires non-empty query" };
  }
  return { ok: true };
}

/**
 * 规范化并校验 RAG 原始响应（fail-closed：畸形响应按无效失败处理，
 * 但保留 ok 语义——服务不可用 vs 无结果由调用方区分）。
 */
export function normalizeRetrieveResponse(raw: unknown): RetrieveResponse {
  if (!isRecord(raw)) {
    return { ok: false, retrievalMode: "none", sources: [], grounded: false, bestSimilarity: null, sourceCount: 0 };
  }
  const rawSources = Array.isArray(raw.sources) ? raw.sources : [];
  const sources: RetrieveSource[] = rawSources
    .filter(isRecord)
    .slice(0, 20)
    .map((s) => ({
      title: toNullableString(s.title),
      snippet: toNullableString(s.snippet),
      model_context: toNullableString(s.model_context),
      url: toNullableString(s.url),
      doc_type: toNullableString(s.doc_type),
      similarity: toNullableNumber(s.similarity),
      sourceId: toNullableString(s.sourceId),
      chunkId: toNullableString(s.chunkId),
      contentHash: toNullableString(s.contentHash),
      effectiveAt: toNullableString(s.effectiveAt),
      rrfScore: toNullableNumber(s.rrfScore),
    }));

  const best = sources.reduce<number | null>(
    (m, s) => (s.similarity != null && (m === null || s.similarity > m) ? s.similarity : m),
    null,
  );
  return {
    ok: raw.ok !== false,
    retrievalMode: typeof raw.retrievalMode === "string" ? raw.retrievalMode : "db",
    queryId: toNullableString(raw.queryId) ?? undefined,
    sources,
    grounded: best !== null && best >= GROUNDED_SIMILARITY_THRESHOLD,
    bestSimilarity: best,
    sourceCount: sources.length,
  };
}

/** 引用是否有效：有来源且 bestSimilarity 达阈值。 */
export function isGrounded(resp: RetrieveResponse): boolean {
  return resp.grounded && resp.sourceCount > 0;
}
