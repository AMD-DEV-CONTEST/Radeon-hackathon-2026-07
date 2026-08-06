import {
  isCurrentFormalAccount,
  isFormalTemplateProfile
} from "./account-profile.mjs";

const REQUIRED_TOOL_GATES = [
  "overall_gate",
  "model_capability_gate",
  "production_safety_gate",
  "privacy_gate",
  "effective_policy_gate"
];

export function evaluateCollectionEvidence({
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
}) {
  const captureFailures = [];

  for (const [name, value] of Object.entries(steps)) {
    if (value !== 0) captureFailures.push(`process:${name}`);
  }
  if (environment?.evidence_eligible !== true) {
    captureFailures.push("environment:evidence_eligible");
  }
  if (environment?.source_integrity_verified !== true) {
    captureFailures.push("environment:source_integrity");
  }
  if (!isCurrentFormalAccount(session)) {
    captureFailures.push("session:account_profile");
  }
  if (!isFormalTemplateProfile(session)) {
    captureFailures.push("session:template_profile");
  }
  for (const gate of REQUIRED_TOOL_GATES) {
    if (toolSummary?.[gate] !== "PASS") {
      captureFailures.push(`tool:${gate}`);
    }
  }
  const regressionGate =
    toolSummary?.regression_gate?.overall_gate ??
    toolSummary?.suite_gates?.["v2-regression"]?.overall_gate ??
    toolSummary?.suite_gates?.regression?.overall_gate;
  const holdoutGate =
    toolSummary?.holdout_gate?.overall_gate ??
    toolSummary?.suite_gates?.["v2-holdout"]?.overall_gate ??
    toolSummary?.suite_gates?.["holdout-v1"]?.overall_gate;
  if (regressionGate !== "PASS") {
    captureFailures.push("tool:regression_gate");
  }
  if (holdoutGate !== "PASS") {
    captureFailures.push("tool:holdout_gate");
  }
  if (toolSummary?.combined_gate?.overall_gate !== "PASS") {
    captureFailures.push("tool:combined_gate");
  }
  if (productAgent?.status !== "PASS") {
    captureFailures.push("product_agent:status");
  }
  if (
    !Number.isSafeInteger(productAgent?.sample_count) ||
    productAgent.sample_count < 1 ||
    productAgent.failed_count !== 0
  ) {
    captureFailures.push("product_agent:results");
  }
  if (publicGolden?.status !== "PASS") {
    captureFailures.push("public_golden:status");
  }
  if (publicGolden?.sample_count !== 36) {
    captureFailures.push("public_golden:sample_count");
  }
  for (const layer of [
    "model_capability",
    "product_completion",
    "safety"
  ]) {
    if (publicGolden?.[layer]?.gate !== "PASS") {
      captureFailures.push(`public_golden:${layer}`);
    }
  }
  for (const failure of validateBaseline(baseline)) {
    captureFailures.push(`baseline:${failure}`);
  }
  if (
    artifact?.status !== "PASS" ||
    artifact?.phase !== "POSTSTART"
  ) {
    captureFailures.push("artifact:poststart_verification");
  }
  if (
    runtimePin?.status !== "PASS" ||
    runtimePin?.phase !== "PRESTART"
  ) {
    captureFailures.push("runtime:prestart_verification");
  }

  const finalizationMissing = [];
  if (!nonEmpty(session?.instance_id)) {
    finalizationMissing.push("session:instance_id");
  }
  if (!nonEmpty(session?.ended_at_utc)) {
    finalizationMissing.push("session:ended_at_utc");
  }
  if (receiptVerification?.status === "FAIL") {
    for (const failure of receiptVerification.failures ?? [
      "operator_receipts"
    ]) {
      finalizationMissing.push(`receipt:${failure}`);
    }
  }

  const uniqueCaptureFailures = [...new Set(captureFailures)];
  const uniqueFinalizationMissing = [...new Set(finalizationMissing)];
  const captureStatus =
    uniqueCaptureFailures.length === 0 ? "PASS" : "FAIL";
  const finalizationStatus =
    uniqueFinalizationMissing.length === 0
      ? "PASS"
      : "FAIL";
  const status =
    captureStatus === "FAIL"
      ? "COLLECTION_FAILED"
      : finalizationStatus === "PASS"
        ? "EVIDENCE_COMPLETE"
        : "EVIDENCE_FINALIZATION_FAILED";

  return {
    status,
    capture_status: captureStatus,
    finalization_status: finalizationStatus,
    capture_failures: uniqueCaptureFailures,
    finalization_missing: uniqueFinalizationMissing
  };
}

export function validateBaseline(baseline) {
  const failures = [];
  if (baseline?.measurement_status !== "PASS") {
    failures.push("measurement_status");
  }
  if (baseline?.benchmark_configuration?.warm_run_count !== 5) {
    failures.push("warm_run_count");
  }
  if (
    baseline?.workload?.kind !== "product_tool_routing_prompt" ||
    baseline?.workload?.tool_count !== 5
  ) {
    failures.push("tool_workload");
  }
  if (!Number.isSafeInteger(baseline?.benchmark_configuration?.kv_cache_memory_bytes)) {
    failures.push("kv_cache_memory_bytes");
  }
  validateRequest(
    baseline?.first_baseline_request_after_readiness_check,
    "first_request",
    failures
  );
  if (!Array.isArray(baseline?.warm_runs) || baseline.warm_runs.length !== 5) {
    failures.push("warm_runs");
  } else {
    baseline.warm_runs.forEach((value, index) =>
      validateRequest(value, `warm_${index + 1}`, failures)
    );
  }
  if (
    baseline?.warm_ttft_ms?.n !== 5 ||
    !positive(baseline?.warm_ttft_ms?.p50) ||
    !positive(baseline?.warm_ttft_ms?.p90)
  ) {
    failures.push("warm_ttft");
  }
  if (
    baseline?.warm_tokens_per_sec?.n !== 5 ||
    !positive(baseline?.warm_tokens_per_sec?.p50) ||
    !positive(baseline?.warm_tokens_per_sec?.p90)
  ) {
    failures.push("warm_tokens_per_sec");
  }
  const peak = baseline?.peak_vram;
  if (
    peak?.status !== "CAPTURED" ||
    !positive(peak?.peak_used_bytes) ||
    !positive(peak?.total_bytes) ||
    !Number.isSafeInteger(peak?.sample_count) ||
    peak.sample_count < 1 ||
    peak.sampling_failures !== 0
  ) {
    failures.push("peak_vram");
  }
  return [...new Set(failures)];
}

function validateRequest(value, label, failures) {
  if (
    !positive(value?.ttft_ms) ||
    !positive(value?.total_ms) ||
    value.total_ms <= value.ttft_ms ||
    !Number.isSafeInteger(value?.prompt_tokens) ||
    value.prompt_tokens < 1 ||
    !Number.isSafeInteger(value?.completion_tokens) ||
    value.completion_tokens < 1 ||
    !positive(value?.tokens_per_sec) ||
    value.usage_reported !== true ||
    !Number.isSafeInteger(value?.tool_call_count) ||
    value.tool_call_count < 1
  ) {
    failures.push(label);
  }
}

function positive(value) {
  return Number.isFinite(value) && value > 0;
}

function nonEmpty(value) {
  return typeof value === "string" && value.trim().length > 0;
}
