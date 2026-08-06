#!/usr/bin/env node
/**
 * 合并基础 draft 集与扩容 draft 集为统一的待标注候选集。
 *
 * 用法：
 *   node scripts/merge-draft-sets.mjs \
 *     --base evals/configs/gold-set-severe-draft-v1.json \
 *     --expansion evals/configs/gold-set-expansion-draft-v1.json \
 *     --out evals/configs/gold-set-human-draft-v1.json
 */

import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");

function parseArgs() {
  const args = process.argv.slice(2);
  const get = (flag, def) => {
    const i = args.indexOf(flag);
    return i >= 0 ? args[i + 1] : def;
  };
  return {
    base: get("--base", "evals/configs/gold-set-severe-draft-v1.json"),
    expansion: get("--expansion", "evals/configs/gold-set-expansion-draft-v1.json"),
    out: get("--out", "evals/configs/gold-set-human-draft-v1.json"),
  };
}

function load(file) {
  const p = path.isAbsolute(file) ? file : path.join(ROOT, file);
  return JSON.parse(readFileSync(p, "utf8"));
}

function main() {
  const opts = parseArgs();
  const base = load(opts.base);
  const expansion = load(opts.expansion);
  const baseIds = new Set(base.cases.map((c) => c.id));
  const seen = new Set(baseIds);
  const cases = [...base.cases];
  const conflicts = [];
  for (const c of expansion.cases) {
    if (seen.has(c.id)) {
      conflicts.push(c.id);
      continue;
    }
    seen.add(c.id);
    cases.push(c);
  }
  if (conflicts.length > 0) {
    console.error("重复 case id，已跳过:", conflicts.join(", "));
  }

  const severe = cases.filter((c) => c.gold?.severe).length;
  const keywordTraps = cases.filter((c) => c.set === "keyword-trap").length;
  const doc = {
    dataset_version: "gold-human-draft-v1.0",
    dataset_type: "draft",
    source_type: "expert-annotated",
    provenance: {
      label_status: "expert-draft",
      description: `合并候选集（base=${base.dataset_version} + expansion=${expansion.dataset_version}），AI 起草，等待双人独立标注与仲裁后升 human-gold`,
      annotators: ["ann-a"],
      frozen: false,
      few_shot_excluded: true,
      severity_scheme: "service-quality-v1",
      ai_drafted_candidates: true,
      base_set: base.dataset_version,
      expansion_set: expansion.dataset_version,
      prevalence: { severe, non_severe: cases.length - severe },
      keyword_trap_count: keywordTraps,
    },
    case_count: cases.length,
    cases,
  };

  const outPath = path.isAbsolute(opts.out) ? opts.out : path.join(ROOT, opts.out);
  writeFileSync(outPath, JSON.stringify(doc, null, 2) + "\n");
  console.log(`合并完成: ${cases.length} 例 → ${outPath}`);
  if (conflicts.length > 0) console.warn("注意: 有重复 id 被跳过");
}

main();
