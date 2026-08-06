/**
 * 重试造数 — 低并发 + 长间隔，避免 Moonshot 限流
 * 启动: node scripts/retry-seed.mjs
 */

const BASE_URL = process.env.BASE_URL || "http://localhost:3001";
const MOONSHOT_KEY = process.env.MOONSHOT_API_KEY;
const MOONSHOT_URL =
  process.env.MOONSHOT_API_URL || "https://api.moonshot.cn/v1/chat/completions";

const PRODUCTS = [
  "华为 Mate 70 Pro 512GB",
  "Adidas Ultraboost 22 跑步鞋",
  "美的 洗碗机 14套 嵌入式",
  "海蓝之谜 精粹水 150ml",
  "格力 空调 大1.5匹 变频",
  "Switch OLED 马力欧红蓝",
];

function pick(arr) {
  return arr[Math.floor(Math.random() * arr.length)];
}

const GENERATOR_PROMPT = `你是一个电商客服对话数据生成器。请生成一个包含 20 个对象的 JSON 数组。

【商品池】${PRODUCTS.join("、")}

【分布要求】
- 5 条（25%）：正常服务对话。客服态度良好，问题得到妥善解决。
- 5 条（25%）：轻微服务瑕疵。客服语气冷淡、推诿。情绪略不满。
- 10 条（50%）：高危或中等违规对话。包含辱骂/讽刺客户、虚假承诺、拒绝合理退款、敷衍威胁。情绪愤怒。

【要求】
- 对话长度 4-8 轮，中国大陆电商口语。
- 每条对话必须包含具体的商品名、订单号或退款金额等真实细节。
- 严禁雷同！

【格式】
{ "conversation": "客服：...\\n客户：...", "agent_name": "从['张建国','王五','孙七','李六']中选", "expected_risk": "low|medium|high|critical" }

严格输出纯 JSON 数组，首字符 [，尾字符 ]。`;

function randomTimestamp(daysBack) {
  const now = Date.now();
  const past = now - daysBack * 86400000;
  return new Date(past + Math.random() * (now - past)).toISOString();
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function main() {
  if (!MOONSHOT_KEY) {
    throw new Error("MOONSHOT_API_KEY is required; refusing to call the provider without an explicit secret.");
  }
  console.log("=== Retry Seed (low concurrency) ===\n");

  // Step 1: Generate
  console.log("[Retry] Generating 20 conversations...");
  const res = await fetch(MOONSHOT_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${MOONSHOT_KEY}`,
    },
    body: JSON.stringify({
      model: "moonshot-v1-128k",
      messages: [
        { role: "system", content: GENERATOR_PROMPT },
        { role: "user", content: "请生成 20 条电商客服对话数据。" },
      ],
      temperature: 0.85,
      max_tokens: 8192,
    }),
  });

  const data = await res.json();
  const content = data.choices?.[0]?.message?.content || "";
  let conversations;
  try {
    conversations = JSON.parse(content);
  } catch {
    const match = content.match(/\[[\s\S]*\]/);
    conversations = match ? JSON.parse(match[0]) : [];
  }
  console.log(`[Retry] Generated ${conversations.length} conversations\n`);

  // Step 2: Evaluate one at a time with 3s delay
  let success = 0;
  let fail = 0;

  for (let i = 0; i < conversations.length; i++) {
    const item = conversations[i];
    const idx = i + 1;

    try {
      const evalRes = await fetch(`${BASE_URL}/api/qa/evaluate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ticket_id: `retry_${Date.now()}_${i}`,
          conversation: item.conversation,
          skip_feishu: true,
          created_at: randomTimestamp(7),
        }),
      });
      const evalData = await evalRes.json();

      if (evalRes.ok && evalData.report_id) {
        success++;
        process.stdout.write(`\r  ${idx}/${conversations.length} ✓ score=${evalData.total_score} risk=${evalData.risk_level}    `);
      } else {
        fail++;
        process.stdout.write(`\r  ${idx}/${conversations.length} ✗ ${evalRes.status}                             `);
      }
    } catch (err) {
      fail++;
      process.stdout.write(`\r  ${idx}/${conversations.length} ✗ ${err.message}                             `);
    }

    // 3 秒间隔，彻底避免限流
    if (i < conversations.length - 1) await sleep(3000);
  }

  console.log(`\n\n[Retry] Done! ${success} success, ${fail} failed`);
}

main().catch(console.error);
