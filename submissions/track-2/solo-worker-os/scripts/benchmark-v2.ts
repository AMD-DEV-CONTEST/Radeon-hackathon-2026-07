/**
 * Benchmark v2: Three-path latency comparison
 *
 * Path A: Direct Qwen API (no tools, no router — baseline LLM latency)
 * Path B: MTClaw Function Router (routing model → tool match or upstream)
 * Path C: Our app /api/chat (Subagent Router → Qwen + filtered tools)
 *
 * Measures end-to-end latency for each path across 6 scenarios.
 *
 * Usage:
 *   npx tsx scripts/benchmark-v2.ts
 */

const QWEN_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions';
const QWEN_MODEL = 'qwen3.7-plus';
const MTCLAW_URL = 'http://127.0.0.1:18790/v1/chat/completions';
const APP_URL = 'http://localhost:3000/api/chat';

function requireQwenKey(): string {
  const key = process.env.DASHSCOPE_API_KEY;
  if (!key) {
    throw new Error('DASHSCOPE_API_KEY is required to run this benchmark.');
  }
  return key;
}

const SCENARIOS = [
  { id: 'overview',  prompt: '给我一个业务概况',                         expectsTool: true  },
  { id: 'search',    prompt: '我的标准付款条款是什么？',                   expectsTool: true  },
  { id: 'list',      prompt: '列出所有项目',                              expectsTool: true  },
  { id: 'create',    prompt: '新客户周晨，企业官网改版，预算 12000 元，截止 8月30日，帮我创建项目', expectsTool: false },
  { id: 'chat',      prompt: '你好，今天天气怎么样？',                     expectsTool: false },
  { id: 'contract',  prompt: '为王浩的项目生成一份合同',                   expectsTool: false },
];

// ─── Path A: Direct Qwen (baseline, no tools) ────────────────────────────────

async function pathA_DirectQwen(prompt: string) {
  const start = Date.now();
  const resp = await fetch(QWEN_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${requireQwenKey()}` },
    body: JSON.stringify({ model: QWEN_MODEL, messages: [{ role: 'user', content: prompt }], stream: false }),
  });
  const data = await resp.json();
  return { latencyMs: Date.now() - start, ok: resp.ok, model: data.model ?? QWEN_MODEL };
}

// ─── Path B: MTClaw Function Router ──────────────────────────────────────────

async function pathB_Mtclaw(prompt: string) {
  const start = Date.now();
  const resp = await fetch(MTCLAW_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: QWEN_MODEL, messages: [{ role: 'user', content: prompt }], stream: false }),
  });
  const data = await resp.json();
  return {
    latencyMs: Date.now() - start,
    ok: resp.ok,
    routedByFR: data.model === 'function-router',
    model: data.model ?? 'unknown',
  };
}

// ─── Path C: Our app /api/chat (SSE stream, measure until 'done') ────────────

async function pathC_AppChat(prompt: string) {
  const start = Date.now();
  const resp = await fetch(APP_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages: [{ role: 'user', content: prompt }], persist: false }),
  });

  if (!resp.ok || !resp.body) {
    return { latencyMs: Date.now() - start, ok: false, route: 'error', toolCalled: false };
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let route = 'unknown';
  let toolCalled = false;
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
        if (evt.type === 'route' && evt.route) route = evt.route.subagent;
        if (evt.type === 'tool') toolCalled = true;
        if (evt.type === 'done') {
          return { latencyMs: Date.now() - start, ok: true, route, toolCalled };
        }
        if (evt.type === 'error') {
          return { latencyMs: Date.now() - start, ok: false, route, toolCalled, error: evt.message };
        }
      } catch { /* skip non-JSON */ }
    }
  }
  return { latencyMs: Date.now() - start, ok: true, route, toolCalled };
}

// ─── Main ────────────────────────────────────────────────────────────────────

async function main() {
  console.log('\n═══════════════════════════════════════════════════════════════');
  console.log('  Benchmark v2: Router vs No-Router Latency Comparison');
  console.log('  Date: ' + new Date().toISOString());
  console.log('═══════════════════════════════════════════════════════════════\n');

  const results: Array<Record<string, unknown>> = [];

  for (const s of SCENARIOS) {
    process.stdout.write(`▶ ${s.id.padEnd(12)}`);

    // Path A: Direct Qwen
    const a = await pathA_DirectQwen(s.prompt).catch(e => ({ latencyMs: -1, ok: false, error: e.message }));
    process.stdout.write(`  A:${a.latencyMs}ms`);

    // Path B: MTClaw
    const b = await pathB_Mtclaw(s.prompt).catch(e => ({ latencyMs: -1, ok: false, routedByFR: false, error: e.message }));
    process.stdout.write(`  B:${b.latencyMs}ms${b.routedByFR ? '(FR)' : ''}`);

    // Path C: App with Subagent Router
    const c = await pathC_AppChat(s.prompt).catch(e => ({ latencyMs: -1, ok: false, route: 'error', toolCalled: false, error: e.message }));
    process.stdout.write(`  C:${c.latencyMs}ms(${c.route})`);
    process.stdout.write('\n');

    results.push({
      scenario: s.id,
      prompt: s.prompt.substring(0, 40),
      expectsTool: s.expectsTool,
      directMs: a.latencyMs,
      mtclawMs: b.latencyMs,
      mtclawFR: b.routedByFR,
      appMs: c.latencyMs,
      appRoute: c.route,
      appTool: c.toolCalled,
    });
  }

  // ─── Summary table ───────────────────────────────────────────────────────
  console.log('\n═══════════════════════════════════════════════════════════════');
  console.log('  Summary Table');
  console.log('═══════════════════════════════════════════════════════════════\n');

  const fmt = (n: number) => n > 0 ? String(n).padStart(8) : '     N/A';
  console.log('Scenario      | Direct(Qwen) | MTClaw(FR?)  | App(Subagent) | MTClaw Speedup | App Speedup | App Route');
  console.log('─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────');

  for (const r of results) {
    const mtclawSp = r.directMs > 0 && r.mtclawMs > 0 ? `${(r.directMs / r.mtclawMs).toFixed(2)}x` : 'N/A';
    const appSp = r.directMs > 0 && r.appMs > 0 ? `${(r.directMs / r.appMs).toFixed(2)}x` : 'N/A';
    console.log(
      `${String(r.scenario).padEnd(12)} | ${fmt(r.directMs)} | ${fmt(r.mtclawMs)}${r.mtclawFR ? ' YES' : '  NO'} | ${fmt(r.appMs)} | ${mtclawSp.padEnd(15)} | ${appSp.padEnd(11)} | ${r.appRoute}`
    );
  }

  // ─── Averages ────────────────────────────────────────────────────────────
  const valid = results.filter(r => r.directMs > 0 && r.mtclawMs > 0);
  const toolMatched = valid.filter(r => r.mtclawFR);
  const toolMissed = valid.filter(r => !r.mtclawFR);

  if (valid.length) {
    const avgDirect = valid.reduce((s, r) => s + (r.directMs as number), 0) / valid.length;
    const avgMtclaw = valid.reduce((s, r) => s + (r.mtclawMs as number), 0) / valid.length;
    const avgApp = valid.reduce((s, r) => s + (r.appMs as number), 0) / valid.length;
    console.log('\n─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────');
    console.log(`Average Direct Qwen:          ${Math.round(avgDirect)}ms`);
    console.log(`Average MTClaw (all):         ${Math.round(avgMtclaw)}ms  (speedup: ${(avgDirect / avgMtclaw).toFixed(2)}x)`);
    console.log(`Average App (Subagent):       ${Math.round(avgApp)}ms  (speedup: ${(avgDirect / avgApp).toFixed(2)}x)`);
    if (toolMatched.length) {
      const avgFR = toolMatched.reduce((s, r) => s + (r.mtclawMs as number), 0) / toolMatched.length;
      const avgFRDirect = toolMatched.reduce((s, r) => s + (r.directMs as number), 0) / toolMatched.length;
      const avgFRApp = toolMatched.reduce((s, r) => s + (r.appMs as number), 0) / toolMatched.length;
      console.log(`Average MTClaw (tool matched): ${Math.round(avgFR)}ms  (${toolMatched.length}/${valid.length} matched, speedup: ${(avgFRDirect / avgFR).toFixed(2)}x)`);
      console.log(`Average App   (tool matched): ${Math.round(avgFRApp)}ms  (speedup: ${(avgFRDirect / avgFRApp).toFixed(2)}x)`);
    }
    if (toolMissed.length) {
      const avgNoFR = toolMissed.reduce((s, r) => s + (r.mtclawMs as number), 0) / toolMissed.length;
      console.log(`Average MTClaw (no tool match): ${Math.round(avgNoFR)}ms  (forwarded to upstream)`);
    }
  }

  console.log('\n✓ Benchmark complete.');
}

main().catch(console.error);
