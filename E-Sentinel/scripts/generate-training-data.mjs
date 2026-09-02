#!/usr/bin/env node
/**
 * 训练/开发候选数据生成器（程序化、确定性、零 LLM 依赖）。
 *
 * 从 training/config/templates.json 的场景矩阵生成候选会话 JSONL。
 * 会话由「客户诉求行 × 客服行为档（low/medium/high/critical）」交织而成，
 * label 严格按 annotation-guideline（§7 合并规则、§8 防误报）构造，
 * source_quote 取客服行为原句（保证是 conversation 的连续子串）。
 *
 * 本生成器不读取、不引用 gold-set；只产出候选，真正的隔离/切分由
 * scripts/contamination-check.mjs 完成。
 *
 * 用法：node scripts/generate-training-data.mjs [--config training/config/templates.json] [--out training/data/candidates.jsonl]
 */

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
function arg(name, def) {
  const i = process.argv.indexOf(name);
  return i >= 0 ? process.argv[i + 1] ?? def : def;
}
const CONFIG = arg("--config", "training/config/templates.json");
const OUT = arg("--out", "training/data/candidates.jsonl");

const config = JSON.parse(readFileSync(path.join(ROOT, CONFIG), "utf8"));
const templates = config.templates;

const SEVERE = { high: true, critical: true, medium: false, low: false };

function buildViolation(tpl, behavior, category, rule, severity, quote) {
  return { category, rule, severity, source_quote: quote };
}

const rows = [];
let counter = 0;
for (const tpl of templates) {
  const customerLines = tpl.customer.lines;
  for (const [behaviorKey, behavior] of Object.entries(tpl.behaviors)) {
    const labelBase = tpl.labels[behaviorKey];
    const violationsSpec = tpl.violations[behaviorKey] || [];
    const behaviorLines = behavior.lines;
    for (const cLine of customerLines) {
      for (const bLine of behaviorLines) {
        counter += 1;
        // 多轮交织：客户 → 客服（若行为有多句则继续交替）
        const conversation = [cLine, bLine];
        if (behavior.extra_customer && behavior.extra_customer[0]) {
          conversation.push(behavior.extra_customer[0]);
          if (behavior.extra_lines && behavior.extra_lines[0]) conversation.push(behavior.extra_lines[0]);
        }
        const violations = violationsSpec.map((v) =>
          buildViolation(tpl, behavior, v.category, v.rule, v.severity, bLine)
        );
        const needsHuman = labelBase.needs_human_review === true;
        const isAbstain = behaviorKey === "abstain";
        rows.push({
          id: `${tpl.seed}-${String(counter).padStart(4, "0")}`,
          source: "programmatic",
          template_seed: tpl.seed,
          platform: tpl.platform || "tmall",
          conversation: conversation.join("\n"),
          label: {
            risk_level: isAbstain ? "low" : labelBase.risk_level,
            severe: isAbstain ? false : SEVERE[labelBase.risk_level],
            violations: isAbstain ? [] : violations,
            needs_human_review: needsHuman || isAbstain,
            requires_tool: tpl.requires_tool === true || violationsSpec.some((v) => v.requires_tool),
            abstain: isAbstain,
          },
          policy_context: tpl.policy_context || "",
        });
      }
    }
  }
}

mkdirSync(path.dirname(path.join(ROOT, OUT)), { recursive: true });
writeFileSync(path.join(ROOT, OUT), rows.map((r) => JSON.stringify(r)).join("\n") + "\n");
console.log(`生成候选 ${rows.length} 条 → ${OUT}`);
console.log(`模板数 ${templates.length}；风险分布：` + Object.entries(
  rows.reduce((a, r) => { a[r.label.risk_level] = (a[r.label.risk_level] || 0) + 1; return a; }, {})
).map(([k, v]) => `${k}:${v}`).join(" "));
