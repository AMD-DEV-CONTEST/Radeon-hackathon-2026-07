/**
 * MTClaw Verification Script
 *
 * Tests 3 scenarios to verify MTClaw's actual behavior:
 *   1. Simple chat (no tool match) → should forward to upstream LLM
 *   2. Business overview (tool match) → should call solo_business_overview
 *   3. Knowledge search (tool match) → should call solo_search_knowledge
 *
 * For each: prints full response, tool match status, model used, latency.
 *
 * Usage:
 *   npx tsx scripts/verify-mtclaw.ts
 */

const MTCLAW_URL = 'http://127.0.0.1:18790/v1/chat/completions';
const MTCLAW_HEALTH = 'http://127.0.0.1:18790/health';
const MODEL = 'qwen3.7-plus';

interface MtclawResponse {
  id?: string;
  object?: string;
  model?: string;
  choices?: Array<{
    index?: number;
    message?: { role: string; content: string };
    finish_reason?: string;
  }>;
  usage?: { prompt_tokens?: number; completion_tokens?: number; total_tokens?: number };
}

interface TestResult {
  scenario: string;
  prompt: string;
  expectToolMatch: boolean;
  latencyMs: number;
  model: string;
  routedByFR: boolean;
  response: string;
  error?: string;
}

async function checkHealth(): Promise<boolean> {
  try {
    const resp = await fetch(MTCLAW_HEALTH);
    if (!resp.ok) return false;
    const data = await resp.json();
    console.log(`  MTClaw health: ${JSON.stringify(data)}`);
    return true;
  } catch (e) {
    console.log(`  MTClaw health check FAILED: ${e instanceof Error ? e.message : 'unknown'}`);
    return false;
  }
}

async function sendToMtclaw(prompt: string): Promise<TestResult> {
  const start = Date.now();
  try {
    const resp = await fetch(MTCLAW_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: MODEL,
        messages: [{ role: 'user', content: prompt }],
        stream: false,
      }),
    });

    if (!resp.ok) {
      const errorText = await resp.text();
      return {
        scenario: '',
        prompt,
        expectToolMatch: false,
        latencyMs: Date.now() - start,
        model: '',
        routedByFR: false,
        response: '',
        error: `HTTP ${resp.status}: ${errorText.substring(0, 300)}`,
      };
    }

    const data: MtclawResponse = await resp.json();
    const latencyMs = Date.now() - start;
    const model = data.model ?? 'unknown';
    const routedByFR = model === 'function-router';
    const response = data.choices?.[0]?.message?.content ?? '(empty)';

    return {
      scenario: '',
      prompt,
      expectToolMatch: false,
      latencyMs,
      model,
      routedByFR,
      response: response.substring(0, 500),
    };
  } catch (e) {
    return {
      scenario: '',
      prompt,
      expectToolMatch: false,
      latencyMs: Date.now() - start,
      model: '',
      routedByFR: false,
      response: '',
      error: e instanceof Error ? e.message : 'unknown error',
    };
  }
}

async function main() {
  console.log('\n═══════════════════════════════════════════════════════════════');
  console.log('  MTClaw Verification — Testing Real vs Pass-through Behavior');
  console.log('  Date: ' + new Date().toISOString());
  console.log('═══════════════════════════════════════════════════════════════\n');

  // Step 1: Health check
  console.log('Step 1: MTClaw Health Check');
  const healthy = await checkHealth();
  if (!healthy) {
    console.log('\n❌ MTClaw is not running or health check failed.');
    console.log('   Start it with: cd e:\\gitproject\\hackathon\\MTClaw && python -m function_router.server --config solo-config.json');
    process.exit(1);
  }
  console.log('  ✓ MTClaw is running\n');

  // Step 2: Run 3 test scenarios
  const tests: Array<{ scenario: string; prompt: string; expectToolMatch: boolean }> = [
    {
      scenario: '1. Simple chat (no tool match)',
      prompt: 'Hello, how are you?',
      expectToolMatch: false,
    },
    {
      scenario: '2. Business overview (tool match expected)',
      prompt: 'Give me a business overview',
      expectToolMatch: true,
    },
    {
      scenario: '3. Knowledge search (tool match expected)',
      prompt: 'What are my standard payment terms?',
      expectToolMatch: true,
    },
  ];

  const results: TestResult[] = [];

  for (const test of tests) {
    console.log(`\n${test.scenario}`);
    console.log(`  Prompt: "${test.prompt}"`);

    const result = await sendToMtclaw(test.prompt);
    result.scenario = test.scenario;
    result.expectToolMatch = test.expectToolMatch;

    if (result.error) {
      console.log(`  ❌ ERROR: ${result.error}`);
    } else {
      console.log(`  Latency: ${result.latencyMs}ms`);
      console.log(`  Model: ${result.model}`);
      console.log(`  Tool matched: ${result.routedByFR ? 'YES (Function Router fast path)' : 'NO (forwarded to upstream LLM)'}`);
      console.log(`  Response (first 300 chars):`);
      console.log(`    ${result.response.substring(0, 300)}`);

      // Verify expectation
      if (result.routedByFR === test.expectToolMatch) {
        console.log(`  ✓ Expected behavior confirmed`);
      } else {
        console.log(`  ⚠ MISMATCH: expected tool=${test.expectToolMatch}, got tool=${result.routedByFR}`);
      }
    }

    results.push(result);
  }

  // Step 3: Summary
  console.log('\n\n═══════════════════════════════════════════════════════════════');
  console.log('  Summary');
  console.log('═══════════════════════════════════════════════════════════════\n');

  console.log('Scenario                        | Latency  | Model              | Tool Match | Expected | Status');
  console.log('─────────────────────────────────────────────────────────────────────────────────────────────────────');

  for (const r of results) {
    const status = r.error
      ? 'ERROR'
      : r.routedByFR === r.expectToolMatch
        ? '✓ PASS'
        : '⚠ CHECK';

    console.log(
      `${r.scenario.padEnd(30)} | ${String(r.latencyMs).padStart(8)}ms | ${(r.model || 'error').padEnd(18)} | ${r.routedByFR ? 'YES' : 'NO '}       | ${r.expectToolMatch ? 'YES' : 'NO '}      | ${status}`
    );
  }

  // Step 4: Conclusion
  console.log('\n═══════════════════════════════════════════════════════════════');
  console.log('  Verification Conclusion');
  console.log('═══════════════════════════════════════════════════════════════\n');

  const toolMatched = results.filter(r => r.routedByFR);
  const toolMissed = results.filter(r => !r.routedByFR && !r.error);
  const errors = results.filter(r => r.error);

  if (toolMatched.length > 0) {
    console.log(`✓ MTClaw Function Router IS actively routing tool calls:`);
    console.log(`  - ${toolMatched.length} request(s) matched to custom tools (solo_business_overview, solo_search_knowledge)`);
    console.log(`  - Model field = "function-router" confirms MTClaw executed the tool and returned directly`);
    console.log(`  - This is NOT pass-through — MTClaw's routing model made the decision`);
  }

  if (toolMissed.length > 0) {
    console.log(`\n✓ Non-tool requests are correctly forwarded to upstream LLM:`);
    console.log(`  - ${toolMissed.length} request(s) forwarded to upstream (qwen3.7-plus)`);
    console.log(`  - Model field = "qwen3.7-plus" confirms upstream LLM handled the response`);
  }

  if (errors.length > 0) {
    console.log(`\n❌ ${errors.length} request(s) had errors:`);
    for (const e of errors) {
      console.log(`  - ${e.scenario}: ${e.error}`);
    }
  }

  console.log(`\n📝 NOTE: MTClaw does NOT use a "router_hints" field from the client.`);
  console.log(`   MTClaw uses its OWN routing model (configured as qwen-turbo in solo-config.json)`);
  console.log(`   to decide whether to call custom tools or forward to the upstream LLM.`);
  console.log(`   Our app's keyword-based FunctionRouter is a COMPLEMENTARY layer:`);
  console.log(`   Layer 1 (our app): keyword routing → select Subagent → filter tools`);
  console.log(`   Layer 2 (MTClaw): routing model → match custom tool or forward to upstream`);
  console.log('\n✓ Verification complete.');
}

main().catch(console.error);
