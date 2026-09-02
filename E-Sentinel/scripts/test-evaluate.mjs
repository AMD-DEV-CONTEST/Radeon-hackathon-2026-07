/**
 * 质检 API 端到端测试
 * 启动: node scripts/test-evaluate.mjs
 */

const API_URL = "http://localhost:3001/api/qa/evaluate";

const SAMPLE_CONVERSATION = `客服：您好，请问有什么可以帮您？
客户：我前天买的那个洗面奶，收到的包装是破的，里面的东西漏了一半，你们怎么发的货？
客服：你自己签收的时候不看一眼的吗？
客户：快递放丰巢柜的，我怎么看？现在我要求退款。
客服：退款需要你先垫付运费寄回来，我们收到货检查没问题才能退。
客户：你们发的问题货为什么要我垫运费？我不接受。
客服：这是公司规定，我也没办法。
客户：那把你的工号给我，我要投诉。
客服：行行行，给你登记了，等通知吧。`;

async function main() {
  console.log("=== QA System E2E Test ===\n");

  console.log("1. Testing /api/qa/evaluate");
  console.log(`   Input: ${SAMPLE_CONVERSATION.length} chars\n`);

  const start = Date.now();
  const res = await fetch(API_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ticket_id: "test_001",
      conversation: SAMPLE_CONVERSATION,
    }),
  });
  const elapsed = Date.now() - start;

  const data = await res.json();
  console.log(`   Status: ${res.status} (${elapsed}ms)`);
  console.log(`   Correlation ID: ${data.correlation_id}`);
  console.log(`   Report ID: ${data.report_id}`);
  console.log(`   Score: ${data.total_score}`);
  console.log(`   Risk: ${data.risk_level}`);
  console.log(`   Sentiment: ${data.sentiment_score}`);
  console.log(`   Violations: ${data.violations_count}`);
  console.log(`   Needs Alert: ${data.needs_alert}`);

  if (data.error) {
    console.log(`   ERROR: ${data.error}`);
  }

  console.log("\n=== Done ===");
}

main().catch(console.error);
