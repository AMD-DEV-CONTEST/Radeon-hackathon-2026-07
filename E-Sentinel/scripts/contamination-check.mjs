#!/usr/bin/env node
/**
 * 训练/开发集去污染管线（诚信红线保障）。
 *
 * 对候选训练数据做三重去污染，与 frozen human-gold 105 例对比：
 *   1. 规范化精确匹配（NFKC + 去标点空白 + 数字归一 + 小写）
 *   2. 字符 5-gram Jaccard 近重复（> 0.70 拒绝）
 *   3. 字符 trigram hash 向量余弦词法近重复（> 0.85 拒绝；字符级 n-gram hashing，非语义 embedding）
 * 随后按 template_seed 整体切分 train/dev（同模板不跨 split），
 * 输出 train.jsonl / dev.jsonl + decontamination-report.json（含 SHA256 清单）。
 *
 * 用法：
 *   node scripts/contamination-check.mjs \
 *     --candidates training/data/candidates.jsonl \
 *     [--gold evals/configs/gold-set-human-v1.json] \
 *     [--out-dir training/data] [--train-ratio 0.9] [--seed 42]
 *
 * 纪律：gold-set 仅用于对比拒绝，绝不并入训练数据；本脚本不会把任何 gold 内容写入候选输出。
 */

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

function arg(name, def) {
  const i = process.argv.indexOf(name);
  return i >= 0 ? process.argv[i + 1] ?? def : def;
}
const CANDIDATES = arg("--candidates");
const GOLD = arg("--gold", "evals/configs/gold-set-human-v1.json");
const OUT_DIR = arg("--out-dir", "training/data");
const TRAIN_RATIO = Number(arg("--train-ratio", "0.9"));
const SEED = Number(arg("--seed", "42"));

// ── 归一化 ──────────────────────────────────────────────────
function normalize(text) {
  return (text || "")
    .normalize("NFKC")
    .toLowerCase()
    .replace(/\d/g, "#")
    .replace(/[\s\p{P}\p{S}]+/gu, "");
}

// 字符 n-gram 集合
function charNGrams(text, n) {
  const s = text.replace(/\s+/g, "");
  const set = new Set();
  for (let i = 0; i <= s.length - n; i++) set.add(s.slice(i, i + n));
  return set;
}

// 5-gram Jaccard
function jaccard(a, b) {
  const sa = charNGrams(a, 5);
  const sb = charNGrams(b, 5);
  if (sa.size === 0 || sb.size === 0) return 0;
  let inter = 0;
  for (const g of sa) if (sb.has(g)) inter++;
  const union = sa.size + sb.size - inter;
  return union === 0 ? 0 : inter / union;
}

// trigram hash → 512 桶计数向量 → 余弦相似（确定性、纯本地，无需外部 embedding）
function trigramVector(text, buckets = 512) {
  const s = text.replace(/\s+/g, "");
  const v = new Float64Array(buckets);
  for (let i = 0; i <= s.length - 3; i++) {
    const h = createHash("sha256").update(s.slice(i, i + 3)).digest().readUInt32BE(0) % buckets;
    v[h] += 1;
  }
  return v;
}
function cosine(a, b) {
  let dot = 0, na = 0, nb = 0;
  for (let i = 0; i < a.length; i++) { dot += a[i] * b[i]; na += a[i] * a[i]; nb += b[i] * b[i]; }
  if (na === 0 || nb === 0) return 0;
  return dot / (Math.sqrt(na) * Math.sqrt(nb));
}

function sha256(text) {
  return createHash("sha256").update(text).digest("hex");
}

// ── 读取候选与 gold ─────────────────────────────────────────
const candidates = readFileSync(CANDIDATES, "utf8")
  .split("\n").filter(Boolean)
  .map((l, i) => { const o = JSON.parse(l); return { line: i + 1, obj: o, conv: o.conversation }; });

const goldRaw = JSON.parse(readFileSync(path.join(ROOT, GOLD), "utf8"));
const goldCases = Array.isArray(goldRaw) ? goldRaw : goldRaw.cases;

// 预计算 gold 索引（只算一次）
const goldNorm = goldCases.map((c) => normalize(c.conversation));
const goldVecs = goldCases.map((c) => trigramVector(c.conversation));

// 字段名 semantic_dup 为历史命名；实为字符 trigram 词法近重复（哈希 n-gram 向量余弦，非语义 embedding）
const rejected = { exact_dup: [], near_dup_ngram: [], semantic_dup: [], bad_evidence: [], missing_conv: [] };

function classify(cand) {
  const cn = normalize(cand.conv);
  if (!cand.conv || !cand.conv.trim()) { rejected.missing_conv.push(cand.line); return null; }
  // 1. 规范化精确匹配
  if (goldNorm.some((g) => g === cn && g !== "")) { rejected.exact_dup.push(cand.line); return null; }
  // 2. 5-gram Jaccard（对每例 gold 取最大相似）
  for (const g of goldCases) {
    if (jaccard(cand.conv, g.conversation) > 0.70) { rejected.near_dup_ngram.push(cand.line); return null; }
  }
  // 3. trigram 向量余弦
  const v = trigramVector(cand.conv);
  for (const gv of goldVecs) {
    if (cosine(v, gv) > 0.85) { rejected.semantic_dup.push(cand.line); return null; }
  }
  // 4. source_quote 必须存在于 conversation（客服侧）
  const label = cand.obj.label || {};
  for (const vio of label.violations || []) {
    const q = (vio.source_quote || "").trim();
    if (q && !cand.conv.includes(q)) { rejected.bad_evidence.push({ line: cand.line, quote: q }); return null; }
  }
  return cand.obj;
}

const kept = [];
for (const c of candidates) {
  const o = classify(c);
  if (o) kept.push(o);
}

// ── 按 template_seed 整体切分（同 seed 不跨 split）───────────
const seedGroups = new Map();
for (const o of kept) {
  const seed = o.template_seed || "default";
  if (!seedGroups.has(seed)) seedGroups.set(seed, []);
  seedGroups.get(seed).push(o);
}
const seeds = [...seedGroups.keys()].sort();
// 确定性 shuffle（mulberry32）
let s = SEED;
const rnd = () => { s |= 0; s = (s + 0x6D2B79F5) | 0; let t = Math.imul(s ^ (s >>> 15), 1 | s); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
for (let i = seeds.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [seeds[i], seeds[j]] = [seeds[j], seeds[i]]; }
const nTrain = Math.max(1, Math.round(seeds.length * TRAIN_RATIO));
const trainSeeds = new Set(seeds.slice(0, nTrain));
const devSeeds = new Set(seeds.slice(nTrain));

const train = [], dev = [];
for (const [seed, group] of seedGroups) {
  (trainSeeds.has(seed) ? train : dev).push(...group);
}

// ── 写出 ────────────────────────────────────────────────────
mkdirSync(path.join(ROOT, OUT_DIR), { recursive: true });
const writeSet = (rows, name) =>
  writeFileSync(path.join(ROOT, OUT_DIR, name), rows.map((o) => JSON.stringify(o)).join("\n") + "\n");
writeSet(train, "train.jsonl");
writeSet(dev, "dev.jsonl");

const convAll = kept.map((o) => o.conversation).join("\n");
const trainAll = train.map((o) => o.conversation).join("\n");
const devAll = dev.map((o) => o.conversation).join("\n");

const report = {
  generated_at: null, // 由调用方打时间戳（Date 不可用场景兼容）
  candidates: candidates.length,
  kept: kept.length,
  train: train.length,
  dev: dev.length,
  rejected: {
    exact_dup: rejected.exact_dup.length,
    near_dup_ngram: rejected.near_dup_ngram.length,
    semantic_dup: rejected.semantic_dup.length,
    bad_evidence: rejected.bad_evidence.length,
    missing_conv: rejected.missing_conv.length,
    total: Object.values(rejected).reduce((a, r) => a + (Array.isArray(r) ? r.length : 0), 0),
  },
  split_by_template_seed: { seeds: seeds.length, train_seeds: trainSeeds.size, dev_seeds: devSeeds.size },
  checksums: {
    gold_set_sha256: sha256(JSON.stringify(goldRaw)),
    train_jsonl_sha256: sha256(trainAll),
    dev_jsonl_sha256: sha256(devAll),
    all_conversations_sha256: sha256(convAll),
  },
  thresholds: { exact_match: "normalized equal", jaccard_5gram: 0.70, cosine_trigram_512: 0.85 },
  rejected_line_examples: {
    exact_dup: rejected.exact_dup.slice(0, 3),
    near_dup_ngram: rejected.near_dup_ngram.slice(0, 3),
    semantic_dup: rejected.semantic_dup.slice(0, 3),
  },
};
writeFileSync(path.join(ROOT, OUT_DIR, "decontamination-report.json"), `${JSON.stringify(report, null, 2)}\n`);

console.log(`候选 ${candidates.length} → 保留 ${kept.length}（train ${train.length} / dev ${dev.length}）`);
console.log(`拒绝: exact ${rejected.exact_dup.length} · ngram ${rejected.near_dup_ngram.length} · trigram-lexical ${rejected.semantic_dup.length} · bad_evidence ${rejected.bad_evidence.length} · missing ${rejected.missing_conv.length}`);
console.log(`模板分组: ${seeds.length} seeds（train ${trainSeeds.size} / dev ${devSeeds.size}）`);
console.log(`报告: ${OUT_DIR}/decontamination-report.json`);
