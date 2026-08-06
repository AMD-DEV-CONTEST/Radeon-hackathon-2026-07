/**
 * Benchmark the local OpenAI-compatible server used by the AMD private-agent track.
 *
 * Usage:
 *   npx tsx scripts/benchmark-local-llm.ts
 *
 * The script never calls a cloud provider. It checks the local /v1/models
 * endpoint, then runs fixed business prompts against /v1/chat/completions.
 * Results are suitable for pasting into the AMD submission notes.
 */

type JsonObject = Record<string, unknown>;

const endpoint = process.env.LOCAL_LLM_BASE_URL ?? 'http://localhost:8000/v1/chat/completions';
const apiKey = process.env.LOCAL_LLM_API_KEY ?? 'EMPTY';
const configuredModel = process.env.LOCAL_LLM_MODEL ?? 'Qwen/Qwen3-8B';
const modelsUrl = endpoint.replace(/\/chat\/completions\/?$/, '/models');
const timeoutMs = Number(process.env.LOCAL_BENCHMARK_TIMEOUT_MS ?? 120_000);

const scenarios = [
  {
    id: 'intake',
    prompt: 'Extract the client, project type, budget, currency, and deadline from: Sarah Chen needs a logo design, budget 800 USD, deadline August 10, 2026. Return concise JSON.',
  },
  {
    id: 'contract',
    prompt: 'Draft a concise payment-terms paragraph for a freelance design contract. Include a 50% upfront payment and the remaining balance on delivery.',
  },
  {
    id: 'private-memory',
    prompt: 'A private freelancer knowledge base says: standard payment terms are 50% upfront and net-7 on delivery. State the terms in one sentence and do not invent other terms.',
  },
];

function withTimeout<T>(promise: Promise<T>, label: string): Promise<T> {
  return Promise.race([
    promise,
    new Promise<T>((_, reject) =>
      setTimeout(() => reject(new Error(`${label} timed out after ${timeoutMs}ms`)), timeoutMs),
    ),
  ]);
}

async function requestJson(url: string, body?: JsonObject): Promise<{ status: number; data: JsonObject }> {
  const response = await withTimeout(
    fetch(url, {
      method: body ? 'POST' : 'GET',
      headers: body
        ? { 'Content-Type': 'application/json', Authorization: `Bearer ${apiKey}` }
        : { Authorization: `Bearer ${apiKey}` },
      body: body ? JSON.stringify(body) : undefined,
    }),
    url,
  );
  const text = await response.text();
  let data: JsonObject = {};
  try {
    data = JSON.parse(text) as JsonObject;
  } catch {
    data = { raw: text.slice(0, 500) };
  }
  if (!response.ok) throw new Error(`${url} returned HTTP ${response.status}: ${JSON.stringify(data)}`);
  return { status: response.status, data };
}

async function main() {
  console.log('AMD local LLM benchmark');
  console.log(`Endpoint: ${endpoint}`);
  console.log(`Configured model: ${configuredModel}`);
  console.log('Cloud APIs: none');

  const modelProbe = await requestJson(modelsUrl);
  const modelList = Array.isArray(modelProbe.data.data)
    ? modelProbe.data.data
        .map((item) => (item && typeof item === 'object' && 'id' in item ? String((item as JsonObject).id) : ''))
        .filter(Boolean)
    : [];
  const model = modelList[0] ?? configuredModel;
  console.log(`Server models: ${modelList.length ? modelList.join(', ') : '(not advertised)'}`);
  console.log(`Using model: ${model}\n`);

  const results: Array<{ id: string; latencyMs: number; chars: number }> = [];
  for (const scenario of scenarios) {
    const started = Date.now();
    const response = await requestJson(endpoint, {
      model,
      messages: [{ role: 'user', content: scenario.prompt }],
      stream: false,
      temperature: 0.2,
      max_tokens: 300,
    });
    const latencyMs = Date.now() - started;
    const choices = Array.isArray(response.data.choices) ? response.data.choices : [];
    const first = choices[0];
    const message = first && typeof first === 'object' && 'message' in first ? (first as JsonObject).message : null;
    const content = message && typeof message === 'object' && 'content' in message ? String((message as JsonObject).content ?? '') : '';
    results.push({ id: scenario.id, latencyMs, chars: content.length });
    console.log(`${scenario.id.padEnd(16)} ${String(latencyMs).padStart(6)} ms  ${String(content.length).padStart(4)} chars`);
  }

  const average = results.reduce((sum, item) => sum + item.latencyMs, 0) / results.length;
  console.log(`\nAverage latency: ${Math.round(average)} ms`);
  console.log(`Completed: ${results.length}/${scenarios.length}`);
  console.log('Note: this benchmark measures end-to-end request latency; GPU utilization and token throughput should be captured on the AMD host with its ROCm tools.');
}

main().catch((error: unknown) => {
  console.error(`\nLOCAL_BENCHMARK_FAILED: ${error instanceof Error ? error.message : String(error)}`);
  console.error('Start vLLM/SGLang locally, set LOCAL_LLM_BASE_URL, then rerun this command.');
  process.exitCode = 1;
});
