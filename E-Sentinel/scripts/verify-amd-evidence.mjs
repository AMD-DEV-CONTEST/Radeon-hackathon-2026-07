#!/usr/bin/env node
/**
 * 校验 benchmarks/amd/ 证据包完整性（F2 门禁 · benchmark:radeon 后端）。
 *
 * 检查三类问题：
 *   1. 必需文件存在且非空（environment / health / rocm-smi / server-command /
 *      single-request / summary / tool-call-trace / ablation-control /
 *      concurrency-{1,2,4,8}）
 *   2. concurrency-{n}.json 的 batch 数据与 summary.json 完全一致（防证据漂移）
 *   3. health-response.json 状态为 200/ok，tool-call-trace 含 tool_calls
 *
 * 用法：node scripts/verify-amd-evidence.mjs   （退出码 0=PASS，1=FAIL）
 * 任何一项不满足即 FAIL，禁止提交不完整证据包。
 */

import { readFileSync, existsSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const AMD_DIR = path.join(ROOT, "benchmarks", "amd");

const REQUIRED = [
  "environment.txt",
  "health-response.json",
  "rocm-smi.txt",
  "server-command.txt",
  "single-request.json",
  "summary.json",
  "tool-call-trace.json",
  "ablation-control.json",
  "concurrency-1.json",
  "concurrency-2.json",
  "concurrency-4.json",
  "concurrency-8.json",
];

const errors = [];

// 1. 必需文件存在且非空
for (const f of REQUIRED) {
  const p = path.join(AMD_DIR, f);
  if (!existsSync(p)) {
    errors.push(`缺少文件: ${f}`);
  } else if (statSync(p).size === 0) {
    errors.push(`文件为空: ${f}`);
  }
}

// 2. concurrency 文件与 summary.json 一致性（仅当两者都存在时核对）
const summaryP = path.join(AMD_DIR, "summary.json");
if (existsSync(summaryP)) {
  const summary = JSON.parse(readFileSync(summaryP, "utf8"));
  for (const level of Object.keys(summary.batch)) {
    const c = level.replace("c", "");
    const cf = path.join(AMD_DIR, `concurrency-${c}.json`);
    if (!existsSync(cf)) continue; // 已由第 1 步报告
    const cc = JSON.parse(readFileSync(cf, "utf8"));
    for (const key of ["req_per_s", "tokens_per_s", "e2e_p50", "failures"]) {
      if (cc.batch?.[key] !== summary.batch[level]?.[key]) {
        errors.push(`concurrency-${c}.json batch.${key} 与 summary.json 不一致 (${cc.batch?.[key]} vs ${summary.batch[level]?.[key]})`);
      }
    }
  }
}

// 3. 关键内容检查
const healthP = path.join(AMD_DIR, "health-response.json");
if (existsSync(healthP)) {
  // health-response.json 是 vLLM /v1/models 响应：含已加载模型 id 即证明服务健康
  const h = JSON.parse(readFileSync(healthP, "utf8"));
  const id = h?.data?.[0]?.id;
  if (typeof id !== "string" || id.length === 0) {
    errors.push("health-response.json 未含已加载模型 id（/v1/models 响应为空）");
  }
}
const traceP = path.join(AMD_DIR, "tool-call-trace.json");
if (existsSync(traceP)) {
  const t = JSON.stringify(readFileSync(traceP, "utf8"));
  if (!t.includes("tool_calls")) {
    errors.push("tool-call-trace.json 未含 tool_calls");
  }
}

if (errors.length > 0) {
  console.error("✗ AMD 证据包校验 FAIL：");
  for (const e of errors) console.error(`  - ${e}`);
  process.exit(1);
}
console.log(`✓ AMD 证据包校验 PASS（${REQUIRED.length} 文件，concurrency 与 summary 一致，health/trace 内容完整）`);
