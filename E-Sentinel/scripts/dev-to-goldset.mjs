#!/usr/bin/env node
/**
 * 把 B′ dev 集（training/data/dev.jsonl，原始候选格式）转为 gold-set 评测格式，
 * 供 evaluate-goldset.mjs 在独立 dev 上做选型评测（Recall/FPR/F1/κ）。
 *
 * 用法：
 *   node scripts/dev-to-goldset.mjs \
 *     [--in training/data/dev.jsonl] [--out evals/configs/dev-goldset.json]
 *
 * 之后：
 *   node scripts/evaluate-goldset.mjs --goldsets evals/configs/dev-goldset.json \
 *     --variants rule_only,dual,agent --base-url http://localhost:3003
 *
 * 注意：dev 与 gold 隔离——dev 用于模型选型，gold 只做最终确认。
 */

import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
function arg(name, def) {
  const i = process.argv.indexOf(name);
  return i >= 0 ? process.argv[i + 1] ?? def : def;
}
const IN = arg("--in", "training/data/dev.jsonl");
const OUT = arg("--out", "evals/configs/dev-goldset.json");

const rows = readFileSync(path.join(ROOT, IN), "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l));

const SEVERE = { high: true, critical: true, medium: false, low: false };
const cases = rows.map((r, i) => ({
  id: r.id || `dev-${String(i + 1).padStart(4, "0")}`,
  set: r.label.risk_level === "high" || r.label.risk_level === "critical" ? "severe" : "non-severe",
  expected_category: r.label.violations?.[0]?.category || "none",
  expected_block: r.label.risk_level === "critical",
  criticality: r.label.risk_level === "critical" ? "p1" : r.label.risk_level === "high" ? "p1" : "p2",
  conversation: r.conversation,
  gold: {
    risk_level: r.label.risk_level,
    severe: SEVERE[r.label.risk_level],
    needs_human_review: r.label.needs_human_review === true,
    violations: r.label.violations || [],
  },
}));

const out = {
  dataset_version: "dev-b1-v1",
  dataset_type: "dev",
  source_type: "synthetic+rehearsal",
  case_count: cases.length,
  cases,
};
writeFileSync(path.join(ROOT, OUT), JSON.stringify(out, null, 2) + "\n");
console.log(`dev 转 goldset: ${cases.length} 例 → ${OUT}`);
console.log(`severe 分布: ` + Object.entries(cases.reduce((a, c) => { a[c.gold.severe ? "severe" : "non-severe"] = (a[c.gold.severe ? "severe" : "non-severe"] || 0) + 1; return a; }, {})).map(([k, v]) => `${k}:${v}`).join(" "));
