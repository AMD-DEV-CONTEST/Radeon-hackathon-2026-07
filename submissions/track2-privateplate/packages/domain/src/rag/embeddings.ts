/**
 * Embedding clients for local RAG.
 * Recommended production path: BAAI/bge-small-zh-v1.5 on a dedicated loopback
 * vLLM port (default 8001), separate from the chat model on 8000.
 * Offline/tests: deterministic hash embedding (not model-quality evidence).
 */

/** Recommended default for PrivatePlate Chinese local RAG. */
export const DEFAULT_EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5";

/** bge-small-zh-v1.5 output size. */
export const DEFAULT_EMBEDDING_DIMS = 512;

/** Dedicated embedding server (chat stays on 8000). */
export const DEFAULT_EMBEDDING_BASE_URL = "http://127.0.0.1:8001/v1";

export type EmbeddingClient = {
  readonly kind: "vllm" | "hash";
  readonly modelId: string;
  /** Fixed output dimensions (hash is fixed; vLLM is discovered on first call). */
  dimensions: number;
  embed(texts: string[]): Promise<number[][]>;
};

export type VllmEmbeddingOptions = {
  baseUrl: string;
  model: string;
  apiKey?: string;
  timeoutMs?: number;
  fetchImpl?: typeof fetch;
  /** Optional fixed dims when the server reports them; otherwise inferred. */
  dimensions?: number;
};

function isLoopbackHost(hostname: string): boolean {
  return (
    hostname === "127.0.0.1" ||
    hostname === "localhost" ||
    hostname === "::1" ||
    hostname === "[::1]"
  );
}

export class VllmEmbeddingClient implements EmbeddingClient {
  readonly kind = "vllm" as const;
  readonly modelId: string;
  dimensions: number;
  private readonly endpoint: URL;
  private readonly apiKey: string | undefined;
  private readonly timeoutMs: number;
  private readonly fetchImpl: typeof fetch;

  constructor(options: VllmEmbeddingOptions) {
    const base = options.baseUrl.endsWith("/")
      ? options.baseUrl
      : `${options.baseUrl}/`;
    const baseUrl = new URL(base);
    if (!isLoopbackHost(baseUrl.hostname)) {
      throw new Error(
        "PrivatePlate RAG embedding must use a loopback vLLM URL (127.0.0.1/localhost)."
      );
    }
    this.endpoint = new URL("embeddings", baseUrl);
    this.modelId = options.model.trim();
    if (!this.modelId) {
      throw new Error("PRIVATEPLATE_EMBEDDING_MODEL is required for vLLM embeddings.");
    }
    this.dimensions = options.dimensions ?? 0;
    this.apiKey = options.apiKey;
    this.timeoutMs = options.timeoutMs ?? 120_000;
    this.fetchImpl = options.fetchImpl ?? fetch;
  }

  get baseUrl(): string {
    return this.endpoint.origin + this.endpoint.pathname.replace(/\/embeddings$/, "");
  }

  async embed(texts: string[]): Promise<number[][]> {
    if (texts.length === 0) return [];
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const headers: Record<string, string> = {
        "content-type": "application/json"
      };
      if (this.apiKey) {
        headers.authorization = `Bearer ${this.apiKey}`;
      }
      const response = await this.fetchImpl(this.endpoint, {
        method: "POST",
        headers,
        body: JSON.stringify({
          model: this.modelId,
          input: texts.length === 1 ? texts[0] : texts
        }),
        signal: controller.signal
      });
      if (!response.ok) {
        const body = await response.text().catch(() => "");
        throw new Error(
          `vLLM embeddings HTTP ${response.status} (${this.endpoint.href}): ${body.slice(0, 400)}`
        );
      }
      const json = (await response.json()) as {
        data?: Array<{ embedding?: number[]; index?: number }>;
      };
      const rows = Array.isArray(json.data) ? json.data : [];
      if (rows.length !== texts.length) {
        throw new Error(
          `vLLM embeddings returned ${rows.length} vectors for ${texts.length} inputs`
        );
      }
      const ordered = [...rows].sort(
        (a, b) => (a.index ?? 0) - (b.index ?? 0)
      );
      const vectors = ordered.map((row) => {
        if (!Array.isArray(row.embedding) || row.embedding.length === 0) {
          throw new Error("vLLM embeddings response missing embedding array");
        }
        return row.embedding.map((n) => Number(n));
      });
      if (this.dimensions === 0) {
        this.dimensions = vectors[0]!.length;
      }
      for (const v of vectors) {
        if (v.length !== this.dimensions) {
          throw new Error(
            `Embedding dim mismatch: expected ${this.dimensions}, got ${v.length}`
          );
        }
      }
      return vectors.map(l2Normalize);
    } finally {
      clearTimeout(timer);
    }
  }
}

/**
 * Offline/test embedder: bag-of-character hash into fixed dims.
 * Not model-quality evidence — only structure tests.
 */
export class HashEmbeddingClient implements EmbeddingClient {
  readonly kind = "hash" as const;
  readonly modelId = "hash-embedding-v1";
  dimensions: number;

  constructor(dimensions = 64) {
    this.dimensions = dimensions;
  }

  async embed(texts: string[]): Promise<number[][]> {
    return texts.map((text) => hashEmbed(text, this.dimensions));
  }
}

/**
 * Resolve embedding client from env.
 *
 * Real RAG (recommended):
 *   PRIVATEPLATE_RAG_MODE=vllm
 *   PRIVATEPLATE_EMBEDDING_BASE_URL=http://127.0.0.1:8001/v1
 *   PRIVATEPLATE_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5   # default when mode=vllm
 *
 * Offline / unit tests:
 *   PRIVATEPLATE_RAG_OFFLINE=yes  OR  omit RAG_MODE and EMBEDDING_*
 */
export function createEmbeddingClientFromEnv(
  env: NodeJS.ProcessEnv = process.env
): EmbeddingClient {
  if (env.PRIVATEPLATE_RAG_OFFLINE === "yes") {
    return new HashEmbeddingClient();
  }

  const mode = (env.PRIVATEPLATE_RAG_MODE ?? "").trim().toLowerCase();
  const explicitModel = env.PRIVATEPLATE_EMBEDDING_MODEL?.trim();
  const explicitBase = env.PRIVATEPLATE_EMBEDDING_BASE_URL?.trim();
  const useVllm =
    mode === "vllm" ||
    mode === "embedding" ||
    Boolean(explicitModel) ||
    Boolean(explicitBase);

  if (!useVllm) {
    return new HashEmbeddingClient();
  }

  const model = explicitModel || DEFAULT_EMBEDDING_MODEL;
  // Prefer dedicated embedding port; do not default to chat :8000.
  const baseUrl =
    explicitBase ||
    env.PRIVATEPLATE_VLLM_EMBED_BASE_URL?.trim() ||
    DEFAULT_EMBEDDING_BASE_URL;

  const options: VllmEmbeddingOptions = {
    baseUrl,
    model,
    timeoutMs: Number(
      env.PRIVATEPLATE_EMBEDDING_TIMEOUT_MS ??
        env.PRIVATEPLATE_REQUEST_TIMEOUT_MS ??
        120_000
    )
  };
  if (env.PRIVATEPLATE_VLLM_API_KEY) {
    options.apiKey = env.PRIVATEPLATE_VLLM_API_KEY;
  }
  if (env.PRIVATEPLATE_EMBEDDING_DIMS) {
    options.dimensions = Number(env.PRIVATEPLATE_EMBEDDING_DIMS);
  } else if (model === DEFAULT_EMBEDDING_MODEL || model.includes("bge-small-zh")) {
    options.dimensions = DEFAULT_EMBEDDING_DIMS;
  }
  return new VllmEmbeddingClient(options);
}

export function describeEmbeddingEnv(env: NodeJS.ProcessEnv = process.env): {
  mode: "vllm" | "hash";
  modelId: string;
  baseUrl: string | null;
  dims: number | null;
} {
  const client = createEmbeddingClientFromEnv(env);
  if (client.kind === "hash") {
    return {
      mode: "hash",
      modelId: client.modelId,
      baseUrl: null,
      dims: client.dimensions
    };
  }
  const baseUrl =
    env.PRIVATEPLATE_EMBEDDING_BASE_URL?.trim() ||
    env.PRIVATEPLATE_VLLM_EMBED_BASE_URL?.trim() ||
    DEFAULT_EMBEDDING_BASE_URL;
  return {
    mode: "vllm",
    modelId: client.modelId,
    baseUrl,
    dims: client.dimensions || DEFAULT_EMBEDDING_DIMS
  };
}

function hashEmbed(text: string, dims: number): number[] {
  const vec = new Array<number>(dims).fill(0);
  const normalized = text.normalize("NFKC").toLowerCase();
  for (let i = 0; i < normalized.length; i++) {
    const code = normalized.charCodeAt(i);
    const unigram = code % dims;
    vec[unigram]! += 1;
    if (i + 1 < normalized.length) {
      const bigram =
        (code * 31 + normalized.charCodeAt(i + 1)) % dims;
      vec[bigram]! += 1.5;
    }
  }
  if (normalized.length === 0) {
    vec[0] = 1;
  }
  return l2Normalize(vec);
}

export function l2Normalize(vector: number[]): number[] {
  let sum = 0;
  for (const n of vector) sum += n * n;
  const norm = Math.sqrt(sum);
  if (norm === 0) return vector.map(() => 0);
  return vector.map((n) => n / norm);
}

export function cosineSimilarity(a: number[], b: number[]): number {
  const n = Math.min(a.length, b.length);
  let dot = 0;
  for (let i = 0; i < n; i++) {
    dot += a[i]! * b[i]!;
  }
  return dot;
}

export function float32ToBuffer(vector: number[]): Buffer {
  const arr = new Float32Array(vector);
  return Buffer.from(arr.buffer, arr.byteOffset, arr.byteLength);
}

export function bufferToFloat32(buf: Buffer | Uint8Array): number[] {
  const copy = Buffer.isBuffer(buf) ? buf : Buffer.from(buf);
  const aligned =
    copy.byteOffset % 4 === 0
      ? copy
      : Buffer.from(copy);
  const view = new Float32Array(
    aligned.buffer,
    aligned.byteOffset,
    aligned.byteLength / 4
  );
  return Array.from(view);
}
