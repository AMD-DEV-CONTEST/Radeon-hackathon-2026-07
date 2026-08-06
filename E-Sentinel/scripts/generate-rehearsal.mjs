#!/usr/bin/env node
/**
 * Stock rehearsal 数据生成器（B′ 能力保持 + 错误揭示）。
 *
 * 原理：对已有已知 label 的会话，用 Stock Qwen3-8B（本地 vLLM，经 QA 服务）生成判定。
 *   - stock 判定 == 已知 label → rehearsal 样本（保持基础能力，防微调遗忘）
 *   - stock 判定 != 已知 label → stock_errors（揭示 stock 误报/漏报，供困难负例分析）
 *
 * 注意：rehearsal 只用于基础能力保持；降 FPR 依赖困难负例/工具上下文样本。
 *
 * 用法：
 *   node scripts/generate-rehearsal.mjs \
 *     --input training/data/candidates-b1.jsonl \
 *     --base-url http://localhost:3003 --concurrency 3
 * 输出：training/data/rehearsal.jsonl + training/data/stock-errors.jsonl + 报告
 */

import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
function arg(name, def) {
  const i = process.argv.indexOf(name);
  return i >= 0 ? process.argv[i + 1] ?? def : def;
}
const INPUT = arg("--input", "training/data/candidates-b1.jsonl");
const BASE_URL = arg("--base-url", "http://localhost:3003");
const CONCURRENCY = Number(arg("--concurrency", "3"));

const rows = readFileSync(path.join(ROOT, INPUT), "utf8").split("\n").filter(Boolean).map((l, i) => ({ line: i + 1, obj: JSON.parse(l) }));

async function evaluate(conversation, toolContext) {
  const body = {
    conversation,
    ticket_id: "rehearsal",
    review_mode: "shadow",
    skip_feishu: true,
    eval_mode: "dual",
    use_agent: false,
    no_cache: true,
    ...(toolContext ? { retrieval_context: toolContext } : {}),
  };
  try {
    const res = await fetch(`${BASE_URL}/api/qa/evaluate`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "x-api-key": process.env.ADMIN_API_KEY || "" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(90000),
    });
    if (!res.ok) return { error: `http_${res.status}` };
    return await res.json();
  } catch (e) {
    return { error: e.message };
  }
}

async function run() {
  const rehearsal = [];
  const errors = [];
  let fail = 0;

  // 并发池
  const queue = [...rows];
  const workers = Array.from({ length: CONCURRENCY }, async () => {
    while (queue.length) {
      const item = queue.shift();
      const gold = item.obj.label;
      const res = await evaluate(item.obj.conversation, item.obj.tool_context);
      if (res.error || !res.risk_level) {
        fail += 1;
        errors.push({ ...item.obj, stock_risk: null, mismatch: "eval_failed", error: res.error });
        continue;
      }
      const stockRisk = res.risk_level;
      if (stockRisk === gold.risk_level) {
        rehearsal.push({
          ...item.obj,
          source: "rehearsal",
          stock_confirmed_risk: stockRisk,
        });
      } else {
        errors.push({
          ...item.obj,
          stock_risk: stockRisk,
          gold_risk: gold.risk_level,
          mismatch: gold.risk_level === "low" || gold.risk_level === "medium" ? "false_positive" : "false_negative",
        });
      }
    }
  });
  await Promise.all(workers);

  mkdirSync(path.join(ROOT, "training/data"), { recursive: true });
  const w = (f, arr) => writeFileSync(path.join(ROOT, f), arr.map((r) => JSON.stringify(r)).join("\n") + "\n");
  w("training/data/rehearsal.jsonl", rehearsal);
  w("training/data/stock-errors.jsonl", errors);

  console.log(`输入 ${rows.length} 条（含失败 ${fail}）`);
  console.log(`rehearsal（stock 判定一致）: ${rehearsal.length}`);
  console.log(`stock_errors（不一致）: ${errors.length}`);
  const fp = errors.filter((e) => e.mismatch === "false_positive");
  const fn = errors.filter((e) => e.mismatch === "false_negative");
  console.log(`  其中误报(应 low/medium 判高): ${fp.length} · 漏报(应 high/critical 判低): ${fn.length}`);
  console.log(`输出: training/data/rehearsal.jsonl + stock-errors.jsonl`);
}

run();
