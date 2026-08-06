#!/usr/bin/env node
/**
 * 消融基线对比 + 退化门禁（Sprint 2）。
 *
 * 用法：
 *   node scripts/compare-ablation.mjs \
 *     --baseline evals/results/ablation-xxx.json \
 *     --current  evals/results/ablation-yyy.json \
 *     --variant agent,rule_only \
 *     --f1-threshold 0.05 \
 *     --kappa-threshold 0.05 \
 *     --write evals/results/comparison-xxx-vs-yyy.md
 *
 * 门禁规则（与计划一致）：任意被对比变体的 Severe F1 或 Cohen's κ
 * 相对基线下降超过阈值时退出码为 1（CI 标记 failed）。
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
    baseline: get("--baseline", ""),
    current: get("--current", ""),
    variants: (get("--variant", "") || "").split(",").filter(Boolean),
    f1Threshold: Number(get("--f1-threshold", "0.05")),
    kappaThreshold: Number(get("--kappa-threshold", "0.05")),
    goldset: get("--goldset", "evals/configs/gold-set-severe-draft-v1.json"),
    write: get("--write", ""),
  };
}

function load(file) {
  const p = path.isAbsolute(file) ? file : path.join(ROOT, file);
  return JSON.parse(readFileSync(p, "utf8"));
}

function variantMap(doc) {
  const m = new Map();
  for (const v of doc.variants || []) m.set(v.variant, v);
  return m;
}

function caseMap(variant) {
  const m = new Map();
  for (const p of variant?.predictions || []) m.set(p.case_id, p.pred);
  return m;
}

function fmt(n, digits = 3) {
  return Number(n).toFixed(digits);
}

function main() {
  const opts = parseArgs();
  if (!opts.baseline || !opts.current) {
    console.error("用法: node scripts/compare-ablation.mjs --baseline <json> --current <json> [--variant a,b]");
    process.exit(2);
  }

  const base = load(opts.baseline);
  const curr = load(opts.current);
  const gold = load(opts.goldset);
  const goldSevere = new Map((gold.cases || []).map((c) => [c.id, Boolean(c.gold?.severe)]));
  const baseVariants = variantMap(base);
  const currVariants = variantMap(curr);
  const selected = opts.variants.length
    ? opts.variants
    : [...new Set([...baseVariants.keys(), ...currVariants.keys()])];

  const lines = [];
  lines.push("# 消融基线对比\n");
  lines.push(`- 基线: ${opts.baseline} (${base.generated_at || "?"})`);
  lines.push(`- 当前: ${opts.current} (${curr.generated_at || "?"})`);
  lines.push(`- Gold Set: ${curr.goldset || base.goldset || "?"}`);
  lines.push(`- 门禁阈值: Severe F1 Δ > ${opts.f1Threshold} 或 Kappa Δ > ${opts.kappaThreshold} → failed`);
  lines.push("");
  lines.push("## 指标对比\n");
  lines.push("| 变体 | 指标 | 基线 | 当前 | Δ |");
  lines.push("|---|---|---|---|---|");

  const failures = [];
  for (const variant of selected) {
    const b = baseVariants.get(variant);
    const c = currVariants.get(variant);
    if (!b || !c) {
      console.warn(`skip ${variant}: 基线或当前结果缺失`);
      continue;
    }
    const metrics = [
      ["Severe Recall", b.metrics.severe.recall, c.metrics.severe.recall],
      ["Severe Precision", b.metrics.severe.precision, c.metrics.severe.precision],
      ["Severe F1", b.metrics.severe.f1, c.metrics.severe.f1],
      ["FPR", b.metrics.severe.fpr, c.metrics.severe.fpr],
      ["Macro-F1(risk)", b.metrics.macroF1Risk, c.metrics.macroF1Risk],
      ["Cohen's κ", b.metrics.cohensKappa, c.metrics.cohensKappa],
      ["RiskAccuracy", b.metrics.riskAccuracy, c.metrics.riskAccuracy],
    ];
    for (const [name, bv, cv] of metrics) {
      const delta = cv - bv;
      const arrow = delta > 0.0005 ? "↑" : delta < -0.0005 ? "↓" : "—";
      lines.push(`| ${variant} | ${name} | ${fmt(bv)} | ${fmt(cv)} | ${arrow} ${delta >= 0 ? "+" : ""}${fmt(delta)} |`);
    }

    const f1Drop = b.metrics.severe.f1 - c.metrics.severe.f1;
    const kappaDrop = b.metrics.cohensKappa - c.metrics.cohensKappa;
    if (f1Drop > opts.f1Threshold) failures.push(`${variant}: Severe F1 下降 ${fmt(f1Drop)} > ${opts.f1Threshold}`);
    if (kappaDrop > opts.kappaThreshold) failures.push(`${variant}: Kappa 下降 ${fmt(kappaDrop)} > ${opts.kappaThreshold}`);
  }

  lines.push("\n## 逐案例严重度变化\n");
  lines.push("| 变体 | case | 变化 | 基线预测 | 当前预测 | 证据摘要 |");
  lines.push("|---|---|---|---|---|---|");
  for (const variant of selected) {
    const b = baseVariants.get(variant);
    const c = currVariants.get(variant);
    if (!b || !c) continue;
    const bCases = caseMap(b);
    const cCases = caseMap(c);
    const ids = [...new Set([...bCases.keys(), ...cCases.keys()])].sort();
    for (const id of ids) {
      const bp = bCases.get(id);
      const cp = cCases.get(id);
      if (!bp || !cp) continue;
      const change = `${bp.severe ? "1" : "0"}→${cp.severe ? "1" : "0"}`;
      if (change === "1→0" || change === "0→1") {
        const gs = goldSevere.get(id);
        const label =
          change === "1→0"
            ? (gs ? "TP→FN" : "FP→TN")
            : (gs ? "FN→TP" : "TN→FP");
        const evidence = cp.escalationEvidence?.length
          ? cp.escalationEvidence.join(" / ").slice(0, 80)
          : (cp.hardRedlineMatches?.length ? "hardline" : cp.riskLevel);
        lines.push(`| ${variant} | ${id} | ${label} | ${bp.riskLevel} | ${cp.riskLevel} | ${String(evidence).slice(0, 90)} |`);
      }
    }
  }

  lines.push("\n## 门禁结论\n");
  if (failures.length === 0) {
    lines.push("PASS — 未发现超过阈值的退化。");
  } else {
    lines.push("FAIL — 以下变体触发退化门禁：");
    for (const f of failures) lines.push(`- ${f}`);
  }

  const report = lines.join("\n") + "\n";
  if (opts.write) {
    const p = path.isAbsolute(opts.write) ? opts.write : path.join(ROOT, opts.write);
    mkdirSync(path.dirname(p), { recursive: true });
    writeFileSync(p, report);
    console.log(`对比报告: ${p}`);
  }
  console.log(report);
  if (failures.length > 0) {
    console.error("退化门禁未通过");
    process.exit(1);
  }
}

main();
