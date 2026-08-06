import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { createRequire } from "node:module";

import {
  callOfficial,
  fetchUsage,
  locateProfilePage,
} from "./tokenfactory_corpus_runner.mjs";


const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const CDP_URL = "http://127.0.0.1:9222";
const MODEL = "Qwen3.6-35B-A3B";
const SAFE_RPM = 20;
const START_INTERVAL_MS = Math.ceil(60_000 / SAFE_RPM);
const MAX_IN_FLIGHT = 4;
const DEFAULT_RUNTIME_MS = 58 * 60 * 1000;
const RESET_GUARD_MS = 180_000;
const STOP_REMAINING_USD = 0.0001;
const CONSERVATIVE_CALL_COST_USD = 0.006;
const MAX_TOKENS = 1600;
const TASK_PATTERN =
  /^(\d{4})\s+\[D\/A\/I\/E\](?:\[([TPX])\])?\s+(.+?)[。.]?\s*$/;


function sha256(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}


function createMutex() {
  let tail = Promise.resolve();
  return async (operation) => {
    const previous = tail;
    let release;
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


async function atomicWriteJson(filePath, payload) {
  await fs.mkdir(path.dirname(filePath), { recursive: true, mode: 0o700 });
  const temporary = `${filePath}.${process.pid}.${crypto.randomUUID()}.tmp`;
  const handle = await fs.open(temporary, "wx", 0o600);
  try {
    await handle.writeFile(`${JSON.stringify(payload, null, 2)}\n`, "utf8");
    await handle.sync();
  } finally {
    await handle.close();
  }
  await fs.rename(temporary, filePath);
  await fs.chmod(filePath, 0o600);
}


async function parseTasks(projectRoot) {
  const sourcePath = path.join(projectRoot, "docs/CORTEX_X_V10_1500_TODO.md");
  const markdown = await fs.readFile(sourcePath, "utf8");
  const tasks = [];
  for (const raw of markdown.split(/\r?\n/)) {
    const match = TASK_PATTERN.exec(raw.trim());
    if (match) {
      tasks.push({
        todo_id: match[1],
        priority: match[2] || null,
        requirement: match[3],
      });
    }
  }
  if (tasks.length !== 1500) {
    throw new Error(`expected 1500 TODOs, observed ${tasks.length}`);
  }
  const program = JSON.parse(
    await fs.readFile(
      path.join(projectRoot, "evidence/v10/program-manifest.json"),
      "utf8",
    ),
  );
  const statusById = new Map(
    (program.todos || []).map((item) => [item.todo_id, item.status]),
  );
  tasks.sort((left, right) => {
    const leftOpen = statusById.get(left.todo_id) === "passed" ? 1 : 0;
    const rightOpen = statusById.get(right.todo_id) === "passed" ? 1 : 0;
    return leftOpen - rightOpen || left.todo_id.localeCompare(right.todo_id);
  });
  return { tasks, source_sha256: sha256(markdown) };
}


const PRODUCT_CONTEXT = [
  "Frozen current product facts as of 2026-08-01:",
  "ProofLaunch has a durable same-origin GTM Agent with Graph/Loop/Harness, content-addressed",
  "evidence, claim binding, B2B/B2C x lifecycle x budget x risk contracts, manual release,",
  "post-release aggregate outcome intake, and human-promoted cross-run learning.",
  "The selected product-critical suite passes 188 tests. Twelve open-source collection",
  "connectors are pinned; only yt-dlp has a live execution contract and no local collector",
  "binary is presently installed. Video and audio remain production briefs, not generated",
  "deliverables. Five-person blind review, real publication/business outcome, causal revenue",
  "lift, and a qualifying Radeon-local key inference remain unobserved. The launch decision",
  "is local_demo_ready_effect_unproven. External model advice cannot close any of those gates.",
].join(" ");

const REVIEW_BUNDLE_PATHS = [
  "docs/product/AUG3_DEMO_RUNBOOK.md",
  "docs/product/GTM_EFFECT_FIRST_EXECUTION_CONTRACT_V1.md",
  "evidence/v10/aug3-product-readiness.json",
];


async function loadReviewBundle(projectRoot) {
  const sections = [];
  for (const relativePath of REVIEW_BUNDLE_PATHS) {
    const body = await fs.readFile(path.join(projectRoot, relativePath), "utf8");
    sections.push(`--- ${relativePath} (sha256:${sha256(body)}) ---\n${body}`);
  }
  return sections.join("\n\n");
}


function promptFor(task, pass, reviewBundle) {
  return [
    "You are the product-closure reviewer for a next-generation 4A GTM employee.",
    "Return one strict RFC 8259 JSON object only. Do not expose hidden reasoning.",
    `TODO ${task.todo_id}: ${task.requirement}`,
    `Review pass: ${pass}.`,
    PRODUCT_CONTEXT,
    "Do not reward architecture inventory or aspiration. Identify the smallest change that",
    "materially improves user-visible strategy, creative craft, multimodal production,",
    "activation reliability, or measurable learning. Reuse mature open-source mechanisms",
    "before new code. Cover zero-budget B2B and B2C consequences. Preserve rights, claims,",
    "human approval, rollback, and competition truth boundaries.",
    "The following frozen, source-labelled project bundle is supplied so the review can",
    "name exact integration seams and avoid recommending already-built inventory:",
    reviewBundle,
    "Use exactly these root keys: todo_id, requirement, disposition, reuse_candidates,",
    "current_evidence, decisive_gap, build_patch, tests, blind_user_behavior,",
    "b2b_zero_budget_delta, b2c_zero_budget_delta, multimodal_delta,",
    "graph_loop_harness_delta, acceptance_metrics, falsifiers, stop_rule, rollback,",
    "external_blockers, current_status, truth_boundary.",
    "todo_id and requirement must exactly match. disposition must be one of",
    "implement_now, verify_now, hold_external, or reject_low_value. reuse_candidates must",
    "contain 3-5 objects with project, license_or_unknown, seam, and why_not_rewrite.",
    "build_patch and tests must each contain 6-8 concrete objects with files/interfaces,",
    "negative cases, and exact assertions. acceptance_metrics and falsifiers must each",
    "contain 6-8 measurable items. Name visible behavior that a blinded expert can compare.",
    "When a revision, license, model result, human score, business lift, or Radeon trace is",
    "not supplied, mark it unknown or externally blocked; never invent it. current_status",
    "must be not_started or in_progress. This output is evaluator-only advisory, is not",
    "training material, and cannot close the TODO by itself. Produce a detailed 900-1300",
    "token response without filler or repeated sentences.",
  ].join("\n");
}


function normalizeJson(raw) {
  const trimmed = String(raw || "").trim();
  const unfenced = trimmed
    .replace(/^```(?:json)?\s*/i, "")
    .replace(/\s*```$/, "")
    .trim();
  const value = JSON.parse(unfenced);
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("response is not one JSON object");
  }
  return value;
}


function validateOutput(value, task) {
  const failures = [];
  if (String(value.todo_id) !== task.todo_id) failures.push("todo_id_mismatch");
  if (String(value.requirement) !== task.requirement) {
    failures.push("requirement_mismatch");
  }
  if (!["implement_now", "verify_now", "hold_external", "reject_low_value"].includes(value.disposition)) {
    failures.push("invalid_disposition");
  }
  for (const field of ["reuse_candidates", "build_patch", "tests", "acceptance_metrics", "falsifiers"]) {
    if (!Array.isArray(value[field]) || value[field].length < (field === "reuse_candidates" ? 3 : 6)) {
      failures.push(`${field}_too_shallow`);
    }
  }
  if (!["not_started", "in_progress"].includes(value.current_status)) {
    failures.push("invalid_current_status");
  }
  for (const field of ["decisive_gap", "blind_user_behavior", "stop_rule", "rollback", "truth_boundary"]) {
    if (typeof value[field] !== "string" || value[field].trim().length < 20) {
      failures.push(`${field}_missing`);
    }
  }
  return failures;
}


async function existingPassed(outputPath, task, sourceSha256) {
  try {
    const row = JSON.parse(await fs.readFile(outputPath, "utf8"));
    return (
      row.status === "passed" &&
      row.todo_id === task.todo_id &&
      row.source_todo_sha256 === sourceSha256 &&
      row.requested_model === MODEL &&
      typeof row.output_sha256 === "string"
    );
  } catch {
    return false;
  }
}


async function main() {
  const projectRoot = path.resolve(process.argv[2] || process.cwd());
  const runtimeMs = Number(process.env.TOKENFACTORY_RUNTIME_MS || DEFAULT_RUNTIME_MS);
  if (!Number.isFinite(runtimeMs) || runtimeMs < 60_000 || runtimeMs > DEFAULT_RUNTIME_MS) {
    throw new Error("TOKENFACTORY_RUNTIME_MS must be between 60000 and 3480000");
  }
  const startedAt = new Date().toISOString();
  const runId = crypto.randomUUID();
  const deadline = Date.now() + runtimeMs;
  const outputRoot = path.join(
    projectRoot,
    "data/tokenfactory_teacher_v10/_product_closure_advisory/qwen3.6-35b-a3b",
  );
  await fs.mkdir(outputRoot, { recursive: true, mode: 0o700 });
  await fs.chmod(outputRoot, 0o700);
  const { tasks, source_sha256: sourceTodoSha256 } = await parseTasks(projectRoot);
  const reviewBundle = await loadReviewBundle(projectRoot);
  const browser = await chromium.connectOverCDP(CDP_URL);
  let page = await locateProfilePage(browser);
  const openingUsage = await fetchUsage(page);
  const resetAt = Date.parse(openingUsage.daily_reset_at);
  const finalDeadline = Number.isFinite(resetAt)
    ? Math.min(deadline, resetAt - RESET_GUARD_MS)
    : deadline;
  const withBudgetLock = createMutex();
  const withRateLock = createMutex();
  let activeReservationsUsd = 0;
  let nextStartAt = Date.now();
  let cursor = 0;
  let attempted = 0;
  let passed = 0;
  let blocked = 0;
  let skipped = 0;
  let stopReason = null;
  const blockedTasks = [];

  async function acquireRateSlot() {
    return withRateLock(async () => {
      const now = Date.now();
      const startAt = Math.max(now, nextStartAt);
      nextStartAt = startAt + START_INTERVAL_MS;
      if (startAt > now) {
        await new Promise((resolve) => setTimeout(resolve, startAt - now));
      }
    });
  }

  async function reserveBudget() {
    return withBudgetLock(async () => {
      if (stopReason) return false;
      if (Date.now() >= finalDeadline) {
        stopReason = "one_hour_or_reset_deadline";
        return false;
      }
      const usage = await fetchUsage(page);
      if (usage.daily_reset_at !== openingUsage.daily_reset_at) {
        stopReason = "daily_window_reset_changed";
        return false;
      }
      const available =
        usage.daily_cost_remaining_usd -
        STOP_REMAINING_USD -
        activeReservationsUsd;
      if (available < CONSERVATIVE_CALL_COST_USD) {
        stopReason = "daily_budget_guard";
        return false;
      }
      activeReservationsUsd += CONSERVATIVE_CALL_COST_USD;
      return true;
    });
  }

  async function releaseBudget() {
    await withBudgetLock(async () => {
      activeReservationsUsd = Math.max(
        0,
        activeReservationsUsd - CONSERVATIVE_CALL_COST_USD,
      );
    });
  }

  async function worker() {
    while (!stopReason) {
      const index = cursor++;
      if (index >= tasks.length) return;
      const task = tasks[index];
      const outputPath = path.join(outputRoot, `${task.todo_id}.json`);
      if (await existingPassed(outputPath, task, sourceTodoSha256)) {
        skipped += 1;
        continue;
      }
      await acquireRateSlot();
      if (!(await reserveBudget())) return;
      try {
        const prompt = promptFor(task, 1, reviewBundle);
        const result = await callOfficial(page, {
          model: MODEL,
          messages: [
            {
              role: "system",
              content:
                "Return strict source-conscious product engineering JSON. Never reveal hidden reasoning or promote unobserved claims.",
            },
            { role: "user", content: prompt },
          ],
          temperature: 0.18,
          max_tokens: MAX_TOKENS,
          chat_template_kwargs: { enable_thinking: false },
          response_format: { type: "json_object" },
        });
        let parsed = null;
        let qualityFailures = [];
        if (!result.ok || !result.content) {
          qualityFailures.push(`upstream_http_${result.http_status || 0}`);
        } else {
          try {
            parsed = normalizeJson(result.content);
            qualityFailures = validateOutput(parsed, task);
          } catch (error) {
            qualityFailures.push(`invalid_json:${String(error.message).slice(0, 160)}`);
          }
        }
        const status = qualityFailures.length ? "blocked" : "passed";
        const record = {
          schema: "ProofLaunchTokenFactoryProductClosureAdvisoryV1",
          run_id: runId,
          todo_id: task.todo_id,
          requirement: task.requirement,
          priority: task.priority,
          status,
          quality_failures: qualityFailures,
          provider: "amd_radeon_token_factory",
          official_endpoint: "https://developer.amd.com.cn/radeon/api/v1/chat/completions",
          requested_model: MODEL,
          returned_model: result.model || null,
          source_todo_sha256: sourceTodoSha256,
          prompt_sha256: sha256(prompt),
          output_sha256: result.content ? sha256(result.content) : null,
          parsed_output_sha256: parsed ? sha256(JSON.stringify(parsed)) : null,
          output: parsed,
          http_status: result.http_status,
          response_id: result.response_id,
          finish_reason: result.finish_reason,
          usage: result.usage,
          duration_ms: result.duration_ms,
          credential_persisted: false,
          hidden_reasoning_persisted: false,
          accepted_as_training_material: false,
          closes_todo: false,
          competition_core_eligible: false,
          truth_boundary:
            "Official Token Factory output is evaluator-only advisory. It is not human review, local Radeon inference, model training, business lift, or TODO closure evidence.",
          generated_at: new Date().toISOString(),
        };
        await atomicWriteJson(outputPath, record);
        attempted += 1;
        if (status === "passed") passed += 1;
        else {
          blocked += 1;
          blockedTasks.push(task.todo_id);
        }
        if (attempted % 28 === 0) {
          const usage = await fetchUsage(page);
          process.stdout.write(`${JSON.stringify({
            event: "product_closure_sprint_progress",
            run_id: runId,
            attempted,
            passed,
            blocked,
            skipped,
            used_usd: usage.daily_cost_used_usd,
            remaining_usd: usage.daily_cost_remaining_usd,
            reset_at: usage.daily_reset_at,
          })}\n`);
        }
      } finally {
        await releaseBudget();
      }
    }
  }

  await Promise.all(Array.from({ length: MAX_IN_FLIGHT }, () => worker()));
  const closingUsage = await fetchUsage(page);
  const receipt = {
    schema: "ProofLaunchTokenFactoryProductClosureSprintReceiptV1",
    run_id: runId,
    status: stopReason ? "stopped" : "completed",
    stop_reason: stopReason,
    source_todo_sha256: sourceTodoSha256,
    model: MODEL,
    safe_rpm: SAFE_RPM,
    max_in_flight: MAX_IN_FLIGHT,
    attempted_requests: attempted,
    passed_advisories: passed,
    blocked_advisories: blocked,
    blocked_todo_ids: blockedTasks,
    skipped_existing: skipped,
    opening_usage: openingUsage,
    closing_usage: closingUsage,
    spend_delta_usd:
      closingUsage.daily_cost_used_usd - openingUsage.daily_cost_used_usd,
    started_at: startedAt,
    completed_at: new Date().toISOString(),
    output_root: outputRoot,
    credential_persisted: false,
    hidden_reasoning_persisted: false,
    accepted_as_training_material: false,
    competition_core_eligible: false,
    truth_boundary:
      "This one-hour sprint creates official external advisory records only. No output closes a TODO or substitutes for human, production, training, or Radeon-local evidence.",
  };
  await atomicWriteJson(
    path.join(projectRoot, "evidence/v10/tokenfactory-product-closure-sprint.json"),
    receipt,
  );
  process.stdout.write(`${JSON.stringify({ event: "product_closure_sprint_complete", ...receipt })}\n`);
  await browser.close();
}


await main();
