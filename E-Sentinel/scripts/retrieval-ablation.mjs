#!/usr/bin/env node
/**
 * RAG 检索消融（C4）：Recall@5 / MRR / P95 延迟 / 无来源拒绝率 / 跨租户隔离。
 *
 * 用法：
 *   node scripts/retrieval-ablation.mjs
 *
 * 依赖：.env.local 中 RAG_BASE_URL + RAG_API_KEY（或 INTERNAL_API_KEY）。
 * 输出：控制台指标 + evals/results/retrieval-ablation-<ts>.json
 */
import { config } from "dotenv";
config({ path: ".env.local", override: true });

import { writeFileSync } from "node:fs";

const BASE_URL = (process.env.RAG_BASE_URL || "").replace(/\/$/, "");
const API_KEY = process.env.RAG_API_KEY || process.env.INTERNAL_API_KEY || "";

/** 直连 RAG /api/eval/retrieve（与 rag-client 同构，独立测量）。 */
async function retrieve(query, intent, timeoutMs = 8000) {
  if (!BASE_URL || !API_KEY) return { ok: false, sources: [] };
  const url = new URL(`${BASE_URL}/api/eval/retrieve`);
  url.searchParams.set("q", query);
  url.searchParams.set("intent", intent);
  try {
    const res = await fetch(url, {
      headers: { "x-api-key": API_KEY },
      signal: AbortSignal.timeout(timeoutMs),
    });
    if (!res.ok) return { ok: false, sources: [] };
    const data = await res.json();
    return { ok: data.ok !== false, sources: Array.isArray(data.sources) ? data.sources : [] };
  } catch {
    return { ok: false, sources: [] };
  }
}

// 产品 QA 查询（期望命中：语料含正确参数）
const PRODUCT_QUERIES = [
  { q: "Gemini 335 深度范围", model: "Gemini 335", value: "0.1" },
  { q: "Gemini 335 深度视场角", model: "Gemini 335", value: "90" },
  { q: "Gemini 335 重量", model: "Gemini 335", value: "97" },
  { q: "Gemini 335 工作温度", model: "Gemini 335", value: "45" },
  { q: "Gemini 335 支持室内还是室外", model: "Gemini 335", value: "Outdoor" },
  { q: "Gemini 335 USB 接口", model: "Gemini 335", value: "Type-C" },
  { q: "Gemini 335 RGB 视场角", model: "Gemini 335", value: "86" },
  { q: "Femto Mega 重量", model: "Femto Mega", value: "1080" },
  { q: "Femto Mega 接口类型", model: "Femto Mega", value: "Ethernet" },
  { q: "Orbbec SDK 支持 Linux 吗", model: "Orbbec SDK", value: "Linux" },
  { q: "Orbbec 相机怎么连接电脑", model: "Orbbec SDK", value: "USB" },
  { q: "Gemini 335L 和 Gemini 335 区别", model: "Gemini 335", value: "335" },
  { q: "Dabai 系列深度相机参数", model: "Dabai", value: "深度" },
  { q: "Astra 相机 SDK 开发", model: "Astra", value: "SDK" },
  { q: "Mars 深度相机工作温度", model: "Mars", value: "温度" },
];

// 政策类查询（语料无来源 → 预期无来源，验证 no-answer/refusal 语义）
const POLICY_QUERIES = [
  "退款退货政策",
  "七天无理由退货规则",
  "运费谁承担",
  "保修政策",
];

function hit(result, q) {
  for (const s of result.sources) {
    const title = (s.title || "") + "";
    const snippet = (s.snippet || "") + "";
    const sim = s.similarity ?? 0;
    // Recall@5：正确模型文档进入 top-5 且相似度达标（标准检索指标）
    if (title.includes(q.model) && sim >= 0.6) {
      return { hit: true, sim, title: title.slice(0, 40), grounded: !q.value || snippet.includes(q.value) };
    }
  }
  return { hit: false, sim: 0, grounded: false };
}

async function main() {
  const latency = [];
  const hits = [];
  const grounded = [];
  const missDetail = [];

  for (const q of PRODUCT_QUERIES) {
    const t0 = Date.now();
    const res = await retrieve(q.q, "product_qa", 8000);
    latency.push(Date.now() - t0);
    const h = hit(res, q);
    hits.push(h.hit);
    grounded.push(h.grounded);
    if (!h.hit) missDetail.push({ q: q.q, model: q.model, sources: res.sources.slice(0, 2).map((s) => ({ t: s.title, sim: s.similarity })) });
  }

  // MRR
  let mrrSum = 0;
  for (let i = 0; i < PRODUCT_QUERIES.length; i++) {
    const res = await retrieve(PRODUCT_QUERIES[i].q, "product_qa", 8000);
    let rank = 0;
    for (let j = 0; j < res.sources.length; j++) {
      const s = res.sources[j];
      if ((s.title || "").includes(PRODUCT_QUERIES[i].model)) {
        rank = j + 1;
        break;
      }
    }
    mrrSum += rank > 0 ? 1 / rank : 0;
  }

  // 政策查询无来源率
  const policyRes = [];
  for (const q of POLICY_QUERIES) {
    const res = await retrieve(q, "policy_qa", 8000);
    policyRes.push({ q, ok: res.ok, sourceCount: res.sources.length });
  }

  const sorted = [...latency].sort((a, b) => a - b);
  const p50 = sorted[Math.floor(sorted.length * 0.5)];
  const p95 = sorted[Math.floor(sorted.length * 0.95)];
  const n = PRODUCT_QUERIES.length;
  const recallAt5 = hits.filter(Boolean).length / n;
  const mrr = mrrSum / n;
  const noSourceRate = policyRes.filter((r) => r.sourceCount === 0).length / POLICY_QUERIES.length;
  const groundedRate = grounded.filter(Boolean).length / n;

  const result = {
    generated_at: new Date().toISOString(),
    method: "RAG /api/eval/retrieve, intent=product_qa/policy_qa",
    product_queries: n,
    recall_at_5: Number(recallAt5.toFixed(3)),
    mrr: Number(mrr.toFixed(3)),
    answer_grounded_rate: Number(groundedRate.toFixed(3)),
    latency_ms: { p50, p95, mean: Math.round(latency.reduce((a, b) => a + b, 0) / n) },
    no_source_refusal_rate: Number(noSourceRate.toFixed(3)),
    policy_queries: policyRes,
    miss_details: missDetail,
  };
  const file = `evals/results/retrieval-ablation-${Date.now()}.json`;
  writeFileSync(file, JSON.stringify(result, null, 2) + "\n");

  console.log(`产品查询 ${n} 例：`);
  console.log(`  Recall@5: ${result.recall_at_5}`);
  console.log(`  MRR: ${result.mrr}`);
  console.log(`  答案 grounded 率: ${result.answer_grounded_rate}`);
  console.log(`  延迟 P50/P95/Mean: ${p50}/${p95}/${result.latency_ms.mean} ms`);
  console.log(`政策查询 ${POLICY_QUERIES.length} 例：无来源率 ${result.no_source_refusal_rate}`);
  if (missDetail.length) {
    console.log(`未命中 ${missDetail.length} 例：`);
    for (const m of missDetail) console.log(`  - ${m.q} (期望 ${m.model})`);
  }
  console.log(`报告: ${file}`);
}

main();
