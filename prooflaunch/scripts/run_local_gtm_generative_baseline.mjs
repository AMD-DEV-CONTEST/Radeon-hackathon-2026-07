#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const INPUT = path.join(ROOT, "data/v10_sft_corpus/episodes.jsonl");
const OUTPUT = path.join(ROOT, "artifacts/local-gtm-generative-baseline-v1");
const LOCAL_OLLAMA = "http://127.0.0.1:11434";

function sha256(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

export function requiredOutputKeys(userPrompt) {
  const match = String(userPrompt).match(/Return outputs:\s*([^\n.]+)/i);
  return [...new Set(match?.[1].toLowerCase().match(/[a-z][a-z0-9_]*/g) ?? [])].sort();
}

export function parseJsonObject(content) {
  const trimmed = String(content).trim();
  const unfenced = trimmed.replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/, "").trim();
  const parsed = JSON.parse(unfenced);
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error("model output is not one JSON object");
  }
  return parsed;
}

export function gradeOutput(content, requiredKeys) {
  try {
    const parsed = parseJsonObject(content);
    const present = requiredKeys.filter((key) => Object.hasOwn(parsed, key));
    return {
      valid_json_object: true,
      required_key_count: requiredKeys.length,
      present_required_key_count: present.length,
      required_key_coverage: requiredKeys.length ? present.length / requiredKeys.length : 0,
      all_required_keys_present: present.length === requiredKeys.length,
      extra_keys: Object.keys(parsed).filter((key) => !requiredKeys.includes(key)).sort(),
    };
  } catch (error) {
    return {
      valid_json_object: false,
      required_key_count: requiredKeys.length,
      present_required_key_count: 0,
      required_key_coverage: 0,
      all_required_keys_present: false,
      extra_keys: [],
      parse_error: error instanceof Error ? error.message : String(error),
    };
  }
}

export function normalizeSingleContractWrapper(content, requiredKeys) {
  const parsed = parseJsonObject(content);
  if (requiredKeys.every((key) => Object.hasOwn(parsed, key))) {
    return { content: JSON.stringify(parsed), applied: false };
  }
  const wrapper = parsed.stage_outputs;
  if (!wrapper || Array.isArray(wrapper) || typeof wrapper !== "object") {
    return { content: JSON.stringify(parsed), applied: false };
  }
  if (!requiredKeys.every((key) => Object.hasOwn(wrapper, key))) {
    return { content: JSON.stringify(parsed), applied: false };
  }
  const flattened = Object.fromEntries(requiredKeys.map((key) => [key, wrapper[key]]));
  return { content: JSON.stringify(flattened), applied: true };
}

async function requestJson(route, options = {}) {
  const response = await fetch(`${LOCAL_OLLAMA}${route}`, {
    ...options,
    signal: AbortSignal.timeout(180_000),
  });
  const body = await response.text();
  if (!response.ok) throw new Error(`local Ollama ${route} returned ${response.status}: ${body.slice(0, 400)}`);
  return JSON.parse(body);
}

function selectCases(rows) {
  const selected = new Map();
  for (const row of rows) {
    const current = selected.get(row.stage);
    const rank = sha256(`local-generative-baseline-v1:${row.content_sha256}`);
    if (!current || rank < current.rank) selected.set(row.stage, { rank, row });
  }
  return [...selected.values()].map((item) => item.row).sort((left, right) => left.stage.localeCompare(right.stage));
}

async function main() {
  const modelName = process.argv[2] ?? "qwen2.5-coder:1.5b";
  const tags = await requestJson("/api/tags");
  const localModel = tags.models?.find((item) => item.name === modelName || item.model === modelName);
  if (!localModel) throw new Error(`local model ${modelName} is absent; automatic pull is disabled`);
  const rows = fs.readFileSync(INPUT, "utf8").trim().split("\n").map(JSON.parse);
  const cases = selectCases(rows);
  if (cases.length !== 14) throw new Error(`expected 14 GTM stages, observed ${cases.length}`);
  fs.mkdirSync(OUTPUT, { recursive: true });
  const outputs = [];
  let modelCalls = 0;
  for (const [index, row] of cases.entries()) {
    const requiredKeys = requiredOutputKeys(row.user_prompt);
    const request = {
      model: localModel.name,
      messages: [
        { role: "system", content: row.system_prompt },
        { role: "user", content: row.user_prompt },
      ],
      format: "json",
      stream: false,
      options: { temperature: 0, num_predict: 512, seed: 42 },
    };
    const started = performance.now();
    const response = await requestJson("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
    modelCalls += 1;
    const content = response.message?.content;
    if (typeof content !== "string") throw new Error(`case ${row.stage} returned no text content`);
    const firstGrade = gradeOutput(content, requiredKeys);
    const attempts = [{
      round: 0,
      response_sha256: sha256(Buffer.from(content)),
      grade: firstGrade,
      latency_ms: Number((performance.now() - started).toFixed(3)),
    }];
    let finalContent = content;
    let finalResponse = response;
    let finalGrade = firstGrade;
    if (!firstGrade.all_required_keys_present) {
      const repairRequest = {
        ...request,
        messages: [
          ...request.messages,
          { role: "assistant", content },
          {
            role: "user",
            content: `Repair the JSON contract. Return exactly one JSON object with these required top-level keys: ${requiredKeys.join(", ")}. Do not nest or rename them. Preserve source bounds and do not add prose.`,
          },
        ],
      };
      const repairStarted = performance.now();
      finalResponse = await requestJson("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(repairRequest),
      });
      modelCalls += 1;
      finalContent = finalResponse.message?.content;
      if (typeof finalContent !== "string") throw new Error(`repair case ${row.stage} returned no text content`);
      finalGrade = gradeOutput(finalContent, requiredKeys);
      attempts.push({
        round: 1,
        response_sha256: sha256(Buffer.from(finalContent)),
        grade: finalGrade,
        latency_ms: Number((performance.now() - repairStarted).toFixed(3)),
      });
    }
    const rawFinalResponseSha256 = sha256(Buffer.from(finalContent));
    let normalizationApplied = false;
    if (!finalGrade.all_required_keys_present && finalGrade.valid_json_object) {
      const normalized = normalizeSingleContractWrapper(finalContent, requiredKeys);
      finalContent = normalized.content;
      normalizationApplied = normalized.applied;
      finalGrade = gradeOutput(finalContent, requiredKeys);
    }
    outputs.push({
      episode_id: row.episode_id,
      stage: row.stage,
      required_keys: requiredKeys,
      request_sha256: sha256(Buffer.from(JSON.stringify(request))),
      response_sha256: sha256(Buffer.from(finalContent)),
      raw_final_response_sha256: rawFinalResponseSha256,
      content: finalContent,
      first_pass_grade: firstGrade,
      grade: finalGrade,
      harness_normalization_applied: normalizationApplied,
      attempts,
      prompt_eval_count: finalResponse.prompt_eval_count ?? null,
      eval_count: finalResponse.eval_count ?? null,
    });
    process.stdout.write(`Evaluated ${index + 1}/${cases.length}: ${row.stage}\n`);
  }
  const firstPassed = outputs.filter((item) => item.first_pass_grade.valid_json_object && item.first_pass_grade.all_required_keys_present).length;
  const passed = outputs.filter((item) => item.grade.valid_json_object && item.grade.all_required_keys_present).length;
  const receipt = {
    schema: "ProofLaunchLocalGTMGenerativeBaselineReceiptV1",
    observed_at: new Date().toISOString(),
    model: {
      name: localModel.name,
      digest: localModel.digest,
      size_bytes: localModel.size,
      details: localModel.details,
    },
    case_count: outputs.length,
    model_call_count: modelCalls,
    repair_call_count: modelCalls - outputs.length,
    deterministic_wrapper_normalization_count: outputs.filter((item) => item.harness_normalization_applied).length,
    first_pass_valid_json_count: outputs.filter((item) => item.first_pass_grade.valid_json_object).length,
    first_pass_all_required_keys_count: firstPassed,
    first_pass_hard_contract_pass_rate: firstPassed / outputs.length,
    valid_json_count: outputs.filter((item) => item.grade.valid_json_object).length,
    all_required_keys_count: outputs.filter((item) => item.grade.all_required_keys_present).length,
    final_hard_contract_pass_rate: passed / outputs.length,
    mean_required_key_coverage: outputs.reduce((sum, item) => sum + item.grade.required_key_coverage, 0) / outputs.length,
    localhost_only: true,
    cloud_api_calls: 0,
    network_download_performed: false,
    training_observed: false,
    execution_pattern: "Graph node plus one bounded repair Loop under a fail-closed Harness",
    automatic_external_action_enabled: false,
    training_admission: "blocked_pending_base_model_license_and_generated-output-rights_review",
    truth_boundary: "This is a frozen local generative contract baseline, not fine-tuning, 4A quality proof, multimodal generation proof, Radeon execution or business lift.",
  };
  const outputText = outputs.map((item) => JSON.stringify(item)).join("\n") + "\n";
  fs.writeFileSync(path.join(OUTPUT, "outputs.jsonl"), outputText);
  receipt.outputs_sha256 = sha256(Buffer.from(outputText));
  receipt.receipt_sha256 = sha256(Buffer.from(canonical(receipt)));
  fs.writeFileSync(path.join(OUTPUT, "receipt.json"), `${JSON.stringify(receipt, null, 2)}\n`);
  process.stdout.write(`${JSON.stringify(receipt, null, 2)}\n`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    process.stderr.write(`${error.stack ?? error.message ?? error}\n`);
    process.exitCode = 1;
  });
}
