#!/usr/bin/env node
/**
 * 导出 AMD vLLM 并发证据文件（B8 证据包收口）。
 *
 * 用途：AMD DevMaster Track 2 提交证据。将 vllm bench 实测输出
 * benchmarks/amd/summary.json 的 batch/interactive 数据按并发级别导出为
 * 独立文件 concurrency-{1,2,4,8}.json，与计划 B8「concurrency-1/4/8」对齐。
 *
 * 用法：node scripts/export-amd-concurrency.mjs
 * 输出：benchmarks/amd/concurrency-{1,2,4,8}.json
 *
 * 数据真实性：仅从 summary.json（实测输出）与 ablation-control.json（同源
 * 硬件/模型元数据）读取，不生成任何新数字；interactive 仅在 summary 中存在
 * 对应并发级别时输出（c4/c8 无 interactive 实测，不编造）。
 */

import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const AMD_DIR = path.join(ROOT, "benchmarks", "amd");

const summary = JSON.parse(readFileSync(path.join(AMD_DIR, "summary.json"), "utf8"));
const control = JSON.parse(readFileSync(path.join(AMD_DIR, "ablation-control.json"), "utf8"));

// 并发级别：summary.batch 全部保留（c1/c2/c4/c8），与 ablation-control 一致
const levels = Object.keys(summary.batch).sort();

const meta = {
  model: control.model,
  hardware: control.hardware,
};

for (const level of levels) {
  const c = level.replace("c", "");
  const file = {
    note: `AMD vLLM 并发=${c} 证据（B8）。来源：benchmarks/amd/summary.json（vllm bench 实测），
与 ablation-control.json 的 concurrency_${c} 同源一致；0 failures 表示该并发下无请求失败。`,
    model: meta.model,
    hardware: meta.hardware,
    concurrency: Number(c),
    batch: summary.batch[level],
  };
  // interactive 仅在实测存在时输出（当前仅 c1/c2 有数据）
  if (summary.interactive && summary.interactive[level]) {
    file.interactive = summary.interactive[level];
  }
  const out = path.join(AMD_DIR, `concurrency-${c}.json`);
  writeFileSync(out, `${JSON.stringify(file, null, 2)}\n`);
  console.log(`✓ ${path.relative(ROOT, out)} (batch ${file.batch.req_per_s} req/s · ${file.batch.tokens_per_s} tok/s · ${file.batch.failures} failures)`);
}
