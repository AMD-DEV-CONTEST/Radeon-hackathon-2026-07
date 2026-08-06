#!/usr/bin/env node
/**
 * Offline static check for R0-5 install plan + runtime pins + scripts.
 * Does not start Radeon, download models, or claim live install success.
 */
import { access, readFile, stat } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { createHash } from "node:crypto";

const root = fileURLToPath(new URL("../../../", import.meta.url));
const errors = [];
const checks = [];

function check(name, ok, detail) {
  checks.push({ name, status: ok ? "PASS" : "FAIL", detail: detail ?? null });
  if (!ok) errors.push(`${name}: ${detail ?? "failed"}`);
}

async function exists(rel) {
  try {
    await access(path.join(root, rel));
    return true;
  } catch {
    return false;
  }
}

const pin = JSON.parse(
  await readFile(path.join(root, "scripts/c0/stage-b/runtime-pin.json"), "utf8")
);
const plan = JSON.parse(
  await readFile(path.join(root, "scripts/c0/stage-b/install-plan.json"), "utf8")
);
const profiles = JSON.parse(
  await readFile(path.join(root, "scripts/c0/stage-b/model-profiles.json"), "utf8")
);

check("plan_schema", plan.schema_version === "1.0", plan.schema_version);
check(
  "plan_status_not_claiming_live",
  plan.status === "PREPARED_NOT_RUN_ON_RADEON",
  plan.status
);

const requiredScripts = [
  "scripts/c0/stage-b/00-install-node22.sh",
  "scripts/c0/stage-b/00-install-runtime.sh",
  "scripts/c0/stage-b/00-stop-vllm.sh",
  "scripts/c0/stage-b/00-verify-runtime.mjs",
  "scripts/c0/stage-b/01-start-vllm.sh",
  "scripts/c0/stage-b/run-all.sh",
  "scripts/c0/stage-b/write-failure-summary.mjs",
  "scripts/c0/stage-b/write-evidence-inventory.mjs"
];
for (const rel of requiredScripts) {
  check(`script_exists:${path.basename(rel)}`, await exists(rel), rel);
}

const sources = Object.fromEntries(
  (plan.official_sources ?? []).map((item) => [item.id, item])
);
check("source_vllm", Boolean(sources.vllm_rocm_wheel), "missing vllm_rocm_wheel");
check(
  "source_vllm_version",
  sources.vllm_rocm_wheel?.exact_version === pin.vllm.exact_version,
  `${sources.vllm_rocm_wheel?.exact_version} vs ${pin.vllm.exact_version}`
);
check(
  "source_vllm_url",
  sources.vllm_rocm_wheel?.url === pin.vllm.wheel_url,
  "wheel url mismatch between plan and pin"
);
check(
  "source_vllm_size",
  sources.vllm_rocm_wheel?.size_bytes === pin.vllm.wheel_size_bytes,
  "wheel size mismatch"
);
check(
  "source_torch",
  sources.torch_base?.exact_base_version === pin.torch.exact_base_version,
  sources.torch_base?.exact_base_version
);
check(
  "source_torch_install",
  sources.torch_base?.url === pin.torch.wheel_url &&
    sources.torch_base?.exact_local_version === pin.torch.exact_local_version &&
    typeof pin.torch.wheel_url === "string" &&
    pin.torch.wheel_url.includes("gitd0c8b1f") &&
    Array.isArray(pin.torch.companion_wheel_urls) &&
    pin.torch.companion_wheel_urls.length >= 1,
  `${pin.torch.exact_local_version} ${pin.torch.wheel_url}`
);
check(
  "source_transformers",
  sources.transformers?.exact_version === pin.transformers.exact_version,
  sources.transformers?.exact_version
);
check(
  "source_compressed_tensors",
  sources.compressed_tensors?.exact_version ===
    pin.compressed_tensors.exact_version,
  sources.compressed_tensors?.exact_version
);
check(
  "source_rocm",
  sources.rocm_image?.exact_version === pin.rocm.exact_version,
  sources.rocm_image?.exact_version
);

const gemma = profiles.profiles?.[profiles.primary_profile];
const gemmaSource = sources.gemma4_primary;
check(
  "gemma_model_id",
  gemma?.model_id === gemmaSource?.model_id &&
    gemma?.model_id === "google/gemma-4-12B-it-qat-w4a16-ct",
  gemma?.model_id
);
check(
  "gemma_revision",
  gemma?.revision === gemmaSource?.revision &&
    gemma?.revision === pin.candidates["gemma4-12b-qat-w4a16-ct"]?.revision,
  gemma?.revision
);
check(
  "gemma_parser",
  gemma?.tool_call_parser === "gemma4" &&
    gemma?.reasoning_parser === "gemma4" &&
    gemmaSource?.tool_call_parser === "gemma4",
  `${gemma?.tool_call_parser}/${gemma?.reasoning_parser}`
);
check(
  "gemma_no_hermes",
  plan.parser_policy?.gemma4_profiles_must_use?.forbid_hermes === true,
  "forbid_hermes"
);
check(
  "gemma_license",
  Boolean(gemma?.license) && Boolean(gemma?.license_link),
  `${gemma?.license} ${gemma?.license_link}`
);

const qwen = profiles.profiles?.qwen14;
const qwenSource = sources.qwen14_comparator;
check(
  "qwen_parser_hermes",
  qwen?.tool_call_parser === "hermes" &&
    qwenSource?.tool_call_parser === "hermes",
  qwen?.tool_call_parser
);
check(
  "qwen_revision",
  qwen?.revision === qwenSource?.revision &&
    qwen?.revision === pin.candidates.qwen14?.revision,
  qwen?.revision
);

const installScript = await readFile(
  path.join(root, "scripts/c0/stage-b/00-install-runtime.sh"),
  "utf8"
);
check(
  "install_script_uses_wheel_url",
  installScript.includes("wheel_url") || installScript.includes("VLLM_WHEEL_URL"),
  "must reference pinned wheel"
);
check(
  "install_script_uninstalls_flash_attn",
  /flash-attn|flash_attn/.test(installScript),
  "must uninstall CUDA flash_attn"
);
check(
  "install_script_has_dry_run",
  installScript.includes("--dry-run") &&
    installScript.includes("PRIVATEPLATE_INSTALL_DRY_RUN"),
  "dry-run mode required for local static use"
);
check(
  "install_before_model_gate",
  installScript.includes("torch must already match") ||
    installScript.includes("torch_or_hip_mismatch"),
  "torch mismatch must fail closed before model"
);

const runAll = await readFile(
  path.join(root, "scripts/c0/stage-b/run-all.sh"),
  "utf8"
);
check(
  "run_all_has_teardown_trap",
  /trap\s+.*EXIT/.test(runAll) && runAll.includes("00-stop-vllm.sh"),
  "run-all must always stop vLLM"
);
check(
  "run_all_has_failure_summary",
  runAll.includes("write-failure-summary.mjs"),
  "unified failure summary required"
);
check(
  "run_all_has_evidence_inventory",
  runAll.includes("write-evidence-inventory.mjs"),
  "evidence inventory required"
);
check(
  "run_all_calls_install_runtime",
  runAll.includes("00-install-runtime.sh"),
  "formal path must include executable install"
);
check(
  "run_all_verifies_global_account",
  runAll.includes("00-verify-account.mjs") &&
    runAll.includes("PRIVATEPLATE_ACCOUNT_CHANNEL") &&
    runAll.includes("PRIVATEPLATE_STORAGE_MODE") &&
    runAll.includes("PRIVATEPLATE_MODEL_DIRECTORY"),
  "formal path must verify the Global account and template before collection"
);

const stopScript = await readFile(
  path.join(root, "scripts/c0/stage-b/00-stop-vllm.sh"),
  "utf8"
);
check(
  "stop_script_writes_receipt",
  stopScript.includes("vllm-stop.json"),
  "stop receipt required"
);
check(
  "stop_script_lifecycle_receipt",
  stopScript.includes("lifecycle_note"),
  "stop receipt must describe its service-lifecycle scope"
);

// Chat template still present and hashed for Gemma tool path.
const templateRel = gemma?.chat_template?.path;
if (templateRel) {
  const abs = path.join(root, templateRel);
  const buf = await readFile(abs);
  const dig = createHash("sha256").update(buf).digest("hex");
  check(
    "gemma_template_sha",
    dig === gemma.chat_template.sha256,
    dig
  );
  const st = await stat(abs);
  check("gemma_template_nonempty", st.size > 0, String(st.size));
}

const payload = {
  schema_version: "1.0",
  stage: "R0-5",
  phase: "STATIC_INSTALL_PLAN",
  status: errors.length === 0 ? "PASS" : "FAIL",
  checked_at_utc: new Date().toISOString(),
  checks,
  errors,
  radeon_status: "NOT_RUN",
  claim_boundary:
    "PASS only means the install plan, pins, scripts, and offline artifacts are consistent. It does not mean a Radeon install was executed."
};

console.log(JSON.stringify(payload, null, 2));
if (errors.length > 0) process.exitCode = 2;
