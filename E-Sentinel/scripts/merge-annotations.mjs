#!/usr/bin/env node
/**
 * 把双通道盲标结果合并进批次文件（A1/A3 通用）。
 *
 * 用法：
 *   node scripts/merge-annotations.mjs \
 *     --results-dir /tmp/qa-ann \
 *     --annotations evals/annotations/v1 \
 *     --report /tmp/qa-ann/disagreement.json
 *
 * 流程：
 *   1. 读 results-dir 下 result-<batch>.json（records: case_id/label/label_detail）；
 *   2. 合并进对应批次文件（label/label_detail）；
 *   3. 校验：label 四值、source_quote 必须逐字存在于对话、total_score=扣分和；
 *   4. 写回批次文件；
 *   5. 输出分歧清单 + 人工逐例确认清单（A4 用）。
 */
import { readFileSync, writeFileSync, readdirSync, existsSync } from "node:fs";
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
    resultsDir: get("--results-dir", "/tmp/qa-ann"),
    annotations: get("--annotations", "evals/annotations/v1"),
    report: get("--report", "/tmp/qa-ann/disagreement.json"),
  };
}

const LABELS = new Set(["low", "medium", "high", "critical"]);
const SEVERITIES = new Set(["minor", "major", "critical"]);

function loadJson(p) {
  return JSON.parse(readFileSync(p, "utf8"));
}

function main() {
  const opts = parseArgs();
  const resultsDir = path.isAbsolute(opts.resultsDir) ? opts.resultsDir : path.join(ROOT, opts.resultsDir);
  const annDir = path.isAbsolute(opts.annotations) ? opts.annotations : path.join(ROOT, opts.annotations);

  const errors = [];
  const resultFiles = readdirSync(resultsDir).filter((f) => /^result-.*\.json$/.test(f));
  if (resultFiles.length === 0) {
    console.error(`结果目录无 result-*.json：${resultsDir}`);
    process.exit(2);
  }

  // 1. 读结果，按 batch 组织
  const byBatch = new Map(); // batch_id -> Map(case_id -> {label,label_detail})
  const resultsMeta = [];
  for (const f of resultFiles.sort()) {
    const data = loadJson(path.join(resultsDir, f));
    const batchId = f.replace(/^result-/, "").replace(/\.json$/, "");
    const records = Array.isArray(data.records) ? data.records : [];
    const map = new Map(records.map((r) => [r.case_id, r]));
    byBatch.set(batchId, map);
    resultsMeta.push(`${f}: ${records.length} cases`);
    if (records.length === 0) errors.push(`结果文件为空: ${f}`);
  }
  console.log("读取结果:", resultsMeta.join(" | "));

  // 2. 合并进批次文件
  const batchFiles = readdirSync(annDir).filter((f) => f.endsWith(".json") && !f.endsWith("arbitration.json"));
  const allCases = new Map(); // case_id -> conversation（用于 source_quote 校验）
  for (const bf of batchFiles) {
    const packPath = path.join(annDir, bf);
    const pack = loadJson(packPath);
    const batchId = pack.meta?.batch_id || bf.replace(/\.json$/, "");
    const resultMap = byBatch.get(batchId);
    if (!resultMap) {
      errors.push(`批次 ${batchId} 无对应结果文件`);
      continue;
    }
    let filled = 0;
    for (const r of pack.records || []) {
      allCases.set(r.case_id, r.conversation);
      const res = resultMap.get(r.case_id);
      if (!res) {
        errors.push(`批次 ${batchId} 缺少标注: ${r.case_id}`);
        continue;
      }
      r.label = res.label;
      r.label_detail = res.label_detail;
      filled++;
    }
    writeFileSync(packPath, JSON.stringify(pack, null, 2) + "\n");
    console.log(`已合并 ${filled}/${(pack.records || []).length} -> ${bf}`);
  }

  // 3. 校验
  for (const [caseId, conv] of allCases) {
    const lines = new Set(conv.split("\n"));
    for (const bf of batchFiles) {
      const pack = loadJson(path.join(annDir, bf));
      const rec = (pack.records || []).find((r) => r.case_id === caseId);
      if (!rec || rec.label === null || rec.label === undefined) continue;
      if (!LABELS.has(rec.label)) errors.push(`非法 label ${rec.label}: ${caseId}`);
      const detail = rec.label_detail || {};
      const vios = Array.isArray(detail.violations) ? detail.violations : [];
      let sum = 0;
      for (const v of vios) {
        if (!SEVERITIES.has(v.severity)) errors.push(`非法 severity ${v.severity}: ${caseId}`);
        if (typeof v.deduction !== "number") errors.push(`缺 deduction: ${caseId}`);
        else sum += v.deduction;
        // source_quote 逐字校验：在对话原始串中（跨行子串）
        if (!conv.includes(v.source_quote || "")) {
          errors.push(`source_quote 不在原对话: ${caseId} :: "${v.source_quote}"`);
        }
      }
      if (vios.length > 0 && detail.total_score !== undefined && Math.abs(detail.total_score - sum) > 0.5) {
        errors.push(`total_score(${detail.total_score})≠扣分和(${sum}): ${caseId}`);
      }
    }
  }

  // 4. 分歧清单 + 确认清单（A4）
  const byCase = new Map();
  for (const bf of batchFiles) {
    const pack = loadJson(path.join(annDir, bf));
    for (const r of pack.records || []) {
      if (r.label === null || r.label === undefined) continue;
      if (!byCase.has(r.case_id)) byCase.set(r.case_id, {});
      byCase.get(r.case_id)[r.annotator_id] = r.label;
    }
  }
  const disagreements = [];
  const confirmation = [];
  for (const [caseId, labels] of [...byCase.entries()].sort()) {
    const conv = allCases.get(caseId) || "";
    const a = labels["ann-a"];
    const b = labels["ann-b"];
    const summary = conv.split("\n").find((l) => l.startsWith("客服：")) || conv.slice(0, 40);
    confirmation.push({
      case_id: caseId,
      ann_a: a,
      ann_b: b,
      disagree: a !== b,
      summary: summary.length > 50 ? summary.slice(0, 50) + "…" : summary,
    });
    if (a !== b) disagreements.push({ case_id: caseId, ann_a: a, ann_b: b });
  }

  const report = {
    generated_at: new Date().toISOString(),
    result_files: resultFiles.length,
    cases_total: byCase.size,
    agreement: byCase.size - disagreements.length,
    disagreement_count: disagreements.length,
    disagreement_rate: byCase.size ? (disagreements.length / byCase.size).toFixed(3) : "0",
    disagreements,
    confirmation_list: confirmation,
  };
  writeFileSync(opts.report, JSON.stringify(report, null, 2) + "\n");

  if (errors.length > 0) {
    console.error("校验失败:");
    for (const e of errors) console.error(" -", e);
    console.error(`报告已写: ${opts.report}（含 ${disagreements.length} 处分歧）`);
    process.exit(1);
  }
  console.log(`合并校验通过: ${byCase.size} 例, 分歧 ${disagreements.length} (${report.disagreement_rate})`);
  console.log(`分歧/确认清单已写: ${opts.report}`);
}

main();
