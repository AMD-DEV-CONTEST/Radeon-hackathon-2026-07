#!/usr/bin/env node
/**
 * B′ 数据生成器：工具上下文 + 反事实对 + 困难负例 + 基础会话分类。
 *
 * 来源：
 *   1. training/config/templates-b1.json（tool_contexts / counterfactual_pairs / hard_negatives）
 *   2. 原 16 场景程序化数据（training/data/candidates.jsonl，作为基础会话分类）
 *
 * 输出：training/data/candidates-b1.jsonl（供 contamination-check 去污染后切分 train/dev）。
 *
 * 用法：node scripts/generate-training-data-b1.mjs
 */

import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const OUT = "training/data/candidates-b1.jsonl";

const config = JSON.parse(readFileSync(path.join(ROOT, "training/config/templates-b1.json"), "utf8"));
const rows = [];
let n = 0;

// 1. 工具上下文样本
for (const t of config.tool_contexts) {
  n += 1;
  rows.push({
    id: `${t.seed}-${String(n).padStart(3, "0")}`,
    source: "tool_context",
    template_seed: t.seed,
    conversation: t.conversation,
    tool_context: t.tool_context,
    label: { ...t.label, violations: t.label.violations || [] },
    policy_context: t.tool_context,
  });
}

// 2. 反事实对（每组 pairs 逐条输出，同 seed 保证切分不拆散）
for (const p of config.counterfactual_pairs) {
  for (let i = 0; i < p.pairs.length; i++) {
    n += 1;
    const pair = p.pairs[i];
    rows.push({
      id: `${p.seed}-${String(n).padStart(3, "0")}`,
      source: "counterfactual",
      template_seed: p.seed,
      kind: p.kind,
      conversation: pair.conversation,
      label: { ...pair.label, violations: pair.label.violations || [] },
    });
  }
}

// 3. 困难负例
for (const h of config.hard_negatives) {
  n += 1;
  rows.push({
    id: `${h.seed}-${String(n).padStart(3, "0")}`,
    source: "hard_negative",
    template_seed: h.seed,
    category: h.category,
    conversation: h.conversation,
    label: { ...h.label, violations: h.label.violations || [] },
  });
}

// 4. 原 16 场景基础数据（复用，作为会话分类负/正例基础）
const base = "training/data/candidates.jsonl";
if (existsSync(path.join(ROOT, base))) {
  for (const l of readFileSync(path.join(ROOT, base), "utf8").split("\n").filter(Boolean)) {
    const o = JSON.parse(l);
    rows.push({ ...o, source: o.source || "programmatic" });
  }
}

mkdirSync(path.dirname(path.join(ROOT, OUT)), { recursive: true });
writeFileSync(path.join(ROOT, OUT), rows.map((r) => JSON.stringify(r)).join("\n") + "\n");
console.log(`B′ 候选 ${rows.length} 条 → ${OUT}`);
console.log(`构成：基础 ${504} + 工具上下文 ${config.tool_contexts.length} + 反事实对 ${config.counterfactual_pairs.length * 2} + 困难负例 ${config.hard_negatives.length}`);
