#!/usr/bin/env node

import { promises as fs } from "node:fs";
import { closeSync, createWriteStream, openSync } from "node:fs";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { performance } from "node:perf_hooks";
import { promisify } from "node:util";

import {
  AGENT_TOOL_ALLOWLIST,
  CONTROL_DECISION_NAMES,
  OpenAiCompatibleToolProvider,
  PrivatePlateAgent,
  isControlDecisionName,
  parseControlDecisionArguments,
  parseModelToolArguments,
  parseModelToolGoal
} from "../../packages/agent-runtime/dist/index.js";
import { HashEmbeddingClient, PrivatePlateDomain } from "../../packages/domain/dist/index.js";

const execFile = promisify((await import("node:child_process")).execFile);

const DEFAULT_MODEL = "google/gemma-4-12B-it-qat-w4a16-ct";
const DEFAULT_REVISION = "1d2c2d7f2466070e69d6fb3fd5ce9a7d75f2f6ee";
const VLLM_BIN = process.env.PP_VLLM_BIN ?? "/opt/venv/bin/vllm";
const PYTHON_BIN = process.env.PP_PYTHON_BIN ?? "/opt/venv/bin/python3";
const CHAT_HOST = "127.0.0.1";
const CHAT_PORT = 8000;
const RAG_BASE_URL = "http://127.0.0.1:8001/v1";
const CHAT_BASE_URL = `http://${CHAT_HOST}:${CHAT_PORT}/v1`;
const MAX_TOKENS = 128;
const MEASURED_REQUESTS = 10;

const argv = process.argv.slice(2);
const hasFlag = (name) => argv.includes(name);
const option = (name, fallback = null) => {
  const index = argv.indexOf(name);
  return index >= 0 && argv[index + 1] ? argv[index + 1] : fallback;
};

const outputDir = option("--out");
if (!outputDir) {
  throw new Error("Missing required --out <directory>.");
}
const modelId = option("--model", DEFAULT_MODEL);
const revision = option("--revision", DEFAULT_REVISION);
const modelSnapshot = option(
  "--model-snapshot",
  `/root/.cache/huggingface/hub/models--google--gemma-4-12B-it-qat-w4a16-ct/snapshots/${revision}`
);
const chatTemplate = option(
  "--chat-template",
  `${process.cwd()}/scripts/c0/stage-b/chat-templates/gemma4-vllm-tool.jinja`
);
const sourceStatePath = option("--source-state");
const prepareOnly = hasFlag("--prepare-only");
const offlineEnv = {
  ...process.env,
  HF_HOME: "/root/.cache/huggingface",
  HF_HUB_CACHE: "/root/.cache/huggingface/hub",
  HUGGINGFACE_HUB_CACHE: "/root/.cache/huggingface/hub",
  HF_HUB_OFFLINE: "1",
  TRANSFORMERS_OFFLINE: "1"
};

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function mkdir(dir) {
  await fs.mkdir(dir, { recursive: true });
}

async function writeText(file, value) {
  await mkdir(file.substring(0, file.lastIndexOf("/")) || ".");
  await fs.writeFile(file, value, "utf8");
}

async function writeJson(file, value) {
  await writeText(file, `${JSON.stringify(value, null, 2)}\n`);
}

async function appendJsonl(file, value) {
  await mkdir(file.substring(0, file.lastIndexOf("/")) || ".");
  await fs.appendFile(file, `${JSON.stringify(value)}\n`, "utf8");
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

async function runCommand(file, args = [], options = {}) {
  try {
    const result = await execFile(file, args, {
      cwd: options.cwd ?? process.cwd(),
      env: options.env ?? process.env,
      maxBuffer: options.maxBuffer ?? 20 * 1024 * 1024
    });
    return {
      ok: true,
      code: 0,
      stdout: result.stdout ?? "",
      stderr: result.stderr ?? ""
    };
  } catch (error) {
    return {
      ok: false,
      code: Number(error?.code ?? 1),
      stdout: error?.stdout ?? "",
      stderr: error?.stderr ?? String(error)
    };
  }
}

async function runShell(command, options = {}) {
  return runCommand("/bin/sh", ["-lc", command], options);
}

async function readableFile(file) {
  const stat = await fs.stat(file);
  if (!stat.isFile() || stat.size < 1) {
    throw new Error(`Local snapshot file is empty or not a regular file: ${file}`);
  }
  await fs.access(file, 4);
  const handle = await fs.open(file, "r");
  try {
    await handle.read(Buffer.alloc(1), 0, 1, 0);
  } finally {
    await handle.close();
  }
  return { path: file, sizeBytes: stat.size, readable: true };
}

async function collectSnapshotEntries(root) {
  const entries = [];
  async function visit(directory, relative = "") {
    for (const entry of await fs.readdir(directory, { withFileTypes: true })) {
      const fullPath = `${directory}/${entry.name}`;
      const relativePath = relative ? `${relative}/${entry.name}` : entry.name;
      if (entry.isSymbolicLink()) {
        try {
          const realPath = await fs.realpath(fullPath);
          const target = await fs.stat(fullPath);
          entries.push({
            path: relativePath,
            type: target.isDirectory() ? "symlink-directory" : "symlink-file",
            realPath
          });
          if (target.isDirectory()) await visit(fullPath, relativePath);
        } catch (error) {
          entries.push({
            path: relativePath,
            type: "broken-symlink",
            error: error instanceof Error ? error.message : String(error)
          });
        }
      } else if (entry.isDirectory()) {
        entries.push({ path: relativePath, type: "directory" });
        await visit(fullPath, relativePath);
      } else {
        entries.push({ path: relativePath, type: "file" });
      }
    }
  }
  await visit(root);
  return entries;
}

async function validateLocalModelSnapshot() {
  const validationFile = `${outputDir}/env/local-snapshot-validation.json`;
  const result = {
    snapshot: modelSnapshot,
    expectedRevision: revision,
    revisionMatchesBasename: modelSnapshot.split("/").at(-1) === revision,
    directoryExists: false,
    brokenSymlinks: [],
    requiredFiles: {},
    weightFiles: [],
    pythonConfigTokenizerCheck: null,
    offlineEnvironment: {
      HF_HOME: offlineEnv.HF_HOME,
      HF_HUB_CACHE: offlineEnv.HF_HUB_CACHE,
      HUGGINGFACE_HUB_CACHE: offlineEnv.HUGGINGFACE_HUB_CACHE,
      HF_HUB_OFFLINE: offlineEnv.HF_HUB_OFFLINE,
      TRANSFORMERS_OFFLINE: offlineEnv.TRANSFORMERS_OFFLINE
    }
  };
  try {
    const stat = await fs.stat(modelSnapshot);
    result.directoryExists = stat.isDirectory();
    if (!result.directoryExists) throw new Error("Local model snapshot is not a directory.");
    if (!result.revisionMatchesBasename) throw new Error("Snapshot basename does not match expected revision.");

    const entries = await collectSnapshotEntries(modelSnapshot);
    result.brokenSymlinks = entries.filter((entry) => entry.type === "broken-symlink");
    if (result.brokenSymlinks.length > 0) throw new Error("Local snapshot contains broken symlinks.");
    const names = new Set(entries.map((entry) => entry.path));
    const required = ["config.json", "generation_config.json"];
    for (const name of required) {
      const file = `${modelSnapshot}/${name}`;
      result.requiredFiles[name] = await readableFile(file);
    }
    const tokenizerName = ["tokenizer.json", "tokenizer.model"].find((name) => names.has(name));
    if (!tokenizerName) throw new Error("Local snapshot has no tokenizer.json or tokenizer.model.");
    result.requiredFiles.tokenizer = await readableFile(`${modelSnapshot}/${tokenizerName}`);
    if (names.has("tokenizer_config.json")) {
      result.requiredFiles.tokenizerConfig = await readableFile(`${modelSnapshot}/tokenizer_config.json`);
    }
    const weightNames = entries
      .filter((entry) => /\.(safetensors|bin|pt|pth|gguf)$/i.test(entry.path))
      .map((entry) => entry.path);
    if (weightNames.length === 0) throw new Error("Local snapshot has no readable model weight file.");
    for (const name of weightNames) {
      result.weightFiles.push(await readableFile(`${modelSnapshot}/${name}`));
    }

    const pythonCheck = await runCommand(
      PYTHON_BIN,
      [
        "-c",
        [
          "import json",
          "from transformers import AutoConfig, AutoTokenizer",
          `path = ${JSON.stringify(modelSnapshot)}`,
          "config = AutoConfig.from_pretrained(path, local_files_only=True)",
          "tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)",
          "print(json.dumps({'model_type': config.model_type, 'tokenizer_class': tokenizer.__class__.__name__}))"
        ].join("; ")
      ],
      { env: offlineEnv, maxBuffer: 4 * 1024 * 1024 }
    );
    result.pythonConfigTokenizerCheck = {
      ok: pythonCheck.ok,
      stdout: pythonCheck.stdout,
      stderr: pythonCheck.stderr,
      exitCode: pythonCheck.code
    };
    if (!pythonCheck.ok) throw new Error("AutoConfig/AutoTokenizer local-only check failed.");
    await writeJson(validationFile, result);
    console.log(`local snapshot validated: ${modelSnapshot}`);
    return result;
  } catch (error) {
    result.error = error instanceof Error ? error.message : String(error);
    await writeJson(validationFile, result);
    throw new Error(`Local model snapshot validation failed: ${result.error}`);
  }
}

async function captureProductionRequest() {
  const captured = [];
  const domain = await PrivatePlateDomain.create(":memory:", {
    embedding: new HashEmbeddingClient()
  });
  const members = domain.getMembers();
  const fakeFetch = async (_url, init) => {
    captured.push(JSON.parse(String(init.body)));
    const response = {
      choices: [
        {
          message: {
            tool_calls: [
              {
                function: {
                  name: "finish_turn",
                  arguments: JSON.stringify({
                    goal: "compose_meal",
                    message: "模板捕获完成。"
                  })
                }
              }
            ]
          }
        }
      ]
    };
    return new Response(JSON.stringify(response), {
      status: 200,
      headers: { "content-type": "application/json" }
    });
  };
  const provider = new OpenAiCompatibleToolProvider({
    baseUrl: CHAT_BASE_URL,
    model: modelId,
    fetchImpl: fakeFetch
  });
  const agent = new PrivatePlateAgent(
    domain,
    "prefix-caching-production-shape",
    provider
  );
  await agent
    .handleUserMessage(
      "请根据今天三位家庭成员的剩余额度、库存和偏好，规划今天的午餐。"
    )
    .catch(() => undefined);
  if (!captured[0]) {
    throw new Error("The real Agent/Provider did not produce a request template.");
  }
  return {
    request: captured[0],
    memberIds: members.map((member) => member.id)
  };
}

function requestUserMessage(request) {
  return request.messages.find((message) => message.role === "user");
}

function makeMeasuredRequest(template, suffix) {
  const userMessage = requestUserMessage(template);
  if (!userMessage || typeof userMessage.content !== "string") {
    throw new Error("Production request template is missing its JSON user message.");
  }
  const context = JSON.parse(userMessage.content);
  context.request =
    `请根据今天三位家庭成员的剩余额度、库存和偏好，规划今天的午餐。` +
    `本次生产形态 Prefix Cache 测量后缀 ${suffix}。`;
  const messages = template.messages.map((message) =>
    message === userMessage
      ? { ...message, content: JSON.stringify(context) }
      : message
  );
  return {
    ...template,
    messages,
    max_tokens: MAX_TOKENS,
    temperature: 0,
    stream: true,
    stream_options: { include_usage: true },
    tool_choice: "required"
  };
}

async function readSourceState() {
  if (!sourceStatePath) {
    return { unavailable: true, reason: "--source-state not supplied" };
  }
  try {
    return JSON.parse(await fs.readFile(sourceStatePath, "utf8"));
  } catch (error) {
    return {
      unavailable: true,
      reason: `source state unavailable: ${error instanceof Error ? error.message : String(error)}`
    };
  }
}

async function collectEnvironment(productionTemplate) {
  const envDir = `${outputDir}/env`;
  await mkdir(envDir);
  const help = await runCommand(VLLM_BIN, ["serve", "--help=all"]);
  const helpText = `${help.stdout}${help.stderr}`;
  await writeText(`${envDir}/vllm-serve-help.txt`, helpText);
  await writeText(
    `${envDir}/vllm-prefix-cache-help.txt`,
    helpText
      .split("\n")
      .filter((line) => /prefix.?cach|enable-prefix|no-enable-prefix/i.test(line))
      .join("\n") +
      "\n"
  );

  const [hostname, uname, gpu, pythonVersions, vllmVersion, templateHash] =
    await Promise.all([
      runCommand("hostname"),
      runCommand("uname", ["-a"]),
      runCommand("rocm-smi", [
        "--showproductname",
        "--showdriverversion",
        "--showmeminfo",
        "vram",
        "--csv"
      ]),
      runCommand(PYTHON_BIN, [
        "-c",
        "import json, torch, vllm; print(json.dumps({'torch': torch.__version__, 'hip': getattr(torch.version, 'hip', None), 'vllm': getattr(vllm, '__version__', 'unavailable')}))"
      ]),
      runCommand(VLLM_BIN, ["--version"]),
      runCommand("sha256sum", [chatTemplate])
    ]);
  await writeText(`${envDir}/gpu.txt`, `${gpu.stdout}${gpu.stderr}`);
  await writeText(`${envDir}/python-versions.txt`, `${pythonVersions.stdout}${pythonVersions.stderr}`);
  await writeText(`${envDir}/hostname.txt`, `${hostname.stdout}${hostname.stderr}`);
  await writeText(`${envDir}/uname.txt`, `${uname.stdout}${uname.stderr}`);
  await writeText(`${envDir}/vllm-version.txt`, `${vllmVersion.stdout}${vllmVersion.stderr}`);
  await writeText(`${envDir}/chat-template-sha256.txt`, `${templateHash.stdout}${templateHash.stderr}`);

  const sourceState = await readSourceState();
  const explicitFlags = {
    off: "--no-enable-prefix-caching",
    on: "--enable-prefix-caching",
    offPresentInHelp: helpText.includes("--no-enable-prefix-caching"),
    onPresentInHelp: helpText.includes("--enable-prefix-caching")
  };
  if (!explicitFlags.offPresentInHelp || !explicitFlags.onPresentInHelp) {
    throw new Error("The installed vLLM help does not expose both explicit prefix-cache flags.");
  }
  const environment = {
    capturedAt: new Date().toISOString(),
    sourceState,
    host: {
      hostname: hostname.stdout.trim() || "unavailable",
      uname: uname.stdout.trim() || "unavailable",
      gpuCommand: "rocm-smi --showproductname --showdriverversion --showmeminfo vram --csv",
      gpuOutputFile: "env/gpu.txt"
    },
    software: {
      torchOutputFile: "env/python-versions.txt",
      vllmOutputFile: "env/python-versions.txt",
      vllmCliVersionFile: "env/vllm-version.txt",
      ragEndpoint: RAG_BASE_URL,
      chatEndpoint: CHAT_BASE_URL
    },
    model: {
      id: modelId,
      revision,
      localSnapshot: modelSnapshot,
      servedModelName: modelId,
      revisionPassedToServer: false,
      quantization: "compressed-tensors",
      attentionBackend: "TRITON_ATTN",
      maxModelLen: 8192,
      kvCacheMemoryBytes: 8589934592,
      chatTemplate,
      chatTemplateSha256File: "env/chat-template-sha256.txt",
      toolCallParser: "gemma4",
      reasoningParser: "gemma4"
    },
    prefixCaching: explicitFlags,
    workload: {
      source: "real PrivatePlateAgent + OpenAiCompatibleToolProvider request shape",
      systemPrompt: "captured from production provider",
      toolSchema: "captured from production provider",
      requestContext: "stable production context; only user request suffix changes",
      concurrency: 1,
      order: "primer, measured-01 through measured-10, serial",
      maxTokens: MAX_TOKENS,
      measuredRequestsPerArm: MEASURED_REQUESTS,
      transport: "streaming replay of the captured production request body; no tool execution during timing window"
    },
    invariantCommandArgs: [
      "--tensor-parallel-size",
      "1",
      "--max-model-len",
      "8192",
      "--kv-cache-memory-bytes",
      "8589934592",
      "--attention-backend",
      "TRITON_ATTN",
      "--enforce-eager",
      "--enable-auto-tool-choice",
      "--tool-call-parser",
      "gemma4",
      "--reasoning-parser",
      "gemma4",
      "--quantization",
      "compressed-tensors",
      "--chat-template",
      chatTemplate,
      "--served-model-name",
      modelId
    ],
    productionRequestSha256: sha256(JSON.stringify(productionTemplate))
  };
  await writeJson(`${envDir}/environment.json`, environment);
  await writeJson(`${envDir}/production-request-template.json`, productionTemplate);
  await writeJson(`${envDir}/production-request-shape.json`, {
    messages: productionTemplate.messages,
    tools: productionTemplate.tools,
    tool_choice: productionTemplate.tool_choice,
    temperature: productionTemplate.temperature,
    source: "captured before timing; generated by PrivatePlateAgent"
  });
  console.log("ENV");
  console.log(`model=${modelId} revision=${revision}`);
  console.log(`chat=${CHAT_BASE_URL} rag=${RAG_BASE_URL}`);
  console.log(`prefix flags: ${explicitFlags.off} / ${explicitFlags.on}`);
  console.log(`production tools=${productionTemplate.tools?.length ?? 0} system+context captured`);
}

function commonServerArgs(prefixFlag) {
  return [
    "serve",
    "--model",
    modelSnapshot,
    "--host",
    CHAT_HOST,
    "--port",
    String(CHAT_PORT),
    "--tensor-parallel-size",
    "1",
    "--max-model-len",
    "8192",
    "--kv-cache-memory-bytes",
    "8589934592",
    "--attention-backend",
    "TRITON_ATTN",
    "--enforce-eager",
    "--enable-auto-tool-choice",
    "--tool-call-parser",
    "gemma4",
    "--reasoning-parser",
    "gemma4",
    "--quantization",
    "compressed-tensors",
    "--chat-template",
    chatTemplate,
    "--served-model-name",
    modelId,
    prefixFlag
  ];
}

async function listChatVllmProcesses() {
  const result = await runCommand("ps", ["-eo", "pid=,args="]);
  return result.stdout
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const match = line.match(/^(\d+)\s+(.*)$/);
      return match ? { pid: Number(match[1]), args: match[2] } : null;
    })
    .filter((entry) => entry && /vllm/i.test(entry.args) && /(?:--port\s+8000|--port=8000)/.test(entry.args));
}

async function terminatePids(pids, reason) {
  const results = [];
  for (const entry of pids) {
    const pid = typeof entry === "number" ? entry : entry.pid;
    const before = await listChatVllmProcesses();
    if (!before.some((item) => item.pid === pid)) {
      results.push({ pid, reason, signal: null, exited: true });
      continue;
    }
    let signal = "SIGTERM";
    try {
      process.kill(pid, "SIGTERM");
    } catch (error) {
      results.push({ pid, reason, signal, exited: false, error: String(error) });
      continue;
    }
    for (let i = 0; i < 30; i += 1) {
      await sleep(500);
      if (!(await listChatVllmProcesses()).some((item) => item.pid === pid)) {
        results.push({ pid, reason, signal, exited: true });
        break;
      }
    }
    if ((await listChatVllmProcesses()).some((item) => item.pid === pid)) {
      signal = "SIGKILL";
      try {
        process.kill(pid, "SIGKILL");
      } catch (error) {
        results.push({ pid, reason, signal, exited: false, error: String(error) });
        continue;
      }
      await sleep(1000);
      results.push({
        pid,
        reason,
        signal,
        exited: !(await listChatVllmProcesses()).some((item) => item.pid === pid)
      });
    }
  }
  return results;
}

async function fetchText(url) {
  try {
    const response = await fetch(url, { signal: AbortSignal.timeout(5000) });
    return { ok: response.ok, status: response.status, text: await response.text() };
  } catch (error) {
    return { ok: false, status: 0, text: String(error) };
  }
}

async function waitForServer(child, armDir) {
  const readinessFile = `${armDir}/raw/readiness.jsonl`;
  for (let attempt = 1; attempt <= 180; attempt += 1) {
    if (child.exitCode !== null) {
      throw new Error(`vLLM exited before readiness with code ${child.exitCode}.`);
    }
    const result = await fetchText(`${CHAT_BASE_URL}/models`);
    const record = {
      attempt,
      at: new Date().toISOString(),
      ok: result.ok,
      status: result.status
    };
    await appendJsonl(readinessFile, record);
    if (result.ok) {
      await writeText(`${armDir}/raw/models-response.json`, result.text);
      return;
    }
    if (attempt === 1 || attempt % 10 === 0) {
      console.log(`waiting for ${armDir.split("/").at(-2)} vLLM (${attempt}/180)`);
    }
    await sleep(2000);
  }
  throw new Error("vLLM did not become ready within 6 minutes.");
}

async function snapshotMetrics(armDir, label) {
  const result = await fetchText(`${CHAT_BASE_URL.replace(/\/v1$/, "")}/metrics`);
  const text = result.text;
  await writeText(`${armDir}/raw/metrics-${label}.txt`, text);
  const relevant = text
    .split("\n")
    .filter((line) => /prefix.?cache|cache.?prefix|cached.?prompt/i.test(line))
    .join("\n");
  await writeText(`${armDir}/raw/metrics-${label}-prefix-cache.txt`, `${relevant}\n`);
  return {
    ok: result.ok,
    status: result.status,
    text,
    relevantLines: relevant.split("\n").filter(Boolean)
  };
}

function parseMetricSamples(text) {
  const samples = {};
  for (const line of text.split("\n")) {
    if (!line || line.startsWith("#") || !/prefix.?cache|cache.?prefix|cached.?prompt/i.test(line)) {
      continue;
    }
    const match = line.match(/^([^\s]+)\s+(-?\d+(?:\.\d+)?(?:e[+-]?\d+)?)/i);
    if (match) samples[match[1]] = Number(match[2]);
  }
  return samples;
}

function diffMetricSamples(before, after) {
  const keys = new Set([...Object.keys(before), ...Object.keys(after)]);
  return Object.fromEntries(
    [...keys].sort().map((key) => [key, (after[key] ?? 0) - (before[key] ?? 0)])
  );
}

function startVramSampler(pid, file) {
  const fd = openSync(file, "a");
  const sampler = spawn(
    "/bin/sh",
    [
      "-lc",
      `while kill -0 ${pid} 2>/dev/null; do date -u +%FT%H:%M:%S.%3NZ; rocm-smi --showmeminfo vram --csv 2>&1; sleep 0.2; done`
    ],
    { stdio: ["ignore", fd, fd] }
  );
  sampler.on("close", () => {
    try {
      closeSync(fd);
    } catch {
      // The sampler owns this descriptor after the child exits.
    }
  });
  return sampler;
}

async function processSseResponse(response, requestStartedAt) {
  const rawChunks = [];
  const decoder = new TextDecoder();
  let pending = "";
  let firstEventMs = null;
  let firstNonEmptyDeltaMs = null;
  let usage = null;
  let toolName = "";
  let toolArguments = "";
  let content = "";
  let eventCount = 0;

  const consume = (line) => {
    if (!line.startsWith("data:")) return;
    const payload = line.slice(5).trim();
    if (!payload || payload === "[DONE]") return;
    let event;
    try {
      event = JSON.parse(payload);
    } catch {
      return;
    }
    eventCount += 1;
    const elapsed = performance.now() - requestStartedAt;
    if (firstEventMs === null) firstEventMs = elapsed;
    if (event.usage) usage = event.usage;
    const choice = event.choices?.[0];
    const delta = choice?.delta;
    const deltaHasContent = Boolean(
      delta?.content ||
        delta?.reasoning_content ||
        delta?.tool_calls?.some(
          (toolCall) => toolCall?.function?.name || toolCall?.function?.arguments
        )
    );
    if (deltaHasContent && firstNonEmptyDeltaMs === null) {
      firstNonEmptyDeltaMs = elapsed;
    }
    if (typeof delta?.content === "string") content += delta.content;
    if (typeof delta?.reasoning_content === "string") content += delta.reasoning_content;
    for (const toolCall of delta?.tool_calls ?? []) {
      if (toolCall?.function?.name) toolName += toolCall.function.name;
      if (typeof toolCall?.function?.arguments === "string") {
        toolArguments += toolCall.function.arguments;
      }
    }
    if (choice?.message?.tool_calls?.[0]?.function?.name) {
      toolName += choice.message.tool_calls[0].function.name;
      toolArguments += choice.message.tool_calls[0].function.arguments ?? "";
    }
  };

  if (!response.body) {
    const text = await response.text();
    rawChunks.push(text);
    return { raw: rawChunks.join(""), firstEventMs, firstNonEmptyDeltaMs, usage, toolName, toolArguments, content, eventCount };
  }
  const reader = response.body.getReader();
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    const chunk = decoder.decode(value, { stream: true });
    rawChunks.push(chunk);
    pending += chunk;
    const lines = pending.split(/\r?\n/);
    pending = lines.pop() ?? "";
    for (const line of lines) consume(line);
  }
  pending += decoder.decode();
  if (pending) consume(pending);
  return { raw: rawChunks.join(""), firstEventMs, firstNonEmptyDeltaMs, usage, toolName, toolArguments, content, eventCount };
}

function validateDecision(response, request) {
  const exposed = new Set((request.tools ?? []).map((tool) => tool.function?.name));
  const record = {
    transport: "native_function",
    toolName: response.toolName || null,
    exposedInRequest: response.toolName ? exposed.has(response.toolName) : false,
    rawArguments: response.toolArguments || null,
    normalizedArguments: null,
    goal: null,
    schemaValid: false,
    protocolErrors: [],
    taskObjective: "compose_meal",
    firstPlanningStepExpected: "get_day_context",
    firstPlanningStepMatched: response.toolName === "get_day_context"
  };
  if (!response.toolName) {
    record.transport = response.content ? "content" : "no_response";
    record.protocolErrors.push("no_native_function_call");
    return record;
  }
  if (!AGENT_TOOL_ALLOWLIST.includes(response.toolName) && !isControlDecisionName(response.toolName)) {
    record.protocolErrors.push("tool_not_in_privateplate_allowlist");
    return record;
  }
  if (!record.exposedInRequest) record.protocolErrors.push("tool_not_exposed_in_request");
  try {
    const parsed = JSON.parse(response.toolArguments);
    if (isControlDecisionName(response.toolName)) {
      const decision = parseControlDecisionArguments(response.toolName, parsed);
      record.normalizedArguments = parsed;
      record.goal = decision.goal;
    } else {
      record.normalizedArguments = parseModelToolArguments(response.toolName, parsed);
      record.goal = parseModelToolGoal(response.toolName, parsed);
    }
    record.schemaValid = true;
  } catch (error) {
    record.protocolErrors.push(
      `schema_invalid:${error instanceof Error ? error.message : String(error)}`
    );
  }
  return record;
}

async function sendMeasuredRequest(request, requestFile, responseFile) {
  await writeJson(requestFile, request);
  const started = performance.now();
  let response;
  try {
    response = await fetch(`${CHAT_BASE_URL}/chat/completions`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(request),
      signal: AbortSignal.timeout(180000)
    });
  } catch (error) {
    const e2eMs = performance.now() - started;
    const failure = {
      httpOk: false,
      status: 0,
      error: String(error),
      e2eMs,
      ttftMs: null,
      promptTokens: null,
      outputTokens: null,
      outputTokensPerSecond: null,
      quality: { protocolErrors: ["http_error"], schemaValid: false }
    };
    await writeJson(responseFile, failure);
    return failure;
  }
  if (!response.ok) {
    const body = await response.text();
    const e2eMs = performance.now() - started;
    const failure = {
      httpOk: false,
      status: response.status,
      error: body.slice(0, 2000),
      e2eMs,
      ttftMs: null,
      promptTokens: null,
      outputTokens: null,
      outputTokensPerSecond: null,
      quality: { protocolErrors: ["http_error"], schemaValid: false }
    };
    await writeText(responseFile, body);
    return failure;
  }
  const stream = await processSseResponse(response, started);
  const e2eMs = performance.now() - started;
  await writeText(responseFile, stream.raw);
  const promptTokens = Number.isFinite(stream.usage?.prompt_tokens)
    ? Number(stream.usage.prompt_tokens)
    : null;
  const outputTokens = Number.isFinite(stream.usage?.completion_tokens)
    ? Number(stream.usage.completion_tokens)
    : null;
  const ttftMs = stream.firstNonEmptyDeltaMs ?? stream.firstEventMs;
  const decodeMs = ttftMs === null ? null : Math.max(0, e2eMs - ttftMs);
  const quality = validateDecision(stream, request);
  return {
    httpOk: true,
    status: response.status,
    e2eMs,
    ttftMs,
    ttftSource: stream.firstNonEmptyDeltaMs === null ? "first_event_fallback" : "first_nonempty_delta",
    firstEventMs: stream.firstEventMs,
    eventCount: stream.eventCount,
    promptTokens,
    outputTokens,
    totalTokens: Number.isFinite(stream.usage?.total_tokens) ? Number(stream.usage.total_tokens) : null,
    outputTokensPerSecond:
      outputTokens !== null && decodeMs !== null && decodeMs > 0
        ? outputTokens / (decodeMs / 1000)
        : null,
    toolName: stream.toolName || null,
    contentPresent: Boolean(stream.content),
    quality
  };
}

function percentile(values, fraction) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.max(0, Math.ceil(sorted.length * fraction) - 1)];
}

function armStats(records) {
  const measured = records.filter((record) => record.measured);
  const number = (key) => measured.map((record) => record[key]).filter((value) => Number.isFinite(value));
  const ttft = number("ttftMs");
  const e2e = number("e2eMs");
  const outputRate = number("outputTokensPerSecond");
  const qualityErrors = measured.flatMap((record) => record.quality?.protocolErrors ?? []);
  const validDecisions = measured.filter((record) => record.quality?.schemaValid && record.quality?.exposedInRequest).length;
  const firstStepMatches = measured.filter((record) => record.quality?.firstPlanningStepMatched).length;
  return {
    measuredRequests: measured.length,
    completedRequests: measured.filter((record) => record.httpOk).length,
    httpErrors: measured.filter((record) => !record.httpOk).length,
    ttftMs: { p50: percentile(ttft, 0.5), p90: percentile(ttft, 0.9), samples: ttft.length },
    e2eMs: { p50: percentile(e2e, 0.5), p90: percentile(e2e, 0.9), samples: e2e.length },
    promptTokens: { p50: percentile(number("promptTokens"), 0.5), samples: number("promptTokens").length },
    outputTokens: { p50: percentile(number("outputTokens"), 0.5), samples: number("outputTokens").length },
    outputTokensPerSecond: { p50: percentile(outputRate, 0.5), samples: outputRate.length },
    quality: {
      validDecisionRate: measured.length ? validDecisions / measured.length : 0,
      firstPlanningStepRate: measured.length ? firstStepMatches / measured.length : 0,
      protocolErrors: qualityErrors
    }
  };
}

async function readVramSummary(file) {
  try {
    const text = await fs.readFile(file, "utf8");
    const values = [...text.matchAll(/Used Memory \(Bytes\)[^\n]*[, ](\d+)/gi)].map((match) => Number(match[1]));
    return {
      samples: values.length,
      peakUsedBytes: values.length ? Math.max(...values) : null,
      rawParser: "Used Memory (Bytes) line",
      unavailableReason: values.length ? null : "rocm-smi output format did not expose a parseable Used Memory (Bytes) value"
    };
  } catch (error) {
    return { samples: 0, peakUsedBytes: null, unavailableReason: String(error) };
  }
}

async function snapshotVram(file) {
  const result = await runCommand("rocm-smi", ["--showmeminfo", "vram", "--csv"]);
  await writeText(file, `${result.stdout}${result.stderr}`);
}

async function runArm(label, prefixFlag, template) {
  const armDir = `${outputDir}/arms/${label}`;
  await mkdir(`${armDir}/raw/requests`);
  const args = commonServerArgs(prefixFlag);
  const oldProcesses = await listChatVllmProcesses();
  await writeJson(`${armDir}/preexisting-chat-vllm.json`, oldProcesses);
  const stoppedBefore = await terminatePids(oldProcesses, "before_new_arm");
  await writeJson(`${armDir}/preexisting-chat-vllm-stop.json`, stoppedBefore);

  const vllmLog = createWriteStream(`${armDir}/raw/vllm.log`, { flags: "a" });
  const child = spawn(VLLM_BIN, args, {
    cwd: process.cwd(),
    env: offlineEnv,
    stdio: ["ignore", "pipe", "pipe"]
  });
  child.stdout.pipe(vllmLog);
  child.stderr.pipe(vllmLog);
  const command = [VLLM_BIN, ...args].map((value) => JSON.stringify(value)).join(" ");
  await writeText(`${armDir}/start-command.txt`, `${command}\n`);
  await writeJson(`${armDir}/launch.json`, {
    arm: label,
    prefixFlag,
    pid: child.pid,
    command: [VLLM_BIN, ...args],
    modelSnapshot,
    servedModelName: modelId,
    revisionPassedToServer: false,
    offlineEnvironment: {
      HF_HOME: offlineEnv.HF_HOME,
      HF_HUB_CACHE: offlineEnv.HF_HUB_CACHE,
      HUGGINGFACE_HUB_CACHE: offlineEnv.HUGGINGFACE_HUB_CACHE,
      HF_HUB_OFFLINE: offlineEnv.HF_HUB_OFFLINE,
      TRANSFORMERS_OFFLINE: offlineEnv.TRANSFORMERS_OFFLINE
    },
    invariants: commonServerArgs("<PREFIX_CACHING_FLAG>").filter((value) => value !== "<PREFIX_CACHING_FLAG>"),
    startedAt: new Date().toISOString(),
    concurrency: 1,
    maxTokens: MAX_TOKENS
  });
  await sleep(1000);
  let procCmdline = "unavailable";
  try {
    procCmdline = (await fs.readFile(`/proc/${child.pid}/cmdline`, "utf8")).replaceAll("\0", " ").trim();
  } catch (error) {
    procCmdline = `unavailable: ${String(error)}`;
  }
  const ps = await runCommand("ps", ["-p", String(child.pid), "-o", "pid=,args="]);
  await writeJson(`${armDir}/process-start.json`, { pid: child.pid, procCmdline, ps: ps.stdout.trim() });

  const records = [];
  let sampler;
  let summary;
  try {
    await waitForServer(child, armDir);
    await snapshotVram(`${armDir}/raw/vram-after-load.txt`);
    const metricsBefore = await snapshotMetrics(armDir, "before");
    sampler = startVramSampler(child.pid, `${armDir}/raw/vram-samples.log`);
    const primerRequest = makeMeasuredRequest(template, "primer");
    const primer = await sendMeasuredRequest(
      primerRequest,
      `${armDir}/raw/requests/primer-request.json`,
      `${armDir}/raw/requests/primer-response.sse`
    );
    const primerRecord = { arm: label, stage: "primer", measured: false, ...primer };
    records.push(primerRecord);
    await appendJsonl(`${armDir}/requests.jsonl`, primerRecord);
    await snapshotMetrics(armDir, "after-primer");
    for (let index = 1; index <= MEASURED_REQUESTS; index += 1) {
      const suffix = `measured-${String(index).padStart(2, "0")}`;
      const request = makeMeasuredRequest(template, suffix);
      const record = await sendMeasuredRequest(
        request,
        `${armDir}/raw/requests/${suffix}-request.json`,
        `${armDir}/raw/requests/${suffix}-response.sse`
      );
      const fullRecord = { arm: label, stage: "measured", measured: true, index, suffix, ...record };
      records.push(fullRecord);
      await appendJsonl(`${armDir}/requests.jsonl`, fullRecord);
      await appendJsonl(`${outputDir}/requests.jsonl`, fullRecord);
      console.log(`${label} ${suffix}: ttft=${record.ttftMs === null ? "unavailable" : `${record.ttftMs.toFixed(1)}ms`} e2e=${record.e2eMs.toFixed(1)}ms tool=${record.toolName ?? "none"}`);
    }
    const metricsAfter = await snapshotMetrics(armDir, "after-measured");
    await snapshotVram(`${armDir}/raw/vram-after-window.txt`);
    const metricBefore = parseMetricSamples(metricsBefore.text);
    const metricAfter = parseMetricSamples(metricsAfter.text);
    const metricDelta = diffMetricSamples(metricBefore, metricAfter);
    const prefixKeys = Object.keys(metricDelta).filter((key) => /prefix.?cache|cache.?prefix|cached.?prompt/i.test(key));
    const requestStats = armStats(records);
    summary = {
      arm: label,
      prefixFlag,
      status:
        requestStats.measuredRequests === MEASURED_REQUESTS &&
        requestStats.completedRequests === MEASURED_REQUESTS
          ? "PASS"
          : "FAIL",
      process: { pid: child.pid, procCmdline },
      requests: requestStats,
      metrics: {
        rawFiles: {
          before: "raw/metrics-before.txt",
          afterPrimer: "raw/metrics-after-primer.txt",
          afterMeasured: "raw/metrics-after-measured.txt",
          prefixCacheFiltered: "raw/metrics-after-measured-prefix-cache.txt"
        },
        prefixCacheMetricNames: prefixKeys,
        before: metricBefore,
        afterMeasured: metricAfter,
        deltaAcrossWindow: Object.fromEntries(prefixKeys.map((key) => [key, metricDelta[key]])),
        queriesDelta: prefixKeys.filter((key) => /quer/i.test(key)).reduce((sum, key) => sum + metricDelta[key], 0),
        hitsDelta: prefixKeys.filter((key) => /hit/i.test(key)).reduce((sum, key) => sum + metricDelta[key], 0),
        cachedPromptTokenDelta: prefixKeys.filter((key) => /cached|prompt.*token|token.*prompt/i.test(key)).reduce((sum, key) => sum + metricDelta[key], 0),
        cacheConfig: "see launch.json, process-start.json, vllm.log and raw metrics"
      },
      vram: {
        afterLoadFile: "raw/vram-after-load.txt",
        afterWindowFile: "raw/vram-after-window.txt",
        requestWindow: await readVramSummary(`${armDir}/raw/vram-samples.log`)
      },
      fallbackUsed: false,
      formatRetries: 0,
      deterministicFallbacks: 0,
      errorCodes: records.filter((record) => !record.httpOk).map((record) => record.status || "HTTP_ERROR")
    };
  } catch (error) {
    const failure = {
      arm: label,
      prefixFlag,
      status: "FAIL",
      failure: String(error),
      requests: armStats(records),
      fallbackUsed: false,
      formatRetries: 0,
      deterministicFallbacks: 0
    };
    await writeJson(`${armDir}/summary.json`, failure);
    summary = failure;
  } finally {
    if (sampler) sampler.kill("SIGTERM");
    await snapshotVram(`${armDir}/raw/vram-final.txt`).catch(() => undefined);
    await terminatePids([{ pid: child.pid }], "end_of_arm");
    vllmLog.end();
  }
  await writeJson(`${armDir}/summary.json`, summary);
  return summary;
}

function percentChange(a, b) {
  if (!Number.isFinite(a) || !Number.isFinite(b) || a === 0) return null;
  return ((b - a) / a) * 100;
}

function comparison(a, b) {
  const aStats = a?.requests;
  const bStats = b?.requests;
  const bErrors = bStats?.quality?.protocolErrors ?? [];
  const aErrors = aStats?.quality?.protocolErrors ?? [];
  const cacheQueries = b?.metrics?.queriesDelta ?? 0;
  const cacheHits = b?.metrics?.hitsDelta ?? 0;
  const cachedPromptTokens = b?.metrics?.cachedPromptTokenDelta ?? 0;
  const cacheEvidence = cacheQueries > 0 || cacheHits > 0 || cachedPromptTokens > 0;
  const qualityNotLower =
    (bStats?.quality?.validDecisionRate ?? 0) >= (aStats?.quality?.validDecisionRate ?? 0) &&
    bErrors.length <= aErrors.length &&
    (bStats?.httpErrors ?? 0) <= (aStats?.httpErrors ?? 0);
  const ttftImproved =
    Number.isFinite(aStats?.ttftMs?.p50) &&
    Number.isFinite(bStats?.ttftMs?.p50) &&
    bStats.ttftMs.p50 < aStats.ttftMs.p50;
  const adoptable = Boolean(cacheEvidence && qualityNotLower && ttftImproved);
  return {
    status: adoptable ? "ADOPTABLE_CANDIDATE" : cacheEvidence ? "CACHE_ACTIVE_NO_ADOPTION" : "NO_CACHE_HIT_EVIDENCE",
    sampleCount: { A: aStats?.measuredRequests ?? 0, B: bStats?.measuredRequests ?? 0 },
    primary: {
      ttftP50Ms: { A: aStats?.ttftMs?.p50 ?? null, B: bStats?.ttftMs?.p50 ?? null, percentChange: percentChange(aStats?.ttftMs?.p50, bStats?.ttftMs?.p50) },
      ttftP90Ms: { A: aStats?.ttftMs?.p90 ?? null, B: bStats?.ttftMs?.p90 ?? null, percentChange: percentChange(aStats?.ttftMs?.p90, bStats?.ttftMs?.p90) },
      e2eP50Ms: { A: aStats?.e2eMs?.p50 ?? null, B: bStats?.e2eMs?.p50 ?? null, percentChange: percentChange(aStats?.e2eMs?.p50, bStats?.e2eMs?.p50) }
    },
    secondary: {
      outputTokensPerSecondP50: { A: aStats?.outputTokensPerSecond?.p50 ?? null, B: bStats?.outputTokensPerSecond?.p50 ?? null, percentChange: percentChange(aStats?.outputTokensPerSecond?.p50, bStats?.outputTokensPerSecond?.p50) },
      promptTokensP50: { A: aStats?.promptTokens?.p50 ?? null, B: bStats?.promptTokens?.p50 ?? null, percentChange: percentChange(aStats?.promptTokens?.p50, bStats?.promptTokens?.p50) }
    },
    prefixCacheEvidence: {
      queriesDeltaB: cacheQueries,
      hitsDeltaB: cacheHits,
      cachedPromptTokenDeltaB: cachedPromptTokens,
      metricNamesB: b?.metrics?.prefixCacheMetricNames ?? [],
      actualHitEvidence: cacheEvidence
    },
    quality: {
      A: aStats?.quality ?? null,
      B: bStats?.quality ?? null,
      qualityNotLower,
      newErrorsInB: bErrors.filter((error) => !aErrors.includes(error))
    },
    limits: [
      "Timing uses streaming replay of the real production request shape; the measured requests do not execute Domain tools.",
      "There are 10 measured serial requests per arm plus one uncounted primer; this is not a statistical performance characterization.",
      "TTFT is the primary signal. Output tokens/s is reported but is not used as a prefix-cache failure criterion.",
      "A separate vLLM process is started for each arm; process-local prefix cache is not shared across arms."
    ],
    decisionRule: "B is adoptable only when quality is not lower, B adds no errors, prefix cache metrics show activity, and TTFT p50 improves."
  };
}

function markdownComparison(result) {
  const p = result.primary;
  const cache = result.prefixCacheEvidence;
  return [
    "# PrivatePlate Prefix Caching A/B",
    "",
    `- status: **${result.status}**`,
    `- measured samples: A=${result.sampleCount.A}, B=${result.sampleCount.B}`,
    "",
    "## Primary latency",
    "",
    "| Metric | A OFF | B ON | Change B vs A |",
    "| --- | ---: | ---: | ---: |",
    `| TTFT p50 (ms) | ${p.ttftP50Ms.A ?? "unavailable"} | ${p.ttftP50Ms.B ?? "unavailable"} | ${p.ttftP50Ms.percentChange === null ? "unavailable" : `${p.ttftP50Ms.percentChange.toFixed(2)}%`} |`,
    `| TTFT p90 (ms) | ${p.ttftP90Ms.A ?? "unavailable"} | ${p.ttftP90Ms.B ?? "unavailable"} | ${p.ttftP90Ms.percentChange === null ? "unavailable" : `${p.ttftP90Ms.percentChange.toFixed(2)}%`} |`,
    `| E2E p50 (ms) | ${p.e2eP50Ms.A ?? "unavailable"} | ${p.e2eP50Ms.B ?? "unavailable"} | ${p.e2eP50Ms.percentChange === null ? "unavailable" : `${p.e2eP50Ms.percentChange.toFixed(2)}%`} |`,
    "",
    "## Cache evidence",
    "",
    `- B prefix-cache queries delta: ${cache.queriesDeltaB}`,
    `- B prefix-cache hits delta: ${cache.hitsDeltaB}`,
    `- B cached prompt-token delta: ${cache.cachedPromptTokenDeltaB}`,
    `- metric names: ${cache.metricNamesB.length ? cache.metricNamesB.join(", ") : "unavailable"}`,
    `- actual hit evidence: ${cache.actualHitEvidence ? "yes" : "no"}`,
    "",
    "## Quality and limits",
    "",
    `- quality not lower: ${result.quality.qualityNotLower ? "yes" : "no"}`,
    `- new B errors: ${result.quality.newErrorsInB.length ? result.quality.newErrorsInB.join(", ") : "none"}`,
    ...result.limits.map((line) => `- ${line}`),
    "",
    `Conclusion: ${result.decisionRule}`,
    ""
  ].join("\n");
}

async function writeAGateFailure(a) {
  const b = {
    arm: "b-on",
    prefixFlag: "--enable-prefix-caching",
    status: "NOT_STARTED_AFTER_A_FAILURE",
    failure: "B was not started because A did not reach a complete measured run.",
    requests: {
      measuredRequests: 0,
      completedRequests: 0,
      httpErrors: 0
    },
    fallbackUsed: false,
    formatRetries: 0,
    deterministicFallbacks: 0
  };
  const result = {
    status: "INFRASTRUCTURE_BLOCKED",
    stage: "A_READINESS_OR_MEASUREMENT_GATE",
    sampleCount: {
      A: a?.requests?.measuredRequests ?? 0,
      B: 0
    },
    arms: { A: a, B: b },
    prefixCacheEvidence: {
      actualHitEvidence: false,
      reason: "B was not started; no valid A/B request window exists."
    },
    conclusion: "A did not complete the required primer plus 10 measured requests, so B was correctly not started.",
    limits: [
      "This retry is limited to one run; no further infrastructure retry is permitted.",
      "No prefix-cache latency or quality conclusion is valid from this blocked run."
    ]
  };
  await writeJson(`${outputDir}/arms/b-on/summary.json`, b);
  await writeJson(`${outputDir}/comparison.json`, result);
  await writeText(
    `${outputDir}/comparison.md`,
    `# PrivatePlate Prefix Caching A/B\n\nStatus: **INFRASTRUCTURE_BLOCKED**\n\nA did not complete the required primer plus 10 measured requests; B was not started.\n`
  );
  return result;
}

async function main() {
  await mkdir(outputDir);
  try {
    await validateLocalModelSnapshot();
    const captured = await captureProductionRequest();
    await collectEnvironment(captured.request);
    if (prepareOnly) {
      await writeJson(`${outputDir}/prepare-only.json`, {
        status: "READY_FOR_ATTACH",
        abStarted: false,
        sessionRequirement: "pp-prefix-ab",
        preparedAt: new Date().toISOString()
      });
      console.log("A/B NOT STARTED — attach to tmux and confirm recording before continuing.");
      return;
    }
    console.log("A OFF");
    const a = await runArm("a-off", "--no-enable-prefix-caching", captured.request);
    if (a.status !== "PASS") {
      console.log("A FAILED — B NOT STARTED");
      const blocked = await writeAGateFailure(a);
      console.log(`status=${blocked.status}`);
      console.log("CLEANUP");
      return;
    }
    console.log("B ON");
    const b = await runArm("b-on", "--enable-prefix-caching", captured.request);
    console.log("COMPARISON");
    const result = comparison(a, b);
    await writeJson(`${outputDir}/comparison.json`, result);
    await writeText(`${outputDir}/comparison.md`, markdownComparison(result));
    console.log(`status=${result.status}`);
    console.log(`TTFT p50 A=${result.primary.ttftP50Ms.A ?? "unavailable"}ms B=${result.primary.ttftP50Ms.B ?? "unavailable"}ms`);
    console.log(`cache evidence=${result.prefixCacheEvidence.actualHitEvidence ? "yes" : "no"}`);
    console.log("CLEANUP");
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    await writeJson(`${outputDir}/comparison.json`, {
      status: "INFRASTRUCTURE_BLOCKED",
      stage: "LOCAL_MODEL_PREFLIGHT",
      sampleCount: { A: 0, B: 0 },
      error: message,
      prefixCacheEvidence: {
        actualHitEvidence: false,
        reason: "A/B did not start because local snapshot preflight failed."
      },
      conclusion: "No A/B conclusion is valid from this retry."
    });
    await writeText(
      `${outputDir}/comparison.md`,
      `# PrivatePlate Prefix Caching A/B\n\nStatus: **INFRASTRUCTURE_BLOCKED**\n\nLocal model snapshot preflight failed; A/B was not started.\n`
    );
    throw error;
  }
}

main().catch(async (error) => {
  await writeJson(`${outputDir}/runner-failure.json`, {
    status: "FAIL",
    error: error instanceof Error ? error.stack ?? error.message : String(error),
    at: new Date().toISOString()
  }).catch(() => undefined);
  console.error(error instanceof Error ? error.stack ?? error.message : String(error));
  process.exitCode = 1;
});
