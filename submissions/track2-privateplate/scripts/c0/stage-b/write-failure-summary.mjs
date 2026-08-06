#!/usr/bin/env node
/**
 * Unified failure / completion summary for a C0-B run.
 * Always safe to call; never claims Radeon success from missing files.
 */
import { access, readFile, writeFile, mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { resolveC0bOutDir } from "./resolve-out-dir.mjs";

const root = fileURLToPath(new URL("../../../", import.meta.url));
const outDir = resolveC0bOutDir(root);
const rawDir = path.join(outDir, "raw");
await mkdir(rawDir, { recursive: true });

const reason =
  process.env.PRIVATEPLATE_FAILURE_REASON ??
  process.env.PRIVATEPLATE_EXIT_REASON ??
  null;
const exitCode = Number(
  process.env.PRIVATEPLATE_OVERALL_EXIT ?? process.env.PRIVATEPLATE_EXIT_CODE ?? 0
);

async function readJsonIfExists(relOrAbs) {
  const abs = path.isAbsolute(relOrAbs) ? relOrAbs : path.join(outDir, relOrAbs);
  try {
    await access(abs);
    return JSON.parse(await readFile(abs, "utf8"));
  } catch {
    return null;
  }
}

async function exists(rel) {
  try {
    await access(path.join(outDir, rel));
    return true;
  } catch {
    return false;
  }
}

const filesPresent = {
  environment: await exists("environment.json"),
  runtime_pin_verification: await exists("raw/runtime-pin-verification.json"),
  runtime_install_receipt: await exists("raw/runtime-install-receipt.json"),
  vllm_launch: await exists("raw/vllm-launch.json"),
  vllm_start_failure: await exists("raw/vllm-start-failure.json"),
  vllm_stop: await exists("raw/vllm-stop.json"),
  model_artifact_verification: await exists("raw/model-artifact-verification.json"),
  baseline_results: await exists("baseline-results.json"),
  tool_calling_jsonl: await exists("tool-calling.jsonl"),
  tool_calling_summary: await exists("tool-calling-summary.json"),
  product_agent_jsonl: await exists("product-agent-e2e.jsonl"),
  product_agent_summary: await exists("product-agent-e2e-summary.json"),
  public_golden_jsonl: await exists("public-golden.jsonl"),
  public_golden_summary: await exists("public-golden-summary.json"),
  agent_diagnostic_summary: await exists("agent-diagnostic-summary.json"),
  cloud_session: await exists("cloud-session.json"),
  collection_summary: await exists("collection-summary.json"),
  run_all_log: await exists("raw/run-all.log"),
  evidence_inventory: await exists("raw/evidence-inventory.json")
};

const runtimePin = await readJsonIfExists("raw/runtime-pin-verification.json");
const installReceipt = await readJsonIfExists("raw/runtime-install-receipt.json");
const startFailure = await readJsonIfExists("raw/vllm-start-failure.json");
const stopReceipt = await readJsonIfExists("raw/vllm-stop.json");
const artifact = await readJsonIfExists("raw/model-artifact-verification.json");
const toolSummary = await readJsonIfExists("tool-calling-summary.json");
const productAgent = await readJsonIfExists("product-agent-e2e-summary.json");
const publicGolden = await readJsonIfExists("public-golden-summary.json");
const collection = await readJsonIfExists("collection-summary.json");
const session = await readJsonIfExists("cloud-session.json");

const stepStatus = {
  tool: process.env.PRIVATEPLATE_TOOL_STEP_STATUS ?? null,
  product_agent:
    process.env.PRIVATEPLATE_PRODUCT_AGENT_STEP_STATUS ?? null,
  public_golden:
    process.env.PRIVATEPLATE_PUBLIC_GOLDEN_STEP_STATUS ?? null,
  baseline: process.env.PRIVATEPLATE_BASELINE_STEP_STATUS ?? null,
  session: process.env.PRIVATEPLATE_SESSION_STEP_STATUS ?? null,
  artifact: process.env.PRIVATEPLATE_ARTIFACT_STEP_STATUS ?? null
};

const failures = [];
if (reason) failures.push(reason);
if (startFailure?.reason) failures.push(`vllm_start:${startFailure.reason}`);
if (runtimePin && runtimePin.status !== "PASS") {
  failures.push("runtime_pin_verification_failed");
}
if (installReceipt && installReceipt.status === "FAIL") {
  failures.push(`install:${installReceipt.reason ?? "FAIL"}`);
}
if (artifact && artifact.status && artifact.status !== "PASS") {
  failures.push("model_artifact_verification_failed");
}
if (toolSummary?.overall_gate === "FAIL") {
  failures.push("tool_gate_failed");
}
if (productAgent?.status === "FAIL") {
  failures.push("product_agent_e2e_failed");
}
if (publicGolden?.status === "FAIL") {
  failures.push("public_golden_failed");
}
if (collection?.capture_status === "FAIL" || collection?.finalization_status === "FAIL") {
  failures.push("collection_summary_fail");
}
for (const [name, value] of Object.entries(stepStatus)) {
  if (value != null && Number(value) !== 0) {
    failures.push(`step_${name}_exit_${value}`);
  }
}

const vllmStopped =
  stopReceipt?.process_alive_after === false ||
  stopReceipt?.stop_method === "pid_file_stale" ||
  stopReceipt?.stop_method === "none";

const destroyStatus =
  session?.destroy_status ??
  process.env.PRIVATEPLATE_DESTROY_STATUS ??
  "NOT_REQUIRED_FREE_INSTANCE";

const status =
  exitCode === 0 && failures.length === 0
    ? "COMPLETED_NO_FAILURE_FLAG"
    : "FAILED_OR_INCOMPLETE";

const payload = {
  schema_version: "1.0",
  stage: "C0-B",
  phase: "FAILURE_OR_COMPLETION_SUMMARY",
  status,
  overall_exit_code: exitCode,
  run_id: process.env.PRIVATEPLATE_RUN_ID ?? path.basename(outDir),
  profile_id: process.env.PRIVATEPLATE_MODEL_PROFILE ?? null,
  written_at_utc: new Date().toISOString(),
  failures: [...new Set(failures)],
  files_present: filesPresent,
  step_status: stepStatus,
  vllm_service: {
    start_failure: startFailure,
    stop_receipt: stopReceipt,
    considered_stopped: Boolean(vllmStopped),
    note: "Model service stop is required on both success and failure paths."
  },
  instance_lifecycle: {
    status: destroyStatus,
    note:
      "The current Global instance is owner-confirmed free to keep running. The automated requirement is to stop the local vLLM service on exit.",
    account_channel:
      session?.account_channel ??
      process.env.PRIVATEPLATE_ACCOUNT_CHANNEL ??
      null,
    profile_url:
      session?.profile_url ?? process.env.PRIVATEPLATE_PROFILE_URL ?? null,
    storage_mode:
      session?.storage_mode ?? process.env.PRIVATEPLATE_STORAGE_MODE ?? null,
    model_directory:
      session?.model_directory ??
      process.env.PRIVATEPLATE_MODEL_DIRECTORY ??
      null,
    instance_id_env_set: Boolean(process.env.PRIVATEPLATE_INSTANCE_ID)
  },
  historical_evidence_readonly: {
    protected: ["privateplate-v2", "privateplate-v2.attempt1-arg-fail"],
    note: "This writer refuses protected run ids via resolveC0bOutDir."
  },
  claim_boundary:
    "This summary records what the run left on disk. It is not an independent scorer and does not invent PASS for missing gates."
};

const outPath = path.join(rawDir, "failure-summary.json");
await writeFile(outPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
console.log(
  JSON.stringify(
    {
      status: payload.status,
      wrote: outPath,
      failures: payload.failures,
      instance_lifecycle_status: destroyStatus,
      vllm_considered_stopped: payload.vllm_service.considered_stopped
    },
    null,
    2
  )
);

if (status !== "COMPLETED_NO_FAILURE_FLAG") {
  process.exitCode = 2;
}
