/**
 * E-Sentinel 造数引擎
 * 生成 50 条时间跨度 7 天的模拟客服对话 → 批量质检 → 灌入 Supabase
 *
 * 启动: node scripts/seed-mock-data.mjs
 * 环境变量: MOONSHOT_API_KEY, NEXT_PUBLIC_SUPABASE_URL (可选)
 */

const BASE_URL = process.env.BASE_URL || "http://localhost:3001";
const MOONSHOT_KEY = process.env.MOONSHOT_API_KEY;
const MOONSHOT_URL =
  process.env.MOONSHOT_API_URL || "https://api.moonshot.cn/v1/chat/completions";

// ── 随机电商参数 ──────────────────────────────────────
const PRODUCTS = [
  "iPhone 16 Pro Max 256GB 沙漠金",
  "Nike Air Force 1 '07 白色低帮",
  "戴森 V15 Detect 无绳吸尘器",
  "SK-II 神仙水 230ml 限量版",
  "海尔 3匹 一级能效 立式空调",
  "乐高 兰博基尼 Sián 机械组 42115",
  "茅台 53度 飞天 500ml",
  "小米 14 Ultra 12+256GB 陶瓷白",
  "YSL 小金条 1966 号哑光口红",
  "骆驼 户外冲锋衣 三合一 男款",
];
const SKUS = ["A", "B", "C", "D", "E"];
const ORDER_PREFIXES = ["DD", "TB", "JD", "PDD", "DY"];
const CITIES = ["杭州", "深圳", "北京", "广州", "成都", "武汉", "南京", "重庆"];
const PRICES = [29.9, 59, 89, 128, 199, 249, 358, 499, 699, 899, 1299, 2599, 3999, 5999, 8999];

function pick(arr) { return arr[Math.floor(Math.random() * arr.length)]; }
function orderNo() { return `${pick(ORDER_PREFIXES)}${Date.now().toString(36).toUpperCase()}${Math.floor(Math.random() * 10000)}`; }

// 预先打乱产品列表，让对话不重复
const shuffledProducts = [...PRODUCTS].sort(() => Math.random() - 0.5);

// ── 造数 Prompt ──────────────────────────────────────────
const GENERATOR_PROMPT = `你是一个电商客服对话数据生成器。请生成一个包含 50 个对象的 JSON 数组。

【产品与订单信息】
请为每条对话随机选择以下真实电商参数注入到对话中，让对话显得非常真实：
- 商品：${shuffledProducts.slice(0, 8).join("、")} 等
- 品牌：Apple、Nike、Dyson、SK-II、海尔、乐高、茅台、小米、YSL、骆驼
- 场景：天猫旗舰店、京东自营、拼多多、抖音直播间、小程序商城
- 细节要求：70% 的对话中要自然出现订单号（如 DD2405XXX）、具体退款金额（如 89.9 元）、物流状态（已揽收/运输中/已签收）、优惠券/满减、会员等级等电商真实细节。

【分布要求】
- 30 条（60%）：正常服务对话。客服态度良好，问题得到妥善解决。情绪平静。
- 10 条（20%）：轻微服务瑕疵。客服语气略显冷淡、推诿，但未触及红线。情绪略不满。
- 10 条（20%）：高危违规对话。包含以下至少一种：辱骂/讽刺客户、虚假承诺、泄露内部信息、拒绝合理退款、敷衍威胁。情绪愤怒或极其愤怒。

【每条对话格式】
{
  "conversation": "客服：...\\n客户：...\\n客服：...\\n客户：...",
  "agent_name": "从['张建国','王五','孙七','李六']中随机选一个",
  "expected_risk": "low|medium|high|critical"
}

对话长度 4-8 轮，使用中国大陆电商场景口语。客服和客户各一句交替。
严禁出现雷同对话！每条对话的商品、问题、情绪都必须不同。

严格输出纯 JSON 数组，首字符必须是 [，尾字符必须是 ]。不要包裹 markdown 代码块。`;

async function generateConversations() {
  if (!MOONSHOT_KEY) {
    throw new Error("MOONSHOT_API_KEY is required; refusing to call the provider without an explicit secret.");
  }
  console.log("[Seed] Generating 50 conversations via Moonshot...");

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
        { role: "user", content: "请生成 50 条电商客服对话数据。" },
      ],
      temperature: 0.8,
      max_tokens: 16384,
    }),
  });

  const data = await res.json();
  const content = data.choices?.[0]?.message?.content || "";

  // Parse JSON array
  let parsed;
  try {
    parsed = JSON.parse(content);
  } catch {
    const match = content.match(/\[[\s\S]*\]/);
    if (match) {
      try {
        parsed = JSON.parse(match[0]);
      } catch {
        console.error("[Seed] Failed to parse Moonshot output");
        console.error(content.slice(0, 500));
        return [];
      }
    }
  }

  if (!Array.isArray(parsed)) {
    console.error("[Seed] Output is not an array");
    return [];
  }

  return parsed;
}

function randomTimestamp(daysBack) {
  const now = Date.now();
  const past = now - daysBack * 86400000;
  return new Date(past + Math.random() * (now - past)).toISOString();
}

async function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function main() {
  console.log("=== E-Sentinel Seed Engine ===\n");

  // Step 1: Generate conversations
  let conversations;
  try {
    conversations = await generateConversations();
  } catch (err) {
    console.error("[Seed] Generation failed:", err.message);
    return;
  }

  if (!conversations || conversations.length === 0) {
    console.error("[Seed] No conversations generated");
    return;
  }

  console.log(`[Seed] Generated ${conversations.length} conversations\n`);

  // Step 2: Add timestamps + agent binding
  const enriched = conversations.map((c, i) => ({
    ...c,
    ticket_id: `seed_${Date.now()}_${i}`,
    created_at: randomTimestamp(7),
  }));

  // Step 3: Batch evaluate (concurrency = 3, no Feishu)
  console.log("[Seed] Starting batch evaluation (concurrency=3)...");
  let success = 0;
  let fail = 0;
  const batchSize = 3;

  for (let i = 0; i < enriched.length; i += batchSize) {
    const batch = enriched.slice(i, i + batchSize);
    const results = await Promise.allSettled(
      batch.map(async (item, bi) => {
        const idx = i + bi + 1;
        const res = await fetch(`${BASE_URL}/api/qa/evaluate`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ticket_id: item.ticket_id,
            conversation: item.conversation,
            skip_feishu: true,
            created_at: item.created_at, // 时间穿梭：分散在近 7 天
          }),
        });
        const data = await res.json();
        return { idx, status: res.status, reportId: data.report_id, score: data.total_score };
      })
    );

    for (const r of results) {
      if (r.status === "fulfilled" && r.value.status === 200) {
        success++;
      } else {
        fail++;
        const errInfo = r.status === "fulfilled" ? r.value : r.reason;
        console.error(`  FAIL #${r.status === "fulfilled" ? r.value.idx : "?"}:`, errInfo);
      }
    }

    process.stdout.write(`\r  Progress: ${Math.min(i + batchSize, enriched.length)}/${enriched.length}  ✓${success} ✗${fail}`);
    if (i + batchSize < enriched.length) await sleep(500); // rate limit
  }

  console.log(`\n\n[Seed] Done! ${success} success, ${fail} failed`);
  console.log(`[Seed] Dashboard: ${BASE_URL}/dashboard`);
}

main().catch(console.error);
