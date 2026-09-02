#!/usr/bin/env node
/**
 * 规则基线 vs Agent 互补分析（Sprint 4）。
 *
 * 用法：
 *   node scripts/complementary-analysis.mjs \
 *     --goldset   evals/configs/gold-set-severe-draft-v1.json \
 *     --rule-only evals/results/ablation-xxx.json \
 *     --agent     evals/results/ablation-yyy.json \
 *     --write     evals/results/complementary-analysis.md
 *
 * 回答两个问题：
 *   1. 规则能抓到、Agent 反而漏了的 case（Agent 覆盖盲区）；
 *   2. Agent 能抓到、规则完全没有覆盖的 case（Agent 增量价值）。
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
    goldset: get("--goldset", "evals/configs/gold-set-severe-draft-v1.json"),
    ruleOnly: get("--rule-only", ""),
    agent: get("--agent", ""),
    write: get("--write", ""),
  };
}

function load(file) {
  const p = path.isAbsolute(file) ? file : path.join(ROOT, file);
  return JSON.parse(readFileSync(p, "utf8"));
}

function predictionsFor(doc, variant) {
  const v = (doc.variants || []).find((x) => x.variant === variant);
  const m = new Map();
  for (const p of v?.predictions || []) m.set(p.case_id, p.pred);
  return m;
}

function catList(violations) {
  return [...new Set((violations || []).map((v) => v.category).filter(Boolean))].join("/") || "—";
}

function main() {
  const opts = parseArgs();
  if (!opts.ruleOnly || !opts.agent) {
    console.error("用法: node scripts/complementary-analysis.mjs --rule-only <json> --agent <json> [--goldset <json>]");
    process.exit(2);
  }

  const gold = load(opts.goldset);
  const goldMap = new Map(gold.cases.map((c) => [c.id, c.gold]));
  const rule = predictionsFor(load(opts.ruleOnly), "rule_only");
  const agent = predictionsFor(load(opts.agent), "agent");
  const ids = [...new Set([...goldMap.keys(), ...rule.keys(), ...agent.keys()])].sort();

  const rows = { bothTP: [], ruleOnlyTP: [], agentOnlyTP: [], ruleOnlyFP: [], agentOnlyFP: [], bothFP: [], bothFN: [], bothTN: [], total: ids.length };
  for (const id of ids) {
    const g = goldMap.get(id);
    const r = rule.get(id);
    const a = agent.get(id);
    if (!g || !r || !a) continue;
    const gs = g.severe;
    const rs = r.severe;
    const as = a.severe;
    let bucket;
    if (rs && as) bucket = gs ? "bothTP" : "bothFP";
    else if (rs && !as) bucket = gs ? "ruleOnlyTP" : "ruleOnlyFP";
    else if (!rs && as) bucket = gs ? "agentOnlyTP" : "agentOnlyFP";
    else bucket = gs ? "bothFN" : "bothTN";
    rows[bucket].push({
      id,
      bucket,
      gold: `${g.risk_level}/${gs}`,
      rule: `${r.riskLevel}/${rs}`,
      agent: `${a.riskLevel}/${as}`,
      goldCats: catList(g.violations),
      ruleCats: catList(r.violations),
      agentCats: catList(a.violations),
      note: g.note || "",
    });
  }

  const count = (b) => (rows[b] || []).length;
  const lines = [];
  lines.push("# 规则基线 vs Agent 互补分析\n");
  lines.push(`- Gold Set: ${opts.goldset}（${gold.case_count || ids.length} 例）`);
  lines.push(`- rule_only 结果: ${opts.ruleOnly}`);
  lines.push(`- agent 结果: ${opts.agent}`);
  lines.push("");
  lines.push("## 总览\n");
  lines.push("| 象限 | 数量 | 含义 |");
  lines.push("|---|---|---|");
  lines.push(`| 两者都抓到（TP） | ${count("bothTP")} | 规则与 Agent 都正确判为严重违规 |`);
  lines.push(`| 仅规则抓到（Agent 漏判） | ${count("ruleOnlyTP")} | gold 严重，规则命中但 Agent 漏判 → Agent 覆盖盲区 |`);
  lines.push(`| 仅 Agent 抓到（规则漏判） | ${count("agentOnlyTP")} | gold 严重，规则未覆盖但 Agent 抓到 → Agent 增量价值 |`);
  lines.push(`| 规则误报（Agent 正确） | ${count("ruleOnlyFP")} | gold 非严重，规则误判但 Agent 未误判 |`);
  lines.push(`| Agent 误报（规则正确） | ${count("agentOnlyFP")} | gold 非严重，Agent 误判但规则未误判 |`);
  lines.push(`| 两者都误报 | ${count("bothFP")} | gold 非严重，两者都误判 |`);
  lines.push(`| 两者都漏 | ${count("bothFN")} | gold 严重，两者都漏判 |`);
  lines.push(`| 两者都正确放过 | ${count("bothTN")} | gold 非严重，两者都未误判 |`);

  if (count("ruleOnlyTP") > 0) {
    lines.push("\n## 规则抓到、Agent 漏判的 case\n");
    lines.push("| case | gold | rule | agent | gold 违规类别 |");
    lines.push("|---|---|---|---|---|");
    for (const r of rows.ruleOnlyTP) lines.push(`| ${r.id} | ${r.gold} | ${r.rule} | ${r.agent} | ${r.goldCats} |`);
    lines.push("\n> 含义：Agent 在这些 case 上产生 FN，需要检查基线裁判/调查员为何降级或未升级。");
  }

  if (count("agentOnlyTP") > 0) {
    lines.push("\n## Agent 抓到、规则未覆盖的 case\n");
    lines.push("| case | gold | rule | agent | gold 违规类别 |");
    lines.push("|---|---|---|---|---|");
    for (const r of rows.agentOnlyTP) lines.push(`| ${r.id} | ${r.gold} | ${r.rule} | ${r.agent} | ${r.goldCats} |`);
    lines.push("\n> 含义：这些是语义违规（无关键词可命中），规则方案永远抓不到，Agent 提供了增量价值。");
  }

  if (count("bothFN") > 0) {
    lines.push("\n## 两者都漏的 case\n");
    lines.push("| case | gold | rule | agent | gold 违规类别 |");
    lines.push("|---|---|---|---|---|");
    for (const r of rows.bothFN) lines.push(`| ${r.id} | ${r.gold} | ${r.rule} | ${r.agent} | ${r.goldCats} |`);
  }

  if (count("ruleOnlyFP") > 0 || count("agentOnlyFP") > 0) {
    lines.push("\n## 误报对比\n");
    lines.push("| 类型 | case | gold | rule | agent |");
    lines.push("|---|---|---|---|---|");
    for (const r of [...rows.ruleOnlyFP, ...rows.agentOnlyFP, ...rows.bothFP]) {
      const label = r.bucket === "ruleOnlyFP" ? "rule_only 误报" : r.bucket === "agentOnlyFP" ? "agent 误报" : "两者误报";
      lines.push(`| ${label} | ${r.id} | ${r.gold} | ${r.rule} | ${r.agent} |`);
    }
  }

  lines.push("\n## 结论建议\n");
  const agentDelta = count("agentOnlyTP") - count("agentOnlyFP");
  const ruleDelta = count("ruleOnlyTP") - count("ruleOnlyFP");
  if (agentDelta >= ruleDelta) {
    lines.push("Agent 在语义违规上的增量 ≥ 其相对规则的新增盲区。建议：以 Agent 为增强层叠加在规则之上（规则兜底 + Agent 升级），而不是替换规则。");
  } else {
    lines.push("Agent 相对规则出现了更多新增盲区。建议：先修 Agent 盲区（FN 分析），再评估是否用 Agent 增强规则。");
  }
  lines.push("注意：当前为 expert-draft 小样本（20 例）对比，结论需在 human-gold 扩容后复核。");

  const report = lines.join("\n") + "\n";
  if (opts.write) {
    const p = path.isAbsolute(opts.write) ? opts.write : path.join(ROOT, opts.write);
    mkdirSync(path.dirname(p), { recursive: true });
    writeFileSync(p, report);
    console.log(`互补分析报告: ${p}`);
  }
  console.log(report);
}

main();
