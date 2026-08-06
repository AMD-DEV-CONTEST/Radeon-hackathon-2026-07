/**
 * Benchmark: General QA Quality Comparison
 *
 * 验证"通用 Benchmark 不退化"——加了 Subagent 架构后，处理不属于
 * 任何专业场景的普通请求时质量不能下降。
 *
 * 本脚本对每条通用问题走两条路径并对比：
 *   Path A: 直接调 Qwen API（无工具、无 Subagent、无系统提示）— 纯 LLM 回答
 *   Path B: 通过 /api/chat 端点（走 Subagent Router + 系统提示 + 工具过滤）— 完整 Agent 链路
 *
 * 对比维度：
 *   - 回答内容（前 200 字符）
 *   - 路由到的 Subagent
 *   - 统计：Subagent 分布、平均回答长度、路由正确率
 *
 * Usage:
 *   npx tsx scripts/benchmark-quality.ts
 */

// ─── Configuration ─────────────────────────────────────────────────────────────

const QWEN_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions';
const QWEN_MODEL = 'qwen3.7-plus';
const APP_URL = 'http://localhost:3000/api/chat';

function requireQwenKey(): string {
  const key = process.env.DASHSCOPE_API_KEY;
  if (!key) {
    throw new Error('DASHSCOPE_API_KEY is required to run this benchmark.');
  }
  return key;
}

/** 通用问题：不应触发任何专业 Subagent（knowledge_rag / data_analysis / writing_assistant）。 */
const GENERAL_QUESTIONS: { id: string; question: string; lang: 'en' | 'zh' }[] = [
  { id: 'q01', question: 'What is 2+2?',                                            lang: 'en' },
  { id: 'q02', question: 'Tell me a joke',                                          lang: 'en' },
  { id: 'q03', question: "What's the weather like?",                lang: 'en' },
  { id: 'q04', question: 'How do I learn programming?',                             lang: 'en' },
  { id: 'q05', question: 'What is artificial intelligence?',                        lang: 'en' },
  { id: 'q06', question: '1加1等于几？',                                             lang: 'zh' },
  { id: 'q07', question: '给我讲个笑话',                                             lang: 'zh' },
  { id: 'q08', question: '什么是机器学习？',                                         lang: 'zh' },
  { id: 'q09', question: 'Explain what a black hole is',                            lang: 'en' },
  { id: 'q10', question: 'How to cook pasta?',                                     lang: 'en' },
  { id: 'q11', question: 'What are some good books to read?',                       lang: 'en' },
  { id: 'q12', question: '地球到月球有多远？',                                       lang: 'zh' },
  { id: 'q13', question: 'What is the meaning of life?',                           lang: 'en' },
  { id: 'q14', question: '推荐几首好听的歌',                                         lang: 'zh' },
  { id: 'q15', question: 'Can you explain recursion in simple terms?',             lang: 'en' },
];

/** 这些 Subagent 被视为"通用路由"——不触发专业工具链。 */
const ACCEPTABLE_SUBAGENTS = new Set(['general', 'quick_chat']);

/** 专业 Subagent——若路由到这里说明路由退化。 */
const SPECIALIZED_SUBAGENTS = ['knowledge_rag', 'data_analysis', 'writing_assistant', 'blockchain'];

// ─── Path A: Direct Qwen API (pure LLM, no tools, no system prompt) ───────────

interface PathAResult {
  ok: boolean;
  response: string;
  latencyMs: number;
  error?: string;
}

async function pathA_DirectQwen(prompt: string): Promise<PathAResult> {
  const start = Date.now();
  const resp = await fetch(QWEN_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${requireQwenKey()}`,
    },
    body: JSON.stringify({
      model: QWEN_MODEL,
      messages: [{ role: 'user', content: prompt }],
      stream: false,
    }),
  });

  if (!resp.ok) {
    const errText = await resp.text().catch(() => 'unknown');
    return { ok: false, response: '', latencyMs: Date.now() - start, error: `HTTP ${resp.status}: ${errText}` };
  }

  const data = await resp.json();
  const content = data.choices?.[0]?.message?.content ?? '';
  return { ok: true, response: content, latencyMs: Date.now() - start };
}

// ─── Path B: Through /api/chat (Subagent Router + system prompt + tools) ───────

interface PathBResult {
  ok: boolean;
  response: string;
  subagent: string;
  routedBy: string;
  confidence: number;
  latencyMs: number;
  error?: string;
}

async function pathB_AppChat(prompt: string): Promise<PathBResult> {
  const start = Date.now();
  const resp = await fetch(APP_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      messages: [{ role: 'user', content: prompt }],
      persist: false,
    }),
  });

  if (!resp.ok || !resp.body) {
    const errText = await resp.text().catch(() => 'unknown');
    return {
      ok: false,
      response: '',
      subagent: 'error',
      routedBy: 'error',
      confidence: 0,
      latencyMs: Date.now() - start,
      error: `HTTP ${resp.status}: ${errText}`,
    };
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let fullText = '';
  let subagent = 'unknown';
  let routedBy = 'unknown';
  let confidence = 0;
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      try {
        const evt = JSON.parse(line.slice(6));
        if (evt.type === 'route' && evt.route) {
          subagent = evt.route.subagent ?? 'unknown';
          routedBy = evt.route.routedBy ?? 'unknown';
          confidence = evt.route.confidence ?? 0;
        }
        if (evt.type === 'text' && evt.delta) {
          fullText += evt.delta;
        }
        if (evt.type === 'done') {
          return { ok: true, response: fullText, subagent, routedBy, confidence, latencyMs: Date.now() - start };
        }
        if (evt.type === 'error') {
          return {
            ok: false,
            response: fullText,
            subagent,
            routedBy,
            confidence,
            latencyMs: Date.now() - start,
            error: evt.message ?? 'Unknown error',
          };
        }
      } catch {
        /* skip non-JSON */
      }
    }
  }

  return { ok: true, response: fullText, subagent, routedBy, confidence, latencyMs: Date.now() - start };
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

/** Truncate text to N characters, normalizing whitespace for display. */
function truncate(text: string, max = 200): string {
  const cleaned = text.replace(/\s+/g, ' ').trim();
  if (cleaned.length <= max) return cleaned;
  return cleaned.slice(0, max) + '…';
}

/** Pad a string to a fixed width, truncating if necessary. */
function pad(str: string, width: number): string {
  const s = String(str);
  if (s.length > width) return s.slice(0, width - 1) + '…';
  return s.padEnd(width);
}

// ─── Main ─────────────────────────────────────────────────────────────────────

interface QuestionResult {
  id: string;
  question: string;
  lang: string;
  pathA_ok: boolean;
  pathA_response: string;
  pathA_latencyMs: number;
  pathB_ok: boolean;
  pathB_response: string;
  pathB_subagent: string;
  pathB_routedBy: string;
  pathB_confidence: number;
  pathB_latencyMs: number;
  pathB_error?: string;
}

async function main() {
  console.log('\n═════════════════════════════════════════════════════════════════════');
  console.log('  Benchmark: General QA Quality Comparison');
  console.log('  通用 Benchmark 不退化测试 — Subagent 架构 vs 纯 LLM');
  console.log('  Date: ' + new Date().toISOString());
  console.log('═════════════════════════════════════════════════════════════════════\n');
  console.log(`  Questions: ${GENERAL_QUESTIONS.length}`);
  console.log(`  Path A:    Direct Qwen API (no tools, no Subagent, no system prompt)`);
  console.log(`  Path B:    /api/chat (Subagent Router + system prompt + tool filtering)`);
  console.log(`  Qwen Model: ${QWEN_MODEL}`);
  console.log(`  App URL:    ${APP_URL}`);
  console.log('');

  const results: QuestionResult[] = [];

  for (const q of GENERAL_QUESTIONS) {
    process.stdout.write(`▶ [${q.id}] ${truncate(q.question, 50)}  `);

    // Path A: Direct Qwen
    const a = await pathA_DirectQwen(q.question).catch((e) => ({
      ok: false,
      response: '',
      latencyMs: -1,
      error: e.message,
    } as PathAResult));
    process.stdout.write(`A:${a.ok ? a.latencyMs + 'ms' : 'FAIL'}  `);

    // Path B: App /api/chat
    const b = await pathB_AppChat(q.question).catch((e) => ({
      ok: false,
      response: '',
      subagent: 'error',
      routedBy: 'error',
      confidence: 0,
      latencyMs: -1,
      error: e.message,
    } as PathBResult));
    process.stdout.write(`B:${b.ok ? b.latencyMs + 'ms' : 'FAIL'} (${b.subagent})\n`);

    results.push({
      id: q.id,
      question: q.question,
      lang: q.lang,
      pathA_ok: a.ok,
      pathA_response: a.response,
      pathA_latencyMs: a.latencyMs,
      pathB_ok: b.ok,
      pathB_response: b.response,
      pathB_subagent: b.subagent,
      pathB_routedBy: b.routedBy,
      pathB_confidence: b.confidence,
      pathB_latencyMs: b.latencyMs,
      pathB_error: b.error,
    });
  }

  // ─── Per-Question Comparison ───────────────────────────────────────────────
  console.log('\n═════════════════════════════════════════════════════════════════════');
  console.log('  Per-Question Comparison (response preview: first 200 chars)');
  console.log('═════════════════════════════════════════════════════════════════════\n');

  for (const r of results) {
    console.log(`┌─ ${r.id} [${r.lang.toUpperCase()}] ${truncate(r.question, 70)}`);
    console.log(`│`);
    console.log(`│  Path A (Direct Qwen)  [${r.pathA_ok ? r.pathA_latencyMs + 'ms' : 'ERROR'}]`);
    console.log(`│  ${truncate(r.pathA_response, 200)}`);
    console.log(`│`);
    console.log(`│  Path B (/api/chat)    [${r.pathB_ok ? r.pathB_latencyMs + 'ms' : 'ERROR'}]`);
    console.log(`│  Subagent: ${r.pathB_subagent}  (routedBy: ${r.pathB_routedBy}, conf: ${Math.round(r.pathB_confidence * 100)}%)`);
    console.log(`│  ${truncate(r.pathB_response, 200)}`);
    if (r.pathB_error) {
      console.log(`│  ERROR: ${r.pathB_error}`);
    }
    console.log(`└${'─'.repeat(78)}\n`);
  }

  // ─── Summary Table ─────────────────────────────────────────────────────────
  console.log('═════════════════════════════════════════════════════════════════════');
  console.log('  Summary Table');
  console.log('═════════════════════════════════════════════════════════════════════\n');

  console.log(
    `${pad('ID', 6)} | ${pad('Question', 42)} | ${pad('A Len', 7)} | ${pad('B Len', 7)} | ${pad('Subagent', 18)} | ${pad('RoutedBy', 10)} | ${pad('Correct?', 9)}`
  );
  console.log(`${'─'.repeat(6)}─┼─${'─'.repeat(42)}─┼─${'─'.repeat(7)}─┼─${'─'.repeat(7)}─┼─${'─'.repeat(18)}─┼─${'─'.repeat(10)}─┼─${'─'.repeat(9)}`);

  for (const r of results) {
    const aLen = r.pathA_response.length;
    const bLen = r.pathB_response.length;
    const isCorrect = ACCEPTABLE_SUBAGENTS.has(r.pathB_subagent);
    console.log(
      `${pad(r.id, 6)} | ${pad(truncate(r.question, 42), 42)} | ${pad(String(aLen), 7)} | ${pad(String(bLen), 7)} | ${pad(r.pathB_subagent, 18)} | ${pad(r.pathB_routedBy, 10)} | ${isCorrect ? '  OK' : '  WRONG'}`
    );
  }

  // ─── Statistics ────────────────────────────────────────────────────────────
  console.log('\n═════════════════════════════════════════════════════════════════════');
  console.log('  Statistics');
  console.log('═════════════════════════════════════════════════════════════════════\n');

  // 1. Subagent distribution
  console.log('── Subagent Distribution ──');
  const subagentCounts = new Map<string, number>();
  for (const r of results) {
    subagentCounts.set(r.pathB_subagent, (subagentCounts.get(r.pathB_subagent) ?? 0) + 1);
  }
  for (const [sub, count] of [...subagentCounts.entries()].sort((a, b) => b[1] - a[1])) {
    const pct = ((count / results.length) * 100).toFixed(1);
    const bar = '█'.repeat(Math.round((count / results.length) * 20));
    console.log(`  ${pad(sub, 18)}  ${String(count).padStart(2)}/${results.length}  (${pct}%)  ${bar}`);
  }

  // 2. Routing correctness
  console.log('\n── Routing Correctness ──');
  const correctCount = results.filter((r) => ACCEPTABLE_SUBAGENTS.has(r.pathB_subagent)).length;
  const wrongCount = results.length - correctCount;
  const correctRate = ((correctCount / results.length) * 100).toFixed(1);
  console.log(`  Correct (general/quick_chat):  ${correctCount}/${results.length}  (${correctRate}%)`);
  console.log(`  Wrong  (specialized):          ${wrongCount}/${results.length}  (${(100 - parseFloat(correctRate)).toFixed(1)}%)`);

  if (wrongCount > 0) {
    console.log('\n  Mis-routed questions:');
    for (const r of results) {
      if (!ACCEPTABLE_SUBAGENTS.has(r.pathB_subagent)) {
        console.log(`    [${r.id}] "${truncate(r.question, 50)}" → ${r.pathB_subagent}`);
      }
    }
  }

  // 3. Average response length
  console.log('\n── Average Response Length ──');
  const validA = results.filter((r) => r.pathA_ok && r.pathA_response.length > 0);
  const validB = results.filter((r) => r.pathB_ok && r.pathB_response.length > 0);
  if (validA.length) {
    const avgA = Math.round(validA.reduce((s, r) => s + r.pathA_response.length, 0) / validA.length);
    console.log(`  Path A (Direct Qwen):  ${avgA} chars  (n=${validA.length})`);
  }
  if (validB.length) {
    const avgB = Math.round(validB.reduce((s, r) => s + r.pathB_response.length, 0) / validB.length);
    console.log(`  Path B (/api/chat):    ${avgB} chars  (n=${validB.length})`);
  }
  if (validA.length && validB.length) {
    const avgA = validA.reduce((s, r) => s + r.pathA_response.length, 0) / validA.length;
    const avgB = validB.reduce((s, r) => s + r.pathB_response.length, 0) / validB.length;
    const diff = avgB - avgA;
    const diffPct = ((diff / avgA) * 100).toFixed(1);
    console.log(`  Difference:            ${diff > 0 ? '+' : ''}${Math.round(diff)} chars  (${diff > 0 ? '+' : ''}${diffPct}%)`);
  }

  // 4. Average latency
  console.log('\n── Average Latency ──');
  if (validA.length) {
    const avgLatA = Math.round(validA.reduce((s, r) => s + r.pathA_latencyMs, 0) / validA.length);
    console.log(`  Path A (Direct Qwen):  ${avgLatA}ms`);
  }
  if (validB.length) {
    const avgLatB = Math.round(validB.reduce((s, r) => s + r.pathB_latencyMs, 0) / validB.length);
    console.log(`  Path B (/api/chat):    ${avgLatB}ms`);
  }

  // 5. RoutedBy distribution
  console.log('\n── RoutedBy Distribution ──');
  const routedByCounts = new Map<string, number>();
  for (const r of results) {
    routedByCounts.set(r.pathB_routedBy, (routedByCounts.get(r.pathB_routedBy) ?? 0) + 1);
  }
  for (const [by, count] of [...routedByCounts.entries()].sort((a, b) => b[1] - a[1])) {
    const pct = ((count / results.length) * 100).toFixed(1);
    console.log(`  ${pad(by, 12)}  ${String(count).padStart(2)}/${results.length}  (${pct}%)`);
  }

  console.log('\n═════════════════════════════════════════════════════════════════════');
  console.log('  Benchmark complete.');
  console.log('  Review the per-question comparison above for quality assessment.');
  console.log('  Key metric: routing correctness should be 100% for general questions.');
  console.log('═════════════════════════════════════════════════════════════════════\n');
}

main().catch(console.error);
