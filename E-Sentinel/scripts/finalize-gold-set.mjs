#!/usr/bin/env node
/**
 * 双人标注结果定稿为 human-gold v1（Sprint 1）。
 *
 * 用法：
 *   node scripts/finalize-gold-set.mjs \
 *     --draft evals/configs/gold-set-human-draft-v1.json \
 *     --annotations evals/annotations/v1 \
 *     --arbitration evals/annotations/v1/arbitration.json \
 *     --out evals/configs/gold-set-human-v1.json \
 *     --annotators ann-a,ann-b
 *
 * 步骤：收集两标注者记录 → 计算 Kappa → 冲突必须仲裁 → 写入校验和与
 * agreement 元数据 → 调用 evals/validate-dataset.mjs 的契约校验。
 */

import { readFileSync, writeFileSync, readdirSync, existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  computeCasesChecksum,
  computeAnnotationsChecksum,
  computeIndependentAgreement,
  validateDataset,
} from "../evals/validate-dataset.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");

function parseArgs() {
  const args = process.argv.slice(2);
  const get = (flag, def) => {
    const i = args.indexOf(flag);
    return i >= 0 ? args[i + 1] : def;
  };
  return {
    draft: get("--draft", "evals/configs/gold-set-human-draft-v1.json"),
    annotations: get("--annotations", "evals/annotations/v1"),
    arbitration: get("--arbitration", ""),
    out: get("--out", "evals/configs/gold-set-human-v1.json"),
    annotators: (get("--annotators", "ann-a,ann-b") || "").split(",").filter(Boolean),
  };
}

function loadJson(p) {
  return JSON.parse(readFileSync(p, "utf8"));
}

function main() {
  const opts = parseArgs();
  const draftPath = path.isAbsolute(opts.draft) ? opts.draft : path.join(ROOT, opts.draft);
  const annDir = path.isAbsolute(opts.annotations) ? opts.annotations : path.join(ROOT, opts.annotations);
  const outPath = path.isAbsolute(opts.out) ? opts.out : path.join(ROOT, opts.out);
  const doc = loadJson(draftPath);

  const rows = [];
  // 每批上限固定为契约值 20（validateDataset 校验批次 ≤ max_cases_per_batch）。
  // ⚠️ 不能取各批 case_count 的最小值：末批不足 20 例不应缩小全量上限。
  const maxCasesPerBatch = 20;
  for (const file of readdirSync(annDir).filter((f) => f.endsWith(".json") && !f.endsWith("arbitration.json"))) {
    const pack = loadJson(path.join(annDir, file));
    for (const r of pack.records || []) {
      if (r.label === null || r.label === undefined || r.label === "") continue;
      rows.push({
        case_id: r.case_id,
        annotator_id: r.annotator_id,
        batch_id: r.batch_id,
        label: String(r.label),
        label_detail: r.label_detail || null,
      });
    }
  }

  const arbitrationMap = new Map();
  if (opts.arbitration && existsSync(opts.arbitration)) {
    for (const row of loadJson(opts.arbitration)) arbitrationMap.set(row.case_id, row);
  }

  // 逐 case 聚合两标注者
  const byCase = new Map();
  for (const r of rows) {
    if (!byCase.has(r.case_id)) byCase.set(r.case_id, []);
    byCase.get(r.case_id).push(r);
  }

  const disagreements = [];
  const finalAnnotations = [];
  const cases = doc.cases.map((c) => ({ ...c }));
  for (const c of cases) {
    const recs = byCase.get(c.id) || [];
    const a = recs.find((r) => r.annotator_id === opts.annotators[0]);
    const b = recs.find((r) => r.annotator_id === opts.annotators[1]);
    if (!a || !b) {
      console.error(`缺少独立标注: ${c.id}（需 ${opts.annotators.join(" + ")} 双方记录）`);
      process.exit(2);
    }
    finalAnnotations.push(
      { case_id: c.id, annotator_id: a.annotator_id, batch_id: a.batch_id, label: a.label },
      { case_id: c.id, annotator_id: b.annotator_id, batch_id: b.batch_id, label: b.label }
    );
    if (a.label !== b.label) {
      const arb = arbitrationMap.get(c.id);
      if (!arb?.final_risk_level) {
        disagreements.push(`${c.id}: ${a.annotator_id}=${a.label} vs ${b.annotator_id}=${b.label}`);
        continue;
      }
      c.gold = {
        risk_level: arb.final_risk_level,
        severe: arb.final_risk_level === "high" || arb.final_risk_level === "critical",
        needs_human_review: arb.final_risk_level === "high" || arb.final_risk_level === "critical",
        total_score: arb.final_total_score ?? 0,
        violations: arb.final_violations || [],
      };
      continue;
    }
    const chosen = a.label_detail && b.label_detail ? a.label_detail : (a.label_detail || b.label_detail || {});
    c.gold = {
      risk_level: a.label,
      severe: a.label === "high" || a.label === "critical",
      needs_human_review: a.label === "high" || a.label === "critical",
      total_score: chosen.total_score ?? 0,
      violations: chosen.violations || [],
    };
  }

  if (disagreements.length > 0) {
    console.error("存在未仲裁的标注分歧，无法定稿：");
    for (const d of disagreements) console.error(" -", d);
    console.error("请先补全 arbitration.json 再重试。");
    process.exit(2);
  }

  const annotationRows = finalAnnotations.map((r) => ({
    case_id: r.case_id,
    annotator_id: r.annotator_id,
    batch_id: r.batch_id,
    label: r.label,
  }));
  const agreement = computeIndependentAgreement(cases, annotationRows, opts.annotators);
  if (agreement.error) {
    console.error("Kappa 计算失败:", agreement.error);
    process.exit(2);
  }

  const finalDoc = {
    dataset_version: "gold-set-human-v1.0",
    dataset_type: "gold",
    source_type: "human-annotated",
    provenance: {
      label_status: "human-gold",
      annotators: opts.annotators,
      independent_annotation: true,
      arbitration_completed: true,
      disagreements_recorded: true,
      frozen: true,
      few_shot_excluded: true,
      max_cases_per_batch: maxCasesPerBatch,
      cases_checksum_sha256: computeCasesChecksum(cases),
      annotations_checksum_sha256: computeAnnotationsChecksum(annotationRows),
      severity_scheme: "service-quality-v1",
      agreement: {
        metric: "cohen_kappa",
        score: agreement.score,
        observed_agreement: agreement.observedAgreement,
        sample_size: agreement.sampleSize,
        wilson_ci: agreement.wilsonCi,
      },
    },
    case_count: cases.length,
    cases,
    annotations: annotationRows,
  };

  writeFileSync(outPath, JSON.stringify(finalDoc, null, 2) + "\n");
  const result = validateDataset(finalDoc);
  if (!result.valid) {
    console.error("生成的 human-gold 未通过校验：");
    for (const e of result.errors) console.error(" -", e);
    process.exit(1);
  }
  console.log(`定稿完成并通过校验: ${outPath} (${cases.length} 例, kappa=${agreement.score.toFixed(3)}, observed=${agreement.observedAgreement.toFixed(3)})`);
}

main();
