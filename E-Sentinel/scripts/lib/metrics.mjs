/**
 * 质检评测指标库（纯函数，node:test 可测）。
 * 用于 Gold Set 消融评测，全部指标在这里计算。
 */

/**
 * 判定是否"严重违规"：与 gold 标注口径一致 —— 仅 risk_level ∈ {high, critical}。
 * （gold 中 4 例 medium + major 违规也标 severe:false；此前把"存在 major 违规"
 *   也算 severe 造成评测口径与 gold 不一致，虚增 FPR。）
 */
export function isSevere(pred) {
  const risk = pred?.riskLevel || pred?.risk_level || "low";
  return risk === "high" || risk === "critical";
}

/** 二元严重违规指标：严重 Recall/Precision/F1/误报率 FPR */
export function binarySeverityMetrics(goldSevere, predSevere) {
  let tp = 0, fp = 0, fn = 0, tn = 0;
  for (let i = 0; i < goldSevere.length; i++) {
    if (goldSevere[i] && predSevere[i]) tp++;
    else if (!goldSevere[i] && predSevere[i]) fp++;
    else if (goldSevere[i] && !predSevere[i]) fn++;
    else tn++;
  }
  const recall = tp + fn > 0 ? tp / (tp + fn) : 0;
  const precision = tp + fp > 0 ? tp / (tp + fp) : 0;
  const f1 = precision + recall > 0 ? (2 * precision * recall) / (precision + recall) : 0;
  const fpr = fp + tn > 0 ? fp / (fp + tn) : 0;
  const fdr = tp + fp > 0 ? fp / (tp + fp) : 0;
  return { tp, fp, fn, tn, recall, precision, f1, fpr, fdr };
}

function f1For(p, r) {
  return p + r > 0 ? (2 * p * r) / (p + r) : 0;
}

/** Macro-F1（risk-level 四分类 one-vs-rest） */
export function macroF1ByRiskClass(goldRisks, predRisks) {
  const classes = ["low", "medium", "high", "critical"];
  const f1s = [];
  for (const c of classes) {
    let tp = 0, fp = 0, fn = 0;
    for (let i = 0; i < goldRisks.length; i++) {
      if (goldRisks[i] === c && predRisks[i] === c) tp++;
      else if (goldRisks[i] !== c && predRisks[i] === c) fp++;
      else if (goldRisks[i] === c && predRisks[i] !== c) fn++;
    }
    const p = tp + fp > 0 ? tp / (tp + fp) : 0;
    const r = tp + fn > 0 ? tp / (tp + fn) : 0;
    f1s.push(f1For(p, r));
  }
  return f1s.reduce((a, b) => a + b, 0) / classes.length;
}

/** Macro-F1（违规分类多标签，categories 五分类） */
export function macroF1ByViolationCategory(goldCatSets, predCatSets, cats) {
  const f1s = [];
  for (const c of cats) {
    let tp = 0, fp = 0, fn = 0;
    for (let i = 0; i < goldCatSets.length; i++) {
      const g = goldCatSets[i].has(c);
      const p = predCatSets[i].has(c);
      if (g && p) tp++;
      else if (!g && p) fp++;
      else if (g && !p) fn++;
    }
    // 该分类零 gold 零预测 → 视为正确（F1=1），并在报告注明
    if (tp + fp + fn === 0) { f1s.push(1); continue; }
    const p = tp + fp > 0 ? tp / (tp + fp) : 0;
    const r = tp + fn > 0 ? tp / (tp + fn) : 0;
    f1s.push(f1For(p, r));
  }
  return f1s.reduce((a, b) => a + b, 0) / cats.length;
}

/** Cohen's Kappa（risk-level 四分类） */
export function cohensKappa(goldRisks, predRisks) {
  const n = goldRisks.length;
  if (n === 0) return 0;
  const classes = ["low", "medium", "high", "critical"];
  const gCount = {}, pCount = {};
  for (const c of classes) { gCount[c] = 0; pCount[c] = 0; }
  let po = 0;
  for (let i = 0; i < n; i++) {
    gCount[goldRisks[i]] = (gCount[goldRisks[i]] || 0) + 1;
    pCount[predRisks[i]] = (pCount[predRisks[i]] || 0) + 1;
    if (goldRisks[i] === predRisks[i]) po++;
  }
  po /= n;
  let pe = 0;
  for (const c of classes) {
    pe += (gCount[c] / n) * (pCount[c] / n);
  }
  return pe < 1 ? (po - pe) / (1 - pe) : 0;
}

/** 证据质量：预测 source_quote 与 gold quote 的字符重叠 F1（≥0.6 视为命中） */
export function evidencePrecision(goldVioSets, predVioSets) {
  let matched = 0, total = 0;
  for (let i = 0; i < predVioSets.length; i++) {
    for (const pv of predVioSets[i]) {
      total++;
      const goldSet = new Set(goldVioSets[i].flatMap((g) => Array.from(g)));
      if (goldSet.size === 0) continue;
      const pChars = new Set(Array.from(pv));
      let inter = 0;
      for (const ch of pChars) if (goldSet.has(ch)) inter++;
      const union = goldSet.size + pChars.size - inter;
      const overlap = union > 0 ? (2 * inter) / union : 0;
      if (overlap >= 0.6) matched++;
    }
  }
  return total > 0 ? matched / total : 0;
}

/** 风险准确率（risk-level 精确匹配） */
export function riskAccuracy(goldRisks, predRisks) {
  let correct = 0;
  for (let i = 0; i < goldRisks.length; i++) if (goldRisks[i] === predRisks[i]) correct++;
  return goldRisks.length > 0 ? correct / goldRisks.length : 0;
}

/** 延迟统计 */
export function summaryStats(latencies) {
  if (!latencies.length) return { p50: 0, p95: 0, mean: 0 };
  const sorted = [...latencies].sort((a, b) => a - b);
  const p = (q) => sorted[Math.min(sorted.length - 1, Math.floor(q * sorted.length))];
  return {
    p50: p(0.5),
    p95: p(0.95),
    mean: latencies.reduce((a, b) => a + b, 0) / latencies.length,
  };
}
