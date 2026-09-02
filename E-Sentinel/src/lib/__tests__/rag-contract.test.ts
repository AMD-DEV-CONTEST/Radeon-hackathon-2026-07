/**
 * RAG 契约测试（C2 冻结版）：
 *   1. 请求校验（空 query 拒绝）
 *   2. 响应规范化（sources 解析、grounded/bestSimilarity 派生）
 *   3. fail-closed（畸形响应按无效处理，不抛异常）
 *   4. 引用有效性判定（isGrounded / 阈值）
 *   5. 富化字段容忍（服务端缺失时按 null，不阻塞）
 */
import {
  validateRetrieveRequest,
  normalizeRetrieveResponse,
  isGrounded,
  GROUNDED_SIMILARITY_THRESHOLD,
} from "../rag-contract";

describe("rag-contract", () => {
  it("validateRetrieveRequest 拒绝空 query", () => {
    expect(validateRetrieveRequest({ query: "" }).ok).toBe(false);
    expect(validateRetrieveRequest({ query: "   " }).ok).toBe(false);
    expect(validateRetrieveRequest({ query: "退款政策" }).ok).toBe(true);
  });

  it("normalizeRetrieveResponse 解析 sources 并派生 bestSimilarity", () => {
    const raw = {
      ok: true,
      retrievalMode: "db",
      sources: [
        { title: "Orbbec Gemini 335", snippet: "深度范围 0.10-20m", similarity: 0.98 },
        { title: "Orbbec Gemini 336", snippet: "深度范围 0.1-20m", similarity: 0.7 },
      ],
    };
    const r = normalizeRetrieveResponse(raw);
    expect(r.ok).toBe(true);
    expect(r.retrievalMode).toBe("db");
    expect(r.sourceCount).toBe(2);
    expect(r.bestSimilarity).toBeCloseTo(0.98, 5);
    expect(r.grounded).toBe(true); // 0.98 >= 0.6
  });

  it("normalizeRetrieveResponse 畸形输入 fail-closed", () => {
    expect(normalizeRetrieveResponse(null).ok).toBe(false);
    expect(normalizeRetrieveResponse("junk").ok).toBe(false);
    expect(normalizeRetrieveResponse({ sources: "not-array" }).ok).toBe(true); // 非 ok:false 视为 ok
    expect(normalizeRetrieveResponse({ ok: false }).ok).toBe(false);
    expect(normalizeRetrieveResponse({ sources: [{ title: 123 }] }).sourceCount).toBe(1); // 非字符串字段降级 null
  });

  it("isGrounded 阈值判定", () => {
    const above = normalizeRetrieveResponse({ ok: true, sources: [{ similarity: GROUNDED_SIMILARITY_THRESHOLD }] });
    expect(isGrounded(above)).toBe(true);
    const below = normalizeRetrieveResponse({ ok: true, sources: [{ similarity: 0.2 }] });
    expect(isGrounded(below)).toBe(false);
    const empty = normalizeRetrieveResponse({ ok: true, sources: [] });
    expect(isGrounded(empty)).toBe(false);
  });

  it("富化字段缺失时容忍为 null", () => {
    const r = normalizeRetrieveResponse({
      ok: true,
      sources: [{ title: "T", snippet: "S", sourceId: "src-1", rrfScore: 0.8 }],
    });
    expect(r.sources[0].sourceId).toBe("src-1");
    expect(r.sources[0].rrfScore).toBe(0.8);
    // 缺失字段为 null 而非 undefined
    expect(r.sources[0].contentHash).toBe(null);
    expect(r.sources[0].effectiveAt).toBe(null);
    expect(r.sources[0].chunkId).toBe(null);
  });
});
