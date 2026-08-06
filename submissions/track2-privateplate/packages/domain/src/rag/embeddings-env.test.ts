import { describe, expect, it } from "vitest";
import {
  DEFAULT_EMBEDDING_BASE_URL,
  DEFAULT_EMBEDDING_MODEL,
  createEmbeddingClientFromEnv,
  describeEmbeddingEnv
} from "./embeddings.js";

describe("embedding env resolution", () => {
  it("defaults to hash offline when RAG is not enabled", () => {
    const client = createEmbeddingClientFromEnv({
      PRIVATEPLATE_RAG_OFFLINE: undefined,
      PRIVATEPLATE_RAG_MODE: undefined,
      PRIVATEPLATE_EMBEDDING_MODEL: undefined,
      PRIVATEPLATE_EMBEDDING_BASE_URL: undefined
    } as NodeJS.ProcessEnv);
    expect(client.kind).toBe("hash");
  });

  it("uses bge-small-zh defaults when RAG_MODE=vllm", () => {
    const env = {
      PRIVATEPLATE_RAG_MODE: "vllm"
    } as NodeJS.ProcessEnv;
    const client = createEmbeddingClientFromEnv(env);
    expect(client.kind).toBe("vllm");
    expect(client.modelId).toBe(DEFAULT_EMBEDDING_MODEL);
    const desc = describeEmbeddingEnv(env);
    expect(desc.baseUrl).toBe(DEFAULT_EMBEDDING_BASE_URL);
    expect(desc.modelId).toBe("BAAI/bge-small-zh-v1.5");
  });

  it("honors dedicated embedding base URL", () => {
    const client = createEmbeddingClientFromEnv({
      PRIVATEPLATE_RAG_MODE: "vllm",
      PRIVATEPLATE_EMBEDDING_BASE_URL: "http://127.0.0.1:9001/v1",
      PRIVATEPLATE_EMBEDDING_MODEL: "BAAI/bge-small-zh-v1.5"
    } as NodeJS.ProcessEnv);
    expect(client.kind).toBe("vllm");
    expect(client.modelId).toBe("BAAI/bge-small-zh-v1.5");
  });

  it("RAG_OFFLINE forces hash even if model is set", () => {
    const client = createEmbeddingClientFromEnv({
      PRIVATEPLATE_RAG_OFFLINE: "yes",
      PRIVATEPLATE_RAG_MODE: "vllm",
      PRIVATEPLATE_EMBEDDING_MODEL: "BAAI/bge-small-zh-v1.5"
    } as NodeJS.ProcessEnv);
    expect(client.kind).toBe("hash");
  });
});
