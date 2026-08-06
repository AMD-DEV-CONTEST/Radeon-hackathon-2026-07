#!/usr/bin/env node
/**
 * 合并 base 40 + 合成 60+ 为总草稿，并生成 A3 盲标工作簿。
 *
 * 用法：
 *   node scripts/build-combined-draft.mjs \
 *     --base evals/configs/gold-set-human-draft-v1.json \
 *     --synth-dir /tmp/qa-ann \
 *     --out evals/configs/gold-set-human-draft-v2.json \
 *     --workbook-dir /tmp/qa-ann/ann-workbooks \
 *     --next-case 41
 *
 * 规则：
 *   - base 40 保持原结构（finalize 会用人工标注覆盖 gold）；
 *   - 合成 case 不携带预设 gold（A3 盲标），id 从 case-041 递增；
 *   - 合成 case 记录 provenance=synthetic-near-real / scenarioType /
 *     generationVersion / reviewStatus；
 *   - 工作簿按批次（≤20）切分，只含 id + conversation（盲标）。
 */
import { readFileSync, writeFileSync, readdirSync, mkdirSync } from "node:fs";
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
    base: get("--base", "evals/configs/gold-set-human-draft-v1.json"),
    synthDir: get("--synth-dir", "/tmp/qa-ann"),
    out: get("--out", "evals/configs/gold-set-human-draft-v2.json"),
    workbookDir: get("--workbook-dir", "/tmp/qa-ann/ann-workbooks"),
    nextCase: parseInt(get("--next-case", "41"), 10),
  };
}

function loadJson(p) {
  return JSON.parse(readFileSync(p, "utf8"));
}

function main() {
  const opts = parseArgs();
  const basePath = path.isAbsolute(opts.base) ? opts.base : path.join(ROOT, opts.base);
  const outPath = path.isAbsolute(opts.out) ? opts.out : path.join(ROOT, opts.out);

  const base = loadJson(basePath);
  const errors = [];

  // 读全部合成结果
  const synthFiles = readdirSync(opts.synthDir).filter((f) => /^synth-.*\.json$/.test(f));
  const synthetic = [];
  for (const f of synthFiles.sort()) {
    let data;
    try {
      data = loadJson(path.join(opts.synthDir, f));
    } catch {
      errors.push(`合成文件解析失败: ${f}`);
      continue;
    }
    for (const c of data.cases || []) {
      if (!c.conversation || typeof c.conversation !== "string") {
        errors.push(`${f}: 缺 conversation`);
        continue;
      }
      if (!c.scenarioType) errors.push(`${f}: 缺 scenarioType`);
      synthetic.push({
        conversation: c.conversation,
        scenarioType: c.scenarioType || "unknown",
        sourceRelevant: c.sourceRelevant === true,
      });
    }
  }

  if (synthetic.length < 60) {
    console.error(`合成案例不足 60（当前 ${synthetic.length}），跳过合并`);
    process.exit(2);
  }

  // 分配 id：base 保持，合成从 nextCase 递增
  const baseCases = (base.cases || []).map((c) => ({ ...c }));
  let n = opts.nextCase;
  const synthCases = synthetic.map((s) => ({
    id: `case-${String(n++).padStart(3, "0")}`,
    set: "synthetic",
    provenance: "synthetic-near-real",
    scenarioType: s.scenarioType,
    sourceRelevant: s.sourceRelevant,
    generationVersion: "v1",
    reviewStatus: "pending",
    conversation: s.conversation,
  }));

  // 严重度分布预估（盲标后校正，这里只记录场景矩阵）
  const scenarioCount = synthCases.reduce((a, c) => {
    a[c.scenarioType] = (a[c.scenarioType] || 0) + 1;
    return a;
  }, {});

  const doc = {
    dataset_version: "gold-human-draft-v2.0",
    dataset_type: "draft",
    source_type: "mixed",
    provenance: {
      label_status: "expert-draft-pending-human-annotation",
      description: `base=${base.dataset_version}(${baseCases.length} 例, AI 起草待人工确认) + synthetic(${synthCases.length} 例, synthetic-near-real 分层矩阵)。等待双通道盲标 + 人工逐例确认仲裁后升 human-gold。`,
      annotators: ["ann-a", "ann-b"],
      frozen: false,
      few_shot_excluded: true,
      severity_scheme: "service-quality-v1",
      base_set: base.dataset_version,
      synthetic_near_real: true,
      scenario_matrix: scenarioCount,
      base_count: baseCases.length,
      synthetic_count: synthCases.length,
    },
    case_count: baseCases.length + synthCases.length,
    cases: [...baseCases, ...synthCases],
  };

  writeFileSync(outPath, JSON.stringify(doc, null, 2) + "\n");

  // 生成 A3 盲标工作簿（只含合成 case，按批 ≤20）
  mkdirSync(opts.workbookDir, { recursive: true });
  const workbooks = [];
  for (let i = 0; i < synthCases.length; i += 20) {
    const slice = synthCases.slice(i, i + 20);
    const wb = {
      dataset: outPath,
      batch_index: Math.floor(i / 20) + 1,
      case_count: slice.length,
      cases: slice.map((c) => ({ id: c.id, conversation: c.conversation })),
    };
    const wbFile = path.join(opts.workbookDir, `workbook-synthetic-${wb.batch_index}.json`);
    writeFileSync(wbFile, JSON.stringify(wb, null, 2) + "\n");
    workbooks.push(wbFile);
  }

  if (errors.length > 0) {
    console.error("警告:");
    for (const e of errors) console.error(" -", e);
  }
  console.log(`合并完成: ${doc.case_count} 例 (base ${baseCases.length} + synthetic ${synthCases.length}) -> ${outPath}`);
  console.log(`盲标工作簿: ${workbooks.length} 批`);
  console.log(`场景分布:`, JSON.stringify(scenarioCount));
}

main();
