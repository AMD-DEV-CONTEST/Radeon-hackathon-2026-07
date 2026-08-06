#!/usr/bin/env node

import { promises as fs } from "node:fs";
import { createWriteStream } from "node:fs";
import { spawn } from "node:child_process";
import { performance } from "node:perf_hooks";
import { promisify } from "node:util";

import {
  OpenAiCompatibleToolProvider,
  PrivatePlateAgent
} from "../../packages/agent-runtime/dist/index.js";
import { PrivatePlateDomain } from "../../packages/domain/dist/index.js";

const execFile = promisify((await import("node:child_process")).execFile);
const args = parseArgs(process.argv.slice(2));
const outputDir = pathValue(args.out);
const modelId = args.model ?? "google/gemma-4-12B-it-qat-w4a16-ct";
const revision = args.revision ?? "1d2c2d7f2466070e69d6fb3fd5ce9a7d75f2f6ee";
const modelSnapshot =
  args["model-snapshot"] ??
  `/root/.cache/huggingface/hub/models--google--gemma-4-12B-it-qat-w4a16-ct/snapshots/${revision}`;
const chatTemplate =
  args["chat-template"] ??
  `${process.cwd()}/scripts/c0/stage-b/chat-templates/gemma4-vllm-tool.jinja`;
const sourceStatePath = args["source-state"];
const vllmBin = process.env.PP_VLLM_BIN ?? "/opt/venv/bin/vllm";
const pythonBin = process.env.PP_PYTHON_BIN ?? "/opt/venv/bin/python3";
const chatBaseUrl = args["base-url"] ?? "http://127.0.0.1:8000/v1";
const ragBaseUrl = args["embedding-base-url"] ?? "http://127.0.0.1:8001/v1";
const chatRootUrl = chatBaseUrl.replace(/\/v1\/?$/, "");
const repeats = 3;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const scenarios = [
  {
    id: "basic-planning",
    setup: null,
    input: "请根据三位家庭成员今天的剩余额度、库存和偏好，规划今天的午餐。"
  },
  {
    id: "meal-completion",
    setup: "规划今天的午餐。",
    input: "这顿饭吃完了，先预览餐后记录。"
  },
  {
    id: "rag-caregiver-preview",
    setup: "规划今天的午餐。",
    input: "先查一下本地晚餐准备规则，再生成给阿姨看的任务卡，先不要发送。"
  }
];
const offlineEnv = {
  ...process.env,
  HF_HOME: "/root/.cache/huggingface",
  HF_HUB_CACHE: "/root/.cache/huggingface/hub",
  HUGGINGFACE_HUB_CACHE: "/root/.cache/huggingface/hub",
  HF_HUB_OFFLINE: "1",
  TRANSFORMERS_OFFLINE: "1",
  PRIVATEPLATE_RAG_MODE: "vllm",
  PRIVATEPLATE_EMBEDDING_BASE_URL: ragBaseUrl
};

process.env.PRIVATEPLATE_RAG_MODE = "vllm";
process.env.PRIVATEPLATE_EMBEDDING_BASE_URL = ragBaseUrl;

if (!outputDir) throw new Error("Missing required --out <directory>.");
if (args["regenerate-derived"]) {
  await regenerateDerivedReports(outputDir);
  process.exit(0);
}
if (!isLoopbackUrl(chatBaseUrl) || !isLoopbackUrl(ragBaseUrl)) {
  throw new Error("Chat and RAG endpoints must be loopback URLs.");
}

const modelHttp = [];
let activeHttpContext = null;
let activeGatewayCapture = null;
const runStartedAt = new Date().toISOString();

await mkdir(outputDir);
console.log("========== ENV ==========");
await validateLocalSnapshot();
const environment = await writeEnvironment();
console.log(`hostname=${environment.runtime.hostname}`);
console.log(`gpu=${environment.runtime.hardware.product}`);
console.log(`vram=${environment.runtime.hardware.vram}`);
console.log(`torchHip=${environment.runtime.torchHip}`);
console.log(`model=${environment.model.id} revision=${environment.model.revision}`);
console.log(`chatTemplate=${environment.model.chatTemplate}`);
console.log("APC=--enable-prefix-caching (A and B)");
console.log("variable=PRIVATEPLATE_FINALIZATION_MODE only");

const armResults = {};
for (const [arm, mode] of [
  ["a-model", "model"],
  ["b-trusted-presenter", "trusted_presenter"]
]) {
  console.log(
    arm === "a-model"
      ? "========== A MODEL =========="
      : "========== B TRUSTED PRESENTER =========="
  );
  armResults[arm] = await runArm(arm, mode);
}

const comparison = buildComparison(armResults);
await writeJson(`${outputDir}/comparison.json`, comparison);
await writeText(`${outputDir}/comparison.md`, renderComparisonMarkdown(comparison));
await writeJson(`${outputDir}/model-http.json`, modelHttp);
await writeJson(`${outputDir}/summary.json`, {
  status: comparison.status,
  runStartedAt,
  finishedAt: new Date().toISOString(),
  arms: armResults,
  comparison
});
console.log("========== COMPARISON ==========");
console.log(`status=${comparison.status}`);
console.log(
  `target model calls A=${comparison.targetModelCalls.A} B=${comparison.targetModelCalls.B}`
);
console.log(
  `target E2E p50 A=${comparison.targetE2eMs.A.p50}ms B=${comparison.targetE2eMs.B.p50}ms`
);
console.log("========== CLEANUP ==========");
for (const arm of Object.values(armResults)) {
  console.log(
    `${arm.arm}: exited=${arm.cleanup?.exited === true} chat8000Remaining=${arm.cleanup?.after?.length ?? "unavailable"}`
  );
}
console.log("raw JSONL and logs saved; old benchmark directories were not touched");
console.log("CLEANUP COMPLETE");

async function runArm(arm, finalizationMode) {
  const armDir = `${outputDir}/arms/${arm}`;
  await mkdir(`${armDir}/raw`);
  await mkdir(`${armDir}/scenario-databases`);
  await mkdir(`${outputDir}/tasks/${arm}`);
  const startArgs = serverArgs();
  const childEnv = {
    ...offlineEnv,
    PRIVATEPLATE_FINALIZATION_MODE: finalizationMode
  };
  const armRecord = {
    arm,
    finalizationMode,
    prefixCaching: "--enable-prefix-caching",
    status: "running",
    tasks: [],
    setupTurns: [],
    modelHttpRequests: 0,
    process: null,
    cleanup: null
  };
  await writeText(
    `${armDir}/start-command.txt`,
    `${formatEnvForEvidence(childEnv)} ${vllmBin} ${startArgs.join(" ")}\n`
  );

  let child = null;
  let logStream = null;
  let baseDomain = null;
  const previousFinalizationMode = process.env.PRIVATEPLATE_FINALIZATION_MODE;
  process.env.PRIVATEPLATE_FINALIZATION_MODE = finalizationMode;
  try {
    const occupied = await listChatVllmProcesses();
    if (occupied.length > 0) {
      throw new Error("Chat port 8000 is occupied before arm startup.");
    }

    logStream = createWriteStream(`${armDir}/raw/vllm.log`, { flags: "w" });
    child = spawn(vllmBin, startArgs, {
      cwd: process.cwd(),
      env: childEnv,
      detached: true,
      stdio: ["ignore", "pipe", "pipe"]
    });
    child.stdout.pipe(logStream);
    child.stderr.pipe(logStream);
    armRecord.process = {
      pid: child.pid ?? null,
      command: [vllmBin, ...startArgs]
    };
    await writeJson(`${armDir}/launch.json`, {
      arm,
      finalizationMode,
      prefixFlag: "--enable-prefix-caching",
      modelSnapshot,
      servedModelName: modelId,
      revisionPassedToServer: false,
      offlineEnvironment: pickOfflineEnvironment(childEnv),
      command: [vllmBin, ...startArgs]
    });
    await waitForServer(child, armDir);
    const processStart = (await listChatVllmProcesses()).find(
      (item) => item.pid === child.pid || item.args.includes(`--port 8000`)
    );
    await writeJson(`${armDir}/process-start.json`, {
      childPid: child.pid ?? null,
      observed: processStart ?? null
    });

    await writeText(
      `${armDir}/raw/vram-after-load.txt`,
      await commandOutput("rocm-smi", [
        "--showproductname",
        "--showdriverversion",
        "--showmeminfo",
        "vram",
        "--csv"
      ])
    );
    await writeMetrics(armDir, "before");
    await runPrimer(arm, armDir);

    baseDomain = await PrivatePlateDomain.create(":memory:");
    for (const scenario of scenarios) {
      for (let iteration = 1; iteration <= repeats; iteration += 1) {
        const task = await runTask(
          arm,
          finalizationMode,
          scenario,
          iteration,
          baseDomain,
          armDir
        );
        armRecord.tasks.push(task);
        await appendJsonl(`${outputDir}/tasks.jsonl`, task);
      }
    }
    await writeMetrics(armDir, "after");
    await writeText(
      `${armDir}/raw/vram-after-window.txt`,
      await commandOutput("rocm-smi", [
        "--showproductname",
        "--showdriverversion",
        "--showmeminfo",
        "vram",
        "--csv"
      ])
    );
    armRecord.status = armRecord.tasks.every((task) => task.evaluation.status === "PASS")
      ? "PASS"
      : "FAIL";
  } catch (error) {
    armRecord.status = "INFRASTRUCTURE_FAILED";
    armRecord.error = serializeError(error);
  } finally {
    if (baseDomain) baseDomain.close();
    if (child) {
      armRecord.cleanup = await stopChild(child, armDir);
    } else {
      armRecord.cleanup = { stopped: false, reason: "not_started" };
    }
    if (logStream) logStream.end();
    if (previousFinalizationMode === undefined) {
      delete process.env.PRIVATEPLATE_FINALIZATION_MODE;
    } else {
      process.env.PRIVATEPLATE_FINALIZATION_MODE = previousFinalizationMode;
    }
    armRecord.modelHttpRequests = modelHttp.filter(
      (item) => item.arm === arm
    ).length;
    await writeJson(`${armDir}/summary.json`, armRecord);
  }
  return armRecord;
}

async function runTask(
  arm,
  finalizationMode,
  scenario,
  iteration,
  baseDomain,
  armDir
) {
  const taskId = `${scenario.id}-${String(iteration).padStart(2, "0")}`;
  const dbPath = `${armDir}/scenario-databases/${taskId}.sqlite`;
  baseDomain.db.exec(`VACUUM INTO '${sqliteLiteral(dbPath)}'`);
  const domain = await PrivatePlateDomain.create(dbPath);
  const provider = new OpenAiCompatibleToolProvider({
    baseUrl: chatBaseUrl,
    model: modelId,
    ...(process.env.PRIVATEPLATE_VLLM_API_KEY
      ? { apiKey: process.env.PRIVATEPLATE_VLLM_API_KEY }
      : {}),
    timeoutMs: 120_000,
    fetchImpl: recordingFetch
  });
  const agent = new PrivatePlateAgent(
    domain,
    `terminal-finalization-${arm}-${taskId}`,
    provider
  );
  attachGatewayRecorder(agent);
  const task = {
    taskId,
    scenarioId: scenario.id,
    iteration,
    finalizationMode,
    setup: null,
    target: null,
    evaluation: null
  };
  try {
    if (scenario.setup) {
      task.setup = await runTurn({
        arm,
        taskId,
        scenarioId: scenario.id,
        phase: "setup",
        input: scenario.setup,
        agent,
        domain
      });
    }
    task.target = await runTurn({
      arm,
      taskId,
      scenarioId: scenario.id,
      phase: "target",
      input: scenario.input,
      agent,
      domain
    });
    task.evaluation = evaluateTask(task);
  } catch (error) {
    task.evaluation = {
      status: "FAIL",
      reason: "task_runner_error",
      error: serializeError(error)
    };
  } finally {
    domain.close();
  }
  return task;
}

async function runTurn({ arm, taskId, scenarioId, phase, input, agent, domain }) {
  const httpStart = modelHttp.length;
  const capture = { toolInvocations: [] };
  const before = snapshot(domain, agent);
  const started = performance.now();
  activeHttpContext = { arm, taskId, phase };
  activeGatewayCapture = capture;
  let result = null;
  let error = null;
  try {
    result = await agent.handleUserMessage(input);
  } catch (caught) {
    error = serializeError(caught);
  } finally {
    activeGatewayCapture = null;
    activeHttpContext = null;
  }
  const after = snapshot(domain, agent);
  const row = {
    arm,
    taskId,
    scenarioId,
    phase,
    input,
    durationMs: round(performance.now() - started),
    modelHttp: modelHttp.slice(httpStart),
    modelHttpCount: modelHttp.length - httpStart,
    modelSteps: pairModelSteps(result?.modelSteps ?? [], capture.toolInvocations),
    modelTrace: sanitize(result?.modelTrace),
    finalizationMode: result?.finalizationMode ?? null,
    toolInvocations: sanitize(capture.toolInvocations),
    answer: result?.answer ?? null,
    phaseAfter: result?.phase ?? agent.state.phase,
    validation: {
      ok: result?.validationOk ?? false,
      reasons: result?.validationReasons ?? []
    },
    taskOutcome: sanitize(result?.taskOutcome),
    uiOnly: sanitize(result?.uiOnly),
    stateBefore: before,
    stateAfter: after,
    taskState: sanitize(agent.getTaskState()),
    retrievalSourceIds: agent.getLastRetrievalIds(),
    error
  };
  await writeJson(
    `${outputDir}/tasks/${arm}/${taskId}-${phase}.json`,
    row
  );
  return row;
}

async function runPrimer(arm, armDir) {
  const body = {
    model: modelId,
    messages: [
      {
        role: "system",
        content: "PrivatePlate local model warm-up. Return a short acknowledgement."
      },
      { role: "user", content: "准备开始本轮本地模型测量。" }
    ],
    temperature: 0,
    max_tokens: 8,
    stream: false
  };
  const started = performance.now();
  let response;
  let error = null;
  try {
    response = await fetch(`${chatBaseUrl}/chat/completions`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(120_000)
    });
    const text = await response.text();
    await writeText(`${armDir}/raw/primer-response.json`, text);
    await writeJson(`${armDir}/raw/primer-request.json`, body);
    await appendJsonl(`${outputDir}/primer.jsonl`, {
      arm,
      status: response.status,
      ok: response.ok,
      durationMs: round(performance.now() - started)
    });
  } catch (caught) {
    error = serializeError(caught);
    await appendJsonl(`${outputDir}/primer.jsonl`, {
      arm,
      ok: false,
      durationMs: round(performance.now() - started),
      error
    });
  }
}

async function recordingFetch(input, init) {
  const started = performance.now();
  const request = {
    url: String(input),
    method: init?.method ?? "GET",
    headers: sanitizeHeaders(init?.headers),
    body: parseJson(init?.body)
  };
  try {
    const response = await fetch(input, init);
    const bodyText = await response.clone().text();
    modelHttp.push({
      ...(activeHttpContext ?? { arm: "unavailable", taskId: "unavailable", phase: "unavailable" }),
      request,
      response: {
        status: response.status,
        ok: response.ok,
        body: parseJson(bodyText)
      },
      durationMs: round(performance.now() - started)
    });
    return response;
  } catch (error) {
    modelHttp.push({
      ...(activeHttpContext ?? { arm: "unavailable", taskId: "unavailable", phase: "unavailable" }),
      request,
      error: serializeError(error),
      durationMs: round(performance.now() - started)
    });
    throw error;
  }
}

function attachGatewayRecorder(agent) {
  const originalInvoke = agent.gateway.invoke.bind(agent.gateway);
  agent.gateway.invoke = async (...invokeArgs) => {
    const outcome = await originalInvoke(...invokeArgs);
    if (activeGatewayCapture) {
      activeGatewayCapture.toolInvocations.push({
        tool: invokeArgs[1],
        requestedArguments: sanitize(invokeArgs[2]),
        sourceUtterance: invokeArgs[3] ?? "",
        availableDomainTools: sanitize(invokeArgs[4]),
        result: sanitize(outcome.result),
        statePatch: sanitize(outcome.statePatch),
        uiOnly: sanitize(outcome.uiOnly),
        durationMs: outcome.durationMs
      });
    }
    return outcome;
  };
}

function evaluateTask(task) {
  const target = task.target;
  if (!target || target.error || !target.validation.ok) {
    return { status: "FAIL", reason: "target_failed" };
  }
  const tools = target.toolInvocations.map((item) => item.tool);
  const fallback = target.modelSteps.some(
    (step) => step.decision === "deterministic_fallback"
  );
  const formatRetries = target.modelSteps.reduce(
    (total, step) => total + Number(step.format_retry_count ?? 0),
    0
  );
  const httpErrors = target.modelHttp.filter(
    (item) => item.error || item.response?.ok !== true
  );
  const falseWriteClaim = containsPositiveWriteClaim(target.answer ?? "");
  const privacyIssue = /(糖尿病|高血压|血糖|胰岛素)/i.test(
    JSON.stringify({
      answer: target.answer,
      taskCard: target.uiOnly?.taskCard,
      preview: target.uiOnly?.preview
    })
  );
  let pass = !fallback && formatRetries === 0 && httpErrors.length === 0 && !falseWriteClaim && !privacyIssue;

  if (task.scenarioId === "basic-planning") {
    const finalize = target.modelSteps.find(
      (step) =>
        step.decision === "tool" &&
        step.tool === "finalize_meal_plan" &&
        step.toolResult?.ok === true
    );
    const plan = [...(target.stateAfter.plans ?? [])]
      .reverse()
      .find((item) => item.status === "valid");
    const selected = finalize?.effectiveArguments?.selectedDishes ?? [];
    pass = pass &&
      tools.includes("get_day_context") &&
      tools.includes("find_dish_candidates") &&
      Boolean(finalize) &&
      plan?.status === "valid" &&
      sameIds(selected.map((item) => item.templateId), plan.agentSelectedTemplateIds) &&
      !falseWriteClaim;
  } else if (task.scenarioId === "meal-completion") {
    pass = pass &&
      setupSucceeded(task.setup) &&
      tools.includes("preview_meal_completion") &&
      target.stateBefore?.inventoryLedgerCount === target.stateAfter?.inventoryLedgerCount &&
      sameJson(target.stateBefore?.mealRecords, target.stateAfter?.mealRecords) &&
      target.taskState?.status === "waiting_confirmation" &&
      /尚未写入|确认/.test(target.answer ?? "");
  } else if (task.scenarioId === "rag-caregiver-preview") {
    const card = target.uiOnly?.taskCard;
    pass = pass &&
      setupSucceeded(task.setup) &&
      tools.includes("retrieve_local_knowledge") &&
      tools.includes("preview_caregiver_task") &&
      target.retrievalSourceIds.length > 0 &&
      card?.recipientLabel === "阿姨" &&
      target.taskState?.status === "waiting_confirmation" &&
      (target.stateAfter?.caregiverTaskCount ?? 0) ===
        (target.stateBefore?.caregiverTaskCount ?? 0) &&
      /尚未发送|确认/.test(target.answer ?? "");
  }

  return {
    status: pass ? "PASS" : "FAIL",
    observedTools: tools,
    modelHttpCount: target.modelHttpCount,
    finalizationMode: target.finalizationMode,
    fallback,
    formatRetries,
    httpErrors: httpErrors.length,
    falseWriteClaim,
    privacyIssue
  };
}

function containsPositiveWriteClaim(text) {
  const positivePatterns = [
    /(?:库存|食材).{0,16}(?:已|已经)(?:被)?(?:扣除|扣减|减少|修改)/u,
    /(?:已|已经)(?:从[^。！？\n]{0,24})?(?:库存|食材).{0,10}(?:扣除|扣减|减少)/u,
    /(?:摄入|家庭记忆|家庭资料|收件箱|任务卡).{0,16}(?:已|已经)(?:写入|记录|发送|提交|入库)/u,
    /(?:已|已经)(?:写入|记录|发送|提交|入库)(?:了)?(?:摄入|家庭记忆|家庭资料|收件箱|任务卡)?/u
  ];
  return text
    .split(/[。！？；;\n]/u)
    .some((clause) =>
      positivePatterns.some((pattern) => pattern.test(clause)) &&
      !/(?:未|没有|不会|尚未|还未|确认前|确认后才|只有.*确认)/u.test(clause)
    );
}

function setupSucceeded(turn) {
  return Boolean(
    turn &&
      !turn.error &&
      turn.validation.ok &&
      turn.stateAfter?.agent?.activePlanId &&
      turn.stateAfter?.plans?.some((plan) => plan.status === "valid")
  );
}

function buildComparison(arms) {
  const a = summarizeArm(arms["a-model"]);
  const b = summarizeArm(arms["b-trusted-presenter"]);
  const qualityNotLower = b.passCount >= a.passCount;
  const noNewErrors = b.errorCount <= a.errorCount;
  const targetCallsReduced = b.targetModelCalls < a.targetModelCalls;
  const e2eImproved = b.targetE2eP50 < a.targetE2eP50;
  const adoptable =
    b.passCount === b.taskCount &&
    qualityNotLower &&
    noNewErrors &&
    targetCallsReduced &&
    e2eImproved;
  const targetE2eMs = {
    A: percentileSummary(a.targetE2eSamples),
    B: percentileSummary(b.targetE2eSamples)
  };
  targetE2eMs.B.percentChangeP50 = percentChange(
    targetE2eMs.B.p50,
    targetE2eMs.A.p50
  );
  targetE2eMs.B.percentChangeP90 = percentChange(
    targetE2eMs.B.p90,
    targetE2eMs.A.p90
  );
  const scenarioMetrics = Object.fromEntries(
    scenarios.map((scenario) => [
      scenario.id,
      compareScenarioMetrics(a.byScenario[scenario.id], b.byScenario[scenario.id])
    ])
  );
  return {
    status: adoptable ? "ADOPTABLE_CANDIDATE" : "NOT_ADOPTED",
    sampleCount: { A: a.taskCount, B: b.taskCount },
    targetE2eMs,
    targetModelCalls: {
      A: a.targetModelCalls,
      B: b.targetModelCalls,
      percentChange: percentChange(b.targetModelCalls, a.targetModelCalls)
    },
    totalModelCallsIncludingSetup: {
      A: a.totalModelCalls,
      B: b.totalModelCalls,
      percentChange: percentChange(b.totalModelCalls, a.totalModelCalls)
    },
    promptTokens: compareOptionalMetric(a.promptTokens, b.promptTokens),
    completionTokens: compareOptionalMetric(a.completionTokens, b.completionTokens),
    scenarioMetrics,
    quality: {
      A: { pass: a.passCount, fail: a.taskCount - a.passCount, errors: a.errorCount },
      B: { pass: b.passCount, fail: b.taskCount - b.passCount, errors: b.errorCount },
      qualityNotLower,
      noNewErrors
    },
    finalizationModes: {
      A: a.finalizationModes,
      B: b.finalizationModes
    },
    correctionNote:
      "仅修正分场景 quality 汇总；没有重新测量；原始任务和性能数据未修改。",
    limitations: [
      "每个场景每个 arm 3 个目标任务；餐后和任务卡目标前的计划生成作为 setup 单独记录。",
      "E2E p50/p90 以目标回合为主，setup 请求计入总模型请求数但不混入目标延迟。",
      "正常成功终态固定消除一次 finish_turn 请求；聚合请求数额外减少可能包含 A 组回答重试或 fallback，不能全部归因于固定节省。",
      "任务通过真实 PrivatePlateAgent、Domain、SQLite 和本地 RAG 执行；没有 scripted provider 参与目标回合。"
    ],
    decisionRule: "B must preserve task quality and safety, eliminate terminal-only model calls, and improve target E2E latency."
  };
}

function summarizeArm(arm) {
  const tasks = arm?.tasks ?? [];
  const targetRows = tasks.map((task) => task.target).filter(Boolean);
  const allTurns = tasks.flatMap((task) => [task.setup, task.target]).filter(Boolean);
  const targetE2eSamples = targetRows.map((row) => row.durationMs);
  const tokenRows = targetRows.flatMap((row) => row.modelHttp ?? []);
  const promptTokens = sumUsage(tokenRows, "prompt_tokens");
  const completionTokens = sumUsage(tokenRows, "completion_tokens");
  const byScenario = Object.fromEntries(
    scenarios.map((scenario) => [
      scenario.id,
      summarizeScenario(
        tasks.filter((task) => task.target?.scenarioId === scenario.id)
      )
    ])
  );
  return {
    taskCount: tasks.length,
    passCount: tasks.filter((task) => task.evaluation?.status === "PASS").length,
    errorCount: tasks.filter((task) => (task.target?.modelHttp ?? []).some((item) => item.error || item.response?.ok !== true)).length,
    targetE2eSamples,
    targetE2eP50: percentile(targetE2eSamples, 0.5),
    targetModelCalls: targetRows.reduce((sum, row) => sum + row.modelHttpCount, 0),
    totalModelCalls: allTurns.reduce((sum, row) => sum + row.modelHttpCount, 0),
    promptTokens,
    completionTokens,
    finalizationModes: countValues(targetRows.map((row) => row.finalizationMode ?? "unavailable")),
    byScenario
  };
}

function summarizeScenario(tasks) {
  const rows = tasks.map((task) => task.target).filter(Boolean);
  const tokenRows = rows.flatMap((row) => row.modelHttp ?? []);
  return {
    samples: rows.length,
    passCount: tasks.filter((task) => task.evaluation?.status === "PASS").length,
    targetE2e: percentileSummary(rows.map((row) => row.durationMs)),
    modelCalls: rows.reduce((sum, row) => sum + row.modelHttpCount, 0),
    promptTokens: sumUsage(tokenRows, "prompt_tokens"),
    completionTokens: sumUsage(tokenRows, "completion_tokens")
  };
}

function compareScenarioMetrics(a, b) {
  const targetE2e = {
    A: a.targetE2e,
    B: {
      ...b.targetE2e,
      percentChangeP50: percentChange(b.targetE2e.p50, a.targetE2e.p50),
      percentChangeP90: percentChange(b.targetE2e.p90, a.targetE2e.p90)
    }
  };
  return {
    samples: { A: a.samples, B: b.samples },
    quality: { A: a.passCount, B: b.passCount },
    targetE2e,
    modelCalls: {
      A: a.modelCalls,
      B: b.modelCalls,
      percentChange: percentChange(b.modelCalls, a.modelCalls)
    },
    promptTokens: compareOptionalMetric(a.promptTokens, b.promptTokens),
    completionTokens: compareOptionalMetric(a.completionTokens, b.completionTokens)
  };
}

function renderComparisonMarkdown(comparison) {
  const lines = [
    "# PrivatePlate Terminal Finalization A/B",
    "",
    `- status: **${comparison.status}**`,
    `- target samples: A=${comparison.sampleCount.A}, B=${comparison.sampleCount.B}`,
    "",
    "## Target E2E latency",
    "",
    "| Metric | A model | B trusted presenter | Change B vs A |",
    "| --- | ---: | ---: | ---: |",
    `| p50 (ms) | ${comparison.targetE2eMs.A.p50} | ${comparison.targetE2eMs.B.p50} | ${comparison.targetE2eMs.B.percentChangeP50}% |`,
    `| p90 (ms) | ${comparison.targetE2eMs.A.p90} | ${comparison.targetE2eMs.B.p90} | ${comparison.targetE2eMs.B.percentChangeP90}% |`,
    "",
    "## Model calls",
    "",
    `- target calls: A=${comparison.targetModelCalls.A}, B=${comparison.targetModelCalls.B}, change=${comparison.targetModelCalls.percentChange}%`,
    `- including setup: A=${comparison.totalModelCallsIncludingSetup.A}, B=${comparison.totalModelCallsIncludingSetup.B}, change=${comparison.totalModelCallsIncludingSetup.percentChange}%`,
    `- prompt tokens: ${metricMarkdown(comparison.promptTokens)}`,
    `- completion tokens: ${metricMarkdown(comparison.completionTokens)}`,
    "",
    "## By-scenario target metrics",
    "",
    "| Scenario | A p50 | B p50 | Change | A calls | B calls | Call change |",
    "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ...scenarios.map((scenario) => {
      const metric = comparison.scenarioMetrics[scenario.id];
      return `| ${scenario.id} | ${metric.targetE2e.A.p50}ms | ${metric.targetE2e.B.p50}ms | ${metric.targetE2e.B.percentChangeP50}% | ${metric.modelCalls.A} | ${metric.modelCalls.B} | ${metric.modelCalls.percentChange}% |`;
    }),
    "",
    "## Quality",
    "",
    `- A pass/fail/errors: ${comparison.quality.A.pass}/${comparison.quality.A.fail}/${comparison.quality.A.errors}`,
    `- B pass/fail/errors: ${comparison.quality.B.pass}/${comparison.quality.B.fail}/${comparison.quality.B.errors}`,
    `- quality not lower: ${comparison.quality.qualityNotLower}`,
    `- no new errors: ${comparison.quality.noNewErrors}`,
    "",
    "## Correction",
    "",
    comparison.correctionNote,
    "",
    "## Conclusion",
    "",
    "Trusted Presenter only runs after a successful terminal Domain tool. The model still selects tools, dishes, budget share and selectionReason; the presenter uses the model-submitted semantic fields and Domain-verified result."
  ];
  return `${lines.join("\n")}\n`;
}

async function regenerateDerivedReports(directory) {
  const summaryPath = `${directory}/summary.json`;
  const previousSummary = JSON.parse(await fs.readFile(summaryPath, "utf8"));
  const arms = {
    "a-model": JSON.parse(
      await fs.readFile(`${directory}/arms/a-model/summary.json`, "utf8")
    ),
    "b-trusted-presenter": JSON.parse(
      await fs.readFile(
        `${directory}/arms/b-trusted-presenter/summary.json`,
        "utf8"
      )
    )
  };
  const comparison = buildComparison(arms);
  await writeJson(`${directory}/comparison.json`, comparison);
  await writeText(`${directory}/comparison.md`, renderComparisonMarkdown(comparison));
  await writeJson(`${summaryPath}`, {
    ...previousSummary,
    status: comparison.status,
    comparison
  });
  console.log(`regenerated derived reports in ${directory}`);
  console.log(comparison.correctionNote);
}

async function validateLocalSnapshot() {
  const result = {
    snapshot: modelSnapshot,
    revision,
    directoryExists: false,
    revisionMatchesBasename: modelSnapshot.split("/").at(-1) === revision,
    requiredFiles: {},
    weightFiles: [],
    brokenSymlinks: [],
    pythonConfigTokenizerCheck: null
  };
  try {
    const stat = await fs.stat(modelSnapshot);
    result.directoryExists = stat.isDirectory();
    if (!result.directoryExists || !result.revisionMatchesBasename) {
      throw new Error("Local model snapshot directory or revision is invalid.");
    }
    const names = await fs.readdir(modelSnapshot);
    for (const name of ["config.json", "generation_config.json", "tokenizer_config.json"]) {
      result.requiredFiles[name] = await readableFile(`${modelSnapshot}/${name}`);
    }
    const tokenizer = names.find((name) => name === "tokenizer.json" || name === "tokenizer.model");
    if (!tokenizer) throw new Error("Tokenizer is missing from local snapshot.");
    result.requiredFiles.tokenizer = await readableFile(`${modelSnapshot}/${tokenizer}`);
    const weights = names.filter((name) => /\.(safetensors|bin|pt|pth|gguf)$/i.test(name));
    if (weights.length === 0) throw new Error("Model weights are missing from local snapshot.");
    for (const name of weights) result.weightFiles.push(await readableFile(`${modelSnapshot}/${name}`));
    const check = await runCommand(pythonBin, [
      "-c",
      `from transformers import AutoConfig, AutoTokenizer; p=${JSON.stringify(modelSnapshot)}; c=AutoConfig.from_pretrained(p, local_files_only=True); t=AutoTokenizer.from_pretrained(p, local_files_only=True); print(c.model_type, t.__class__.__name__)`
    ], { env: offlineEnv });
    result.pythonConfigTokenizerCheck = { ok: check.ok, stdout: check.stdout, stderr: check.stderr, exitCode: check.code };
    if (!check.ok) throw new Error("AutoConfig/AutoTokenizer local-only check failed.");
    await writeJson(`${outputDir}/environment/local-snapshot-validation.json`, result);
  } catch (error) {
    result.error = serializeError(error);
    await writeJson(`${outputDir}/environment/local-snapshot-validation.json`, result);
    throw error;
  }
}

async function writeEnvironment() {
  const [version, python, gpuProduct, gpuVram, gpuCombined, rocminfo, hostname, sourceState, templateHash] = await Promise.all([
    commandOutput(vllmBin, ["--version"]),
    commandOutput(pythonBin, ["-c", "import json, torch, vllm; print(json.dumps({'torch':torch.__version__,'hip':torch.version.hip,'vllm':vllm.__version__}))"]),
    runCommand("rocm-smi", ["--showproductname"]),
    runCommand("rocm-smi", ["--showmeminfo", "vram", "--csv"]),
    runCommand("rocm-smi", ["--showproductname", "--showdriverversion", "--showmeminfo", "vram", "--csv"]),
    runCommand("rocminfo"),
    commandOutput("hostname"),
    readSourceState(),
    commandOutput("sha256sum", [chatTemplate])
  ]);
  const help = await commandOutput(vllmBin, ["serve", "--help=all"]);
  const env = {
    runKind: "terminal_finalization_ab",
    startedAt: runStartedAt,
    sourceState,
    model: {
      id: modelId,
      revision,
      localSnapshot: modelSnapshot,
      servedModelName: modelId,
      quantization: "compressed-tensors",
      attentionBackend: "TRITON_ATTN",
      maxModelLen: 8192,
      kvCacheMemoryBytes: 8589934592,
      chatTemplate,
      chatTemplateSha256: templateHash.trim(),
      toolCallParser: "gemma4",
      reasoningParser: "gemma4"
    },
    runtime: {
      chatEndpoint: chatBaseUrl,
      ragEndpoint: ragBaseUrl,
      ragMode: "vllm",
      vllmVersion: version.trim(),
      torchHip: python.trim(),
      gpu: commandValue(gpuProduct),
      hostname: hostname.trim(),
      hardware: {
        product: commandValue(gpuProduct),
        vram: commandValue(gpuVram),
        combinedRocmSmi: commandValue(gpuCombined),
        rocminfoAvailable: rocminfo.ok
      }
    },
    finalizationArms: {
      A: "PRIVATEPLATE_FINALIZATION_MODE=model",
      B: "PRIVATEPLATE_FINALIZATION_MODE=trusted_presenter"
    },
    invariants: {
      prefixCaching: "--enable-prefix-caching",
      modelSnapshot,
      revisionPassedToServer: false,
      chatTemplate,
      toolParser: "gemma4",
      attentionBackend: "TRITON_ATTN",
      kvCacheMemoryBytes: 8589934592,
      maxModelLen: 8192,
      temperature: 0,
      concurrency: 1,
      repeatsPerScenario: repeats
    },
    vllmHelpFlags: {
      prefixCaching: help.includes("--enable-prefix-caching"),
      noRevisionInArmCommand: true
    },
    safety: {
      deterministicFallbackAllowed: false,
      remoteModelAllowed: false
    }
  };
  await writeText(`${outputDir}/environment/vllm-help.txt`, help);
  await writeText(`${outputDir}/environment/vllm-version.txt`, version);
  await writeText(`${outputDir}/environment/python-versions.txt`, python);
  await writeText(`${outputDir}/environment/gpu-product.txt`, commandText(gpuProduct));
  await writeText(`${outputDir}/environment/gpu-vram.txt`, commandText(gpuVram));
  await writeText(`${outputDir}/environment/gpu-combined.txt`, commandText(gpuCombined));
  await writeText(`${outputDir}/environment/rocminfo.txt`, commandText(rocminfo));
  await writeJson(`${outputDir}/environment.json`, env);
  return env;
}

function serverArgs() {
  return [
    "serve",
    "--model",
    modelSnapshot,
    "--host",
    "127.0.0.1",
    "--port",
    "8000",
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
    "--enable-prefix-caching"
  ];
}

async function waitForServer(child, armDir) {
  const readiness = `${armDir}/raw/readiness.jsonl`;
  for (let attempt = 1; attempt <= 180; attempt += 1) {
    if (child.exitCode !== null) throw new Error(`vLLM exited before readiness: ${child.exitCode}`);
    const response = await fetchText(`${chatBaseUrl}/models`);
    await appendJsonl(readiness, {
      attempt,
      at: new Date().toISOString(),
      status: response.status,
      ok: response.ok
    });
    if (response.ok) {
      await writeText(`${armDir}/raw/models-response.json`, response.text);
      return;
    }
    if (attempt === 1 || attempt % 10 === 0) console.log(`waiting for vLLM (${attempt}/180)`);
    await sleep(2000);
  }
  throw new Error("vLLM did not become ready within 6 minutes.");
}

async function writeMetrics(armDir, label) {
  const result = await fetchText(`${chatRootUrl}/metrics`);
  await writeText(`${armDir}/raw/metrics-${label}.txt`, result.text);
  await writeText(
    `${armDir}/raw/metrics-${label}-prefix-cache.txt`,
    result.text.split("\n").filter((line) => /prefix.?cache|cache.?prefix/i.test(line)).join("\n") + "\n"
  );
}

async function stopChild(child, armDir) {
  const before = await listChatVllmProcesses();
  const result = { childPid: child.pid ?? null, before, signal: null, exited: false };
  if (child.exitCode === null) {
    result.signal = "SIGTERM";
    try {
      if (child.pid) process.kill(-child.pid, "SIGTERM");
    } catch {
      if (child.pid) process.kill(child.pid, "SIGTERM");
    }
    await waitForChildExit(child, 30_000);
  }
  if (child.exitCode === null) {
    result.signal = "SIGKILL";
    try {
      if (child.pid) process.kill(-child.pid, "SIGKILL");
    } catch {
      if (child.pid) process.kill(child.pid, "SIGKILL");
    }
    await waitForChildExit(child, 5_000);
  }
  result.exited = child.exitCode !== null;
  result.after = await listChatVllmProcesses();
  await writeJson(`${armDir}/process-stop.json`, result);
  return result;
}

async function waitForChildExit(child, timeoutMs) {
  if (child.exitCode !== null) return;
  await Promise.race([
    new Promise((resolve) => child.once("exit", resolve)),
    sleep(timeoutMs)
  ]);
}

async function listChatVllmProcesses() {
  const result = await runCommand("ps", ["-eo", "pid=,args="]);
  return result.stdout.split("\n").map((line) => {
    const match = line.trim().match(/^(\d+)\s+(.*)$/);
    return match ? { pid: Number(match[1]), args: match[2] } : null;
  }).filter((item) => item && /vllm/i.test(item.args) && /--port\s+8000|--port=8000/.test(item.args));
}

function pairModelSteps(steps, invocations) {
  let index = 0;
  return steps.map((step) => {
    if (step.decision !== "tool") return step;
    const invocation = invocations[index];
    index += 1;
    return { ...step, gatewayInvocation: invocation ?? null };
  });
}

function snapshot(domain, agent) {
  const db = domain.db;
  const householdId = domain.householdId;
  const count = (sql) => Number(db.prepare(sql).get()?.count ?? 0);
  const plans = db.prepare(
    `SELECT id, version, parent_plan_id, status, plan_json FROM meal_plans
     WHERE session_id IN (SELECT id FROM meal_planning_sessions WHERE household_id = ?)
     ORDER BY version`
  ).all(householdId).map((row) => {
    const plan = parseJson(row.plan_json) ?? {};
    const selection = plan.selectionTrace?.agentSelection ?? null;
    return {
      id: row.id,
      version: row.version,
      parentPlanId: row.parent_plan_id,
      status: row.status,
      selectedTemplateIds: (plan.sharedTemplates ?? []).map((item) => item.templateId),
      agentSelectedTemplateIds: (selection?.selectedDishes ?? []).map((item) => item.templateId)
    };
  });
  return sanitize({
    plans,
    inventoryLedgerCount: count("SELECT COUNT(*) AS count FROM inventory_ledger"),
    mealRecords: db.prepare("SELECT id, status, plan_id, plan_version FROM meal_records ORDER BY created_at").all(),
    caregiverTaskCount: count("SELECT COUNT(*) AS count FROM caregiver_tasks"),
    preferencesCount: count("SELECT COUNT(*) AS count FROM member_preferences WHERE active = 1"),
    pendingActionCount: count("SELECT COUNT(*) AS count FROM pending_actions WHERE status = 'pending'"),
    agent: {
      phase: agent.state.phase,
      activePlanId: agent.state.activePlanId,
      activePlanVersion: agent.state.activePlanVersion,
      pendingActionId: agent.state.pendingActionId,
      taskState: agent.getTaskState()
    }
  });
}

async function readSourceState() {
  if (!sourceStatePath) return { unavailable: true, reason: "--source-state not supplied" };
  try {
    return JSON.parse(await fs.readFile(sourceStatePath, "utf8"));
  } catch (error) {
    return { unavailable: true, reason: serializeError(error) };
  }
}

async function readableFile(file) {
  const stat = await fs.stat(file);
  if (!stat.isFile() || stat.size < 1) throw new Error(`Unreadable snapshot file: ${file}`);
  await fs.access(file, 4);
  return { path: file, sizeBytes: stat.size, readable: true };
}

function percentileSummary(values) {
  return {
    p50: round(percentile(values, 0.5)),
    p90: round(percentile(values, 0.9)),
    samples: values.length,
    percentChangeP50: null,
    percentChangeP90: null
  };
}

function compareOptionalMetric(a, b) {
  if (a == null || b == null) return { A: a, B: b, percentChange: null };
  return { A: a, B: b, percentChange: percentChange(b, a) };
}

function sumUsage(rows, field) {
  const values = rows.map((row) => row.response?.body?.usage?.[field]).filter((value) => Number.isFinite(value));
  return values.length === rows.length && rows.length > 0 ? values.reduce((sum, value) => sum + value, 0) : null;
}

function percentile(values, fraction) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const index = Math.min(sorted.length - 1, Math.max(0, Math.ceil(sorted.length * fraction) - 1));
  return sorted[index];
}

function percentChange(after, before) {
  if (!Number.isFinite(before) || before === 0 || !Number.isFinite(after)) return null;
  return round(((after - before) / before) * 100);
}

function metricMarkdown(metric) {
  return metric.A == null || metric.B == null
    ? `unavailable (A=${metric.A}, B=${metric.B})`
    : `A=${metric.A}, B=${metric.B}, change=${metric.percentChange}%`;
}

function countValues(values) {
  return values.reduce((counts, value) => {
    counts[value] = (counts[value] ?? 0) + 1;
    return counts;
  }, {});
}

function sameIds(a, b) {
  return JSON.stringify(a ?? []) === JSON.stringify(b ?? []);
}

function sameJson(a, b) {
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
}

function formatEnvForEvidence(env) {
  return [
    `HF_HOME=${env.HF_HOME}`,
    `HF_HUB_CACHE=${env.HF_HUB_CACHE}`,
    `HUGGINGFACE_HUB_CACHE=${env.HUGGINGFACE_HUB_CACHE}`,
    "HF_HUB_OFFLINE=1",
    "TRANSFORMERS_OFFLINE=1",
    "PRIVATEPLATE_RAG_MODE=vllm",
    `PRIVATEPLATE_EMBEDDING_BASE_URL=${env.PRIVATEPLATE_EMBEDDING_BASE_URL}`,
    `PRIVATEPLATE_FINALIZATION_MODE=${env.PRIVATEPLATE_FINALIZATION_MODE}`
  ].join(" ");
}

function pickOfflineEnvironment(env) {
  return {
    HF_HOME: env.HF_HOME,
    HF_HUB_CACHE: env.HF_HUB_CACHE,
    HUGGINGFACE_HUB_CACHE: env.HUGGINGFACE_HUB_CACHE,
    HF_HUB_OFFLINE: env.HF_HUB_OFFLINE,
    TRANSFORMERS_OFFLINE: env.TRANSFORMERS_OFFLINE,
    PRIVATEPLATE_FINALIZATION_MODE: env.PRIVATEPLATE_FINALIZATION_MODE
  };
}

async function fetchText(url) {
  try {
    const response = await fetch(url, { signal: AbortSignal.timeout(5000) });
    return { ok: response.ok, status: response.status, text: await response.text() };
  } catch (error) {
    return { ok: false, status: 0, text: serializeError(error) };
  }
}

async function commandOutput(file, commandArgs = []) {
  const result = await runCommand(file, commandArgs);
  return `${result.stdout}${result.stderr}`;
}

function commandValue(result) {
  return result.ok && result.stdout.trim() ? result.stdout.trim() : "unavailable";
}

function commandText(result) {
  return `${result.stdout}${result.stderr}`;
}

async function runCommand(file, commandArgs = [], options = {}) {
  try {
    const result = await execFile(file, commandArgs, {
      cwd: options.cwd ?? process.cwd(),
      env: options.env ?? process.env,
      maxBuffer: options.maxBuffer ?? 20 * 1024 * 1024
    });
    return { ok: true, code: 0, stdout: result.stdout ?? "", stderr: result.stderr ?? "" };
  } catch (error) {
    return { ok: false, code: Number(error?.code ?? 1), stdout: error?.stdout ?? "", stderr: error?.stderr ?? String(error) };
  }
}

function parseArgs(argv) {
  const out = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith("--")) continue;
    const key = token.slice(2);
    out[key] = argv[index + 1] && !argv[index + 1].startsWith("--") ? argv[++index] : true;
  }
  return out;
}

function pathValue(value) {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function isLoopbackUrl(value) {
  const url = new URL(value);
  return ["127.0.0.1", "localhost", "::1"].includes(url.hostname);
}

function sqliteLiteral(value) {
  return value.replaceAll("'", "''");
}

function parseJson(value) {
  if (typeof value !== "string") return value ?? null;
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}

function sanitizeHeaders(headers) {
  if (!headers) return {};
  const entries = headers instanceof Headers ? [...headers.entries()] : Object.entries(headers);
  return Object.fromEntries(entries.map(([key, value]) => [
    key.toLowerCase() === "authorization" ? key : key,
    key.toLowerCase() === "authorization" ? "<redacted>" : String(value)
  ]));
}

function sanitize(value) {
  if (Array.isArray(value)) return value.map(sanitize);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, nested]) => [
      key,
      /confirmationToken|apiKey|authorization/i.test(key) ? "<redacted>" : sanitize(nested)
    ]));
  }
  return value;
}

function serializeError(error) {
  return error instanceof Error ? { name: error.name, message: error.message, stack: error.stack } : { message: String(error) };
}

function round(value) {
  return Math.round(value * 100) / 100;
}

async function mkdir(directory) {
  await fs.mkdir(directory, { recursive: true });
}

async function writeText(file, value) {
  await mkdir(file.slice(0, file.lastIndexOf("/")) || ".");
  await fs.writeFile(file, value, "utf8");
}

async function writeJson(file, value) {
  await writeText(file, `${JSON.stringify(value, null, 2)}\n`);
}

async function appendJsonl(file, value) {
  await mkdir(file.slice(0, file.lastIndexOf("/")) || ".");
  await fs.appendFile(file, `${JSON.stringify(value)}\n`, "utf8");
}
