#!/usr/bin/env node
/**
 * vLLM 延迟/吞吐 benchmark（用于 FP16 vs GPTQ 性能门禁对比）。
 *
 * 用法：node scripts/bench-latency.mjs --base-url http://localhost:8000 --model <id> [--concurrency 1,4,8]
 * 输出：TTFT / E2E P50/P95 / output tok/s / request/s（JSON 到 stdout）
 */
import { config } from "dotenv";
config({ path: ".env.local", override: true });

function arg(name, def) {
  const i = process.argv.indexOf(name);
  return i >= 0 ? process.argv[i + 1] ?? def : def;
}
const BASE_URL = arg("--base-url", "http://localhost:8000");
const MODEL = arg("--model", "/workspace/Qwen3-8B");
const CONCURRENCIES = arg("--concurrency", "1,4,8").split(",").map(Number);

const PROMPT = "你是客服质检裁判。请评估以下客服会话并输出 JSON。客服：您好，请问有什么可以帮您？客户：我收到的相机是假的。客服：我们自己确认是正品，你爱信不信。";

async function oneRequest(concurrentN, idx) {
  const t0 = Date.now();
  const res = await fetch(`${BASE_URL}/v1/chat/completions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model: MODEL,
      messages: [{ role: "user", content: PROMPT }],
      max_tokens: 200,
      chat_template_kwargs: { enable_thinking: false },
    }),
    signal: AbortSignal.timeout(120000),
  });
  const ttft = Date.now() - t0;
  if (!res.ok) return { ok: false, error: `http_${res.status}`, ttft };
  const j = await res.json();
  const usage = j.usage || {};
  return {
    ok: true,
    ttft,
    e2e: Date.now() - t0,
    outTokens: usage.completion_tokens || 0,
  };
}

async function runConcurrency(n) {
  const results = [];
  const workers = Array.from({ length: n }, async (_, i) => {
    const r = await oneRequest(n, i);
    results.push(r);
  });
  await Promise.all(workers);
  const ok = results.filter((r) => r.ok);
  const ttfts = ok.map((r) => r.ttft).sort((a, b) => a - b);
  const e2es = ok.map((r) => r.e2e).sort((a, b) => a - b);
  const totalTok = ok.reduce((a, r) => a + r.outTokens, 0);
  const wallMs = Math.max(...e2es, 1);
  const p = (arr, q) => arr.length ? arr[Math.min(arr.length - 1, Math.floor(arr.length * q))] : 0;
  return {
    concurrency: n,
    requests: ok.length,
    failures: results.length - ok.length,
    ttft_ms: { p50: p(ttfts, 0.5), p95: p(ttfts, 0.95) },
    e2e_ms: { p50: p(e2es, 0.5), p95: p(e2es, 0.95) },
    output_tok_per_s: Math.round(totalTok / (wallMs / 1000)),
    requests_per_s: Number((ok.length / (wallMs / 1000)).toFixed(2)),
    total_output_tokens: totalTok,
  };
}

const out = { base_url: BASE_URL, model: MODEL, generated_at: null, runs: [] };
for (const n of CONCURRENCIES) {
  const r = await runConcurrency(n);
  out.runs.push(r);
  console.log(`并发 ${n}: req/s=${r.requests_per_s} tok/s=${r.output_tok_per_s} TTFT p50=${r.ttft_ms.p50}ms E2E p50=${r.e2e_ms.p50}ms 失败=${r.failures}`);
}
console.log(JSON.stringify(out, null, 2));
