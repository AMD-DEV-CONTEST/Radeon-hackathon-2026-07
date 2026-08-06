import crypto from "node:crypto";
import fs from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";

import {
  callOfficial,
  fetchUsage,
  locateProfilePage,
} from "./tokenfactory_corpus_runner.mjs";
import {
  inputFingerprint,
  QUALITY_PROTOCOL_VERSION,
  redactedRepairHints,
  sha256,
  validateOpenTodoResponse,
  validateStoredOpenTodoRecord,
} from "./tokenfactory_open_todo_quality.mjs";


const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const CDP_URL = "http://127.0.0.1:9222";
const OFFICIAL_ENDPOINT =
  "https://developer.amd.com.cn/radeon/api/v1/chat/completions";
const SAFE_RPM = 28;
const START_INTERVAL_MS = Math.ceil(60_000 / SAFE_RPM);
const MAX_IN_FLIGHT = 28;
const QUALITY_CHUNK_SIZE = SAFE_RPM * 4;
const MINIMUM_CIRCUIT_SAMPLE = 12;
const MINIMUM_HEALTHY_CHUNK_PASS_RATE = 0.5;
const REPAIR_PASSES = 2;
const STOP_REMAINING_USD = 0.0001;
const RESET_GUARD_MS = 180_000;
const DEFAULT_RUNTIME_MS = 4 * 60 * 60 * 1000;
const CONSERVATIVE_CALL_COST_USD = 0.0045;
const DERIVATIVE_GENERATION_ALLOWED = false;
const TERMS_RECEIPT_SHA256 = null;

const ROLES = Object.freeze([
  ["systems_architect", "Qwen3.6-35B-A3B"],
  ["training_data_curator", "Qwen3.6-35B-A3B"],
  ["adversarial_research_reviewer", "DeepSeek-V4-Flash"],
  ["four_a_strategy_director", "Qwen3.6-35B-A3B"],
  ["multimodal_product_director", "Qwen3.6-35B-A3B"],
  ["causal_effectiveness_lead", "DeepSeek-V4-Flash"],
  ["agent_reliability_engineer", "Qwen3.6-35B-A3B"],
  ["radeon_training_engineer", "Qwen3.6-35B-A3B"],
  ["rights_safety_auditor", "DeepSeek-V4-Flash"],
  ["creative_production_director", "Qwen3.6-35B-A3B"],
  ["seo_geo_growth_scientist", "Qwen3.6-35B-A3B"],
  ["media_activation_optimizer", "DeepSeek-V4-Flash"],
  ["gtm_data_analytics_lead", "Qwen3.6-35B-A3B"],
  ["video_audio_quality_lead", "Qwen3.6-35B-A3B"],
  ["blind_human_eval_designer", "DeepSeek-V4-Flash"],
  ["execution_evidence_compiler", "Qwen3.6-35B-A3B"],
]);


function taskMap(markdown) {
  const result = new Map();
  for (const line of markdown.split(/\r?\n/)) {
    const match = /^(\d{4})\s+\[D\/A\/I\/E\](?:\[[TPX]\])?\s+(.+?)[。.]?\s*$/.exec(
      line.trim(),
    );
    if (match) result.set(match[1], match[2]);
  }
  return result;
}


function roleInstruction(role) {
  const shared = [
    "Return one strict RFC 8259 JSON object and no Markdown or prose outside it.",
    "Use exactly these root keys: todo_id, role, reuse, hypothesis, mechanism,",
    "implementation, training_examples, ablations, metrics, stop_rule, rollback,",
    "radeon_action, rights_gate, evidence_class, external_blockers, current_status.",
    "todo_id and role must exactly match the supplied values. training_examples must",
    "be an array of 6-8 distinct source-safe objects. Every example must visibly",
    "contain state, action, observation, repair, acceptance_target. Cover positive,",
    "negative, adversarial, and repair cases with concrete schemas or tool arguments.",
    "Set evidence_class to planned_official_advisory. Set rights_gate to",
    "evaluator_only_pending_terms; output_training_rights_not_captured. current_status",
    "must be not_started or in_progress. Do not pad, invent citations, claim execution,",
    "expose hidden reasoning, or turn self-review into evidence. Plans never close TODOs.",
  ].join(" ");
  const specific = {
    systems_architect:
      "Design the smallest typed architecture delta that is meaningfully beyond generic multi-agent orchestration.",
    training_data_curator:
      "Design rights-bound CPT/SFT/preference/trajectory/repair examples, leakage controls, sampling and rejection rules.",
    adversarial_research_reviewer:
      "Try to falsify novelty and quality; identify missing baselines, negative controls, confounders and reproducibility gaps.",
    four_a_strategy_director:
      "Specify North-American top-agency-level strategy and craft behavior without copying protected campaigns or identities.",
    multimodal_product_director:
      "Specify the image, video, audio, text and analytics product behavior, direct manipulation and blind user-visible comparison.",
    causal_effectiveness_lead:
      "Specify unit, treatment, counterfactual, negative control, interference, attribution and decision thresholds; reject proxy uplift.",
    agent_reliability_engineer:
      "Specify state ownership, tool contracts, retries, idempotency, observability, recovery, long-horizon and adversarial tests.",
    radeon_training_engineer:
      "Specify executable ROCm LoRA/SFT or evaluation steps, memory fit, checkpointing, single-card truth and >=2-GPU equivalence gates.",
    rights_safety_auditor:
      "Separate public research reference, licensed training material, evaluator-only model output, privacy, claim and human-release gates.",
    creative_production_director:
      "Turn the mechanism into a coherent cross-channel creative production system with craft grammar, accessibility, brand locks and reversible asset repair.",
    seo_geo_growth_scientist:
      "Specify search, GEO, discoverability and content-system experiments with query cohorts, citation integrity, cannibalization and incrementality controls.",
    media_activation_optimizer:
      "Specify audience, creative, budget, pacing, auction, fatigue and channel-allocation decisions with causal holdouts and spend safety.",
    gtm_data_analytics_lead:
      "Specify metric ontology, event schemas, data quality, attribution, uncertainty, dashboards, anomaly response and decision thresholds.",
    video_audio_quality_lead:
      "Specify 4K video and production-audio continuity, identity, motion, lip-sync, pronunciation, temporal and perceptual quality gates.",
    blind_human_eval_designer:
      "Specify blinded expert review, sample allocation, anchors, inter-rater reliability, disagreement routing and preregistered promotion thresholds.",
    execution_evidence_compiler:
      "Compile a build-ready D/A/I/E record with exact files, tests and evidence locators; retain every external blocker truthfully.",
  }[role];
  if (!specific) throw new Error(`missing role instruction: ${role}`);
  return `${specific} ${shared}`;
}


async function secureDirectory(directoryPath) {
  await fs.mkdir(directoryPath, { recursive: true, mode: 0o700 });
  await fs.chmod(directoryPath, 0o700);
}


async function syncDirectory(directoryPath) {
  let handle;
  try {
    handle = await fs.open(directoryPath, "r");
    await handle.sync();
  } catch (error) {
    if (!["EINVAL", "ENOTSUP", "EBADF"].includes(error?.code)) throw error;
  } finally {
    await handle?.close();
  }
}


async function atomicWriteJson(filePath, payload) {
  const directoryPath = path.dirname(filePath);
  await fs.mkdir(directoryPath, { recursive: true });
  const temporaryPath = path.join(
    directoryPath,
    `.${path.basename(filePath)}.${process.pid}.${crypto.randomUUID()}.tmp`,
  );
  const serialized = `${JSON.stringify(payload, null, 2)}\n`;
  let handle;
  try {
    handle = await fs.open(temporaryPath, "wx", 0o600);
    await handle.writeFile(serialized, "utf8");
    await handle.sync();
    await handle.close();
    handle = null;
    await fs.chmod(temporaryPath, 0o600);
    await fs.rename(temporaryPath, filePath);
    await fs.chmod(filePath, 0o600);
    await syncDirectory(directoryPath);
  } catch (error) {
    await handle?.close();
    await fs.unlink(temporaryPath).catch(() => {});
    throw error;
  }
}


function safeStoredResult(result, violations) {
  const suppressContent = violations.includes("credential_pattern_present");
  return {
    ok: result?.ok === true,
    http_status: Number(result?.http_status || 0),
    response_id: result?.response_id || null,
    model: result?.model || null,
    content: suppressContent ? "" : String(result?.content || ""),
    reasoning_present: result?.reasoning_present === true,
    finish_reason: result?.finish_reason || null,
    usage:
      result?.usage && typeof result.usage === "object" ? result.usage : {},
    error_code: result?.error_code || null,
    error_message: null,
    duration_ms: Number(result?.duration_ms || 0),
  };
}


function temperatureFor(role) {
  return role.includes("adversarial") ? 0.05 : 0.15;
}


async function priorRoleOutputHashes(privateRoot, todoId, roundIndex) {
  const hashes = [];
  for (let index = 0; index < roundIndex; index += 1) {
    const [priorRole] = ROLES[index];
    try {
      const payload = JSON.parse(
        await fs.readFile(
          path.join(privateRoot, priorRole, `${todoId}.json`),
          "utf8",
        ),
      );
      if (
        payload.status === "passed" &&
        payload.quality_protocol === QUALITY_PROTOCOL_VERSION &&
        typeof payload.output_sha256 === "string"
      ) {
        hashes.push(payload.output_sha256);
      }
    } catch {
      // The strict role barrier prevents a later role from starting if this occurs.
    }
  }
  return hashes;
}


function expectedInput({ todoId, requirement, role, model, priorOutputSha256s }) {
  const instruction = roleInstruction(role);
  const temperature = temperatureFor(role);
  const maxTokens = 4096;
  return {
    instruction,
    temperature,
    maxTokens,
    fingerprint: inputFingerprint({
      todoId,
      requirement,
      role,
      roleInstruction: instruction,
      model,
      temperature,
      maxTokens,
      derivativeGenerationAllowed: DERIVATIVE_GENERATION_ALLOWED,
      priorOutputSha256s,
    }),
  };
}


function additionalRecordViolations(record, expectedPriorOutputSha256s) {
  const violations = [];
  if (record?.status !== "passed") violations.push("record_status_not_passed");
  if (record?.quality_protocol !== QUALITY_PROTOCOL_VERSION) {
    violations.push("quality_protocol_mismatch");
  }
  if (
    !Array.isArray(record?.quality_violations) ||
    record.quality_violations.length !== 0
  ) {
    violations.push("stored_quality_violations_present");
  }
  if (record?.derivative_generation_allowed !== false) {
    violations.push("derivative_generation_not_false");
  }
  if (record?.terms_receipt_sha256 !== null) {
    violations.push("terms_receipt_not_null");
  }
  if (!Array.isArray(record?.prior_output_sha256s)) {
    violations.push("prior_output_hashes_missing");
  } else if (
    JSON.stringify(record.prior_output_sha256s) !==
    JSON.stringify(expectedPriorOutputSha256s)
  ) {
    violations.push("prior_output_hashes_mismatch");
  }
  if (!Number.isInteger(record?.attempts) || record.attempts < 1) {
    violations.push("attempt_count_invalid");
  }
  if (typeof record?.generated_at !== "string" || !record.generated_at) {
    violations.push("generated_at_missing");
  }
  if (typeof record?.run_id !== "string" || !record.run_id) {
    violations.push("run_id_missing");
  }
  return violations;
}


async function readExisting(filePath) {
  try {
    const raw = await fs.readFile(filePath, "utf8");
    return { record: JSON.parse(raw), recordSha256: sha256(raw) };
  } catch {
    return { record: null, recordSha256: null };
  }
}


async function assessOrMigrateExisting({
  filePath,
  todoId,
  requirement,
  role,
  model,
  expected,
  priorOutputSha256s,
  legacyMigrationAllowed,
  runId,
}) {
  const { record, recordSha256 } = await readExisting(filePath);
  if (!record) {
    return {
      passed: false,
      migrated: false,
      violations: ["missing_record"],
      attempts: 0,
      previousAttemptOutputSha256s: [],
    };
  }

  if (record.quality_protocol === QUALITY_PROTOCOL_VERSION) {
    const validation = validateStoredOpenTodoRecord(record, {
      todoId,
      role,
      inputFingerprint: expected.fingerprint,
    });
    const violations = [
      ...new Set([
        ...validation.violations,
        ...additionalRecordViolations(record, priorOutputSha256s),
      ]),
    ];
    return {
      passed: violations.length === 0,
      migrated: false,
      violations,
      attempts: Number.isInteger(record.attempts) ? record.attempts : 0,
      previousAttemptOutputSha256s: [
        ...(Array.isArray(record.prior_attempt_output_sha256s)
          ? record.prior_attempt_output_sha256s
          : []),
        ...(typeof record.output_sha256 === "string"
          ? [record.output_sha256]
          : []),
      ],
    };
  }

  const legacyValidation = validateOpenTodoResponse({
    result: record.result,
    todoId,
    role,
    expectedOutputSha256: record.output_sha256 || null,
  });
  const legacyFlagsSafe =
    record.accepted_as_training_material === false &&
    record.credential_persisted === false &&
    record.derivative_generation_allowed !== true;
  if (legacyMigrationAllowed && legacyFlagsSafe && legacyValidation.passed) {
    const migratedRecord = {
      schema: "ProofLaunchOfficialOpenTodoDeepReviewV2",
      status: "passed",
      quality_protocol: QUALITY_PROTOCOL_VERSION,
      quality_violations: [],
      todo_id: todoId,
      requirement,
      role,
      requested_model: model,
      input_fingerprint_sha256: expected.fingerprint,
      prompt_sha256:
        typeof record.prompt_sha256 === "string" ? record.prompt_sha256 : null,
      prior_output_sha256s: priorOutputSha256s,
      prior_attempt_output_sha256s: [],
      prior_outputs_reused: false,
      attempts: Math.max(1, Number(record.attempts || 1)),
      http_status: record.result.http_status,
      output_sha256: legacyValidation.outputSha256,
      parsed_output_sha256: legacyValidation.parsedOutputSha256,
      result: safeStoredResult(record.result, legacyValidation.violations),
      generated_at: new Date().toISOString(),
      run_id: runId,
      derivative_generation_allowed: DERIVATIVE_GENERATION_ALLOWED,
      terms_receipt_sha256: TERMS_RECEIPT_SHA256,
      accepted_as_training_material: false,
      training_admission_reason: "AMD output-training terms not captured",
      credential_persisted: false,
      migration: {
        from_schema: record.schema || null,
        original_record_sha256: recordSha256,
        migrated_at: new Date().toISOString(),
        deterministic_revalidation_passed: true,
      },
    };
    await atomicWriteJson(filePath, migratedRecord);
    return {
      passed: true,
      migrated: true,
      violations: [],
      attempts: migratedRecord.attempts,
      previousAttemptOutputSha256s: [],
    };
  }

  const violations = [...legacyValidation.violations];
  if (!legacyMigrationAllowed) violations.push("legacy_prior_reuse_not_migratable");
  if (!legacyFlagsSafe) violations.push("legacy_rights_flags_not_safe");
  return {
    passed: false,
    migrated: false,
    violations: [...new Set(violations)],
    attempts: Number.isInteger(record.attempts) ? record.attempts : 0,
    previousAttemptOutputSha256s:
      typeof record.output_sha256 === "string" ? [record.output_sha256] : [],
  };
}


function buildPrompt({ todoId, requirement, role, instruction, repairHints }) {
  const repairContext = repairHints.length
    ? [
        "Deterministic repair hints only; no prior output or excerpt is supplied:",
        repairHints.join(", "),
        "Rebuild the entire JSON object from the canonical TODO and role contract.",
      ].join(" ")
    : "No prior output, excerpt, or derivative context is supplied.";
  return [
    `Canonical TODO ${todoId}: ${requirement}`,
    `Role: ${role}`,
    `The JSON member todo_id MUST be the exact four-character string "${todoId}". Do not prefix, suffix, explain, or repeat the requirement inside todo_id.`,
    instruction,
    repairContext,
    "Provider output remains evaluator-only while output-training terms are unresolved.",
  ].join("\n\n");
}


function createMutex() {
  let tail = Promise.resolve();
  return async (operation) => {
    let release;
    const previous = tail;
    tail = new Promise((resolve) => {
      release = resolve;
    });
    await previous;
    try {
      return await operation();
    } finally {
      release();
    }
  };
}


function transientPageFailure(error) {
  const message = String(error?.message || error);
  return (
    message.includes("Execution context was destroyed") ||
    message.includes("Cannot find context with specified id") ||
    message.includes("Target page, context or browser has been closed") ||
    message.includes("Failed to fetch") ||
    message.includes("NetworkError")
  );
}


function blockedCallResult(errorCode) {
  return {
    ok: false,
    http_status: 0,
    response_id: null,
    model: null,
    content: "",
    reasoning_present: false,
    finish_reason: null,
    usage: {},
    error_code: errorCode,
    error_message: null,
    duration_ms: 0,
  };
}


async function main() {
  const projectRoot = path.resolve(process.argv[2] || process.cwd());
  const receiptPath = path.join(
    projectRoot,
    "evidence/v10/open-todo-official-deep-review-run.json",
  );
  const runId = crypto.randomUUID();
  const startedAt = new Date().toISOString();
  const runtimeMs = Number(process.env.TOKENFACTORY_RUNTIME_MS || DEFAULT_RUNTIME_MS);
  let requirements = new Map();
  let openIds = [];
  let privateRoot = null;
  let browser = null;
  let page = null;
  let openingUsage = null;
  let closingUsage = null;
  let expectedResetAt = null;
  let deadline = Date.now() + runtimeMs;
  let nextStartAt = Date.now();
  let stopReason = null;
  let fatalError = null;
  let attempted = 0;
  let passedAttempts = 0;
  let blockedAttempts = 0;
  let skipped = 0;
  let migrated = 0;
  let activeBudgetReservationsUsd = 0;
  const roleSummaries = [];
  const withBudgetLock = createMutex();
  const withPageRecoveryLock = createMutex();

  async function callOfficialWithPageRecovery(payload) {
    for (let attempt = 1; attempt <= 3; attempt += 1) {
      try {
        return await callOfficial(page, payload);
      } catch (error) {
        if (!transientPageFailure(error) || attempt === 3) {
          return blockedCallResult("page_context_error");
        }
        await withPageRecoveryLock(async () => {
          page = await locateProfilePage(browser);
        });
        await new Promise((resolve) => setTimeout(resolve, attempt * 500));
      }
    }
    return blockedCallResult("page_recovery_exhausted");
  }

  async function reserveBudget() {
    return withBudgetLock(async () => {
      if (stopReason) return null;
      if (Date.now() >= deadline) {
        stopReason = "four_hour_or_reset_deadline";
        return null;
      }
      const usage = await fetchUsage(page);
      if (usage.daily_reset_at !== expectedResetAt) {
        stopReason = "daily_window_reset_changed";
        return null;
      }
      const availableUsd =
        usage.daily_cost_remaining_usd -
        STOP_REMAINING_USD -
        activeBudgetReservationsUsd;
      if (availableUsd < CONSERVATIVE_CALL_COST_USD) {
        stopReason = "daily_budget_guard";
        return null;
      }
      activeBudgetReservationsUsd += CONSERVATIVE_CALL_COST_USD;
      return { reservedUsd: CONSERVATIVE_CALL_COST_USD };
    });
  }

  async function releaseBudget(reservation) {
    if (!reservation) return;
    await withBudgetLock(async () => {
      activeBudgetReservationsUsd = Math.max(
        0,
        activeBudgetReservationsUsd - reservation.reservedUsd,
      );
    });
  }

  async function acquireRateSlot() {
    const now = Date.now();
    const startAt = Math.max(now, nextStartAt);
    nextStartAt = startAt + START_INTERVAL_MS;
    if (startAt > now) {
      await new Promise((resolve) => setTimeout(resolve, startAt - now));
    }
  }

  try {
    if (!Number.isFinite(runtimeMs) || runtimeMs <= 0) {
      throw new Error("TOKENFACTORY_RUNTIME_MS must be a positive number");
    }
    const todoPath = path.join(projectRoot, "docs/CORTEX_X_V10_1500_TODO.md");
    const markdown = await fs.readFile(todoPath, "utf8");
    requirements = taskMap(markdown);
    const sourceTodoSha256 = sha256(markdown);
    const program = JSON.parse(
      await fs.readFile(
        path.join(projectRoot, "evidence/v10/program-manifest.json"),
        "utf8",
      ),
    );
    openIds = program.todos
      .filter((item) => item.status !== "passed")
      .map((item) => item.todo_id)
      .filter((todoId) => requirements.has(todoId));
    privateRoot = path.join(
      projectRoot,
      "data/tokenfactory_teacher_v10/_open_todo_deep_review",
    );
    await secureDirectory(privateRoot);
    browser = await chromium.connectOverCDP(CDP_URL);
    page = await locateProfilePage(browser);
    openingUsage = await fetchUsage(page);
    expectedResetAt = openingUsage.daily_reset_at;
    const resetEpochMs = Date.parse(expectedResetAt);
    if (Number.isFinite(resetEpochMs)) {
      deadline = Math.min(deadline, resetEpochMs - RESET_GUARD_MS);
    }

    for (let roundIndex = 0; roundIndex < ROLES.length; roundIndex += 1) {
      if (stopReason) break;
      const [role, model] = ROLES[roundIndex];
      const roleRoot = path.join(privateRoot, role);
      await secureDirectory(roleRoot);
      const summary = {
        role,
        model,
        attempted: 0,
        passed_attempts: 0,
        blocked_attempts: 0,
        migrated: 0,
        passed_records: 0,
        blocked_records: 0,
      };
      roleSummaries.push(summary);

      for (let pass = 0; pass <= REPAIR_PASSES; pass += 1) {
        if (stopReason) break;
        const pending = [];
        let passedRecords = 0;
        for (const todoId of openIds) {
          const requirement = requirements.get(todoId);
          const priorOutputSha256s = await priorRoleOutputHashes(
            privateRoot,
            todoId,
            roundIndex,
          );
          if (priorOutputSha256s.length !== roundIndex) {
            stopReason = "strict_role_lineage_barrier";
            break;
          }
          const expected = expectedInput({
            todoId,
            requirement,
            role,
            model,
            priorOutputSha256s,
          });
          const outputPath = path.join(roleRoot, `${todoId}.json`);
          const assessment = await assessOrMigrateExisting({
            filePath: outputPath,
            todoId,
            requirement,
            role,
            model,
            expected,
            priorOutputSha256s,
            legacyMigrationAllowed: roundIndex === 0,
            runId,
          });
          if (assessment.migrated) {
            migrated += 1;
            summary.migrated += 1;
          }
          if (assessment.passed) {
            passedRecords += 1;
            if (pass === 0 && !assessment.migrated) skipped += 1;
            continue;
          }
          pending.push({
            todoId,
            requirement,
            priorOutputSha256s,
            expected,
            outputPath,
            priorViolations: assessment.violations,
            attempts: assessment.attempts,
            previousAttemptOutputSha256s:
              assessment.previousAttemptOutputSha256s,
          });
        }
        if (stopReason) break;
        summary.passed_records = passedRecords;
        if (!pending.length) break;

        for (let chunkStart = 0; chunkStart < pending.length; chunkStart += QUALITY_CHUNK_SIZE) {
          if (stopReason) break;
          const chunk = pending.slice(chunkStart, chunkStart + QUALITY_CHUNK_SIZE);
          let cursor = 0;
          const results = new Array(chunk.length);

          async function worker() {
            while (!stopReason) {
              const index = cursor++;
              if (index >= chunk.length) return;
              const item = chunk[index];
              await acquireRateSlot();
              const reservation = await reserveBudget();
              if (!reservation) return;
              try {
                const repairHints = redactedRepairHints(item.priorViolations);
                const prompt = buildPrompt({
                  todoId: item.todoId,
                  requirement: item.requirement,
                  role,
                  instruction: item.expected.instruction,
                  repairHints,
                });
                const result = await callOfficialWithPageRecovery({
                  model,
                  messages: [
                    {
                      role: "system",
                      content:
                        "Create source-bound, falsifiable GTM engineering and training artifacts. Never reveal hidden reasoning.",
                    },
                    { role: "user", content: prompt },
                  ],
                  temperature: item.expected.temperature,
                  max_tokens: item.expected.maxTokens,
                  chat_template_kwargs: { enable_thinking: false },
                });
                const validation = validateOpenTodoResponse({
                  result,
                  todoId: item.todoId,
                  role,
                });
                const qualityViolations = validation.violations;
                const priorAttemptOutputSha256s = [
                  ...new Set(item.previousAttemptOutputSha256s),
                ];
                const record = {
                  schema: "ProofLaunchOfficialOpenTodoDeepReviewV2",
                  status: validation.passed ? "passed" : "blocked",
                  quality_protocol: QUALITY_PROTOCOL_VERSION,
                  quality_violations: qualityViolations,
                  todo_id: item.todoId,
                  requirement: item.requirement,
                  role,
                  requested_model: model,
                  input_fingerprint_sha256: item.expected.fingerprint,
                  prompt_sha256: sha256(prompt),
                  prior_output_sha256s: item.priorOutputSha256s,
                  prior_attempt_output_sha256s: priorAttemptOutputSha256s,
                  prior_outputs_reused: false,
                  repair_hints: repairHints,
                  repair_pass: pass,
                  attempts: item.attempts + 1,
                  http_status: result.http_status,
                  output_sha256: validation.outputSha256,
                  parsed_output_sha256: validation.parsedOutputSha256,
                  result: safeStoredResult(result, qualityViolations),
                  source_todo_sha256: sourceTodoSha256,
                  accepted_as_training_material: false,
                  training_admission_reason:
                    "AMD output-training terms not captured",
                  derivative_generation_allowed: DERIVATIVE_GENERATION_ALLOWED,
                  terms_receipt_sha256: TERMS_RECEIPT_SHA256,
                  credential_persisted: false,
                  generated_at: new Date().toISOString(),
                  run_id: runId,
                };
                await atomicWriteJson(item.outputPath, record);
                attempted += 1;
                summary.attempted += 1;
                if (record.status === "passed") {
                  passedAttempts += 1;
                  summary.passed_attempts += 1;
                } else {
                  blockedAttempts += 1;
                  summary.blocked_attempts += 1;
                }
                results[index] = { status: record.status };
              } finally {
                await releaseBudget(reservation);
              }
            }
          }

          await Promise.all(
            Array.from(
              { length: Math.min(MAX_IN_FLIGHT, chunk.length) },
              () => worker(),
            ),
          );
          const completedResults = results.filter(Boolean);
          const chunkPassed = completedResults.filter(
            (item) => item.status === "passed",
          ).length;
          if (completedResults.length) {
            const usage = await fetchUsage(page);
            process.stdout.write(
              `${JSON.stringify({
                event: "official_open_todo_progress",
                run_id: runId,
                round: roundIndex + 1,
                role,
                repair_pass: pass,
                attempted,
                passed_attempts: passedAttempts,
                blocked_attempts: blockedAttempts,
                skipped,
                migrated,
                chunk_passed: chunkPassed,
                chunk_blocked: completedResults.length - chunkPassed,
                used_usd: usage.daily_cost_used_usd,
                remaining_usd: usage.daily_cost_remaining_usd,
                reset_at: usage.daily_reset_at,
              })}\n`,
            );
          }
          if (
            completedResults.length >= MINIMUM_CIRCUIT_SAMPLE &&
            chunkPassed / completedResults.length < MINIMUM_HEALTHY_CHUNK_PASS_RATE
          ) {
            stopReason = "quality_circuit_breaker";
          }
        }
      }

      if (stopReason) break;
      let rolePassedRecords = 0;
      for (const todoId of openIds) {
        const requirement = requirements.get(todoId);
        const priorOutputSha256s = await priorRoleOutputHashes(
          privateRoot,
          todoId,
          roundIndex,
        );
        const expected = expectedInput({
          todoId,
          requirement,
          role,
          model,
          priorOutputSha256s,
        });
        const assessment = await assessOrMigrateExisting({
          filePath: path.join(roleRoot, `${todoId}.json`),
          todoId,
          requirement,
          role,
          model,
          expected,
          priorOutputSha256s,
          legacyMigrationAllowed: false,
          runId,
        });
        if (assessment.passed) rolePassedRecords += 1;
      }
      summary.passed_records = rolePassedRecords;
      summary.blocked_records = openIds.length - rolePassedRecords;
      if (rolePassedRecords !== openIds.length) {
        stopReason = "strict_role_quality_barrier";
      }
    }
  } catch (error) {
    fatalError = error;
    stopReason ||= "runner_exception";
  } finally {
    if (page) {
      try {
        closingUsage = await fetchUsage(page);
      } catch {
        closingUsage = null;
      }
    }
    const receipt = {
      schema: "ProofLaunchOfficialOpenTodoDeepReviewRunV2",
      run_id: runId,
      run_status: fatalError
        ? "failed"
        : stopReason
          ? "stopped"
          : "completed",
      official_endpoint: OFFICIAL_ENDPOINT,
      quality_protocol: QUALITY_PROTOCOL_VERSION,
      open_todo_count: openIds.length,
      roles: ROLES.map(([role, model]) => ({ role, model })),
      role_summaries: roleSummaries,
      safe_rpm: SAFE_RPM,
      max_in_flight: MAX_IN_FLIGHT,
      repair_passes: REPAIR_PASSES,
      attempted_requests: attempted,
      passed_attempts: passedAttempts,
      blocked_attempts: blockedAttempts,
      skipped_valid_records: skipped,
      migrated_legacy_records: migrated,
      stop_reason: stopReason,
      opening_usage: openingUsage,
      closing_usage: closingUsage,
      spend_delta_usd:
        openingUsage && closingUsage
          ? closingUsage.daily_cost_used_usd - openingUsage.daily_cost_used_usd
          : null,
      started_at: startedAt,
      completed_at: new Date().toISOString(),
      private_records_persisted: privateRoot !== null,
      credential_persisted: false,
      accepted_as_training_material: false,
      derivative_generation_allowed: DERIVATIVE_GENERATION_ALLOWED,
      terms_receipt_sha256: TERMS_RECEIPT_SHA256,
      truth_boundary:
        "Official API review is evaluator-only advisory; it is not Radeon-local inference, fine-tuning, TODO closure, human review, business lift, or permission to train on provider outputs.",
    };
    try {
      const runReceiptPath = path.join(
        projectRoot,
        `evidence/v10/open-todo-official-deep-review-run-${runId}.json`,
      );
      await atomicWriteJson(runReceiptPath, receipt);
      await atomicWriteJson(receiptPath, receipt);
      process.stdout.write(
        `${JSON.stringify({ event: "official_open_todo_complete", ...receipt })}\n`,
      );
    } catch (receiptError) {
      if (!fatalError) fatalError = receiptError;
    }
  }

  if (fatalError) throw fatalError;
}


await main();
