export const DIMENSIONS = 1536;

// ── Embedding API (OpenAI-compatible) ─────────────────────────
// Supports any OpenAI-compatible embedding endpoint.
// Set EMBEDDING_API_KEY + EMBEDDING_API_URL to enable real embeddings.
// Without them, falls back to local character trigram/bigram hashing.
const EMBEDDING_API_KEY = process.env.EMBEDDING_API_KEY || "";
const EMBEDDING_API_URL =
  process.env.EMBEDDING_API_URL ||
  "https://api.siliconflow.cn/v1/embeddings";
const EMBEDDING_MODEL = process.env.EMBEDDING_MODEL || "BAAI/bge-large-zh-v1.5";
const embeddingCache = new Map<string, number[]>();

function hashContent(text: string): string {
  let h = 0;
  for (let i = 0; i < text.length; i++) {
    h = ((h << 5) - h + text.charCodeAt(i)) | 0;
  }
  return String(h);
}

export interface EmbeddingResult {
  embedding: number[];
  cached: boolean;
  error?: string;
}

/** Pad or truncate embedding to match DIMENSIONS (schema requires vector(1536)). */
function normalizeDimensions(vec: number[]): number[] {
  if (vec.length === DIMENSIONS) return vec;
  if (vec.length > DIMENSIONS) return vec.slice(0, DIMENSIONS);
  // Pad with zeros — extra zeros don't affect cosine distance
  return [...vec, ...new Array(DIMENSIONS - vec.length).fill(0)];
}

async function callEmbeddingApi(input: string | string[]): Promise<number[][]> {
  const res = await fetch(EMBEDDING_API_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${EMBEDDING_API_KEY}`,
    },
    body: JSON.stringify({
      model: EMBEDDING_MODEL,
      input: typeof input === "string" ? input.trim().slice(0, 8191) : input.map((t) => t.trim().slice(0, 8191)),
    }),
  });

  if (!res.ok) {
    const errText = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${errText.slice(0, 200)}`);
  }

  const data = (await res.json()) as { data?: Array<{ embedding: number[]; index?: number }> };
  const embeddings = data.data || [];
  // Sort by index for batch responses
  embeddings.sort((a, b) => (a.index ?? 0) - (b.index ?? 0));
  return embeddings.map((e) => e.embedding || []);
}

function fallbackLocal(text: string, key: string): EmbeddingResult {
  const local = textToEmbedding(text);
  embeddingCache.set(key, local);
  return { embedding: local, cached: false, error: "local_trigram" };
}

/**
 * Generate embedding — tries EMBEDDING_API_URL first (defaults to SiliconFlow BGE model),
 * falls back to local character trigram/bigram hashing.
 * Both produce pgvector-compatible 1536-d vectors.
 */
export async function getEmbedding(text: string): Promise<EmbeddingResult> {
  const key = hashContent(text.trim());
  const cached = embeddingCache.get(key);
  if (cached) return { embedding: cached, cached: true };

  if (!EMBEDDING_API_KEY) return fallbackLocal(text, key);

  try {
    const embeddings = await callEmbeddingApi(text);
    const raw = embeddings[0] || [];
    if (raw.length > 0) {
      const embedding = normalizeDimensions(raw);
      embeddingCache.set(key, embedding);
      return { embedding, cached: false };
    }
    return fallbackLocal(text, key);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error("[Embedding] API error:", msg);
    return fallbackLocal(text, key);
  }
}

/** Batch embedding — API when available, local trigram fallback per text. */
export async function getEmbeddings(texts: string[]): Promise<EmbeddingResult[]> {
  const results: EmbeddingResult[] = [];
  const uncached: { index: number; text: string }[] = [];

  for (let i = 0; i < texts.length; i++) {
    const key = hashContent(texts[i].trim());
    const cached = embeddingCache.get(key);
    if (cached) {
      results[i] = { embedding: cached, cached: true };
    } else {
      uncached.push({ index: i, text: texts[i] });
    }
  }

  if (uncached.length === 0) return results;
  if (!EMBEDDING_API_KEY) {
    for (const { index, text } of uncached) {
      const k = hashContent(text.trim());
      const local = textToEmbedding(text);
      embeddingCache.set(k, local);
      results[index] = { embedding: local, cached: false, error: "local_trigram" };
    }
    return results;
  }

  try {
    const embeddings = await callEmbeddingApi(uncached.map((u) => u.text));
    for (let i = 0; i < uncached.length; i++) {
      const { index, text } = uncached[i];
      const emb = normalizeDimensions(embeddings[i] || []);
      const k = hashContent(text.trim());
      if (emb.length > 0) {
        embeddingCache.set(k, emb);
        results[index] = { embedding: emb, cached: false };
      } else {
        const local = textToEmbedding(text);
        embeddingCache.set(k, local);
        results[index] = { embedding: local, cached: false, error: "empty_response" };
      }
    }
    return results;
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error("[Embedding] Batch API error:", msg);
    for (const { index, text } of uncached) {
      const k = hashContent(text.trim());
      const local = textToEmbedding(text);
      embeddingCache.set(k, local);
      results[index] = { embedding: local, cached: false, error: `api_error` };
    }
    return results;
  }
}

/** Format a number[] embedding as a pgvector-compatible string literal: '[0.1,0.2,...]' */
export function embeddingToPgVector(embedding: number[]): string {
  return `[${embedding.map((v) => v.toFixed(6)).join(",")}]`;
}

/** Compute embedding and format it for SQL INSERT (pgvector cast from text) */
export function computeEmbeddingForSQL(text: string): string {
  const vec = textToEmbedding(text);
  return embeddingToPgVector(vec);
}

function hashTrigram(str: string): number {
  let hash = 5381;
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) + hash + str.charCodeAt(i)) | 0;
  }
  return Math.abs(hash);
}

export function textToEmbedding(text: string): number[] {
  const vec = new Array(DIMENSIONS).fill(0);
  const normalized = text.toLowerCase().replace(/\s+/g, "");

  for (let i = 0; i < normalized.length - 2; i++) {
    const trigram = normalized.substring(i, i + 3);
    const hashVal = hashTrigram(trigram) % DIMENSIONS;
    vec[hashVal] = 1.0;
  }

  for (let i = 0; i < normalized.length - 1; i++) {
    const bigram = normalized.substring(i, i + 2);
    const hashVal = (hashTrigram(bigram) * 31 + 7) % DIMENSIONS;
    vec[hashVal] = 1.0;
  }

  const magnitude = Math.sqrt(vec.reduce((sum, v) => sum + v * v, 0));
  if (magnitude > 0) {
    for (let i = 0; i < DIMENSIONS; i++) vec[i] /= magnitude;
  }

  return vec;
}
