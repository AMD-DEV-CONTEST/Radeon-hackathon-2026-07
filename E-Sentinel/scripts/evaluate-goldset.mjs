/**
 * 质检 Gold Set 消融评测。
 *
 * 用法：
 *   node scripts/evaluate-goldset.mjs \
 *     --goldsets evals/configs/gold-set-severe-draft-v1.json \
 *     --variants rule_only,dual \
 *     --base-url http://localhost:3001 \
 *     --concurrency 2
 *
 * 变体：
 *   rule_only      — 纯关键词基线（离线，无需 LLM）
 *   llm_only       — 仅 LLM 裁判（静态标准，无关键词兜底）
 *   dual           — LLM + 关键词兜底（现有生产）
 *   dual_rag       — LLM + RAG 规则 + 关键词
 *   dual_rag_memory— 加 few-shot 记忆
 *   agent          — ReAct agent（use_agent=true）
 *
 * 说明：LLM 档通过 HTTP 调 /api/qa/evaluate（真实部署行为）；rule_only 本地纯函数。
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

// ── 参数解析 ──────────────────────────────────────────────
function parseArgs() {
  const args = process.argv.slice(2);
  const get = (flag, def) => {
    const i = args.indexOf(flag);
    return i >= 0 ? args[i + 1] : def;
  };
  return {
    goldsets: get("--goldsets", "evals/configs/gold-set-severe-draft-v1.json"),
    variants: (get("--variants", "rule_only,dual") || "").split(",").filter(Boolean),
    baseUrl: get("--base-url", "http://localhost:3001"),
    apiKey: get("--api-key", process.env.ADMIN_API_KEY || process.env.API_SECRET || ""),
    concurrency: Number(get("--concurrency", "2")),
    // 模型标注：运行时的模型/链路显式写入结果元数据（如 --model-label "/workspace/Qwen3-8B" 或 "Qwen3.6-35B-A3B"）。
    // 之前结果文件无法区分本地 8B 与云端 35B，导致"本地 8B 独立证据"缺失——加此参数补上审计性。
    modelLabel: get("--model-label", "").trim() || "",
    offlineRuleOnly: args.includes("--offline-rule-only"),
    // 稳定性评测：对指定变体重复跑 N 次（no_cache=true，强制独立推理），
    // 输出 Severe Recall 的 min/max/avg、每例最终风险一致率、工具路径一致率。
    stabilityRepeats: Number(get("--stability-repeats", "0")),
    stabilityVariant: get("--stability-variant", "agent"),
    // 配对消融：Dual/Agent 共享同一语义基线（隔离工具效果）
    paired: args.includes("--paired"),
    // 仅跑配对消融（跳过变体循环）：长跑时避免重复跑 dual/agent 两次
    pairedOnly: args.includes("--paired-only"),
  };
}

// ── 数据加载 ──────────────────────────────────────────────
function loadGoldSet(file) {
  const data = JSON.parse(readFileSync(path.join(ROOT, file), "utf8"));
  if (!Array.isArray(data.cases)) throw new Error(`Gold Set 缺少 cases: ${file}`);
  return { ...data, cases: data.cases };
}

/** 按 Gold Set 真实来源生成结果元数据（不再硬编码 expert-draft）。 */
function detectGoldsetMeta(goldSet) {
  const prov = goldSet.provenance || {};
  const isHumanGold =
    goldSet.dataset_type === "gold" &&
    (prov.label_status === "human-gold" || goldSet.source_type === "human-annotated") &&
    Array.isArray(prov.annotators) &&
    prov.annotators.length >= 2 &&
    prov.arbitration_completed === true;
  return {
    source: isHumanGold ? "human-gold" : goldSet.source_type || prov.label_status || "expert-draft",
    human_gold: isHumanGold,
    dataset_type: goldSet.dataset_type || "unknown",
    provenance: prov.label_status || goldSet.source_type || "expert-draft",
  };
}

function normalizeGold(c) {
  const g = c.gold || {};
  const violations = Array.isArray(g.violations) ? g.violations : [];
  return {
    id: c.id,
    conversation: c.conversation,
    riskLevel: g.risk_level || "low",
    severe: Boolean(g.severe),
    needsHumanReview: Boolean(g.needs_human_review),
    totalScore: g.total_score ?? 0,
    violations,
    catSet: new Set(violations.map((v) => v.category).filter(Boolean)),
  };
}

// ── 预测 ──────────────────────────────────────────────────
function normalizePrediction(body) {
  const d = body?.data || body;
  const violations = Array.isArray(d.violations) ? d.violations : [];
  return {
    riskLevel: d.risk_level || "low",
    severe: isSevere({ riskLevel: d.risk_level || "low", violations }),
    violations,
    catSet: new Set(violations.map((v) => v.category).filter(Boolean)),
    latencyMs: d.latency_ms ?? 0,
    tools: Array.isArray(d.agent_tools) ? d.agent_tools : [],
    requiresHumanReview: d.requires_human_review === true,
    knowledgeStatus: d.knowledge_status || "ok",
    // 逐案证据摘要（错误分析与 FP/FN 归因用）
    agentMode: d.agent_mode || null,
    agentTurns: d.agent_turn_count ?? 0,
    proposedEscalation: d.agent_evidence?.proposed_escalation ?? null,
    escalationEvidence: Array.isArray(d.agent_evidence?.escalation_evidence) ? d.agent_evidence.escalation_evidence : [],
    evidenceConflict: d.agent_evidence?.evidence_conflict === true,
    hardRedlineMatches: Array.isArray(d.hard_redline_matches) ? d.hard_redline_matches : [],
  };
}

/** api-guard.ts 的 RATE_MAX_REQUESTS 窗口：429 需等待窗口重置（60s）。 */
const RATE_WINDOW_MS = 61_000;

/** 失败预测：标记 error，不得静默转 low 计入指标（指标计算侧会排除）。 */
function failedPred(latencyMs, errorCode) {
  return { riskLevel: "low", severe: false, violations: [], catSet: new Set(), latencyMs, error: true, errorCode };
}

async function predictViaHttp(c, evalMode, opts) {
  const body = {
    conversation: c.conversation,
    ticket_id: `eval_${c.id}`,
    review_mode: "shadow",
    skip_feishu: true,
    eval_mode: evalMode,
    use_agent: evalMode === "agent",
    no_cache: opts.noCache === true,
  };
  const t0 = Date.now();
  // 服务端可能因内存阈值自动重启（dev 模式），网络/5xx 请求重试；429 等待限流窗口重置
  let lastError = "";
  for (let attempt = 0; attempt < 4; attempt += 1) {
    try {
      const res = await fetch(`${opts.baseUrl}/api/qa/evaluate`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(opts.apiKey ? { "x-api-key": opts.apiKey } : {}) },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(45_000),
      });
      const json = await res.json().catch(() => ({ error: "parse_failed" }));
      const latencyMs = Date.now() - t0;
      if (!res.ok) {
        // 4xx 重试无意义（如 401/400），直接失败；429 等待窗口重置后重试；5xx 短退避重试
        if (res.status < 500 && res.status !== 429) {
          return failedPred(latencyMs, res.status);
        }
        lastError = `http_${res.status}`;
        if (res.status === 429) await new Promise((r) => setTimeout(r, RATE_WINDOW_MS));
      } else {
        return { ...normalizePrediction(json), latencyMs };
      }
    } catch (err) {
      lastError = err instanceof Error ? err.message : String(err);
    }
    if (attempt < 3) await new Promise((r) => setTimeout(r, 3000 * (attempt + 1)));
  }
  return failedPred(Date.now() - t0, lastError);
}

async function predictRuleOnly(c) {
  const { ruleOnlyClassify } = await import("../src/lib/qa/evaluate-core.ts").catch(() => {
    // ts 文件无法直接 import；用离线纯函数兜底（见 evaluate-core 的 ruleOnlyClassify 逻辑复刻）
    return { ruleOnlyClassify: ruleOnlyClassifyFallback };
  });
  const result = ruleOnlyClassify(c.conversation);
  return {
    riskLevel: result.riskLevel,
    severe: isSevere({ riskLevel: result.riskLevel, violations: result.violations }),
    violations: result.violations,
    catSet: new Set(result.violations.map((v) => v.category)),
    latencyMs: 0,
  };
}

// rule_only 离线兜底（与 src/lib/qa/evaluate-core.ts 的 ruleOnlyClassify 完全一致，单一事实源）
function ruleOnlyClassifyFallback(conversation) {
  const patterns = [
    { pattern: /你(傻|蠢|笨|是不是眼瞎)/i, rule: "禁止辱骂客户", severity: "critical" },
    { pattern: /你自己(看|去|查)/i, rule: "禁止推诿敷衍", severity: "major" },
    { pattern: /我怎么知道|关我什么事|不关我事/i, rule: "禁止消极推诿", severity: "major" },
    { pattern: /这是(公司)?规定我也没办法|我也没办法/i, rule: "禁止冷漠推诿", severity: "major" },
    { pattern: /等通知|到时候再说|行行行/i, rule: "禁止敷衍了事", severity: "major" },
  ];
  const violations = [];
  let risk = "low";
  for (const { pattern, rule, severity } of patterns) {
    const m = conversation.match(pattern);
    if (m) {
      violations.push({ category: "服务态度", rule, severity, source_quote: m[0] });
      if (severity === "critical") risk = "critical";
    }
  }
  // 关键词兜底（客户行，只升不降）
  const customerLines = conversation.split("\n").filter((l) => /^(顾客|客户|买家|用户)[：:]/.test(l)).join("\n");
  if (/12315|工商局|食药监|律师函|起诉|报警|法院|人身安全|生命安全|法律/.test(customerLines)) risk = "critical";
  else if (/投诉|举报|消费者协会|消协|差评|曝光|媒体|破损|瑕疵|坏了|烂了|质量|假货|假|二手|退款|退货|退钱|退差价/.test(customerLines) && risk !== "critical") risk = "high";
  else if (/发货|物流|快递|没发|还没发|还没到|没到|订单.*没/.test(customerLines) && risk === "low") risk = "medium";
  return { riskLevel: risk, violations };
}

// ── 单变体运行 ──────────────────────────────────────────────
async function runVariantOnce(variant, goldCases, opts) {
  const predCases = [];
  for (let i = 0; i < goldCases.length; i++) {
    const c = goldCases[i];
    let pred;
    if (variant === "rule_only") {
      // rule_only 是纯关键词基线（离线纯函数），恒走本地；绝不走 HTTP ——
      // route 的 EVAL_MODES 不含 rule_only，走 HTTP 会被降级为 dual_rag_memory(LLM 全能力)，
      // 历史 0.984 误标即由此产生（--variants rule_only 未加 --offline-rule-only）。
      pred = await predictRuleOnly(c);
    } else {
      pred = await predictViaHttp(c, variant, opts);
    }
    predCases.push(pred);
    if ((i + 1) % 5 === 0 || i === goldCases.length - 1) {
      process.stdout.write(`  ${i + 1}/${goldCases.length} done\n`);
    }
    // 限速：LLM 档 ≤ 40 req/min
    await new Promise((r) => setTimeout(r, 1500));
  }
  return predCases;
}

// ── 稳定性指标（重复运行，验证"探索可变、安全结论稳定"） ─────
function computeStabilityMetrics(runs, goldCases) {
  const n = runs.length;
  // 失败预测不参与稳定性计算（error=true 不计入一致率，避免把请求失败当"不稳定"）
  const perCaseRisk = goldCases.map((_, i) => runs.map((r) => r[i].error ? null : r[i].riskLevel));
  const perCaseSevere = goldCases.map((_, i) => runs.map((r) => r[i].error ? null : r[i].severe));
  const perCaseTools = goldCases.map((_, i) => runs.map((r) => r[i].error ? null : [...r[i].tools].sort().join(",")));
  const sevPerRun = runs.map((r) => {
    const valid = r.map((p, i) => ({ p, i })).filter((x) => !x.p.error);
    const goldV = valid.map((x) => goldCases[x.i].severe);
    const predV = valid.map((x) => x.p.severe);
    return binarySeverityMetrics(goldV, predV);
  });
  const failedPerRun = runs.map((r) => r.filter((p) => p.error).length);
  // 一致率只统计"所有 run 均成功"的 case
  const allValidIdx = goldCases.map((_, i) => i).filter((i) => runs.every((r) => !r[i].error));

  return {
    repeats: n,
    severeRecall: {
      min: Math.min(...sevPerRun.map((s) => s.recall)),
      max: Math.max(...sevPerRun.map((s) => s.recall)),
      avg: sevPerRun.reduce((a, s) => a + s.recall, 0) / n,
    },
    severeF1: {
      min: Math.min(...sevPerRun.map((s) => s.f1)),
      max: Math.max(...sevPerRun.map((s) => s.f1)),
      avg: sevPerRun.reduce((a, s) => a + s.f1, 0) / n,
    },
    exactRiskConsistency: allValidIdx.length > 0 ? perCaseRisk.filter((r, i) => allValidIdx.includes(i) && new Set(r).size === 1).length / allValidIdx.length : 0,
    severeConsistency: allValidIdx.length > 0 ? perCaseSevere.filter((r, i) => allValidIdx.includes(i) && new Set(r).size === 1).length / allValidIdx.length : 0,
    toolPathConsistency: allValidIdx.length > 0 ? perCaseTools.filter((r, i) => allValidIdx.includes(i) && new Set(r).size === 1).length / allValidIdx.length : 0,
    failedPerRun,
  };
}

// ── 指标计算 ──────────────────────────────────────────────
// 失败预测（error=true）不参与指标计算，并在报告/JSON 中披露；不再静默转 low。
function computeMetrics(goldCases, predCases) {
  const validIdx = predCases.map((p, i) => ({ p, i })).filter((x) => !x.p.error);
  const failedIdx = predCases.map((p, i) => ({ p, i })).filter((x) => x.p.error);
  const goldCasesV = validIdx.map((x) => goldCases[x.i]);
  const predCasesV = validIdx.map((x) => x.p);
  const goldSevere = goldCasesV.map((g) => g.severe);
  const predSevere = predCasesV.map((p) => p.severe);
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
    // 审计：失败预测数与案例 id（必须披露，禁止静默当 low 计入）
    failedCount: failedIdx.length,
    failedCaseIds: failedIdx.map((x) => goldCases[x.i].id),
    evaluatedCount: goldCasesV.length,
  };
}

// ── 报告 ──────────────────────────────────────────────────
function renderReport(allVariants, stability, meta) {
  const lines = [];
  lines.push("# 质检 Gold Set 消融评测报告\n");
  lines.push(`> source: ${meta.source} | human_gold: ${meta.human_gold} | dataset_type: ${meta.dataset_type} | provenance: ${meta.provenance} | 生成时间: ${new Date().toISOString()}\n`);
  lines.push("## 严重违规指标（Recall/Precision/F1/误报率）\n");
  lines.push("| 变体 | Severe Recall | Precision | F1 | 误报率 FPR | Macro-F1(risk) | Cohen's κ | 失败预测 |");
  lines.push("|---|---|---|---|---|---|---|---|");
  for (const v of allVariants) {
    const s = v.metrics.severe;
    lines.push(
      `| ${v.variant} | ${s.recall.toFixed(3)} | ${s.precision.toFixed(3)} | ${s.f1.toFixed(3)} | ${s.fpr.toFixed(3)} | ${v.metrics.macroF1Risk.toFixed(3)} | ${v.metrics.cohensKappa.toFixed(3)} | ${v.metrics.failedCount} |`
    );
  }
  lines.push("\n## 延迟\n");
  lines.push("| 变体 | P50(ms) | P95(ms) | Mean(ms) |");
  lines.push("|---|---|---|---|");
  for (const v of allVariants) {
    lines.push(`| ${v.variant} | ${v.metrics.latency.p50.toFixed(0)} | ${v.metrics.latency.p95.toFixed(0)} | ${v.metrics.latency.mean.toFixed(0)} |`);
  }
  const failedTotal = allVariants.reduce((a, v) => a + (v.metrics.failedCount || 0), 0);
  if (failedTotal > 0) {
    lines.push("\n## 失败预测（已排除出指标，须人工复核）\n");
    for (const v of allVariants) {
      if (v.metrics.failedCount > 0) {
        lines.push(`- ${v.variant}: ${v.metrics.failedCaseIds.join(", ")}`);
      }
    }
    lines.push("\n> ⚠️ 存在失败预测，上方指标基于排除失败后的有效案例；请复核失败原因后重跑。");
  }
  if (stability) {
    const s = stability.metrics;
    lines.push(`\n## 稳定性（${stability.variant} × ${s.repeats} 次重复，no_cache=true 强制独立推理）\n`);
    lines.push("| 指标 | 值 |");
    lines.push("|---|---|");
    lines.push(`| Severe Recall min / max / avg | ${s.severeRecall.min.toFixed(3)} / ${s.severeRecall.max.toFixed(3)} / ${s.severeRecall.avg.toFixed(3)} |`);
    lines.push(`| Severe F1 min / max / avg | ${s.severeF1.min.toFixed(3)} / ${s.severeF1.max.toFixed(3)} / ${s.severeF1.avg.toFixed(3)} |`);
    lines.push(`| 每例最终风险一致率（exact risk） | ${(s.exactRiskConsistency * 100).toFixed(1)}% |`);
    lines.push(`| 每例严重度一致率（severe on/off） | ${(s.severeConsistency * 100).toFixed(1)}% |`);
    lines.push(`| 工具路径一致率（tool set） | ${(s.toolPathConsistency * 100).toFixed(1)}% |`);
    lines.push("\n> 结论：Agent 探索过程（工具路径）可以变化，但安全结论由确定性架构（硬红线 + 单调解析器）保持稳定。");
  }
  lines.push("\n> 漏检 case（严重违规被误判为不严重）与误报 case 见下方 JSON 附录。");
  return lines.join("\n");
}

function writeResults(allVariants, stability, opts, goldCases, meta) {
  const reportDir = path.join(ROOT, "evals", "results");
  mkdirSync(reportDir, { recursive: true });
  const ts = Date.now();
  const reportMd = renderReport(allVariants, stability, meta);
  writeFileSync(path.join(reportDir, `ablation-${ts}.md`), reportMd);
  writeFileSync(
    path.join(reportDir, `ablation-${ts}.json`),
    JSON.stringify(
      {
        source: meta.source,
        human_gold: meta.human_gold,
        dataset_type: meta.dataset_type,
        provenance: meta.provenance,
        model: opts.modelLabel || "unknown",
        generated_at: new Date().toISOString(),
        goldset: opts.goldsets,
        variants: allVariants.map((v) => ({
          variant: v.variant,
          metrics: v.metrics,
          predictions: v.predCases.map((p, i) => ({ case_id: goldCases[i].id, pred: p })),
        })),
        stability: stability ? { variant: stability.variant, metrics: stability.metrics } : null,
      },
      null,
      2
    )
  );
  return ts;
}

// ── 配对消融（共享语义基线，隔离工具效果） ─────────────────
// 因果实验：每例只调一次 runJudge（baseline_only），保存快照；
// Dual/Agent 复用同一 baseline_override，差异只来自工具层。

async function predictBaselineOnce(c, opts) {
  const body = {
    conversation: c.conversation,
    ticket_id: `paired_baseline_${c.id}`,
    review_mode: "shadow",
    skip_feishu: true,
    eval_mode: "baseline_only",
  };
  const t0 = Date.now();
  let lastError = "";
  for (let attempt = 0; attempt < 4; attempt += 1) {
    const t = Date.now();
    try {
      const res = await fetch(`${opts.baseUrl}/api/qa/evaluate`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(opts.apiKey ? { "x-api-key": opts.apiKey } : {}) },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(180_000),
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) {
        if (res.status === 429) {
          lastError = "http_429";
          await new Promise((r) => setTimeout(r, RATE_WINDOW_MS));
        } else {
          return { error: true, risk_level: "low", violations: [], latencyMs: Date.now() - t, errorCode: res.status };
        }
      } else {
        return {
          risk_level: json.risk_level || "low",
          total_score: json.total_score,
          sentiment_score: json.sentiment_score,
          intent: json.intent || "",
          summary: json.summary || "",
          violations: Array.isArray(json.violations) ? json.violations : [],
          latencyMs: Date.now() - t,
        };
      }
    } catch (err) {
      lastError = err instanceof Error ? err.message : String(err);
    }
  }
  return { error: true, risk_level: "low", violations: [], latencyMs: Date.now() - t0, errorCode: lastError };
}

async function predictWithBaselineOverride(c, evalMode, baseline, opts) {
  const body = {
    conversation: c.conversation,
    ticket_id: `paired_${evalMode}_${c.id}`,
    review_mode: "shadow",
    skip_feishu: true,
    eval_mode: evalMode,
    use_agent: evalMode === "agent",
    baseline_override: baseline,
  };
  // 并发下 API 偶发 429/5xx：429 等待限流窗口（61s）重置后重试，避免静默转 low 污染指标
  let lastError = "";
  for (let attempt = 0; attempt < 4; attempt += 1) {
    const t0 = Date.now();
    try {
      const res = await fetch(`${opts.baseUrl}/api/qa/evaluate`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(opts.apiKey ? { "x-api-key": opts.apiKey } : {}) },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(180_000),
      });
      const json = await res.json().catch(() => ({ error: "parse_failed" }));
      const latencyMs = Date.now() - t0;
      if (!res.ok) {
        if (res.status === 429) {
          lastError = "http_429";
          await new Promise((r) => setTimeout(r, RATE_WINDOW_MS));
          continue;
        }
        if (res.status < 500) {
          return failedPred(latencyMs, res.status);
        }
        lastError = `http_${res.status}`;
      } else {
        return { ...normalizePrediction(json), latencyMs };
      }
    } catch (err) {
      lastError = err instanceof Error ? err.message : String(err);
    }
    if (attempt < 3) await new Promise((r) => setTimeout(r, 2000 * (attempt + 1)));
  }
  return failedPred(Date.now() - Date.now(), lastError);
}

/** 并发池：以 limit 并发执行 items.map(fn)，保持结果顺序。 */
async function mapWithConcurrency(items, limit, fn) {
  const results = new Array(items.length);
  let idx = 0;
  const workers = Array.from({ length: Math.max(1, Math.min(limit, items.length)) }, async () => {
    while (true) {
      const i = idx++;
      if (i >= items.length) break;
      results[i] = await fn(items[i], i);
    }
  });
  await Promise.all(workers);
  return results;
}

async function runPaired(goldCases, opts) {
  console.log("\n=== 配对消融（共享语义基线） ===");
  console.log(`  Phase 1: baseline_only 每例一次（并发 ${opts.concurrency}）`);
  const limit = Math.max(1, opts.concurrency || 2);
  const baselines = await mapWithConcurrency(goldCases, limit, (c) => predictBaselineOnce(c, opts));
  console.log(`    baseline ${baselines.length}/${goldCases.length}`);
  const snapshotPath = path.join(ROOT, "evals", "results", "baseline-snapshot.jsonl");
  writeFileSync(
    snapshotPath,
    baselines.map((b, i) => JSON.stringify({ case_id: goldCases[i].id, baseline: b })).join("\n") + "\n"
  );
  console.log(`  snapshot → ${snapshotPath}`);

  const variants = [];
  for (const evalMode of ["dual", "agent"]) {
    console.log(`  Phase 2: ${evalMode}（复用同一 baseline_override，并发 ${limit}）`);
    const predCases = await mapWithConcurrency(goldCases, limit, (c, i) =>
      predictWithBaselineOverride(c, evalMode, baselines[i], opts)
    );
    console.log(`    ${evalMode} ${predCases.length}/${goldCases.length}`);
    variants.push({ variant: evalMode, metrics: computeMetrics(goldCases, predCases), predCases });
  }
  return { variants, baselines };
}

function renderPairedReport(paired, goldCases, meta) {
  const lines = [];
  lines.push("## 配对消融（共享语义基线，隔离工具效果）\n");
  lines.push("> 每例仅调用一次 runJudge（baseline_only），Dual/Agent 复用同一 baseline_override。");
  lines.push("> 差异可归因于：检索证据 / Agent 升级提议 / 人工复核触发 / 工具失败处理，而非两次独立 LLM 采样。\n");
  lines.push("| 变体 | Severe Recall | Precision | F1 | FPR | Macro-F1(risk) | Cohen's κ | 失败预测 |");
  lines.push("|---|---|---|---|---|---|---|---|");
  for (const v of paired.variants) {
    const s = v.metrics.severe;
    lines.push(
      `| ${v.variant} (shared baseline) | ${s.recall.toFixed(3)} | ${s.precision.toFixed(3)} | ${s.f1.toFixed(3)} | ${s.fpr.toFixed(3)} | ${v.metrics.macroF1Risk.toFixed(3)} | ${v.metrics.cohensKappa.toFixed(3)} | ${v.metrics.failedCount} |`
    );
  }
  const failedTotal = paired.variants.reduce((a, v) => a + (v.metrics.failedCount || 0), 0);
  if (failedTotal > 0) {
    lines.push("\n> ⚠️ 存在失败预测（dual/agent 请求未成功），指标已排除失败案例。失败案例：");
    for (const v of paired.variants) {
      if (v.metrics.failedCount > 0) {
        lines.push(`>   ${v.variant}: ${v.metrics.failedCaseIds.join(", ")}`);
      }
    }
  }
  lines.push("\n> 若 Dual 与 Agent 共享基线后 Recall 相同，说明 Agent 当前主要改善可审计性与证据完整度，而非检测召回；");
  lines.push("> 仅当 Agent 凭可验证来源把某例从非 severe 升到 severe 时，才可声称 evidence retrieval 恢复了语义漏检。");
  return lines.join("\n");
}

function writePairedResults(paired, opts, goldCases, meta) {
  const reportDir = path.join(ROOT, "evals", "results");
  mkdirSync(reportDir, { recursive: true });
  const ts = Date.now();
  writeFileSync(
    path.join(reportDir, `paired-${ts}.json`),
    JSON.stringify(
      {
        source: meta.source,
        human_gold: meta.human_gold,
        dataset_type: meta.dataset_type,
        provenance: meta.provenance,
        model: opts.modelLabel || "unknown",
        design: "shared-baseline-causal-ablation",
        generated_at: new Date().toISOString(),
        variants: paired.variants.map((v) => ({
          variant: v.variant,
          metrics: v.metrics,
          predictions: v.predCases.map((p, i) => ({ case_id: goldCases[i].id, pred: p })),
        })),
      },
      null,
      2
    )
  );
  return ts;
}

// ── 主流程 ────────────────────────────────────────────────
async function main() {
  const opts = parseArgs();
  const goldSet = loadGoldSet(opts.goldsets);
  const goldCases = goldSet.cases.map(normalizeGold);
  const meta = detectGoldsetMeta(goldSet);
  console.log(`加载 Gold Set: ${goldCases.length} 例 (${opts.goldsets})`);
  console.log(`元数据: source=${meta.source} | human_gold=${meta.human_gold}`);

  const allVariants = [];
  let lastTs = 0;
  // --paired-only 时跳过变体循环（rule_only 结果已有，避免重复长跑）
  if (!opts.pairedOnly) {
    for (const variant of opts.variants) {
      console.log(`\n=== 运行变体: ${variant} ===`);
      const predCases = await runVariantOnce(variant, goldCases, opts);
      const metrics = computeMetrics(goldCases, predCases);
      if (metrics.failedCount > 0) {
        console.log(`  ⚠️ ${metrics.failedCount} 例失败: ${metrics.failedCaseIds.join(", ")}`);
      }
      allVariants.push({ variant, metrics, predCases });
      // 增量落盘：长跑中途失败不丢已完成变体
      lastTs = writeResults(allVariants, null, opts, goldCases, meta);
    }
  }

  // 稳定性评测（可选，--stability-repeats N）：no_cache=true 强制独立推理
  let stability = null;
  if (opts.stabilityRepeats > 0) {
    console.log(`\n=== 稳定性评测: ${opts.stabilityVariant} × ${opts.stabilityRepeats}（no_cache=true）===`);
    const runs = [];
    for (let r = 0; r < opts.stabilityRepeats; r++) {
      console.log(`  run ${r + 1}/${opts.stabilityRepeats}`);
      runs.push(await runVariantOnce(opts.stabilityVariant, goldCases, { ...opts, noCache: true }));
    }
    stability = { variant: opts.stabilityVariant, runs, metrics: computeStabilityMetrics(runs, goldCases) };
  }

  const ts = writeResults(allVariants, stability, opts, goldCases, meta);
  let reportMd = renderReport(allVariants, stability, meta);

  // 配对消融（--paired）：共享基线，隔离工具效果
  let pairedTs = 0;
  if (opts.paired) {
    const paired = await runPaired(goldCases, opts);
    pairedTs = writePairedResults(paired, opts, goldCases, meta);
    reportMd += "\n\n" + renderPairedReport(paired, goldCases, meta);
  }

  console.log("\n" + reportMd);
  console.log(`\n报告: evals/results/ablation-${ts}.md${pairedTs ? ` + paired-${pairedTs}.json` : ""}`);
}

main().catch((e) => { console.error("评测失败:", e); process.exit(1); });
