import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { PrivatePlateDomain } from "../service/privateplate-domain.js";
import { HashEmbeddingClient } from "./embeddings.js";

describe("local RAG (embedding retrieval)", () => {
  let domain: PrivatePlateDomain;

  beforeAll(async () => {
    domain = await PrivatePlateDomain.create(":memory:", {
      embedding: new HashEmbeddingClient(64)
    });
  });

  afterAll(() => domain.close());

  it("indexes corpus and reports hash embedding kind offline", () => {
    const info = domain.getEmbeddingInfo();
    expect(info.kind).toBe("hash");
    expect(info.modelId).toBe("hash-embedding-v1");
    const count = domain.db
      .prepare(`SELECT COUNT(*) AS c FROM rag_chunks`)
      .get() as { c: number };
    expect(count.c).toBeGreaterThan(0);
  });

  it("retrieves task-card privacy chunks for disclosure queries", async () => {
    const result = await domain.retrieveLocalKnowledge({
      query: "发给保姆的任务卡能不能写疾病名？最小披露怎么做？",
      topK: 3
    });
    expect(result.embeddingKind).toBe("hash");
    expect(result.retrievalVersion).toContain("rag-embedding");
    expect(result.hits.length).toBeGreaterThan(0);
    const blob = result.hits.map((h) => `${h.title} ${h.content}`).join("\n");
    expect(blob).toMatch(/疾病|披露|任务卡/);
    expect(result.hits[0]!.sourcePath).toMatch(/knowledge\/corpus\//);
    expect(result.hits[0]!.score).toBeGreaterThan(0);
  });

  it("retrieves agent-selection protocol for ranking questions", async () => {
    const result = await domain.retrieveLocalKnowledge({
      query: "Domain 会不会自动选 winner 或给菜品打分排名？",
      topK: 2
    });
    expect(result.hits.length).toBeGreaterThan(0);
    const blob = result.hits.map((h) => `${h.title} ${h.content}`).join("\n");
    expect(blob).toMatch(/winner|打分|Agent|选菜|校验/);
  });
});
