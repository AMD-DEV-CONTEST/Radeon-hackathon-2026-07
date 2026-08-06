#!/usr/bin/env node
/**
 * Smoke-check the dedicated embedding vLLM (default :8001, bge-small-zh-v1.5).
 * Usage:
 *   node scripts/rag/check-embeddings.mjs
 *   PRIVATEPLATE_EMBEDDING_BASE_URL=http://127.0.0.1:8001/v1 node scripts/rag/check-embeddings.mjs
 */
const baseUrl = (
  process.env.PRIVATEPLATE_EMBEDDING_BASE_URL ||
  process.env.PRIVATEPLATE_VLLM_EMBED_BASE_URL ||
  "http://127.0.0.1:8001/v1"
).replace(/\/$/, "");
const model =
  process.env.PRIVATEPLATE_EMBEDDING_MODEL || "BAAI/bge-small-zh-v1.5";

const modelsUrl = `${baseUrl}/models`;
const embedUrl = `${baseUrl}/embeddings`;

console.log(`[rag-check] models: ${modelsUrl}`);
console.log(`[rag-check] model:  ${model}`);

let modelsRes;
try {
  modelsRes = await fetch(modelsUrl);
} catch (error) {
  console.error(
    `[rag-check] FAIL cannot reach embedding server: ${error.message}`
  );
  console.error(
    "Start bge-small on loopback :8001, e.g. bash scripts/rag/serve-bge-small.example.sh"
  );
  process.exit(1);
}

if (!modelsRes.ok) {
  console.error(`[rag-check] FAIL /models HTTP ${modelsRes.status}`);
  process.exit(1);
}
const modelsJson = await modelsRes.json();
console.log(
  `[rag-check] /models ok, ids:`,
  (modelsJson.data || []).map((m) => m.id).join(", ") || "(none listed)"
);

const embedRes = await fetch(embedUrl, {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({
    model,
    input: "任务卡能不能写疾病名？最小披露怎么做？"
  })
});
const embedText = await embedRes.text();
if (!embedRes.ok) {
  console.error(`[rag-check] FAIL /embeddings HTTP ${embedRes.status}`);
  console.error(embedText.slice(0, 500));
  process.exit(1);
}
let embedJson;
try {
  embedJson = JSON.parse(embedText);
} catch {
  console.error("[rag-check] FAIL embeddings body is not JSON");
  process.exit(1);
}
const vector = embedJson?.data?.[0]?.embedding;
if (!Array.isArray(vector) || vector.length === 0) {
  console.error("[rag-check] FAIL missing data[0].embedding array");
  process.exit(1);
}
console.log(
  `[rag-check] PASS embedding dim=${vector.length} sample=[${vector
    .slice(0, 4)
    .map((n) => Number(n).toFixed(4))
    .join(", ")}…]`
);
console.log(
  "[rag-check] Next: export PRIVATEPLATE_RAG_MODE=vllm and start PrivatePlate server."
);
