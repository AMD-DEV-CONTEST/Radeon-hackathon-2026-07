#!/usr/bin/env node
/**
 * 生成双人独立标注包（Sprint 1 multi-annotator）。
 *
 * 用法：
 *   node evals/build-annotation-pack.mjs \
 *     --dataset evals/configs/gold-set-human-draft-v1.json \
 *     --out evals/annotations/v1 \
 *     --annotators ann-a,ann-b \
 *     --per-batch 20
 *
 * 输出：每个标注者每批一个 JSON（label=null 待填），外加 README。
 */

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
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
    dataset: get("--dataset", "evals/configs/gold-set-human-draft-v1.json"),
    out: get("--out", "evals/annotations/v1"),
    annotators: (get("--annotators", "ann-a,ann-b") || "").split(",").filter(Boolean),
    perBatch: Number(get("--per-batch", "20")),
  };
}

function main() {
  const opts = parseArgs();
  const dsPath = path.isAbsolute(opts.dataset) ? opts.dataset : path.join(ROOT, opts.dataset);
  const doc = JSON.parse(readFileSync(dsPath, "utf8"));
  const cases = doc.cases;
  if (opts.perBatch < 1 || opts.perBatch > 20) {
    console.error("per-batch 必须在 1-20 之间（human-gold 校验要求）");
    process.exit(2);
  }

  const outDir = path.isAbsolute(opts.out) ? opts.out : path.join(ROOT, opts.out);
  mkdirSync(outDir, { recursive: true });

  const batches = [];
  for (let i = 0; i < cases.length; i += opts.perBatch) {
    batches.push(cases.slice(i, i + opts.perBatch));
  }

  for (const annotator of opts.annotators) {
    batches.forEach((batch, bi) => {
      const batchId = `${annotator}-batch-${String(bi + 1).padStart(2, "0")}`;
      const records = batch.map((c) => ({
        case_id: c.id,
        annotator_id: annotator,
        batch_id: batchId,
        conversation: c.conversation,
        draft_risk_level: c.gold?.risk_level || "low",
        draft_violations: c.gold?.violations || [],
        label: null,
        label_detail: null,
      }));
      const file = path.join(outDir, `${batchId}.json`);
      writeFileSync(
        file,
        JSON.stringify(
          {
            meta: {
              annotator_id: annotator,
              batch_id: batchId,
              case_count: batch.length,
              instructions: "独立标注：label 填 risk_level(low|medium|high|critical)；label_detail 填 {total_score, severe, needs_human_review, violations:[{category,rule,severity,source_quote,deduction}]}。可参考 draft 标签，但必须独立判断，不一致将由仲裁解决。",
            },
            records,
          },
          null,
          2
        ) + "\n"
      );
      console.log(`生成 ${file}`);
    });
  }

  writeFileSync(
    path.join(outDir, "README.md"),
    `# 标注包 v1\n\n- 数据集: ${dsPath}\n- 案例数: ${cases.length}\n- 每批上限: ${opts.perBatch}（human-gold 校验上限 20）\n- 标注者: ${opts.annotators.join(", ")}\n\n流程：\n1. 每位标注者独立完成所有批次（不要互相商量）。\n2. label 填风险等级；label_detail 填完整违规结构与证据引用。\n3. 不一致 case 由第三人或双人协商仲裁，写入 arbitration.json：\n   {"case_id":"case-021","final_risk_level":"high","final_violations":[...],"note":"协商结论"}\n4. 全部完成后运行:\n   node scripts/finalize-gold-set.mjs --annotations ${outDir} --arbitration ${path.join(outDir, "arbitration.json")}\n`
  );
  console.log("标注包生成完成。");
}

main();
