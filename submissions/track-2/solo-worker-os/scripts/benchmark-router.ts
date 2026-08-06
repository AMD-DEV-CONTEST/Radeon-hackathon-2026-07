/**
 * Benchmark: Router vs No-Router Latency Comparison
 *
 * Measures two paths:
 *   A) Direct to Qwen API (no MTClaw, no Subagent routing)
 *   B) Through MTClaw Function Router (tool match → fast path, no LLM)
 *   C) Through our app's Subagent Router → Qwen (keyword routing + tool filter)
 *
 * Outputs a comparison table for performance analysis.
 *
 * Usage:
 *   npx tsx scripts/benchmark-router.ts
 */

import { createServiceClient } from '@/lib/supabase-server';
import { getAgent } from '@/lib/agent';
import { buildSystemPrompt } from '@/lib/agent/prompt';
import { routeMessageSync, getRoutedTools } from '@/lib/agent/router';
import { getToolSpecsForMode, executeToolForMode } from '@/lib/tools';
import { todayISO } from '@/lib/utils';

// ─── Benchmark scenarios ─────────────────────────────────────────────────────

interface BenchScenario {
  id: string;
  prompt: string;
  domain: string;
  /** Whether MTClaw should match a custom tool for this prompt */
  expectsMtclawTool: boolean;
}

const SCENARIOS: BenchScenario[] = [
  {
    id: 'overview',
    prompt: 'Give me a business overview',
    domain: 'data_analysis',
    expectsMtclawTool: true,
  },
  {
    id: 'search',
    prompt: 'What are my standard payment terms?',
    domain: 'knowledge_rag',
    expectsMtclawTool: true,
  },
  {
    id: 'list',
    prompt: 'List all my projects',
    domain: 'general',
    expectsMtclawTool: true,
  },
  {
    id: 'create',
    prompt: 'Create a new project for John Smith, website design, budget 5000 USD, deadline 2026-08-30',
    domain: 'general',
    expectsMtclawTool: false,
  },
  {
    id: 'chat',
    prompt: 'Hello, how are you?',
    domain: 'quick_chat',
    expectsMtclawTool: false,
  },
  {
    id: 'contract',
    prompt: 'Generate a contract for Marcus Rivera',
    domain: 'writing_assistant',
    expectsMtclawTool: false,
  },
];

// ─── Path A: Direct Qwen (no router, no tools) ──────────────────────────────

async function benchDirectQwen(prompt: string): Promise<{ latencyMs: number; response: string }> {
  const start = Date.now();
  const resp = await fetch('https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${process.env.DASHSCOPE_API_KEY}`,
    },
    body: JSON.stringify({
      model: process.env.QWEN_MODEL ?? 'qwen-plus',
      messages: [{ role: 'user', content: prompt }],
      stream: false,
    }),
  });
  const data = await resp.json();
  const latencyMs = Date.now() - start;
  const response = data.choices?.[0]?.message?.content ?? '(no response)';
  return { latencyMs, response: response.substring(0, 200) };
}

// ─── Path B: MTClaw Function Router (may match custom tools) ─────────────────

async function benchMtclaw(prompt: string): Promise<{ latencyMs: number; response: string; routedTool: boolean }> {
  const start = Date.now();
  const resp = await fetch('http://127.0.0.1:18790/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      model: 'qwen3.7-plus',
      messages: [{ role: 'user', content: prompt }],
      stream: false,
    }),
  });
  const data = await resp.json();
  const latencyMs = Date.now() - start;
  const response = data.choices?.[0]?.message?.content ?? '(no response)';
  const routedTool = data.model === 'function-router';
  return { latencyMs, response: response.substring(0, 200), routedTool };
}

// ─── Path C: Our Subagent Router → Qwen ─────────────────────────────────────

async function benchSubagentRouter(prompt: string): Promise<{ latencyMs: number; response: string; subagent: string; confidence: number }> {
  const start = Date.now();

  // Step 1: Keyword routing (~0ms)
  const routeResult = routeMessageSync(prompt);

  // Step 2: Build system prompt with subagent context
  const supabase = createServiceClient();
  const { data: projects } = await supabase.from('projects').select('*');
  const system = buildSystemPrompt(
    (projects as any[]) ?? [],
    todayISO(),
    'default',
    routeResult.subagent
  );

  // Step 3: Filter tools based on routing
  const allSpecs = getToolSpecsForMode('default');
  const allowedToolNames = getRoutedTools(routeResult.subagent, allSpecs.map(t => t.name));
  const toolSpecs = allSpecs.filter(t => allowedToolNames.includes(t.name));

  // Step 4: Call LLM with filtered tools
  const agent = await getAgent();
  const finalText = await agent.runStream({
    system,
    messages: [{ role: 'user', content: prompt }],
    tools: toolSpecs,
    executeTool: async (name, input) => executeToolForMode('default', name, input, supabase),
    callbacks: {},
  });

  const latencyMs = Date.now() - start;
  return {
    latencyMs,
    response: finalText.substring(0, 200),
    subagent: routeResult.subagent,
    confidence: routeResult.confidence,
  };
}

// ─── Main ────────────────────────────────────────────────────────────────────

async function main() {
  console.log('\n═══════════════════════════════════════════════════════════════');
  console.log('  Benchmark: Router vs No-Router Latency Comparison');
  console.log('═══════════════════════════════════════════════════════════════\n');

  const results: Array<{
    scenario: string;
    prompt: string;
    directMs: number;
    mtclawMs: number;
    mtclawTool: boolean;
    subagentMs: number;
    subagent: string;
    confidence: number;
    speedup: string;
  }> = [];

  for (const scenario of SCENARIOS) {
    console.log(`▶ Testing: ${scenario.id} — "${scenario.prompt.substring(0, 50)}..."`);

    // Path A: Direct Qwen
    const direct = await benchDirectQwen(scenario.prompt).catch(e => ({
      latencyMs: -1,
      response: `ERROR: ${e.message}`,
    }));
    console.log(`  A) Direct Qwen:     ${direct.latencyMs}ms`);

    // Path B: MTClaw
    const mtclaw = await benchMtclaw(scenario.prompt).catch(e => ({
      latencyMs: -1,
      response: `ERROR: ${e.message}`,
      routedTool: false,
    }));
    console.log(`  B) MTClaw Router:   ${mtclaw.latencyMs}ms  (tool=${mtclaw.routedTool})`);

    // Path C: Subagent Router
    const subagent = await benchSubagentRouter(scenario.prompt).catch(e => ({
      latencyMs: -1,
      response: `ERROR: ${e.message}`,
      subagent: 'error',
      confidence: 0,
    }));
    console.log(`  C) Subagent Router: ${subagent.latencyMs}ms  (${subagent.subagent}, ${Math.round(subagent.confidence * 100)}%)`);

    const speedup = direct.latencyMs > 0 && mtclaw.latencyMs > 0
      ? `${(direct.latencyMs / mtclaw.latencyMs).toFixed(2)}x`
      : 'N/A';

    results.push({
      scenario: scenario.id,
      prompt: scenario.prompt.substring(0, 40),
      directMs: direct.latencyMs,
      mtclawMs: mtclaw.latencyMs,
      mtclawTool: mtclaw.routedTool,
      subagentMs: subagent.latencyMs,
      subagent: subagent.subagent,
      confidence: subagent.confidence,
      speedup,
    });

    console.log(`  → Speedup (Direct/MTClaw): ${speedup}\n`);
  }

  // ─── Summary table ──────────────────────────────────────────────────────────
  console.log('\n═══════════════════════════════════════════════════════════════');
  console.log('  Summary');
  console.log('═══════════════════════════════════════════════════════════════\n');
  console.log('Scenario              | Direct(ms) | MTClaw(ms) | Tool? | Subagent(ms) | Subagent        | Conf  | Speedup');
  console.log('─────────────────────────────────────────────────────────────────────────────────────────────────────────────────');
  for (const r of results) {
    console.log(
      `${r.scenario.padEnd(20)} | ${String(r.directMs).padStart(10)} | ${String(r.mtclawMs).padStart(10)} | ${r.mtclawTool ? '  YES' : '  NO '} | ${String(r.subagentMs).padStart(12)} | ${r.subagent.padEnd(15)} | ${String(Math.round(r.confidence * 100)).padStart(4)}% | ${r.speedup}`
    );
  }

  // ─── Averages ───────────────────────────────────────────────────────────────
  const validDirect = results.filter(r => r.directMs > 0);
  const validMtclaw = results.filter(r => r.mtclawMs > 0);
  const toolMatched = results.filter(r => r.mtclawTool);

  if (validDirect.length && validMtclaw.length) {
    const avgDirect = validDirect.reduce((s, r) => s + r.directMs, 0) / validDirect.length;
    const avgMtclaw = validMtclaw.reduce((s, r) => s + r.mtclawMs, 0) / validMtclaw.length;
    const avgTool = toolMatched.length
      ? toolMatched.reduce((s, r) => s + r.mtclawMs, 0) / toolMatched.length
      : 0;

    console.log('\n─────────────────────────────────────────────────────────────────────────────────────────────────────────────────');
    console.log(`Average Direct Qwen:     ${Math.round(avgDirect)}ms`);
    console.log(`Average MTClaw (all):    ${Math.round(avgMtclaw)}ms  (speedup: ${(avgDirect / avgMtclaw).toFixed(2)}x)`);
    if (toolMatched.length) {
      console.log(`Average MTClaw (tool matched only): ${Math.round(avgTool)}ms  (speedup: ${(avgDirect / avgTool).toFixed(2)}x)`);
      console.log(`Tool match rate: ${toolMatched.length}/${results.length} (${Math.round(toolMatched.length / results.length * 100)}%)`);
    }
  }

  console.log('\n✓ Benchmark complete.');
}

main().catch(console.error);
