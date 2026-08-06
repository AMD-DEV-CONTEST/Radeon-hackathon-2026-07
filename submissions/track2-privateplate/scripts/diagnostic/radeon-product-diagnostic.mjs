#!/usr/bin/env node

import { appendFile, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { performance } from "node:perf_hooks";
import {
  OpenAiCompatibleToolProvider,
  PrivatePlateAgent
} from "../../packages/agent-runtime/dist/index.js";
import { PrivatePlateDomain } from "../../packages/domain/dist/index.js";

const runStartedAt = new Date().toISOString();
const args = parseArgs(process.argv.slice(2));
const outDir = path.resolve(args.out ?? "");
if (!args.out) throw new Error("--out is required");

const baseUrl = args.baseUrl ?? process.env.PRIVATEPLATE_VLLM_BASE_URL ?? "http://127.0.0.1:8000/v1";
const embeddingBaseUrl =
  args.embeddingBaseUrl ??
  process.env.PRIVATEPLATE_EMBEDDING_BASE_URL ??
  "http://127.0.0.1:8001/v1";
const model =
  args.model ??
  process.env.PRIVATEPLATE_MODEL_ACTIVE ??
  process.env.PRIVATEPLATE_MODEL_ID ??
  process.env.PRIVATEPLATE_MODEL;
if (!model) throw new Error("--model or PRIVATEPLATE_MODEL is required");
if (!isLoopbackUrl(baseUrl) || !isLoopbackUrl(embeddingBaseUrl)) {
  throw new Error("Chat and RAG endpoints must be loopback URLs.");
}
if (process.env.PRIVATEPLATE_RAG_MODE !== "vllm") {
  throw new Error("This diagnostic requires PRIVATEPLATE_RAG_MODE=vllm.");
}

await mkdir(outDir, { recursive: true });
const scenarioDbDir = path.join(outDir, "scenario-databases");
await mkdir(scenarioDbDir, { recursive: true });
const dbPath = path.join(outDir, "diagnostic.sqlite");
const turnsPath = path.join(outDir, "turns.jsonl");
const modelHttp = [];
const scenarios = [];
const liveAgents = new Map();
const liveCredentials = new Map();
const openDomains = new Set();
let activeCapture = null;
let domain = null;

const provider = new OpenAiCompatibleToolProvider({
  baseUrl,
  model,
  ...(process.env.PRIVATEPLATE_VLLM_API_KEY
    ? { apiKey: process.env.PRIVATEPLATE_VLLM_API_KEY }
    : {}),
  timeoutMs: 120_000,
  fetchImpl: recordingFetch
});

const environment = {
  runKind: "radeon_product_diagnostic",
  status: "running",
  startedAt: runStartedAt,
  source: {
    gitSha: process.env.PRIVATEPLATE_SOURCE_SHA ?? "unavailable",
    dirty: process.env.PRIVATEPLATE_SOURCE_DIRTY ?? "unavailable",
    manifestSha256: process.env.PRIVATEPLATE_SOURCE_MANIFEST_SHA256 ?? "unavailable",
    remoteSourceDir: process.env.PRIVATEPLATE_REMOTE_SOURCE_DIR ?? "unavailable"
  },
  provider: {
    mode: provider.mode,
    model: provider.model,
    chatEndpoint: baseUrl,
    ragEndpoint: embeddingBaseUrl,
    ragMode: process.env.PRIVATEPLATE_RAG_MODE,
    deterministicFallbackAllowed: false
  },
  instance: {
    id: process.env.PRIVATEPLATE_INSTANCE_ID ?? "unavailable",
    host: process.env.PRIVATEPLATE_RADEON_HOST_LABEL ?? "unavailable"
  },
  runtime: {
    node: process.version,
    platform: process.platform,
    arch: process.arch
  }
};
await writeJson(path.join(outDir, "environment.json"), environment);

try {
  domain = await PrivatePlateDomain.create(dbPath);
  openDomains.add(domain);
  const primaryDomain = domain;

  const planAgent = openAgent("diagnostic-plan");
  const planScenario = createScenario(
    "core-1-basic-planning",
    "core",
    "请根据三位家庭成员今天的剩余额度、库存和偏好，规划今天的午餐。"
  );
  await scenarioTurn(planScenario, planAgent, planScenario.input);
  planScenario.evaluation = evaluateBasicPlanning(planScenario);
  await saveScenario(planScenario);

  const inventoryAgent = openAgent("diagnostic-inventory");
  const inventoryScenario = createScenario(
    "core-2-inventory-loop",
    "core",
    "刚买了两盒豆腐，帮我记入库存。"
  );
  await scenarioTurn(inventoryScenario, inventoryAgent, inventoryScenario.input);
  const inventoryTurn = inventoryScenario.turns.at(-1);
  const inventoryCredential = credentialFor(inventoryScenario);
  if (inventoryCredential) {
    inventoryScenario.confirmations.push(
      confirmPending(inventoryScenario, inventoryAgent, inventoryCredential, 0)
    );
  } else {
    inventoryScenario.confirmations.push({
      status: "unavailable",
      reason: "preview did not return a UI confirmation credential"
    });
  }

  const afterInventoryAgent = openAgent("diagnostic-after-inventory");
  await scenarioTurn(
    inventoryScenario,
    afterInventoryAgent,
    "根据刚更新的库存规划今天的午餐。"
  );
  inventoryScenario.evaluation = evaluateInventoryLoop(inventoryScenario);
  await saveScenario(inventoryScenario);

  const inventoryPlanReady = hasActivePlan(afterInventoryAgent);
  const inventoryPlanCheckpoint = inventoryPlanReady
    ? cloneCheckpoint(afterInventoryAgent.exportCheckpoint())
    : null;
  let inventoryBaseDomain = null;
  if (inventoryPlanCheckpoint) {
    inventoryBaseDomain = await createScenarioDatabaseBranch(
      "inventory-base",
      primaryDomain
    );
    environment.scenarioIsolation = {
      source: "inventory-confirmed-plan",
      checkpointSessionId: inventoryPlanCheckpoint.agentState.sessionId,
      baseDatabase: path.join(scenarioDbDir, "inventory-base.sqlite"),
      branchDatabases: {}
    };
  }

  const mealScenario = createScenario(
    "core-3-meal-completion-loop",
    "core",
    "这顿饭吃完了，先预览餐后记录。"
  );
  if (inventoryPlanCheckpoint && inventoryBaseDomain) {
    domain = await createScenarioDatabaseBranch(
      "core-3-meal-completion",
      inventoryBaseDomain
    );
    const mealAgent = openAgentFromCheckpoint(
      "diagnostic-core-3-meal-completion",
      inventoryPlanCheckpoint
    );
    await scenarioTurn(mealScenario, mealAgent, mealScenario.input);
    const mealCredential = credentialFor(mealScenario);
    if (mealCredential) {
      mealScenario.confirmations.push(
        confirmPending(mealScenario, mealAgent, mealCredential, 0)
      );
    } else {
      mealScenario.confirmations.push({
        status: "unavailable",
        reason: "preview did not return a UI confirmation credential"
      });
    }
    const afterMealAgent = openAgent("diagnostic-after-meal");
    await scenarioTurn(
      mealScenario,
      afterMealAgent,
      "查看今天更新后的剩余额度和库存。"
    );
    mealScenario.evaluation = evaluateMealCompletion(mealScenario);
  } else {
    markBlockedScenario(
      mealScenario,
      "core-2-inventory-loop.follow-up",
      "库存确认后的真实规划没有生成有效活动计划。"
    );
  }
  await saveScenario(mealScenario);

  const revisionScenario = createScenario(
    "aux-1-plan-revision",
    "auxiliary",
    "不要鸡腿，保留其他限制，重新规划。"
  );
  if (inventoryPlanCheckpoint && inventoryBaseDomain) {
    domain = await createScenarioDatabaseBranch(
      "aux-1-plan-revision",
      inventoryBaseDomain
    );
    const revisionAgent = openAgentFromCheckpoint(
      "diagnostic-aux-1-plan-revision",
      inventoryPlanCheckpoint
    );
    await scenarioTurn(revisionScenario, revisionAgent, revisionScenario.input);
    revisionScenario.evaluation = evaluatePlanRevision(revisionScenario);
  } else {
    markBlockedScenario(
      revisionScenario,
      "core-2-inventory-loop.follow-up",
      "没有可供修订的有效活动计划。"
    );
  }
  await saveScenario(revisionScenario);

  domain = primaryDomain;
  const memoryAgent = openAgent("diagnostic-memory");
  const memoryScenario = createScenario(
    "aux-2-family-memory",
    "auxiliary",
    "记住全家喜欢少油清淡。"
  );
  await scenarioTurn(memoryScenario, memoryAgent, memoryScenario.input);
  const memoryCredential = credentialFor(memoryScenario);
  if (memoryCredential) {
    memoryScenario.confirmations.push(
      confirmPending(memoryScenario, memoryAgent, memoryCredential, 0)
    );
  } else {
    memoryScenario.confirmations.push({
      status: "unavailable",
      reason: "preview did not return a UI confirmation credential"
    });
  }
  const memoryReadAgent = openAgent("diagnostic-memory-read");
  await scenarioTurn(
    memoryScenario,
    memoryReadAgent,
    "查看今天家庭情况，并告诉我刚记住的偏好是否生效。"
  );
  memoryScenario.evaluation = evaluateFamilyMemory(memoryScenario);
  await saveScenario(memoryScenario);

  const ragScenario = createScenario(
    "aux-3-rag-caregiver-preview",
    "auxiliary",
    "先查一下本地晚餐准备规则，再生成给保姆看的任务卡，先不要发送。"
  );
  if (inventoryPlanCheckpoint && inventoryBaseDomain) {
    domain = await createScenarioDatabaseBranch(
      "aux-3-rag-caregiver-preview",
      inventoryBaseDomain
    );
    const ragAgent = openAgentFromCheckpoint(
      "diagnostic-aux-3-rag-caregiver-preview",
      inventoryPlanCheckpoint
    );
    await scenarioTurn(ragScenario, ragAgent, ragScenario.input);
    await scenarioTurn(
      ragScenario,
      ragAgent,
      "收件人改成阿姨，确认前不要发送。"
    );
    ragScenario.evaluation = evaluateRagHandoff(ragScenario);
  } else {
    markBlockedScenario(
      ragScenario,
      "core-2-inventory-loop.follow-up",
      "没有可供任务卡交接的有效活动计划。"
    );
  }
  await saveScenario(ragScenario);
} catch (error) {
  environment.status = "failed";
  environment.fatalError = serializeError(error);
  await writeJson(path.join(outDir, "environment.json"), environment);
} finally {
  for (const instance of openDomains) instance.close();
  environment.status = environment.status === "failed" ? "failed" : "completed";
  environment.finishedAt = new Date().toISOString();
  environment.modelHttpRequestCount = modelHttp.length;
  await writeJson(path.join(outDir, "environment.json"), environment);
  await writeJson(path.join(outDir, "model-http.json"), modelHttp);
  await writeJson(path.join(outDir, "scenarios.json"), scenarios);
  await writeJson(
    path.join(outDir, "summary.json"),
    buildSummary(environment, scenarios)
  );
}

function parseArgs(argv) {
  const result = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith("--")) continue;
    const key = token.slice(2);
    result[key] = argv[index + 1] && !argv[index + 1].startsWith("--")
      ? argv[++index]
      : true;
  }
  return result;
}

function isLoopbackUrl(value) {
  const url = new URL(value);
  return ["127.0.0.1", "localhost", "::1"].includes(url.hostname);
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
      request,
      response: {
        status: response.status,
        ok: response.ok,
        body: parseJson(bodyText)
      },
      durationMs: Math.round((performance.now() - started) * 100) / 100
    });
    return response;
  } catch (error) {
    modelHttp.push({
      request,
      error: serializeError(error),
      durationMs: Math.round((performance.now() - started) * 100) / 100
    });
    throw error;
  }
}

function createScenario(id, category, input) {
  const scenario = {
    id,
    category,
    input,
    startedAt: new Date().toISOString(),
    turns: [],
    confirmations: [],
    evaluation: null
  };
  scenarios.push(scenario);
  return scenario;
}

function openAgent(sessionId) {
  if (liveAgents.has(sessionId)) return liveAgents.get(sessionId);
  const agent = new PrivatePlateAgent(domain, sessionId, provider);
  attachGatewayRecorder(agent);
  liveAgents.set(sessionId, agent);
  return agent;
}

function openAgentFromCheckpoint(sessionId, checkpoint) {
  const agent = openAgent(sessionId);
  const branchCheckpoint = cloneCheckpoint(checkpoint);
  branchCheckpoint.agentState.sessionId = sessionId;
  agent.restoreState(branchCheckpoint);
  return agent;
}

async function createScenarioDatabaseBranch(label, sourceDomain) {
  const branchPath = path.join(scenarioDbDir, `${label}.sqlite`);
  sourceDomain.db.exec(`VACUUM INTO '${sqliteLiteral(branchPath)}'`);
  const branch = await PrivatePlateDomain.create(branchPath);
  openDomains.add(branch);
  if (environment.scenarioIsolation?.branchDatabases) {
    environment.scenarioIsolation.branchDatabases[label] = branchPath;
  }
  return branch;
}

function cloneCheckpoint(checkpoint) {
  return JSON.parse(JSON.stringify(checkpoint));
}

function sqliteLiteral(value) {
  return value.replaceAll("'", "''");
}

function attachGatewayRecorder(agent) {
  const originalInvoke = agent.gateway.invoke.bind(agent.gateway);
  agent.gateway.invoke = async (...invokeArgs) => {
    const started = performance.now();
    try {
      const outcome = await originalInvoke(...invokeArgs);
      if (activeCapture) {
        activeCapture.toolInvocations.push({
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
    } catch (error) {
      if (activeCapture) {
        activeCapture.toolInvocations.push({
          tool: invokeArgs[1],
          requestedArguments: sanitize(invokeArgs[2]),
          error: serializeError(error),
          durationMs: Math.round((performance.now() - started) * 100) / 100
        });
      }
      throw error;
    }
  };
}

async function scenarioTurn(scenario, agent, input) {
  const httpStart = modelHttp.length;
  const capture = { toolInvocations: [] };
  const before = snapshot(domain, agent);
  const started = performance.now();
  activeCapture = capture;
  let result = null;
  let error = null;
  try {
    result = await agent.handleUserMessage(input);
  } catch (caught) {
    error = serializeError(caught);
  } finally {
    activeCapture = null;
  }
  const after = snapshot(domain, agent);
  const modelSteps = result
    ? pairModelSteps(result.modelSteps, capture.toolInvocations)
    : [];
  const turn = {
    index: scenario.turns.length,
    input,
    durationMs: Math.round((performance.now() - started) * 100) / 100,
    modelHttp: modelHttp.slice(httpStart),
    modelSteps: sanitize(modelSteps),
    toolInvocations: sanitize(capture.toolInvocations),
    answer: result?.answer ?? null,
    phase: result?.phase ?? agent.state.phase,
    taskOutcome: sanitize(result?.taskOutcome),
    validation: {
      ok: result?.validationOk ?? false,
      reasons: result?.validationReasons ?? []
    },
    routingEvidenceKind: result?.routingEvidenceKind ?? "unavailable",
    uiOnly: sanitize(result?.uiOnly),
    stateBefore: before,
    stateAfter: after,
    agentState: sanitize(agent.state),
    taskState: sanitize(agent.getTaskState()),
    checkpoint: sanitize(agent.exportCheckpoint()),
    retrievalSourceIds: agent.getLastRetrievalIds(),
    error
  };
  scenario.turns.push(turn);
  liveCredentials.set(`${scenario.id}:${turn.index}`, result?.uiOnly ?? null);
  await appendFile(turnsPath, `${JSON.stringify({ scenarioId: scenario.id, turn })}\n`);
  return turn;
}

function credentialFor(scenario) {
  return liveCredentials.get(`${scenario.id}:${scenario.turns.length - 1}`) ?? null;
}

function pairModelSteps(steps, invocations) {
  let invocationIndex = 0;
  return steps.map((step) => {
    if (step.decision !== "tool") return { ...step };
    const invocation = invocations[invocationIndex];
    invocationIndex += 1;
    return { ...step, gatewayInvocation: invocation ?? null };
  });
}

function confirmPending(scenario, agent, uiOnly, turnIndex) {
  const pendingActionId = uiOnly.pendingActionId;
  const idempotencyKey = `${runId()}-${scenario.id}-${turnIndex}-${pendingActionId}`;
  const before = snapshot(domain, agent);
  const first = agent.confirmPending({
    pendingActionId,
    confirmationToken: uiOnly.confirmationToken,
    idempotencyKey,
    payloadHash: uiOnly.payloadHash
  });
  const afterFirst = snapshot(domain, agent);
  const replay = first.ok
    ? agent.confirmPending({
        pendingActionId,
        confirmationToken: uiOnly.confirmationToken,
        idempotencyKey,
        payloadHash: uiOnly.payloadHash
      })
    : null;
  const afterReplay = snapshot(domain, agent);
  return {
    turnIndex,
    actionType: uiOnly.actionType ?? "unavailable",
    pendingActionId,
    payloadHash: uiOnly.payloadHash ?? "unavailable",
    idempotencyKey,
    first: sanitize(first),
    replay: sanitize(replay),
    stateBefore: before,
    stateAfterFirst: afterFirst,
    stateAfterReplay: afterReplay,
    firstWriteDelta: writeDelta(before, afterFirst),
    replayWriteDelta: writeDelta(afterFirst, afterReplay)
  };
}

function snapshot(currentDomain, agent) {
  const db = currentDomain.db;
  const householdId = currentDomain.householdId;
  const inventoryRows = db
    .prepare(
      `SELECT id, food_id, raw_name, normalized_gram_range_json, state
       FROM inventory_items WHERE household_id = ? ORDER BY id`
    )
    .all(householdId);
  const preferences = db
    .prepare(
      `SELECT member_id, kind, note, polarity, source, active
       FROM member_preferences WHERE household_id = ? AND active = 1 ORDER BY id`
    )
    .all(householdId);
  const healthFactCount = db
    .prepare(
      `SELECT COUNT(*) AS count FROM member_health_facts
       WHERE household_id = ? AND active = 1`
    )
    .get(householdId)?.count ?? 0;
  const inventory = inventoryRows.map((row) => ({
    id: row.id,
    foodId: row.food_id,
    rawName: row.raw_name,
    state: row.state,
    quantity: parseJson(row.normalized_gram_range_json)
  }));
  const plans = db
    .prepare(
      `SELECT id, session_id, version, parent_plan_id, status, plan_json
       FROM meal_plans WHERE session_id IN
       (SELECT id FROM meal_planning_sessions WHERE household_id = ?)
       ORDER BY session_id, version`
    )
    .all(householdId)
    .map((row) => summarizePlanRow(row));
  const pending = db
    .prepare(
      `SELECT id, action_type, status, payload_hash, idempotency_key, expires_at
       FROM pending_actions WHERE household_id = ? ORDER BY created_at`
    )
    .all(householdId);
  const household = db
    .prepare(
      `SELECT version, inventory_version FROM households WHERE id = ?`
    )
    .get(householdId);
  const intake = db
    .prepare(
      `SELECT intake_version FROM household_intake_versions WHERE household_id = ?`
    )
    .get(householdId);
  const mealRecords = db
    .prepare(
      `SELECT id, meal_type, status, plan_id, plan_version, diner_ids_json
       FROM meal_records WHERE household_id = ? ORDER BY created_at`
    )
    .all(householdId)
    .map((row) => ({ ...row, dinerIds: parseJson(row.diner_ids_json) }));
  const ledger = db
    .prepare(
      `SELECT reason, food_id, delta_g, before_estimate_g, after_estimate_g,
              related_meal_record_id, related_pending_action_id
       FROM inventory_ledger WHERE household_id = ? ORDER BY created_at`
    )
    .all(householdId);
  const taskCount = db
    .prepare(`SELECT COUNT(*) AS count FROM caregiver_tasks WHERE household_id = ?`)
    .get(householdId)?.count ?? 0;
  return sanitize({
    householdId,
    inventory,
    preferences,
    healthFactCount,
    plans,
    pendingActions: pending,
    mealRecords,
    ledger,
    caregiverTaskCount: taskCount,
    versions: {
      household: household?.version ?? null,
      inventory: household?.inventory_version ?? null,
      intake: intake?.intake_version ?? null
    },
    agent: {
      sessionId: agent.state.sessionId,
      phase: agent.state.phase,
      activePlanId: agent.state.activePlanId,
      activePlanVersion: agent.state.activePlanVersion,
      pendingActionId: agent.state.pendingActionId,
      taskState: agent.getTaskState()
    }
  });
}

function summarizePlanRow(row) {
  const plan = parseJson(row.plan_json) ?? {};
  const selection = plan.selectionTrace ?? {};
  const agentSelection = selection.agentSelection ?? null;
  return {
    id: row.id,
    sessionId: row.session_id,
    version: row.version,
    parentPlanId: row.parent_plan_id,
    status: row.status,
    mealType: plan.mealType ?? null,
    dinerIds: plan.dinerIds ?? [],
    selectedTemplateIds: (plan.sharedTemplates ?? []).map((item) => item.templateId),
    rejectedFoodIds: plan.rejectedFoodIds ?? [],
    rejectedTemplateIds: plan.rejectedTemplateIds ?? [],
    agentSelectedTemplateIds: (agentSelection?.selectedDishes ?? []).map(
      (item) => item.templateId
    ),
    candidateSetId: agentSelection?.candidateSetId ?? null
  };
}

function writeDelta(before, after) {
  return {
    inventoryVersion: after.versions.inventory - before.versions.inventory,
    intakeVersion: after.versions.intake - before.versions.intake,
    inventoryLedger: after.ledger.length - before.ledger.length,
    mealRecords: after.mealRecords.length - before.mealRecords.length,
    pendingActions: after.pendingActions.length - before.pendingActions.length,
    caregiverTasks: after.caregiverTaskCount - before.caregiverTaskCount
  };
}

function evaluateBasicPlanning(scenario) {
  const turn = scenario.turns[0];
  const tools = toolNames(turn);
  const plan = latestSuccessfulPlan(turn);
  const finalize = successfulToolStep(turn, "finalize_meal_plan");
  const selected = finalize?.rawArguments?.selectedDishes ?? [];
  const persisted = plan?.agentSelectedTemplateIds ?? [];
  return verdict(
    Boolean(
      !turn.error &&
        hasNativeModel(turn) &&
        !hasFallback(turn) &&
        hasToolsInOrder(tools, [
          "get_day_context",
          "find_dish_candidates",
          "finalize_meal_plan"
        ]) &&
        finalize &&
        plan?.status === "valid" &&
        sameIds(selected.map((item) => item.templateId), persisted) &&
        !claimsWrite(turn)
    ),
    {
      observedTools: tools,
      selectedTemplateIds: selected.map((item) => item.templateId),
      persistedSelectedTemplateIds: persisted,
      noWriteClaim: !claimsWrite(turn)
    }
  );
}

function evaluateInventoryLoop(scenario) {
  const preview = scenario.turns[0];
  const followUp = scenario.turns[1];
  const confirmation = scenario.confirmations[0];
  const beforePreview = preview?.stateBefore;
  const afterPreview = preview?.stateAfter;
  const afterReplay = confirmation?.stateAfterReplay;
  const tofuBefore = quantityForFood(beforePreview, "food-tofu");
  const tofuAfter = quantityForFood(afterReplay, "food-tofu");
  return verdict(
    Boolean(
      preview &&
        hasNativeModel(preview) &&
        !hasFallback(preview) &&
        successfulToolStep(preview, "preview_inventory_change") &&
        sameJson(beforePreview?.inventory, afterPreview?.inventory) &&
        taskIsWaitingConfirmation(preview) &&
        confirmation?.first?.ok === true &&
        confirmation?.replay?.ok === true &&
        confirmation?.replay?.receipt?.replayed === true &&
        confirmation?.firstWriteDelta?.inventoryLedger === 1 &&
        confirmation?.replayWriteDelta?.inventoryLedger === 0 &&
        Math.round((tofuAfter - tofuBefore) * 1000) / 1000 === 700 &&
        followUp &&
        hasNativeModel(followUp) &&
        !hasFallback(followUp) &&
        successfulToolStep(followUp, "finalize_meal_plan") &&
        turnHasActivePlan(followUp) &&
        latestSuccessfulPlan(followUp)?.status === "valid"
    ),
    {
      observedTools: [...toolNames(preview), ...toolNames(followUp)],
      previewDidNotWrite: sameJson(beforePreview?.inventory, afterPreview?.inventory),
      tofuDeltaG: Math.round((tofuAfter - tofuBefore) * 1000) / 1000,
      firstWriteDelta: confirmation?.firstWriteDelta ?? null,
      replayWriteDelta: confirmation?.replayWriteDelta ?? null,
      followUpPlanReady:
        turnHasActivePlan(followUp) &&
        latestSuccessfulPlan(followUp)?.status === "valid"
    }
  );
}

function evaluateMealCompletion(scenario) {
  const preview = scenario.turns[0];
  const readBack = scenario.turns[1];
  const confirmation = scenario.confirmations[0];
  return verdict(
    Boolean(
      preview &&
        hasNativeModel(preview) &&
        !hasFallback(preview) &&
        successfulToolStep(preview, "preview_meal_completion") &&
        sameJson(preview.stateBefore?.ledger, preview.stateAfter?.ledger) &&
        sameJson(preview.stateBefore?.mealRecords, preview.stateAfter?.mealRecords) &&
        confirmation?.first?.ok === true &&
        confirmation?.replay?.ok === true &&
        confirmation?.replay?.receipt?.replayed === true &&
        confirmation?.firstWriteDelta?.mealRecords === 1 &&
        confirmation?.replayWriteDelta?.mealRecords === 0 &&
        confirmation?.firstWriteDelta?.intakeVersion === 1 &&
        confirmation?.replayWriteDelta?.intakeVersion === 0 &&
        readBack &&
        hasNativeModel(readBack) &&
        !hasFallback(readBack)
    ),
    {
      observedTools: [...toolNames(preview), ...toolNames(readBack)],
      previewDidNotWrite:
        sameJson(preview.stateBefore?.ledger, preview.stateAfter?.ledger) &&
        sameJson(preview.stateBefore?.mealRecords, preview.stateAfter?.mealRecords),
      firstWriteDelta: confirmation?.firstWriteDelta ?? null,
      replayWriteDelta: confirmation?.replayWriteDelta ?? null
    }
  );
}

function evaluatePlanRevision(scenario) {
  const turn = scenario.turns[0];
  const finalize = successfulToolStep(turn, "finalize_meal_plan");
  const plan = latestSuccessfulPlan(turn);
  const rejected = new Set([
    ...(finalize?.effectiveArguments?.rejectedFoodIds ?? []),
    ...(plan?.rejectedFoodIds ?? [])
  ]);
  return verdict(
    Boolean(
      turn &&
        hasNativeModel(turn) &&
        !hasFallback(turn) &&
        successfulToolStep(turn, "find_dish_candidates") &&
        finalize &&
        plan?.status === "valid" &&
        rejected.has("food-chicken-leg")
    ),
    {
      observedTools: toolNames(turn),
      rejectedFoodIds: [...rejected],
      activePlan: plan
    }
  );
}

function evaluateFamilyMemory(scenario) {
  const preview = scenario.turns[0];
  const readBack = scenario.turns[1];
  const confirmation = scenario.confirmations[0];
  const beforeMemory = preview?.stateBefore?.preferences ?? [];
  const afterPreviewMemory = preview?.stateAfter?.preferences ?? [];
  const afterReplayMemory = confirmation?.stateAfterReplay?.preferences ?? [];
  return verdict(
    Boolean(
      preview &&
        hasNativeModel(preview) &&
        !hasFallback(preview) &&
        successfulToolStep(preview, "preview_member_memory_change") &&
        sameJson(beforeMemory, afterPreviewMemory) &&
        confirmation?.first?.ok === true &&
        confirmation?.replay?.ok === true &&
        confirmation?.replay?.receipt?.replayed === true &&
        afterReplayMemory.some((item) => item.note.includes("少油清淡")) &&
        readBack &&
        hasNativeModel(readBack) &&
        !hasFallback(readBack)
    ),
    {
      observedTools: [...toolNames(preview), ...toolNames(readBack)],
      previewDidNotWrite: sameJson(beforeMemory, afterPreviewMemory),
      memoryVisibleAfterConfirm: afterReplayMemory.filter((item) =>
        item.note.includes("少油清淡")
      )
    }
  );
}

function evaluateRagHandoff(scenario) {
  const first = scenario.turns[0];
  const corrected = scenario.turns[1];
  const firstPreview = successfulToolStep(first, "preview_caregiver_task");
  const correctedPreview = successfulToolStep(corrected, "preview_caregiver_task");
  const latestPending = corrected?.stateAfter?.pendingActions?.at(-1);
  const taskCardText = JSON.stringify(
    correctedPreview?.gatewayInvocation?.result?.data?.taskCard ??
      corrected?.uiOnly?.taskCard ??
      ""
  );
  const unsafe = /(糖尿病|高血压|血糖|胰岛素|药物|healthTags|confirmationToken)/i.test(
    taskCardText
  );
  return verdict(
    Boolean(
      first &&
        corrected &&
        hasNativeModel(first) &&
        hasNativeModel(corrected) &&
        !hasFallback(first) &&
        !hasFallback(corrected) &&
        toolNames(first).includes("retrieve_local_knowledge") &&
        first.retrievalSourceIds?.length > 0 &&
        firstPreview &&
        correctedPreview &&
        corrected?.uiOnly?.taskCard?.recipientLabel === "阿姨" &&
        latestPending?.status === "pending" &&
        !unsafe
    ),
    {
      observedTools: [...toolNames(first), ...toolNames(corrected)],
      retrievedSourceIds: first.retrievalSourceIds ?? [],
      firstRecipient: first?.uiOnly?.taskCard?.recipientLabel ?? null,
      correctedRecipient: corrected?.uiOnly?.taskCard?.recipientLabel ?? null,
      latestPendingStatus: latestPending?.status ?? null,
      disclosureSafe: !unsafe
    }
  );
}

function verdict(pass, details) {
  return { status: pass ? "PASS" : "FAIL", details };
}

function markBlockedScenario(scenario, blockedBy, reason) {
  scenario.blockedBy = blockedBy;
  scenario.evaluation = {
    status: "BLOCKED",
    details: { blockedBy, reason }
  };
}

function toolNames(turn) {
  return (turn?.toolInvocations ?? []).map((item) => item.tool);
}

function successfulToolStep(turn, name) {
  return (turn?.modelSteps ?? []).find(
    (step) => {
      if (
        step.decision !== "tool" ||
        step.tool !== name ||
        step.toolResult?.ok !== true
      ) {
        return false;
      }
      if (name !== "finalize_meal_plan") return true;
      return hasValidPlanResult(step.gatewayInvocation?.result?.data);
    }
  );
}

function hasValidPlanResult(data) {
  const plan = data?.plan;
  return Boolean(
    (data?.status === "ok" || data?.status === "valid") &&
      plan &&
      (plan.status === "ok" || plan.status === "valid") &&
      Array.isArray(plan.menu) &&
      plan.menu.length > 0
  );
}

function hasActivePlan(agent) {
  return Boolean(agent?.state?.activePlanId && agent?.state?.activePlanVersion);
}

function turnHasActivePlan(turn) {
  return Boolean(
    turn?.stateAfter?.agent?.activePlanId ?? turn?.agentState?.activePlanId
  );
}

function latestSuccessfulPlan(turn) {
  const plans = turn?.stateAfter?.plans ?? [];
  return [...plans].reverse().find((plan) => plan.status === "valid") ?? null;
}

function hasNativeModel(turn) {
  return Boolean(
    turn &&
      turn.modelSteps.length > 0 &&
      turn.modelSteps.every((step) => step.providerMode === "local_vllm") &&
      turn.modelHttp.length > 0
  );
}

function hasFallback(turn) {
  return Boolean(
    turn?.modelSteps?.some((step) => step.decision === "deterministic_fallback")
  );
}

function claimsWrite(turn) {
  return Boolean(
    /(已入库|已扣除|已经发送|已发送|已写入|库存已增加|库存已减少)/.test(
      turn?.answer ?? ""
    )
  );
}

function taskIsWaitingConfirmation(turn) {
  return (
    turn?.taskState?.status === "waiting_confirmation" &&
    turn?.taskState?.workflowStage === "awaiting_confirm"
  );
}

function hasToolsInOrder(actual, required) {
  let cursor = 0;
  for (const item of actual) {
    if (item === required[cursor]) cursor += 1;
    if (cursor === required.length) return true;
  }
  return false;
}

function sameIds(left, right) {
  return JSON.stringify(left) === JSON.stringify(right);
}

function sameJson(left, right) {
  return JSON.stringify(left) === JSON.stringify(right);
}

function quantityForFood(snapshotValue, foodId) {
  const item = snapshotValue?.inventory?.find((row) => row.foodId === foodId);
  return Number(item?.quantity?.estimateG ?? 0);
}

function runId() {
  return process.env.PRIVATEPLATE_RUN_ID ?? "radeon-diagnostic";
}

function buildSummary(environmentValue, scenarioValues) {
  const core = scenarioValues.filter((item) => item.category === "core");
  const auxiliary = scenarioValues.filter((item) => item.category === "auxiliary");
  const safety = {
    deterministicFallbacks: scenarioValues.flatMap((item) =>
      item.turns.flatMap((turn) =>
        turn.modelSteps
          .filter((step) => step.decision === "deterministic_fallback")
          .map((step) => ({ scenarioId: item.id, step }))
      )
    ),
    formatRetries: scenarioValues.flatMap((item) =>
      item.turns.flatMap((turn) =>
        turn.modelSteps
          .filter((step) => step.decision === "retry")
          .map((step) => ({ scenarioId: item.id, step }))
      )
    ),
    falseWriteClaims: scenarioValues.flatMap((item) =>
      item.turns
        .filter((turn) => claimsWrite(turn))
        .map((turn) => ({ scenarioId: item.id, turnIndex: turn.index }))
    ),
    privacyIssues: scenarioValues.flatMap((item) =>
      item.turns.flatMap((turn) =>
        turn.modelSteps
          .filter((step) => step.policy?.privacyViolation)
          .map((step) => ({ scenarioId: item.id, step }))
      )
    )
  };
  const corePassed = core.every((item) => item.evaluation?.status === "PASS");
  const auxiliaryPassed = auxiliary.filter(
    (item) => item.evaluation?.status === "PASS"
  ).length;
  const conclusion = corePassed && auxiliaryPassed >= 2
    ? "READY_FOR_WEB"
    : corePassed
      ? "NEED_ONE_FOCUSED_FIX"
      : "PRODUCT_FLOW_BLOCKED";
  return {
    runKind: "diagnostic",
    environment: {
      status: environmentValue.status,
      provider: environmentValue.provider,
      source: environmentValue.source,
      instance: environmentValue.instance
    },
    scenarios: scenarioValues.map((item) => ({
      id: item.id,
      category: item.category,
      status: item.evaluation?.status ?? "FAIL",
      blockedBy: item.blockedBy ?? item.evaluation?.details?.blockedBy ?? null,
      details: item.evaluation?.details ?? null,
      turnCount: item.turns.length,
      confirmationCount: item.confirmations.length
    })),
    corePassed,
    auxiliaryPassed,
    independentFailureCount: scenarioValues.filter(
      (item) =>
        item.evaluation?.status === "FAIL" &&
        !(item.blockedBy ?? item.evaluation?.details?.blockedBy)
    ).length,
    blockedScenarioCount: scenarioValues.filter(
      (item) => item.evaluation?.status === "BLOCKED"
    ).length,
    safety,
    conclusion
  };
}

function parseJson(value) {
  if (value == null) return value ?? null;
  if (typeof value !== "string") return sanitize(value);
  try {
    return sanitize(JSON.parse(value));
  } catch {
    return value;
  }
}

function sanitize(value, key = "") {
  if (value == null) return value;
  const lowerKey = key.toLowerCase();
  if (
    lowerKey.includes("confirmationtoken") ||
    lowerKey.includes("confirmation_token") ||
    lowerKey === "authorization" ||
    lowerKey === "apikey" ||
    lowerKey === "api_key"
  ) {
    return "[redacted]";
  }
  if (Array.isArray(value)) return value.map((item) => sanitize(item));
  if (typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value).map(([entryKey, entryValue]) => [
      entryKey,
      sanitize(entryValue, entryKey)
    ])
  );
}

function sanitizeHeaders(headers) {
  if (!headers) return {};
  return Object.fromEntries(
    [...new Headers(headers).entries()].map(([key, value]) => [
      key,
      key === "authorization" ? "[redacted]" : value
    ])
  );
}

function serializeError(error) {
  return {
    name: error?.name ?? "Error",
    message: error?.message ?? String(error),
    code: error?.code ?? null,
    stack: error?.stack ?? null
  };
}

async function saveScenario(scenario) {
  await writeJson(path.join(outDir, `scenario-${scenario.id}.json`), scenario);
}

async function writeJson(filePath, value) {
  await writeFile(filePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}
