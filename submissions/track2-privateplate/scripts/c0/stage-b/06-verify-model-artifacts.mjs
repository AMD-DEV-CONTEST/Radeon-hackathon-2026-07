#!/usr/bin/env node
/**
 * Formal post-start verification.
 * It binds the running process and API model to the pinned profile, then hashes
 * every declared model file. Runtime compatibility must already have passed.
 */
import { createHash } from "node:crypto";
import {
  access,
  readFile,
  rename,
  stat,
  writeFile
} from "node:fs/promises";
import { createReadStream } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { resolveC0bOutDir } from "./resolve-out-dir.mjs";
import { resolveModelSnapshotDir } from "./runtime-checks.mjs";

const root = fileURLToPath(new URL("../../../", import.meta.url));
const outDir = resolveC0bOutDir(root);
const rawDir = path.join(outDir, "raw");
const outPath = path.join(rawDir, "model-artifact-verification.json");
const runtimePath = path.join(rawDir, "runtime-pin-verification.json");

if (process.env.PRIVATEPLATE_I_CONFIRM_RADEON_RUN !== "yes") {
  throw new Error(
    "Post-start model verification is only valid inside an owner-approved formal Radeon run."
  );
}
await assertDoesNotExist(outPath);

const profiles = await readJson(
  path.join(root, "scripts/c0/stage-b/model-profiles.json")
);
const runtimePin = await readJson(
  path.join(root, "scripts/c0/stage-b/runtime-pin.json")
);
let profileId = process.env.PRIVATEPLATE_MODEL_PROFILE;
if (profiles.aliases?.[profileId]) profileId = profiles.aliases[profileId];
const profile = profiles.profiles?.[profileId];
const candidatePin = runtimePin.candidates?.[profileId];
if (!profile || !candidatePin) {
  throw new Error(`Unknown or unpinned model profile: ${profileId ?? "missing"}`);
}

const errors = [];
const localArtifactChecks = [];
const runtimeEvidence = await readRequiredJson(runtimePath, errors);
if (
  runtimeEvidence?.status !== "PASS" ||
  runtimeEvidence?.phase !== "PRESTART" ||
  runtimeEvidence?.profile_id !== profileId
) {
  errors.push("Pinned PRESTART runtime verification is missing or does not match.");
}

await verifyVendoredArtifact(
  profile.chat_template?.path,
  profile.chat_template?.sha256,
  "chat_template"
);
await verifyVendoredArtifact(
  profile.quantization?.config_snapshot_path,
  profile.quantization?.config_snapshot_sha256,
  "quantization_config"
);
await verifyVendoredArtifact(
  profile.quantization?.recipe_snapshot_path,
  profile.quantization?.recipe_snapshot_sha256,
  "quantization_recipe"
);

const revision = profile.revision;
const declaredWeights = (profile.weights?.files ?? []).map(
  (item) => item.path
);
const snapshotDir = resolveModelSnapshotDir({
  env: process.env,
  modelId: profile.model_id,
  revision,
  weightFiles: declaredWeights
});
const weightChecks = [];
for (const declaration of profile.weights?.files ?? []) {
  const result = {
    path: declaration.path,
    expected_size_bytes: declaration.size_bytes ?? null,
    actual_size_bytes: null,
    expected_sha256: declaration.lfs_sha256 ?? null,
    actual_sha256: null,
    status: "FAIL"
  };
  if (
    !Number.isSafeInteger(declaration.size_bytes) ||
    !/^[0-9a-f]{64}$/.test(declaration.lfs_sha256 ?? "")
  ) {
    errors.push(`Incomplete byte declaration for ${declaration.path}.`);
    weightChecks.push(result);
    continue;
  }
  const localPath = path.join(snapshotDir, declaration.path);
  try {
    const fileStat = await stat(localPath);
    result.actual_size_bytes = fileStat.size;
    if (fileStat.size !== declaration.size_bytes) {
      errors.push(`Size mismatch for ${declaration.path}.`);
      result.status = "SIZE_MISMATCH";
    } else {
      result.actual_sha256 = await sha256File(localPath);
      if (result.actual_sha256 !== declaration.lfs_sha256) {
        errors.push(`SHA-256 mismatch for ${declaration.path}.`);
        result.status = "SHA_MISMATCH";
      } else {
        result.status = "SHA_VERIFIED";
      }
    }
  } catch (error) {
    errors.push(
      `Missing declared model file ${declaration.path}: ${String(error?.message ?? error)}`
    );
    result.status = "NOT_PRESENT";
  }
  weightChecks.push(result);
}
if (weightChecks.length === 0) {
  errors.push("The selected profile declares no model files.");
}

const launchPath = path.join(rawDir, "vllm-launch.json");
const processPath = path.join(rawDir, "vllm-process-cmdline.json");
const modelsPath = path.join(rawDir, "vllm-models.json");
const activeModelPath = path.join(rawDir, "active-model.txt");
const launch = await readRequiredJson(launchPath, errors);
const processCommand = await readRequiredJson(processPath, errors);
const modelsResponse = await readRequiredJson(modelsPath, errors);
const activeModel = await readRequiredText(activeModelPath, errors);

const launchChecks = [];
const checkLaunch = (name, actual, expected) => {
  const ok = actual === expected;
  launchChecks.push({
    name,
    status: ok ? "PASS" : "FAIL",
    actual: actual ?? null,
    expected: expected ?? null
  });
  if (!ok) errors.push(`Launch mismatch: ${name}.`);
};

if (launch) {
  checkLaunch("profile_id", launch.profile_id, profileId);
  checkLaunch("model_id", launch.model_id, profile.model_id);
  checkLaunch("revision", launch.revision, profile.revision);
  checkLaunch("revision_pinned", launch.revision_pinned, true);
  checkLaunch(
    "tool_call_parser",
    launch.tool_call_parser,
    profile.tool_call_parser
  );
  checkLaunch(
    "reasoning_parser",
    launch.reasoning_parser ?? null,
    profile.reasoning_parser ?? null
  );
  checkLaunch(
    "quantization",
    launch.quantization ?? null,
    profile.quantization?.vllm_quantization_arg ?? null
  );
  checkLaunch(
    "attention_backend",
    launch.attention_backend,
    profile.attention_backend
  );
  checkLaunch("max_model_len", launch.max_model_len, profile.max_model_len);
  checkLaunch(
    "kv_cache_memory_bytes",
    launch.kv_cache_memory_bytes,
    profile.kv_cache_memory_bytes
  );
  checkLaunch(
    "chat_template_path",
    launch.chat_template_path ?? null,
    profile.chat_template?.path ?? null
  );
  checkLaunch(
    "chat_template_sha256",
    launch.chat_template_sha256 ?? null,
    profile.chat_template?.sha256 ?? null
  );
  checkLaunch(
    "image_digest",
    launch.image_digest,
    runtimeEvidence?.image?.digest ?? null
  );
  checkLaunch("license", launch.license, profile.license);
  checkLaunch("license_link", launch.license_link, profile.license_link);

  if (!Array.isArray(launch.cmdline) || launch.cmdline.length === 0) {
    errors.push("Launch command line is missing.");
  } else {
    const launchFingerprint = fingerprintArgs(launch.cmdline);
    checkLaunch(
      "launch_fingerprint",
      launch.launch_fingerprint,
      launchFingerprint
    );
    checkRequiredFlag(launch.cmdline, "--model", profile.model_id);
    checkRequiredFlag(launch.cmdline, "--revision", profile.revision);
    checkRequiredFlag(
      launch.cmdline,
      "--tool-call-parser",
      profile.tool_call_parser
    );
    checkRequiredFlag(
      launch.cmdline,
      "--kv-cache-memory-bytes",
      String(profile.kv_cache_memory_bytes)
    );
    checkRequiredFlag(
      launch.cmdline,
      "--attention-backend",
      profile.attention_backend
    );
    checkRequiredFlag(
      launch.cmdline,
      "--chat-template",
      profile.chat_template?.path
        ? path.join(root, profile.chat_template.path)
        : null
    );
    checkRequiredFlag(
      launch.cmdline,
      "--reasoning-parser",
      profile.reasoning_parser ?? null
    );
    checkRequiredFlag(
      launch.cmdline,
      "--quantization",
      profile.quantization?.vllm_quantization_arg ?? null
    );
    if (launch.cmdline.includes("--gpu-memory-utilization")) {
      errors.push(
        "Formal launch must use fixed KV cache bytes, not gpu-memory-utilization."
      );
    }
  }
}

if (processCommand && launch?.cmdline) {
  const actualFingerprint = fingerprintArgs(processCommand.args ?? []);
  if (actualFingerprint !== processCommand.sha256) {
    errors.push("Recorded process command-line SHA-256 is invalid.");
  }
  if (actualFingerprint !== launch.launch_fingerprint) {
    errors.push("Live vLLM process command line differs from the launch record.");
  }
  if (JSON.stringify(processCommand.args) !== JSON.stringify(launch.cmdline)) {
    errors.push("Live vLLM process arguments differ from the launch arguments.");
  }
}

const modelIds = Array.isArray(modelsResponse?.data)
  ? modelsResponse.data
      .map((item) => item?.id)
      .filter((value) => typeof value === "string")
  : [];
if (modelIds.length !== 1 || modelIds[0] !== profile.model_id) {
  errors.push(
    `/v1/models must report only ${profile.model_id}; got ${JSON.stringify(modelIds)}.`
  );
}
if (activeModel !== profile.model_id) {
  errors.push(
    `active-model.txt must equal ${profile.model_id}; got ${activeModel ?? "missing"}.`
  );
}

const status =
  errors.length === 0 &&
  weightChecks.every((item) => item.status === "SHA_VERIFIED")
    ? "PASS"
    : "FAIL";
const payload = {
  schema_version: "2.0",
  stage: "C0-B",
  phase: "POSTSTART",
  collected_at_utc: new Date().toISOString(),
  profile_id: profileId,
  model_id: profile.model_id,
  revision: profile.revision,
  license: {
    spdx: profile.license,
    url: profile.license_link
  },
  quantization: profile.quantization,
  chat_template: profile.chat_template,
  runtime_verification: {
    path: "raw/runtime-pin-verification.json",
    status: runtimeEvidence?.status ?? "MISSING"
  },
  local_artifact_checks: localArtifactChecks,
  snapshot_directory: snapshotDir,
  weight_checks: weightChecks,
  launch_checks: launchChecks,
  process_command_line: processCommand
    ? {
        path: "raw/vllm-process-cmdline.json",
        sha256: processCommand.sha256
      }
    : null,
  models_api: {
    path: "raw/vllm-models.json",
    model_ids: modelIds
  },
  active_model: activeModel,
  status,
  errors,
  claim_boundary:
    "PASS binds the selected revision, declared model bytes, launch arguments, running process, template, parser, quantization, license metadata, and /v1/models response. It does not itself prove model quality."
};

await writeFile(outPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
await updateEnvironment(payload, runtimeEvidence);
console.log(
  JSON.stringify(
    {
      status,
      profile_id: profileId,
      verified_files: weightChecks.filter(
        (item) => item.status === "SHA_VERIFIED"
      ).length,
      wrote: outPath,
      errors
    },
    null,
    2
  )
);
if (status !== "PASS") process.exitCode = 2;

function checkRequiredFlag(args, flag, expected) {
  const indexes = args
    .map((value, index) => (value === flag ? index : -1))
    .filter((index) => index >= 0);
  if (expected == null) {
    if (indexes.length > 0) {
      errors.push(`Launch must omit ${flag} for profile ${profileId}.`);
    }
    return;
  }
  if (indexes.length !== 1 || args[indexes[0] + 1] !== expected) {
    errors.push(`Launch requires exactly ${flag} ${expected}.`);
  }
}

async function verifyVendoredArtifact(relativePath, expectedSha, label) {
  if (!relativePath && !expectedSha) return;
  const result = {
    label,
    path: relativePath ?? null,
    expected_sha256: expectedSha ?? null,
    actual_sha256: null,
    status: "FAIL"
  };
  if (!relativePath || !/^[0-9a-f]{64}$/.test(expectedSha ?? "")) {
    errors.push(`Incomplete ${label} declaration.`);
  } else {
    try {
      const bytes = await readFile(path.join(root, relativePath));
      result.actual_sha256 = createHash("sha256").update(bytes).digest("hex");
      result.status =
        result.actual_sha256 === expectedSha ? "PASS" : "SHA_MISMATCH";
      if (result.status !== "PASS") {
        errors.push(`${label} SHA-256 mismatch.`);
      }
    } catch (error) {
      errors.push(`Cannot read ${label}: ${String(error?.message ?? error)}`);
    }
  }
  localArtifactChecks.push(result);
}

async function sha256File(filePath) {
  const hash = createHash("sha256");
  await new Promise((resolve, reject) => {
    const stream = createReadStream(filePath);
    stream.on("data", (chunk) => hash.update(chunk));
    stream.on("error", reject);
    stream.on("end", resolve);
  });
  return hash.digest("hex");
}

function fingerprintArgs(args) {
  const hash = createHash("sha256");
  for (const value of args) {
    hash.update(String(value));
    hash.update("\0");
  }
  return hash.digest("hex");
}

async function readJson(filePath) {
  return JSON.parse(await readFile(filePath, "utf8"));
}

async function readRequiredJson(filePath, errorList) {
  try {
    return await readJson(filePath);
  } catch (error) {
    errorList.push(
      `Required evidence missing or invalid: ${path.relative(outDir, filePath)} (${String(error?.message ?? error)})`
    );
    return null;
  }
}

async function readRequiredText(filePath, errorList) {
  try {
    const value = (await readFile(filePath, "utf8")).trim();
    if (!value) throw new Error("empty file");
    return value;
  } catch (error) {
    errorList.push(
      `Required evidence missing or invalid: ${path.relative(outDir, filePath)} (${String(error?.message ?? error)})`
    );
    return null;
  }
}

async function assertDoesNotExist(filePath) {
  try {
    await access(filePath);
  } catch {
    return;
  }
  throw new Error(
    `Refusing to overwrite existing evidence: ${path.relative(root, filePath)}`
  );
}

async function updateEnvironment(artifactPayload, runtimePayload) {
  const environmentPath = path.join(outDir, "environment.json");
  const environment = await readJson(environmentPath);
  const updated = {
    ...environment,
    software_versions: {
      ...environment.software_versions,
      status: runtimePayload?.status === "PASS" ? "PIN_VERIFIED" : "FAIL",
      python: runtimePayload?.runtime?.python?.full ?? null,
      torch: runtimePayload?.runtime?.torch ?? null,
      hip: runtimePayload?.runtime?.hip ?? null,
      vllm: runtimePayload?.runtime?.vllm ?? null,
      transformers: runtimePayload?.runtime?.transformers ?? null,
      compressed_tensors:
        runtimePayload?.runtime?.compressed_tensors ?? null,
      attention_backend: profile.attention_backend,
      tool_call_parser: profile.tool_call_parser,
      reasoning_parser: profile.reasoning_parser ?? null,
      image_digest: runtimePayload?.image?.digest ?? null
    },
    model_artifact: {
      status: artifactPayload.status,
      model_id: profile.model_id,
      revision: profile.revision,
      weight_checksums: artifactPayload.weight_checks.map((item) => ({
        path: item.path,
        sha256: item.actual_sha256,
        status: item.status
      })),
      quantization: profile.quantization?.label ?? null,
      license: profile.license,
      license_link: profile.license_link,
      chat_template_sha256: profile.chat_template?.sha256 ?? null
    }
  };
  const tempPath = `${environmentPath}.${process.pid}.tmp`;
  await writeFile(tempPath, `${JSON.stringify(updated, null, 2)}\n`, "utf8");
  await rename(tempPath, environmentPath);
}
