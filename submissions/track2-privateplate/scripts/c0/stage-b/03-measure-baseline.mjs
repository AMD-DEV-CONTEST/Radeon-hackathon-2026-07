#!/usr/bin/env node
/**
 * Measure the collection's first baseline request and warm baseline requests
 * against loopback vLLM.
 * Does not invent numbers — only writes what the live server returns.
 */
import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { access, writeFile, mkdir, readFile } from "node:fs/promises";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath, pathToFileURL } from "node:url";
import { promisify } from "node:util";
import path from "node:path";
import {
  assertLoopbackProvider,
  assertVerifiedRadeonEnvironment
} from "./evidence-guard.mjs";
import { verifyRecordedSource } from "./source-integrity.mjs";
import { resolveC0bOutDir } from "./resolve-out-dir.mjs";

const execFileAsync = promisify(execFile);

const root = fileURLToPath(new URL("../../../", import.meta.url));
const outDir = resolveC0bOutDir(root);
const rawDir = path.join(outDir, "raw");
const outPath = path.join(outDir, "baseline-results.json");
const productToolDefinitionsPath = path.join(
  root,
  "packages/agent-runtime/dist/model/tool-definitions.js"
);
await assertFileDoesNotExist(outPath);

const baseUrl = (process.env.PRIVATEPLATE_VLLM_BASE_URL ?? "http://127.0.0.1:8000/v1").replace(
  /\/?$/,
  "/"
);
assertLoopbackProvider(baseUrl);
const environmentPath = path.join(outDir, "environment.json");
const environment = await assertVerifiedRadeonEnvironment(environmentPath);
const sourceIntegrity = await verifyRecordedSource(root, environmentPath);
const model =
  process.env.PRIVATEPLATE_MODEL_ACTIVE ??
  (await readFile(path.join(rawDir, "active-model.txt"), "utf8")).trim();
if (!model) {
  throw new Error("Baseline requires an explicit active model id (no default).");
}
const { PRIVATEPLATE_MODEL_TOOLS } = await import(
  pathToFileURL(productToolDefinitionsPath).href
);
if (!Array.isArray(PRIVATEPLATE_MODEL_TOOLS) || PRIVATEPLATE_MODEL_TOOLS.length !== 5) {
  throw new Error("Baseline requires the compiled product's exact five tool definitions.");
}

// Product-shaped workload with enough trusted ids for a real tool call.
const productWorkloadMessages = [
  {
    role: "system",
    content:
      "You are PrivatePlate's Chinese household meal tool router. Use exactly one supplied tool when the request needs an action. Use only ids supplied in the request context."
  },
  {
    role: "user",
    content: JSON.stringify({
      request: "我们三个人规划午餐，不要鸡腿，优先豆腐，做得简单一点。",
      state: {
        phase: "COLLECTING_DINERS",
        dinerIds: ["mem-admin", "mem-father", "mem-mother"],
        activePlanId: null,
        activePlanVersion: null
      },
      dinerIdsLocked: true,
      members: [
        { id: "mem-admin", displayName: "管理员", aliases: ["我"] },
        { id: "mem-father", displayName: "父亲", aliases: ["爸爸"] },
        { id: "mem-mother", displayName: "母亲", aliases: ["妈妈"] }
      ],
      fixtureIds: {
        foods: [
          { id: "food-tofu", name: "豆腐", aliases: [] },
          { id: "food-chicken-leg", name: "鸡腿", aliases: [] }
        ],
        templates: [],
        planTags: [],
        caregiverRecipientLabels: ["家庭保姆", "保姆", "阿姨"]
      }
    })
  }
];
const prompt = productWorkloadMessages.map((m) => m.content).join("\n");
const warmRuns = 5;
const maxTokens = 128;
const workloadKind = "product_tool_routing_prompt";
const requestTimeoutMs = Number(
  process.env.PRIVATEPLATE_REQUEST_TIMEOUT_MS ?? 120_000
);
const vramSampleIntervalMs = 250;
const launch = JSON.parse(
  await readFile(path.join(rawDir, "vllm-launch.json"), "utf8")
);
if (!Number.isSafeInteger(launch.kv_cache_memory_bytes)) {
  throw new Error("Baseline requires fixed kv_cache_memory_bytes in launch evidence.");
}

async function streamOnce() {
  const started = performance.now();
  let firstTokenAt = null;
  let text = "";
  let reasoning = "";
  let firstOutputKind = null;
  const toolCalls = [];
  let completionTokens = null;
  let promptTokens = null;

  const response = await fetch(new URL("chat/completions", baseUrl), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(process.env.PRIVATEPLATE_VLLM_API_KEY
        ? {
            Authorization: `Bearer ${process.env.PRIVATEPLATE_VLLM_API_KEY}`
          }
        : {})
    },
    body: JSON.stringify({
      model,
      stream: true,
      stream_options: { include_usage: true },
      max_tokens: maxTokens,
      messages: productWorkloadMessages,
      tools: PRIVATEPLATE_MODEL_TOOLS,
      tool_choice: "auto",
      temperature: 0
    }),
    signal: AbortSignal.timeout(requestTimeoutMs)
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`HTTP ${response.status}: ${body.slice(0, 500)}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n");
    buffer = chunks.pop() ?? "";
    for (const line of chunks) {
      const trimmed = line.trim();
      if (!trimmed.startsWith("data:")) continue;
      const data = trimmed.slice(5).trim();
      if (data === "[DONE]") continue;
      const json = JSON.parse(data);
      const delta = json.choices?.[0]?.delta ?? {};
      const contentDelta = typeof delta.content === "string" ? delta.content : "";
      const reasoningDelta =
        typeof delta.reasoning_content === "string"
          ? delta.reasoning_content
          : typeof delta.reasoning === "string"
            ? delta.reasoning
            : "";
      const toolDeltas = Array.isArray(delta.tool_calls) ? delta.tool_calls : [];
      const hasToolOutput = toolDeltas.some(
        (call) =>
          (typeof call?.id === "string" && call.id.length > 0) ||
          (typeof call?.function?.name === "string" &&
            call.function.name.length > 0) ||
          (typeof call?.function?.arguments === "string" &&
            call.function.arguments.length > 0)
      );
      if (contentDelta || reasoningDelta || hasToolOutput) {
        if (firstTokenAt == null) {
          firstTokenAt = performance.now();
          firstOutputKind = contentDelta
            ? "content"
            : reasoningDelta
              ? "reasoning"
              : "tool_call";
        }
        text += contentDelta;
        reasoning += reasoningDelta;
        for (const call of toolDeltas) {
          const index = Number.isSafeInteger(call?.index) ? call.index : 0;
          const current = toolCalls[index] ?? {
            id: "",
            name: "",
            arguments: ""
          };
          current.id += typeof call?.id === "string" ? call.id : "";
          current.name +=
            typeof call?.function?.name === "string" ? call.function.name : "";
          current.arguments +=
            typeof call?.function?.arguments === "string"
              ? call.function.arguments
              : "";
          toolCalls[index] = current;
        }
      }
      if (json.usage) {
        completionTokens = json.usage.completion_tokens ?? completionTokens;
        promptTokens = json.usage.prompt_tokens ?? promptTokens;
      }
    }
  }

  const ended = performance.now();
  const ttftMs = firstTokenAt == null ? null : firstTokenAt - started;
  const totalMs = ended - started;
  const completedToolCalls = toolCalls.filter(
    (call) => call?.name.length > 0 && call?.arguments.length > 0
  );
  const toolCallChars = completedToolCalls.reduce(
    (sum, call) =>
      sum +
      Array.from(call?.name ?? "").length +
      Array.from(call?.arguments ?? "").length,
    0
  );
  const outputChars =
    Array.from(text).length + Array.from(reasoning).length + toolCallChars;
  const generationSeconds =
    ttftMs == null || totalMs <= ttftMs ? null : (totalMs - ttftMs) / 1000;
  const tokensPerSec =
    completionTokens == null || generationSeconds == null
      ? null
      : completionTokens / generationSeconds;
  const charsPerSec =
    generationSeconds == null ? null : outputChars / generationSeconds;

  return {
    ttft_ms: ttftMs == null ? null : Math.round(ttftMs),
    total_ms: Math.round(totalMs),
    output_chars: outputChars,
    prompt_tokens: promptTokens,
    completion_tokens: completionTokens,
    tokens_per_sec: tokensPerSec == null ? null : Number(tokensPerSec.toFixed(2)),
    chars_per_sec_proxy:
      charsPerSec == null ? null : Number(charsPerSec.toFixed(2)),
    usage_reported: completionTokens != null,
    first_output_kind: firstOutputKind,
    tool_call_count: completedToolCalls.length,
    tool_call_names: completedToolCalls.map((call) => call.name),
    sample_text_preview: text.slice(0, 120)
  };
}

function percentile(values, p) {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const idx = Math.min(sorted.length - 1, Math.ceil((p / 100) * sorted.length) - 1);
  return sorted[idx];
}

function startVramSampler(intervalMs) {
  let stopped = false;
  const samples = [];
  const failures = [];
  const task = (async () => {
    while (!stopped) {
      try {
        samples.push(await readVramSample());
      } catch (error) {
        failures.push(String(error?.message ?? error));
      }
      if (!stopped) await delay(intervalMs);
    }
  })();

  return {
    async stop() {
      stopped = true;
      await task;
      if (samples.length === 0) {
        return {
          status: failures.length > 0 ? "FAILED" : "MISSING",
          scope: "baseline_requests_only",
          source: "rocm-smi --showmeminfo vram",
          sample_interval_ms: intervalMs,
          sample_count: 0,
          failure:
            failures[0] ??
            "No parseable VRAM samples were returned during the baseline window."
        };
      }

      const peak = samples.reduce((best, sample) =>
        sample.used_bytes > best.used_bytes ? sample : best
      );
      return {
        status: "CAPTURED",
        scope: "baseline_requests_only",
        source: "rocm-smi --showmeminfo vram",
        sample_interval_ms: intervalMs,
        sample_count: samples.length,
        peak_used_bytes: peak.used_bytes,
        peak_used_gib: Number(
          (peak.used_bytes / 1024 / 1024 / 1024).toFixed(2)
        ),
        total_bytes: peak.total_bytes,
        gpu_count: peak.gpu_count,
        first_sample_at_utc: samples[0].collected_at_utc,
        last_sample_at_utc: samples.at(-1).collected_at_utc,
        sampling_failures: failures.length
      };
    }
  };
}

async function readVramSample() {
  const { stdout } = await execFileAsync(
    "rocm-smi",
    ["--showmeminfo", "vram"],
    { timeout: 10_000, maxBuffer: 1024 * 1024 }
  );
  const used = [
    ...stdout.matchAll(/VRAM Total Used Memory \(B\):\s*(\d+)/g)
  ].map((match) => Number(match[1]));
  const totals = [
    ...stdout.matchAll(/VRAM Total Memory \(B\):\s*(\d+)/g)
  ].map((match) => Number(match[1]));
  if (
    used.length === 0 ||
    totals.length !== used.length ||
    used.some((value) => !Number.isFinite(value)) ||
    totals.some((value) => !Number.isFinite(value))
  ) {
    throw new Error("rocm-smi returned no parseable VRAM byte counters.");
  }
  return {
    status: "CAPTURED",
    collected_at_utc: new Date().toISOString(),
    used_bytes: used.reduce((sum, value) => sum + value, 0),
    total_bytes: totals.reduce((sum, value) => sum + value, 0),
    gpu_count: used.length
  };
}

await mkdir(outDir, { recursive: true });
await mkdir(rawDir, { recursive: true });

let activeModel = model;
try {
  activeModel = (await readFile(path.join(rawDir, "active-model.txt"), "utf8")).trim() || model;
} catch {
  // optional
}

let vramAfterModelLoad = null;
try {
  vramAfterModelLoad = await readVramSample();
} catch (error) {
  vramAfterModelLoad = {
    status: "FAILED",
    error: String(error?.message ?? error)
  };
}

const sampler = startVramSampler(vramSampleIntervalMs);
let firstRequest = null;
const warm = [];
let measurementError = null;
try {
  firstRequest = await streamOnce();
  for (let i = 0; i < warmRuns; i += 1) {
    warm.push(await streamOnce());
  }
} catch (error) {
  measurementError = {
    name: error?.name ?? "Error",
    message: String(error?.message ?? error)
  };
}
const peakVram = await sampler.stop();

const measurementErrors = [];
if (measurementError) {
  measurementErrors.push(measurementError.message);
}
validateRequestMeasurement("first_request", firstRequest, measurementErrors);
if (warm.length !== warmRuns) {
  measurementErrors.push(
    `warm_runs: expected ${warmRuns}, got ${warm.length}`
  );
}
for (const [index, result] of warm.entries()) {
  validateRequestMeasurement(`warm_${index + 1}`, result, measurementErrors);
}
if (
  vramAfterModelLoad?.status !== "CAPTURED" ||
  !Number.isFinite(vramAfterModelLoad.used_bytes) ||
  !Number.isFinite(vramAfterModelLoad.total_bytes)
) {
  measurementErrors.push("after_model_load VRAM sample is missing or invalid");
}
if (
  peakVram.status !== "CAPTURED" ||
  !Number.isFinite(peakVram.peak_used_bytes) ||
  !Number.isFinite(peakVram.total_bytes) ||
  !Number.isSafeInteger(peakVram.sample_count) ||
  peakVram.sample_count < 1 ||
  peakVram.sampling_failures !== 0
) {
  measurementErrors.push("peak VRAM sampling is incomplete or invalid");
}

const warmTtft = warm.map((r) => r.ttft_ms).filter((v) => typeof v === "number");
const warmTps = warm
  .map((r) => r.tokens_per_sec)
  .filter((v) => typeof v === "number");
const warmCharsPerSec = warm
  .map((r) => r.chars_per_sec_proxy)
  .filter((v) => typeof v === "number");

const loadedBytes =
  vramAfterModelLoad && typeof vramAfterModelLoad.used_bytes === "number"
    ? vramAfterModelLoad.used_bytes
    : null;
const peakBytes =
  peakVram && typeof peakVram.peak_used_bytes === "number"
    ? peakVram.peak_used_bytes
    : null;

const payload = {
  schema_version: "2.1",
  stage: "C0-B",
  collected_at_utc: new Date().toISOString(),
  provider_mode: "local_vllm_radeon",
  remote_api: false,
  evidence_eligible: true,
  workload: {
    kind: workloadKind,
    description:
      "Multi-message product tool-routing prompt (meal plan with reject + priority), not single-line chitchat.",
    max_tokens: maxTokens,
    warm_runs: warmRuns,
    message_count: productWorkloadMessages.length,
    tool_count: PRIVATEPLATE_MODEL_TOOLS.length,
    expected_tool: "compose_family_meal",
    user_prompt_sha256: createHash("sha256")
      .update(productWorkloadMessages[1].content)
      .digest("hex")
  },
  model: activeModel,
  model_profile: process.env.PRIVATEPLATE_MODEL_PROFILE ?? null,
  run_id: process.env.PRIVATEPLATE_RUN_ID ?? null,
  preferred_model: activeModel,
  fallback_model: null,
  source_provenance: {
    git_commit: environment.git_commit,
    git_dirty: environment.git_dirty,
    integrity_mode: sourceIntegrity.mode,
    manifest_sha256: sourceIntegrity.manifest_sha256,
    file_count: sourceIntegrity.file_count
  },
  base_url: baseUrl,
  prompt,
  max_tokens: maxTokens,
  measurement_status: measurementErrors.length === 0 ? "PASS" : "FAIL",
  measurement_errors: measurementErrors,
  benchmark_configuration: {
    prompt_fixed: true,
    warm_run_count: warmRuns,
    max_tokens: maxTokens,
    vram_sample_interval_ms: vramSampleIntervalMs,
    kv_cache_memory_bytes: launch.kv_cache_memory_bytes
  },
  ttft: {
    first_request_after_readiness_ms: firstRequest?.ttft_ms ?? null,
    warm_p50_ms: percentile(warmTtft, 50),
    warm_p90_ms: percentile(warmTtft, 90),
    distinction:
      "first_request_after_readiness is the first baseline call in this collection; warm_* excludes that first call."
  },
  first_baseline_request_after_readiness_check: firstRequest,
  warm_runs: warm,
  warm_ttft_ms: {
    p50: percentile(warmTtft, 50),
    p90: percentile(warmTtft, 90),
    n: warmTtft.length
  },
  warm_tokens_per_sec: {
    p50: percentile(warmTps, 50),
    p90: percentile(warmTps, 90),
    n: warmTps.length
  },
  warm_chars_per_sec_proxy: {
    p50: percentile(warmCharsPerSec, 50),
    p90: percentile(warmCharsPerSec, 90),
    n: warmCharsPerSec.length,
    claim_boundary:
      "Character throughput is only a fallback proxy and must not be reported as token throughput."
  },
  vram: {
    after_model_load: vramAfterModelLoad,
    during_requests_peak: peakVram,
    request_window_increment_bytes:
      loadedBytes != null && peakBytes != null ? peakBytes - loadedBytes : null,
    note: "after_model_load is sampled before baseline requests; peak is during requests. Do not report only the 0.90 reservation target as measured use."
  },
  peak_vram: peakVram,
  claim_boundary:
    "These numbers come from a live loopback vLLM stream on the measurement host. The first sample is the first baseline request made by this collection after a readiness check; it is not proof of server or model cold start. Token throughput is reported only when vLLM returns usage. Peak VRAM covers only the sampled baseline-request window."
};

await writeFile(outPath, JSON.stringify(payload, null, 2) + "\n", "utf8");
console.log(
  JSON.stringify(
    {
      wrote: outPath,
      measurement_status: payload.measurement_status,
      first_baseline_request_ttft_ms: firstRequest?.ttft_ms ?? null,
      warm_ttft_p50: payload.warm_ttft_ms.p50,
      peak_vram_status: peakVram.status
    },
    null,
    2
  )
);
if (payload.measurement_status !== "PASS") {
  process.exitCode = 2;
}

function validateRequestMeasurement(label, result, errors) {
  if (!result) {
    errors.push(`${label}: request result missing`);
    return;
  }
  if (!Number.isFinite(result.ttft_ms) || result.ttft_ms <= 0) {
    errors.push(`${label}: TTFT must be a positive number`);
  }
  if (
    !Number.isFinite(result.total_ms) ||
    result.total_ms <= result.ttft_ms
  ) {
    errors.push(`${label}: total time must be greater than TTFT`);
  }
  if (
    !Number.isSafeInteger(result.prompt_tokens) ||
    result.prompt_tokens < 1 ||
    !Number.isSafeInteger(result.completion_tokens) ||
    result.completion_tokens < 1 ||
    result.usage_reported !== true
  ) {
    errors.push(`${label}: prompt/completion token usage is required`);
  }
  if (
    !Number.isFinite(result.tokens_per_sec) ||
    result.tokens_per_sec <= 0
  ) {
    errors.push(`${label}: tokens_per_sec must be a positive number`);
  }
  if (result.tool_call_count < 1) {
    errors.push(`${label}: product workload must produce a tool call`);
  }
}

async function assertFileDoesNotExist(filePath) {
  try {
    await access(filePath);
  } catch {
    return;
  }
  throw new Error(
    `Refusing to overwrite existing baseline evidence: ${path.relative(root, filePath)}`
  );
}
