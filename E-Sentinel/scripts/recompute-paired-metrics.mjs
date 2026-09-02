#!/usr/bin/env node
/**
 * 用修复后的 isSevere（仅 risk_level ∈ {high,critical}）重算已有 paired 结果的 metrics。
 * predictions 已存 risk_level，无需重跑评测。
 *
 * 用法：node scripts/recompute-paired-metrics.mjs <paired-*.json> [--model-label <label>]
 * 输出：新文件 paired-recomputed-<ts>.json（原文件保留）
 */
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  isSevere,
  binarySeverityMetrics,
  macroF1ByRiskClass,
  macroF1ByViolationCategory,
  cohensKappa,
  riskAccuracy,
  summaryStats,
} from "./lib/metrics.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const CATEGORIES = ["服务态度", "专业性", "响应效率", "解决问题", "合规与隐私"];

function computeMetrics(goldCases, predCases) {
  const validIdx = predCases.map((p, i) => ({ p, i })).filter((x) => !x.p.error);
  const failedIdx = predCases.map((p, i) => ({ p, i })).filter((x) => x.p.error);
  const goldCasesV = validIdx.map((x) => goldCases[x.i]);
  const predCasesV = validIdx.map((x) => x.p);
  const goldSevere = goldCasesV.map((g) => g.severe);
  const predSevere = predCasesV.map((p) => isSevere({ riskLevel: p.riskLevel || p.risk_level || "low", violations: p.violations }));
  const goldRisks = goldCasesV.map((g) => g.riskLevel);
  const predRisks = predCasesV.map((p) => p.riskLevel);
  const goldCats = goldCasesV.map((g) => g.catSet);
  const predCats = predCasesV.map((p) => p.catSet);
  const latencies = predCasesV.map((p) => p.latencyMs).filter(Boolean);
  return {
    severe: binarySeverityMetrics(goldSevere, predSevere),
    macroF1Risk: macroF1ByRiskClass(goldRisks, predRisks),
    macroF1Category: macroF1ByViolationCategory(goldCats, predCats, CATEGORIES),
    cohensKappa: cohensKappa(goldRisks, predRisks),
    riskAccuracy: riskAccuracy(goldRisks, predRisks),
    latency: summaryStats(latencies),
    failedCount: failedIdx.length,
    failedCaseIds: failedIdx.map((x) => goldCases[x.i].id),
    evaluatedCount: goldCasesV.length,
  };
}

function main() {
  const args = process.argv.slice(2);
  const src = args.find((a) => a.startsWith("evals/") || a.includes("paired-"));
  const modelLabel = args.indexOf("--model-label") >= 0 ? args[args.indexOf("--model-label") + 1] : "";

  if (!src) {
    console.error("用法: node scripts/recompute-paired-metrics.mjs <paired-*.json> [--model-label <label>]");
    process.exit(1);
  }

  const paired = JSON.parse(readFileSync(path.join(ROOT, src), "utf8"));
  const goldSet = JSON.parse(readFileSync(path.join(ROOT, "evals/configs/gold-set-human-v1.json"), "utf8"));
  const goldCases = goldSet.cases.map((c) => {
    const g = c.gold || {};
    const violations = Array.isArray(g.violations) ? g.violations : [];
    return {
      id: c.id,
      riskLevel: g.risk_level || "low",
      severe: Boolean(g.severe),
      catSet: new Set(violations.map((v) => v.category).filter(Boolean)),
    };
  });
  const goldById = new Map(goldCases.map((g) => [g.id, g]));

  paired.variants.forEach((v) => {
    const predCases = v.predictions.map((p) => {
      const gold = goldById.get(p.case_id) || { riskLevel: "low", severe: false, catSet: new Set() };
      const pred = p.pred;
      return {
        riskLevel: pred.riskLevel || pred.risk_level || "low",
        severe: pred.error ? false : isSevere({ riskLevel: pred.riskLevel || pred.risk_level || "low", violations: pred.violations }),
        catSet: new Set((pred.violations || []).map((x) => x.category).filter(Boolean)),
        latencyMs: pred.latencyMs || 0,
        error: pred.error,
      };
    });
    v.metrics = computeMetrics(goldCases, predCases);
    if (modelLabel) paired.model = modelLabel;
  });

  const ts = Date.now();
  const outDir = path.join(ROOT, "evals", "results");
  mkdirSync(outDir, { recursive: true });
  const outPath = path.join(outDir, `paired-recomputed-${ts}.json`);
  writeFileSync(outPath, JSON.stringify(paired, null, 2));
  console.log(`写入: ${outPath}`);
  console.log(`model: ${paired.model || "unknown"} | human_gold: ${paired.human_gold}`);
  for (const v of paired.variants) {
    const s = v.metrics.severe;
    console.log(
      `  ${v.variant}: recall=${s.recall.toFixed(3)} precision=${s.precision.toFixed(3)} f1=${s.f1.toFixed(3)} fpr=${s.fpr.toFixed(3)} κ=${v.metrics.cohensKappa.toFixed(3)} | 失败=${v.metrics.failedCount}`
    );
  }
}

main();
