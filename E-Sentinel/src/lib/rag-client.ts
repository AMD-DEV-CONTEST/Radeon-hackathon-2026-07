/**
 * RAG 检索客户端。
 *
 * 服务级融合：E-Sentinel 的 agent 工具 `retrieve_policy` / `retrieve_knowledge`
 * 通过 HTTP 调 RAG 的 /api/eval/retrieve，拿回带引用的知识来源。
 *
 * 用法：
 *   RAG_BASE_URL=http://localhost:3000   # RAG 服务地址
 *   RAG_API_KEY=<rag 的 INTERNAL_API_KEY>
 */
import {
  normalizeRetrieveResponse,
  validateRetrieveRequest,
  isGrounded,
  type RetrieveRequest,
  type RetrieveSource,
  type RetrieveResponse,
} from "./rag-contract";

export type { RetrieveSource };
export type RAGSource = RetrieveSource;

/** 检索结果 = 契约响应 + 供 agent 工具使用的 contextText 摘要。 */
export interface RAGRetrievalResult extends RetrieveResponse {
  contextText: string;
}

const RAG_BASE_URL = (process.env.RAG_BASE_URL || "").replace(/\/$/, "");
const RAG_API_KEY = process.env.RAG_API_KEY || process.env.INTERNAL_API_KEY || "";

function buildContextText(sources: RAGSource[]): string {
  return sources
    .map((s, i) => `[${i + 1}] ${s.title || "来源"}${s.snippet ? `\n${s.snippet}` : ""}`)
    .join("\n\n");
}

/**
 * 检索 RAG 知识库。失败返回 ok:false（不抛异常，供 agent 工具容错）。
 * 走 C2 冻结契约：请求校验 + 响应规范化（含 grounded/bestSimilarity 派生字段）。
 */
export async function retrieveRag(
  query: string,
  intent = "product_qa",
  timeoutMs = 8000,
): Promise<RAGRetrievalResult> {
  const req: RetrieveRequest = { query, intent };
  const check = validateRetrieveRequest(req);
  if (!check.ok || !RAG_BASE_URL || !RAG_API_KEY) {
    return { ok: false, retrievalMode: "none", sources: [], contextText: "", grounded: false, bestSimilarity: null, sourceCount: 0 };
  }

  const url = new URL(`${RAG_BASE_URL}/api/eval/retrieve`);
  url.searchParams.set("q", query);
  url.searchParams.set("intent", intent);

  try {
    const res = await fetch(url, {
      headers: { "x-api-key": RAG_API_KEY },
      signal: AbortSignal.timeout(timeoutMs),
    });
    if (!res.ok) {
      return { ok: false, retrievalMode: "none", sources: [], contextText: "", grounded: false, bestSimilarity: null, sourceCount: 0 };
    }
    const normalized = normalizeRetrieveResponse(await res.json());
    const contextText = buildContextText(normalized.sources);
    return { ...normalized, contextText };
  } catch {
    return { ok: false, retrievalMode: "none", sources: [], contextText: "", grounded: false, bestSimilarity: null, sourceCount: 0 };
  }
}

/** 引用是否有效（有来源且 bestSimilarity 达阈值）。供 citation validation（C3）使用。 */
export function retrievalGrounded(result: RAGRetrievalResult): boolean {
  return isGrounded(result);
}
