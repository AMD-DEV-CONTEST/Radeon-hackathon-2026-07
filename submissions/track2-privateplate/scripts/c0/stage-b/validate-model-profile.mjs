#!/usr/bin/env node
/**
 * Local, offline integrity check for model profiles and vendored artifacts.
 * Does NOT claim model inference success. Does NOT contact Radeon.
 */
import { createHash } from "node:crypto";
import { readFile, access } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = fileURLToPath(new URL("../../../", import.meta.url));
const profilesPath = path.join(root, "scripts/c0/stage-b/model-profiles.json");
const profiles = JSON.parse(await readFile(profilesPath, "utf8"));
const runtimePin = JSON.parse(
  await readFile(path.join(root, "scripts/c0/stage-b/runtime-pin.json"), "utf8")
);

const errors = [];
const notes = [];

function sha256(buf) {
  return createHash("sha256").update(buf).digest("hex");
}

async function mustExist(rel) {
  const abs = path.join(root, rel);
  try {
    await access(abs);
    return abs;
  } catch {
    errors.push(`missing file: ${rel}`);
    return null;
  }
}

async function checkSha(rel, expected) {
  const abs = await mustExist(rel);
  if (!abs || !expected) return;
  const dig = sha256(await readFile(abs));
  if (dig !== expected) {
    errors.push(`sha mismatch ${rel}: expected ${expected}, got ${dig}`);
  }
}

const primaryId = profiles.primary_profile;
const primary = profiles.profiles?.[primaryId];
if (!primary) {
  errors.push(`primary_profile missing: ${primaryId}`);
} else {
  if (primary.model_id !== "google/gemma-4-12B-it-qat-w4a16-ct") {
    errors.push(
      `primary model_id must be google/gemma-4-12B-it-qat-w4a16-ct, got ${primary.model_id}`
    );
  }
  if (primary.revision !== "1d2c2d7f2466070e69d6fb3fd5ce9a7d75f2f6ee") {
    errors.push(`primary revision pin mismatch: ${primary.revision}`);
  }
  if (primary.tool_call_parser !== "gemma4") {
    errors.push(`primary tool_call_parser must be gemma4`);
  }
  if (primary.reasoning_parser !== "gemma4") {
    errors.push(`primary reasoning_parser must be gemma4`);
  }
  if (primary.quantization?.vllm_quantization_arg !== "compressed-tensors") {
    errors.push(`primary quantization flag must be compressed-tensors`);
  }
  if (primary.judgment?.model_capability === "PASS") {
    errors.push(
      "primary judgment.model_capability must not be PASS without live evidence"
    );
  }
  await checkSha(
    primary.chat_template.path,
    primary.chat_template.sha256
  );
  await checkSha(
    primary.chat_template_model_repo_reference.path,
    primary.chat_template_model_repo_reference.sha256
  );
  await checkSha(
    primary.quantization.config_snapshot_path,
    primary.quantization.config_snapshot_sha256
  );
  await checkSha(
    primary.quantization.recipe_snapshot_path,
    primary.quantization.recipe_snapshot_sha256
  );
  notes.push(
    "Declared model bytes are verified only by the formal post-start verifier."
  );
}

// Alias resolution
if (profiles.aliases?.gemma4 !== "gemma4-12b-qat-w4a16-ct") {
  errors.push("alias gemma4 must resolve to gemma4-12b-qat-w4a16-ct");
}

// No silent 7B default model_id assignment in any profile.
for (const [id, profile] of Object.entries(profiles.profiles ?? {})) {
  if (
    profile.model_id === "Qwen/Qwen2.5-7B-Instruct" ||
    String(profile.model_id ?? "").includes("Qwen2.5-7B")
  ) {
    errors.push(`profile ${id} must not use Qwen2.5-7B as model_id`);
  }
  const candidatePin = runtimePin.candidates?.[id];
  if (!candidatePin) {
    errors.push(`runtime pin missing candidate ${id}`);
    continue;
  }
  if (!profile.revision_pinned || !/^[0-9a-f]{40}$/.test(profile.revision ?? "")) {
    errors.push(`profile ${id} requires an exact 40-character revision`);
  }
  if (profile.model_id !== candidatePin.model_id) {
    errors.push(`profile ${id} model_id differs from runtime pin`);
  }
  if (profile.revision !== candidatePin.revision) {
    errors.push(`profile ${id} revision differs from runtime pin`);
  }
  if (profile.tool_call_parser !== candidatePin.tool_call_parser) {
    errors.push(`profile ${id} tool parser differs from runtime pin`);
  }
  if (
    (profile.reasoning_parser ?? null) !==
    (candidatePin.reasoning_parser ?? null)
  ) {
    errors.push(`profile ${id} reasoning parser differs from runtime pin`);
  }
  if (
    (profile.quantization?.vllm_quantization_arg ?? null) !==
    (candidatePin.quantization ?? null)
  ) {
    errors.push(`profile ${id} quantization differs from runtime pin`);
  }
  if (profile.kv_cache_memory_bytes !== candidatePin.kv_cache_memory_bytes) {
    errors.push(`profile ${id} KV cache bytes differ from runtime pin`);
  }
  if (!Number.isSafeInteger(profile.kv_cache_memory_bytes)) {
    errors.push(`profile ${id} requires integer kv_cache_memory_bytes`);
  }
  if (!profile.license || !/^https:\/\//.test(profile.license_link ?? "")) {
    errors.push(`profile ${id} requires license and license_link`);
  }
  const weights = profile.weights?.files;
  if (!Array.isArray(weights) || weights.length === 0) {
    errors.push(`profile ${id} requires declared weight files`);
  }
  for (const weight of weights ?? []) {
    if (
      !weight.path ||
      !Number.isSafeInteger(weight.size_bytes) ||
      !/^[0-9a-f]{64}$/.test(weight.lfs_sha256 ?? "")
    ) {
      errors.push(`profile ${id} has incomplete weight declaration`);
    }
  }
  if (profile.chat_template?.path) {
    await checkSha(profile.chat_template.path, profile.chat_template.sha256);
  } else if (profile.chat_template?.sha256 != null) {
    errors.push(`profile ${id} chat template path/hash must both be null`);
  }
}
if (profiles.forbidden_defaults?.default_model) {
  errors.push("forbidden_defaults.default_model must be null");
}
if (profiles.forbidden_defaults?.auto_fallback_model) {
  errors.push("forbidden_defaults.auto_fallback_model must be null");
}

const report = {
  status: errors.length === 0 ? "PASS" : "FAIL",
  scope: "local_profile_artifact_integrity_only",
  primary_profile: primaryId,
  primary_model_id: primary?.model_id ?? null,
  primary_revision: primary?.revision ?? null,
  model_inference: "NOT_RUN",
  holdout_live: "NOT_RUN",
  errors,
  notes
};

console.log(JSON.stringify(report, null, 2));
if (errors.length > 0) process.exitCode = 1;
