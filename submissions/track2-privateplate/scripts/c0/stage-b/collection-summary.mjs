import { createHash } from "node:crypto";
import { readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";

import { evaluateCollectionEvidence } from "./collection-evaluation.mjs";

const STEP_ENV = {
  tool_gate: "PRIVATEPLATE_TOOL_STEP_STATUS",
  product_agent: "PRIVATEPLATE_PRODUCT_AGENT_STEP_STATUS",
  public_golden: "PRIVATEPLATE_PUBLIC_GOLDEN_STEP_STATUS",
  baseline: "PRIVATEPLATE_BASELINE_STEP_STATUS",
  session_metadata: "PRIVATEPLATE_SESSION_STEP_STATUS",
  artifact_verification: "PRIVATEPLATE_ARTIFACT_STEP_STATUS"
};

export async function writeCollectionSummary({ outDir, env = process.env }) {
  const outPath = path.join(outDir, "collection-summary.json");
  const existing = await readOptionalJson(outPath);
  const steps = Object.fromEntries(
    Object.entries(STEP_ENV).map(([name, envName]) => [
      name,
      readStepStatus(env[envName], existing?.process_exit_codes?.[name])
    ])
  );
  const toolSummary = await readOptionalJson(
    path.join(outDir, "tool-calling-summary.json")
  );
  const baseline = await readOptionalJson(
    path.join(outDir, "baseline-results.json")
  );
  const productAgent = await readOptionalJson(
    path.join(outDir, "product-agent-e2e-summary.json")
  );
  const publicGolden = await readOptionalJson(
    path.join(outDir, "public-golden-summary.json")
  );
  const session = await readOptionalJson(path.join(outDir, "cloud-session.json"));
  const environment = await readOptionalJson(
    path.join(outDir, "environment.json")
  );
  const artifact = await readOptionalJson(
    path.join(outDir, "raw/model-artifact-verification.json")
  );
  const runtimePin = await readOptionalJson(
    path.join(outDir, "raw/runtime-pin-verification.json")
  );
  const receiptVerification = await verifyOperatorReceipts(outDir, session);
  const evaluation = evaluateCollectionEvidence({
    steps,
    toolSummary,
    productAgent,
    publicGolden,
    baseline,
    session,
    environment,
    artifact,
    runtimePin,
    receiptVerification
  });

  const payload = {
    schema_version: "2.0",
    stage: "C0-B",
    collected_at_utc: new Date().toISOString(),
    ...evaluation,
    process_exit_codes: steps,
    tool_gate: toolSummary?.overall_gate ?? "MISSING",
    product_agent_gate: productAgent?.status ?? "MISSING",
    public_golden_gate: publicGolden?.status ?? "MISSING",
    public_golden_model_capability_gate:
      publicGolden?.model_capability?.gate ?? "MISSING",
    public_golden_product_completion_gate:
      publicGolden?.product_completion?.gate ?? "MISSING",
    public_golden_safety_gate:
      publicGolden?.safety?.gate ?? "MISSING",
    model_capability_gate:
      toolSummary?.model_capability_gate ?? "MISSING",
    production_safety_gate:
      toolSummary?.production_safety_gate ?? "MISSING",
    privacy_gate: toolSummary?.privacy_gate ?? "MISSING",
    effective_policy_gate:
      toolSummary?.effective_policy_gate ?? "MISSING",
    holdout_gate:
      toolSummary?.holdout_gate?.overall_gate ??
      toolSummary?.suite_gates?.["v2-holdout"]?.overall_gate ??
      toolSummary?.suite_gates?.["holdout-v1"]?.overall_gate ??
      "MISSING",
    regression_gate:
      toolSummary?.regression_gate?.overall_gate ??
      toolSummary?.suite_gates?.["v2-regression"]?.overall_gate ??
      toolSummary?.suite_gates?.regression?.overall_gate ??
      "MISSING",
    artifact_verification: artifact?.status ?? "MISSING",
    runtime_pin_verification: runtimePin?.status ?? "MISSING",
    baseline_status: baseline?.measurement_status ?? "MISSING",
    peak_vram_status: baseline?.peak_vram?.status ?? "MISSING",
    destroy_status: session?.destroy_status ?? "MISSING",
    operator_receipts: receiptVerification,
    model_profile:
      artifact?.profile_id ??
      environment?.model_profile ??
      env.PRIVATEPLATE_MODEL_PROFILE ??
      null,
    run_id: environment?.run_id ?? env.PRIVATEPLATE_RUN_ID ?? null,
    source_provenance: {
      git_commit: environment?.git_commit ?? null,
      git_dirty: environment?.git_dirty ?? null,
      integrity_verified:
        environment?.source_integrity_verified ?? false,
      integrity_mode: environment?.source_integrity_mode ?? null,
      manifest_sha256:
        environment?.source_manifest_sha256 ?? null,
      file_count: environment?.source_file_count ?? null
    },
    fail_closed:
      "Every required tool gate, product-agent turn, performance value, runtime pin, model artifact, source-integrity field, instance id, and end time must explicitly pass.",
    claim_boundary:
      "EVIDENCE_COMPLETE means the package is complete and internally consistent. Final model selection still requires comparing both candidate runs and owner review."
  };

  const tempPath = `${outPath}.${process.pid}.tmp`;
  await writeFile(tempPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  await rename(tempPath, outPath);
  return payload;
}

async function verifyOperatorReceipts(outDir, session) {
  const failures = [];
  const checks = {};
  for (const name of ["credits_before", "destroy", "credits_after"]) {
    const receipt = session?.operator_receipts?.[name];
    if (receipt == null || receipt.status === "NOT_REQUIRED") {
      checks[name] = {
        status: "NOT_REQUIRED",
        path: null,
        expected_sha256: null,
        actual_sha256: null,
        expected_size_bytes: null,
        actual_size_bytes: null
      };
      continue;
    }
    const check = {
      status: "FAIL",
      path: receipt?.path ?? null,
      expected_sha256: receipt?.sha256 ?? null,
      actual_sha256: null,
      expected_size_bytes: receipt?.size_bytes ?? null,
      actual_size_bytes: null
    };
    if (
      receipt?.status !== "CAPTURED" ||
      !isSafeRelativePath(receipt.path) ||
      !/^[0-9a-f]{64}$/.test(receipt.sha256 ?? "") ||
      !Number.isSafeInteger(receipt.size_bytes) ||
      receipt.size_bytes < 1
    ) {
      failures.push(name);
      checks[name] = check;
      continue;
    }
    try {
      const bytes = await readFile(path.join(outDir, receipt.path));
      check.actual_sha256 = createHash("sha256").update(bytes).digest("hex");
      check.actual_size_bytes = bytes.length;
      check.status =
        check.actual_sha256 === receipt.sha256 &&
        check.actual_size_bytes === receipt.size_bytes
          ? "PASS"
          : "FAIL";
    } catch {
      check.status = "FAIL";
    }
    if (check.status !== "PASS") failures.push(name);
    checks[name] = check;
  }
  return {
    status:
      failures.length > 0
        ? "FAIL"
        : Object.values(checks).some((check) => check.status === "PASS")
          ? "PASS"
          : "NOT_REQUIRED",
    failures,
    checks
  };
}

function isSafeRelativePath(value) {
  return (
    typeof value === "string" &&
    value.length > 0 &&
    !path.isAbsolute(value) &&
    !value.split(/[\\/]/).includes("..")
  );
}

function readStepStatus(envValue, previousValue) {
  const value = envValue ?? previousValue ?? 1;
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : 1;
}

async function readOptionalJson(filePath) {
  try {
    return JSON.parse(await readFile(filePath, "utf8"));
  } catch (error) {
    if (error?.code === "ENOENT") return null;
    throw error;
  }
}
