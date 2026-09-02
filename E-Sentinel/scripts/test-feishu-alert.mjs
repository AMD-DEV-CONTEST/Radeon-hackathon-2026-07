/**
 * 飞书预警派发 E2E 测试
 * 启动: node scripts/test-feishu-alert.mjs
 */

const BASE = "http://localhost:3001/api/qa";

// 此对话包含多项严重违规：辱骂客户、虚假承诺、泄露内部信息
const BAD_CONVERSATION = `客服：您好，有什么问题？
客户：我昨天下的订单，付款成功了但到现在都没发货，怎么回事？
客服：急什么，我们又不是只有你一个客户，排队等着就行了。
客户：但是你们承诺的24小时内发货，现在已经过了。
客服：那个承诺你也信？都是广告而已，别太当真。
客户：你这是什么态度？我要投诉你！
客服：随便投诉，我们主管是我亲戚，你以为投诉有用吗？
客户：那你把你们公司的投诉电话给我。
客服：你没长眼睛吗？官网上有自己不会找？我还有别的客户，不跟你浪费时间了。
客户：我要退款！
客服：退款可以，你的银行卡号发过来，我把钱退你。`;

async function main() {
  console.log("=== Feishu Alert Dispatch Test ===\n");

  console.log("1. Submitting conversation with severe violations...");
  const start = Date.now();
  const res = await fetch(`${BASE}/evaluate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ticket_id: "feishu_test_001",
      agent_id: null, // 不提供 agent_id，测试无绑定客服场景
      conversation: BAD_CONVERSATION,
    }),
  });
  const data = await res.json();
  const elapsed = Date.now() - start;

  console.log(`   ${res.status} (${elapsed}ms)`);
  console.log(`   Report ID: ${data.report_id}`);
  console.log(`   Score: ${data.total_score}`);
  console.log(`   Risk: ${data.risk_level}`);
  console.log(`   Sentiment: ${data.sentiment_score}`);
  console.log(`   Violations: ${data.violations_count}`);
  console.log(`   Needs Alert: ${data.needs_alert}`);
  console.log(`   Alert Method: ${data.alert_method}`);
  console.log(`   Trace: ${data.correlation_id}`);

  if (data.alert_method !== "none") {
    console.log("\n   ✅ Feishu alert dispatched successfully!");
  } else if (data.needs_alert) {
    console.log("\n   ⚠️ Alert was needed but dispatch failed (check Feishu credentials)");
  } else {
    console.log("\n   ℹ️ Risk not high enough to trigger alert");
  }

  console.log("\n=== Done ===");
}

main().catch(console.error);
