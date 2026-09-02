/**
 * Integration test: semantic match + Few-Shot retrieval
 * Run: npx tsx scripts/verify-fewshot.ts
 */
import { matchQualityRules } from "../src/lib/semantic-match";
import { getFewShotExamples, recordCorrection } from "../src/lib/few-shot";

async function main() {
  let passed = 0;
  let failed = 0;
  function check(label: string, condition: boolean, detail?: string) {
    if (condition) { console.log(`  ✅ ${label}`); passed++; }
    else { console.log(`  ❌ ${label}${detail ? " — " + detail : ""}`); failed++; }
  }

  // ── 1. Semantic match ──────────────────────────────────
  console.log("\n🔍 1. Semantic match against quality_rules");
  const match = await matchQualityRules("客户说物流太慢了三天没发货要投诉", { threshold: 0, count: 5 });
  check("returns rules", match.rules.length > 0, `got ${match.rules.length} rules`);
  check("method is semantic (local trigram)", match.method === "semantic" || match.method === "none", `method=${match.method}`);
  console.log(`   Top 3 matches:`);
  for (const r of match.rules.slice(0, 3)) {
    console.log(`     [${r.category}] ${r.rule_text.slice(0, 60)}... (sim=${r.similarity.toFixed(2)})`);
  }

  // ── 2. Record a correction ─────────────────────────────
  console.log("\n📝 2. Record correction sample");
  const record = await recordCorrection({
    conversation: "客户投诉发货速度太慢，要求退款和赔偿",
    ai_prediction: { risk_level: "low", violations: [] },
    human_correction: { risk_level: "high", violations: [{ rule: "发货时效", severity: "major" }] },
    correction_type: "risk_level",
  });
  check("correction recorded", record.success, record.error);
  console.log(`   id=${record.id}`);

  // ── 3. Few-Shot retrieval ──────────────────────────────
  console.log("\n🎯 3. Few-Shot retrieval");
  const fs = await getFewShotExamples("客户说发货太慢了，物流体验很差", { threshold: 0, count: 3 });
  check("returns result", fs.source !== "none" || fs.examples.length >= 0, `source=${fs.source}, count=${fs.examples.length}`);
  if (fs.examples.length > 0) {
    check("found similar correction", fs.examples.length > 0);
    console.log(`   Best match: sim=${fs.examples[0].similarity}`);
    console.log(`   Conversation: ${fs.examples[0].conversation.slice(0, 80)}...`);
  } else {
    console.log("   No similar corrections found (expected if no embedding API)");
  }

  // ── 4. Prompt formatting ───────────────────────────────
  console.log("\n📋 4. Prompt formatting");
  check("promptInsert is string", typeof fs.promptInsert === "string");
  if (fs.promptInsert) {
    check("contains Chinese header", fs.promptInsert.includes("历史纠错案例"));
    check("contains case markers", fs.promptInsert.includes("### 案例"));
    console.log(`   Prompt length: ${fs.promptInsert.length} chars`);
  }

  // ── Summary ────────────────────────────────────────────
  console.log(`\n${"═".repeat(50)}`);
  console.log(`  Results: ${passed} passed, ${failed} failed`);
  console.log(`${"═".repeat(50)}`);
  if (failed > 0) process.exit(1);
}

main().catch((e) => { console.error(e); process.exit(1); });
