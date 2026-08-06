/**
 * Stress test for the QA system Edge Function.
 * Sends simulated Feishu messages in batches and measures response.
 * Usage: npx tsx scripts/stress-test.ts [count] [concurrency]
 */
const COUNT = parseInt(process.argv[2] || "50", 10);
const CONCURRENCY = parseInt(process.argv[3] || "5", 10);
const EDGE_URL = process.env.EDGE_URL ?? "";
if (!EDGE_URL) throw new Error("EDGE_URL is required (stress test target)");
const CHAT_ID = process.env.CHAT_ID || "oc_test_stress";

const TEST_MESSAGES = [
  "我的订单什么时候发货？",
  "这个摄像头能看多远？",
  "帮我查一下物流单号7512345678",
  "你们支持7天无理由退货吗？",
  "这个产品有什么优惠吗？",
  "昨天买的怎么还没发货？",
  "你们客服电话多少？",
  "质保多久？坏了怎么办？",
  "能不能便宜点？",
  "我要退货，怎么操作？",
];

function getRandomMessage(): string {
  return TEST_MESSAGES[Math.floor(Math.random() * TEST_MESSAGES.length)];
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

interface TestResult {
  index: number;
  status: number;
  duration: number;
  error?: string;
}

async function sendOne(index: number): Promise<TestResult> {
  const start = performance.now();
  try {
    const body = JSON.stringify({
      schema: "2.0",
      header: { event_id: `stress_${Date.now()}_${index}`, event_type: "im.message.receive_v1" },
      event: {
        message: {
          chat_id: CHAT_ID,
          message_type: "text",
          content: JSON.stringify({ text: getRandomMessage() }),
        },
        sender: { sender_id: { open_id: "stress_test_user" } },
      },
    });

    const res = await fetch(EDGE_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });

    return {
      index,
      status: res.status,
      duration: Math.round(performance.now() - start),
      error: res.ok ? undefined : `HTTP ${res.status}: ${await res.text().catch(() => "")}`,
    };
  } catch (err) {
    return {
      index,
      status: 0,
      duration: Math.round(performance.now() - start),
      error: err instanceof Error ? err.message : String(err),
    };
  }
}

async function runBatch(startIdx: number, count: number): Promise<TestResult[]> {
  const tasks = Array.from({ length: count }, (_, i) => sendOne(startIdx + i));
  return Promise.all(tasks);
}

async function main() {
  console.log(`\n🔥 压力测试开始`);
  console.log(`─────────────────────────────`);
  console.log(`总请求数: ${COUNT}`);
  console.log(`并发数:   ${CONCURRENCY}`);
  console.log(`目标 URL: ${EDGE_URL}`);
  console.log(`─────────────────────────────\n`);

  const allResults: TestResult[] = [];
  const startTime = performance.now();
  let completed = 0;

  for (let i = 0; i < COUNT; i += CONCURRENCY) {
    const batchSize = Math.min(CONCURRENCY, COUNT - i);
    const results = await runBatch(i, batchSize);
    allResults.push(...results);
    completed += batchSize;
    process.stdout.write(`\r  进度: ${completed}/${COUNT} (${Math.round(completed / COUNT * 100)}%)`);
  }
  console.log("\n");

  const totalTime = Math.round(performance.now() - startTime);

  // Stats
  const successResults = allResults.filter((r) => r.status === 200);
  const failedResults = allResults.filter((r) => r.status !== 200 && r.status !== 0);
  const timeoutResults = allResults.filter((r) => r.status === 0);
  const durations = successResults.map((r) => r.duration).sort((a, b) => a - b);

  console.log(`📊 测试结果`);
  console.log(`─────────────────────────────`);
  console.log(`总耗时:         ${formatDuration(totalTime)}`);
  console.log(`总请求:         ${COUNT}`);
  console.log(`成功 (200):     ${successResults.length} (${Math.round(successResults.length / COUNT * 100)}%)`);
  console.log(`失败 (HTTP错误): ${failedResults.length}`);
  console.log(`超时/网络错误:   ${timeoutResults.length}`);
  console.log(`─────────────────────────────`);

  if (durations.length > 0) {
    const avg = Math.round(durations.reduce((a, b) => a + b, 0) / durations.length);
    const p50 = durations[Math.floor(durations.length * 0.5)];
    const p90 = durations[Math.floor(durations.length * 0.9)];
    const p99 = durations[Math.floor(durations.length * 0.99)];
    const min = durations[0];
    const max = durations[durations.length - 1];

    console.log(`⏱️  响应时间 (成功请求)`);
    console.log(`─────────────────────────────`);
    console.log(`平均:  ${formatDuration(avg)}`);
    console.log(`最小:  ${formatDuration(min)}`);
    console.log(`最大:  ${formatDuration(max)}`);
    console.log(`P50:   ${formatDuration(p50)}`);
    console.log(`P90:   ${formatDuration(p90)}`);
    console.log(`P99:   ${formatDuration(p99)}`);
    console.log(`─────────────────────────────`);
  }

  if (failedResults.length > 0) {
    console.log(`\n❌ 失败详情:`);
    failedResults.slice(0, 10).forEach((r) => {
      console.log(`  #${r.index}: ${r.error} (${formatDuration(r.duration)})`);
    });
    if (failedResults.length > 10) {
      console.log(`  ... 还有 ${failedResults.length - 10} 条`);
    }
  }

  // Verdict
  const successRate = successResults.length / COUNT;
  console.log(`\n${"═".repeat(30)}`);
  if (successRate >= 0.95) {
    console.log(`✅ 压力测试通过 — 成功率 ${Math.round(successRate * 100)}%`);
  } else if (successRate >= 0.8) {
    console.log(`⚠️  压力测试部分通过 — 成功率 ${Math.round(successRate * 100)}%，需要关注`);
  } else {
    console.log(`❌ 压力测试失败 — 成功率仅 ${Math.round(successRate * 100)}%`);
  }
  console.log(`${"═".repeat(30)}\n`);
}

main().catch(console.error);
