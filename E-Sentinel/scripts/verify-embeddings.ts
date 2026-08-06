/**
 * Verification script: embedding generation, semantic match, Few-Shot.
 * Run: npx tsx scripts/verify-embeddings.ts
 */
import { getEmbedding, getEmbeddings, textToEmbedding, embeddingToPgVector } from "../src/lib/embedding";

async function main() {
  let passed = 0;
  let failed = 0;

  function check(label: string, condition: boolean, detail?: string) {
    if (condition) {
      console.log(`  ✅ ${label}`);
      passed++;
    } else {
      console.log(`  ❌ ${label}${detail ? ` — ${detail}` : ""}`);
      failed++;
    }
  }

  // ── 1. Embedding dimension ──────────────────────────────
  console.log("\n📐 1. Embedding dimension check");
  const emb1 = textToEmbedding("测试文本");
  check("textToEmbedding returns 1536-d", emb1.length === 1536, `got ${emb1.length}`);
  check("vector is normalized (magnitude ~1)", Math.abs(Math.sqrt(emb1.reduce((s, v) => s + v * v, 0)) - 1) < 0.001);

  // ── 2. getEmbedding (local fallback) ────────────────────
  console.log("\n🔤 2. getEmbedding — local trigram fallback");
  const r1 = await getEmbedding("客户投诉物流延迟");
  check("getEmbedding returns embedding", r1.embedding.length > 0, `len=${r1.embedding.length}`);
  check("error signals local_trigram", r1.error === "local_trigram", `error=${r1.error}`);

  // ── 3. Cache hit ────────────────────────────────────────
  console.log("\n💾 3. In-memory cache");
  const r2 = await getEmbedding("客户投诉物流延迟");
  check("second call returns cached", r2.cached === true);

  const r3 = await getEmbedding("不同的文本内容");
  check("different text is NOT cached", r3.cached === false);

  // ── 4. Batch embedding ─────────────────────────────────
  console.log("\n📦 4. Batch embedding");
  const batch = await getEmbeddings(["文本A", "文本B", "客户投诉物流延迟"]);
  check("batch returns 3 results", batch.length === 3);
  check("batch[0] is fresh", !batch[0].cached && batch[0].embedding.length > 0);
  check("batch[2] is cached (same text)", batch[2].cached === true);

  // ── 5. pgVector formatting ──────────────────────────────
  console.log("\n📐 5. pgVector formatting");
  const vec = embeddingToPgVector(emb1);
  check("starts with [", vec.startsWith("["));
  check("ends with ]", vec.endsWith("]"));
  check("contains comma-separated floats", vec.includes(",") && vec.includes("."));
  check("exactly 1536 elements", vec.split(",").length === 1536, `got ${vec.split(",").length}`);

  // ── 6. Cosine similarity sanity ─────────────────────────
  console.log("\n📊 6. Cosine similarity sanity check");
  const a = textToEmbedding("物流太慢了我要投诉");
  const b = textToEmbedding("快递延迟很严重");
  const c = textToEmbedding("今天天气不错适合出去玩");
  const cosAB = cosineSimilarity(a, b);
  const cosAC = cosineSimilarity(a, c);
  check("similar texts (物流) have higher similarity", cosAB > cosAC, `cos(AB)=${cosAB.toFixed(3)} cos(AC)=${cosAC.toFixed(3)}`);

  // ── Summary ─────────────────────────────────────────────
  console.log(`\n${"═".repeat(50)}`);
  console.log(`  Results: ${passed} passed, ${failed} failed`);
  console.log(`${"═".repeat(50)}`);

  if (failed > 0) process.exit(1);
}

function cosineSimilarity(a: number[], b: number[]): number {
  let dot = 0, na = 0, nb = 0;
  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i];
    na += a[i] * a[i];
    nb += b[i] * b[i];
  }
  return dot / (Math.sqrt(na) * Math.sqrt(nb));
}

main().catch((e) => { console.error(e); process.exit(1); });
