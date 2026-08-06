#!/usr/bin/env node
/**
 * C4 三路检索对照 + 跨租户隔离（#171）。
 *
 * 固定同一查询集，比较三条检索路径：
 *   1. pgvector（Supabase hybrid_search_vector，vector_only）
 *   2. RAG（/api/eval/retrieve）
 *   3. no-RAG 基线（不检索 → 无来源 → 拒答/人工的对照）
 *
 * 指标：Recall@5、MRR、延迟 P50/P95、政策查询无来源率、跨租户泄漏数（预期=0）。
 *
 * 用法：
 *   node --env-file=.env.local scripts/retrieval-ablation-3way.mjs
 * 输出：evals/results/retrieval-ablation-3way-<ts>.json
 *
 * 说明：RAG 语料（Gemini 335 相机参数）与 Supabase 语料（政策/摄像头）不同，
 * 三路 Recall 如实报告——语料覆盖差异本身就是检索系统对比的有效证据。
 */

import { config } from "dotenv";
config({ path: ".env.local", override: true });

import { writeFileSync } from "node:fs";
import { createClient } from "@supabase/supabase-js";

// ── 复刻 src/lib/embedding.ts 的 textToEmbedding（trigram+bigram → 1536 稀疏向量）──
const DIM = 1536;
function hashTrigram(str) {
  let h = 5381;
  for (let i = 0; i < str.length; i++) h = ((h << 5) + h + str.charCodeAt(i)) | 0;
  return Math.abs(h);
}
function textToEmbedding(text) {
  const vec = new Array(DIM).fill(0);
  const norm = text.toLowerCase().replace(/\s+/g, "");
  for (let i = 0; i < norm.length - 2; i++) {
    vec[hashTrigram(norm.substring(i, i + 3)) % DIM] = 1.0;
  }
  for (let i = 0; i < norm.length - 1; i++) {
    vec[(hashTrigram(norm.substring(i, i + 2)) * 31 + 7) % DIM] = 1.0;
  }
  return vec;
}
function embeddingToPgVector(emb) {
  return `[${emb.map((v) => v.toFixed(6)).join(",")}]`;
}

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL;
const SUPABASE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY;
const RAG_URL = (process.env.RAG_BASE_URL || "").replace(/\/$/, "");
const RAG_KEY = process.env.RAG_API_KEY || process.env.INTERNAL_API_KEY || "";
const TENANT_A = process.env.NEXT_PUBLIC_DASHBOARD_TENANT_ID || "";
const TENANT_B = process.env.QA_TENANT_B_ID || "tenant-b-secret"; // 第二租户（隔离测试）

const sb = SUPABASE_URL && SUPABASE_KEY ? createClient(SUPABASE_URL, SUPABASE_KEY) : null;

// ── 查询集（统一） ──
const QUERIES = [
  // 产品 QA（RAG 语料）
  { q: "Gemini 335 深度范围", expect: "Gemini 335" },
  { q: "Gemini 335 深度视场角", expect: "Gemini 335" },
  { q: "Gemini 335 重量", expect: "Gemini 335" },
  { q: "Gemini 335 USB 接口", expect: "Gemini 335" },
  { q: "Femto Mega 接口类型", expect: "Femto Mega" },
  { q: "Orbbec SDK 支持 Linux 吗", expect: "Orbbec SDK" },
  // 摄像头/连接（Supabase 语料）
  { q: "摄像头怎么连接WiFi", expect: "摄像头" },
  { q: "摄像头连接WiFi步骤", expect: "WiFi" },
  // 政策（两库都可能）
  { q: "退货退款流程", expect: "" },
  { q: "7天无理由退货规则", expect: "" },
];

// ── 三路检索 ──
async function pgvectorRetrieve(query, tenantId) {
  if (!sb) return { ok: false, sources: [] };
  try {
    const { data, error } = await sb.rpc("hybrid_search_vector", {
      query_embedding: embeddingToPgVector(textToEmbedding(query)),
      match_count: 5,
      tenant_id: tenantId,
    });
    if (error) return { ok: false, sources: [], error: error.message };
    return { ok: true, sources: (data || []).map((r) => ({ title: r.title || "", snippet: r.content || "", similarity: r.similarity ?? 0, tenant: r.tenant_id })) };
  } catch (e) {
    return { ok: false, sources: [], error: e.message };
  }
}

async function ragRetrieve(query) {
  if (!RAG_URL || !RAG_KEY) return { ok: false, sources: [] };
  try {
    const url = new URL(`${RAG_URL}/api/eval/retrieve`);
    url.searchParams.set("q", query);
    url.searchParams.set("intent", "product_qa");
    const res = await fetch(url, { headers: { "x-api-key": RAG_KEY }, signal: AbortSignal.timeout(8000) });
    if (!res.ok) return { ok: false, sources: [] };
    const data = await res.json();
    return { ok: data.ok !== false, sources: Array.isArray(data.sources) ? data.sources.map((s) => ({ title: (s.title || "") + "", snippet: (s.snippet || "") + "", similarity: s.similarity ?? 0 })) : [] };
  } catch {
    return { ok: false, sources: [] };
  }
}

function hit(sources, expect) {
  if (!expect) return sources.length > 0 ? { hit: true, sim: Math.max(...sources.map((s) => s.similarity)) } : { hit: false, sim: 0 };
  for (const s of sources) if (s.title && s.title.includes(expect)) return { hit: true, sim: s.similarity };
  return { hit: false, sim: 0 };
}

async function main() {
  const t0 = Date.now();
  const paths = { pgvector: pgvectorRetrieve, rag: ragRetrieve };
  const results = {};

  for (const [name, fn] of Object.entries(paths)) {
    const lat = [];
    const hits = [];
    const rows = [];
    for (const query of QUERIES) {
      const s = Date.now();
      const res = await fn(query.q, TENANT_A);
      lat.push(Date.now() - s);
      const h = hit(res.sources, query.expect);
      hits.push(h.hit);
      rows.push({ q: query.q, expect: query.expect, ok: res.ok, sourceCount: res.sources.length, hit: h.hit, sim: Number(h.sim.toFixed(3)), err: res.error || undefined });
    }
    // MRR
    let mrr = 0;
    for (const query of QUERIES) {
      const res = await fn(query.q, TENANT_A);
      let rank = 0;
      for (let j = 0; j < res.sources.length; j++) {
        if (!query.expect || res.sources[j].title?.includes(query.expect)) { rank = j + 1; break; }
      }
      mrr += rank > 0 ? 1 / rank : 0;
    }
    const sorted = [...lat].sort((a, b) => a - b);
    const n = QUERIES.length;
    const noSource = rows.filter((r) => r.sourceCount === 0).length / n;
    results[name] = {
      recall_at_5: Number((hits.filter(Boolean).length / n).toFixed(3)),
      mrr: Number((mrr / n).toFixed(3)),
      no_source_rate: Number(noSource.toFixed(3)),
      latency_ms: { p50: sorted[Math.floor(n * 0.5)], p95: sorted[Math.floor(n * 0.95)], mean: Math.round(lat.reduce((a, b) => a + b, 0) / n) },
      per_query: rows,
    };
  }

  // no-RAG 基线：不检索 → 无来源（政策查询必然拒答/转人工）
  results.no_rag = {
    note: "不检索基线：任何查询都无来源 → 无来源拒绝率 1.0（fail-closed 转人工），Recall@5 N/A",
    recall_at_5: "N/A",
    mrr: "N/A",
    no_source_rate: 1.0,
  };

  // ── 跨租户泄漏测试（pgvector 路：tenant A 查询，结果必须全部属于 A）──
  let leakCount = 0;
  let tenantRowsChecked = 0;
  if (sb) {
    for (const query of QUERIES) {
      const res = await pgvectorRetrieve(query.q, TENANT_A);
      for (const s of res.sources) {
        tenantRowsChecked += 1;
        if (s.tenant && s.tenant !== TENANT_A) leakCount += 1;
      }
    }
  }
  results.cross_tenant = {
    method: "pgvector: tenant A 查询，检查返回行 tenant_id",
    rows_checked: tenantRowsChecked,
    leaks: leakCount,
    expected: 0,
  };

  const file = `evals/results/retrieval-ablation-3way-${Date.now()}.json`;
  const out = { generated_at: new Date().toISOString(), queries: QUERIES.length, results };
  writeFileSync(file, JSON.stringify(out, null, 2) + "\n");

  for (const [k, v] of Object.entries(results)) {
    if (k === "cross_tenant") continue;
    console.log(`${k}: Recall@5=${v.recall_at_5} MRR=${v.mrr} 无来源率=${v.no_source_rate} P50=${v.latency_ms?.p50 ?? "-"}ms`);
  }
  console.log(`跨租户泄漏: ${results.cross_tenant.leaks} / ${results.cross_tenant.rows_checked} 行（预期 0）`);
  console.log(`报告: ${file}`);
}

main();
