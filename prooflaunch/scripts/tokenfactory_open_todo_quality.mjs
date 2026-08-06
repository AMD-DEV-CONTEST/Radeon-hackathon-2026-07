import crypto from "node:crypto";


export const QUALITY_PROTOCOL_VERSION = "open-todo-deep-v2";

export const REQUIRED_FIELDS = Object.freeze([
  "todo_id",
  "role",
  "reuse",
  "hypothesis",
  "mechanism",
  "implementation",
  "training_examples",
  "ablations",
  "metrics",
  "stop_rule",
  "rollback",
  "radeon_action",
  "rights_gate",
  "evidence_class",
  "external_blockers",
  "current_status",
]);

export const TRAINING_EXAMPLE_REQUIRED_FIELDS = Object.freeze([
  "state",
  "action",
  "observation",
  "repair",
  "acceptance_target",
]);

const SAFE_CURRENT_STATUSES = new Set(["not_started", "in_progress"]);
const SAFE_EVIDENCE_CLASSES = new Set([
  "planned",
  "planned_official_advisory",
  "proposal",
  "simulation_plan",
  "source_bound",
]);
const CREDENTIAL_PATTERNS = Object.freeze([
  /\brc-[A-Za-z0-9_-]{12,}\b/,
  /\bsk-[A-Za-z0-9_-]{12,}\b/,
  /\bBearer\s+[A-Za-z0-9._~+\/-]{16,}\b/i,
]);


export function sha256(value) {
  return crypto.createHash("sha256").update(String(value)).digest("hex");
}


function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}


function isVisibleValue(value) {
  if (value === null) return true;
  if (typeof value === "string") return value.trim().length > 0;
  if (Array.isArray(value)) return value.length > 0;
  if (isObject(value)) return Object.keys(value).length > 0;
  return typeof value === "number" || typeof value === "boolean";
}


function containsCredential(value) {
  return CREDENTIAL_PATTERNS.some((pattern) => pattern.test(String(value)));
}


function canonicalFingerprintPayload(input) {
  return {
    quality_protocol: QUALITY_PROTOCOL_VERSION,
    todo_id: String(input.todoId),
    requirement: String(input.requirement),
    role: String(input.role),
    role_instruction_sha256: sha256(input.roleInstruction),
    model: String(input.model),
    temperature: Number(input.temperature),
    max_tokens: Number(input.maxTokens),
    derivative_generation_allowed: Boolean(input.derivativeGenerationAllowed),
    prior_output_sha256s: [...(input.priorOutputSha256s || [])].map(String),
  };
}


export function inputFingerprint(input) {
  return sha256(JSON.stringify(canonicalFingerprintPayload(input)));
}


export function validateOpenTodoResponse({
  result,
  todoId,
  role,
  expectedOutputSha256 = null,
}) {
  const violations = [];
  const content = typeof result?.content === "string" ? result.content.trim() : "";

  if (result?.http_status !== 200) violations.push("upstream_http_status");
  if (result?.ok !== true) violations.push("upstream_not_ok");
  if (result?.finish_reason !== "stop") violations.push("finish_reason_not_stop");
  if (!content) violations.push("empty_content");
  if (content.includes("```")) violations.push("markdown_fence_present");
  if (containsCredential(content)) violations.push("credential_pattern_present");

  const actualOutputSha256 = content ? sha256(content) : null;
  if (
    expectedOutputSha256 &&
    actualOutputSha256 !== expectedOutputSha256
  ) {
    violations.push("output_sha256_mismatch");
  }

  let parsed = null;
  if (content) {
    try {
      parsed = JSON.parse(content);
    } catch {
      violations.push("invalid_json");
    }
  }
  if (parsed !== null && !isObject(parsed)) {
    violations.push("root_not_object");
    parsed = null;
  }

  if (parsed) {
    const keys = new Set(Object.keys(parsed));
    for (const field of REQUIRED_FIELDS) {
      if (!keys.has(field)) violations.push(`missing_field:${field}`);
    }
    for (const field of keys) {
      if (!REQUIRED_FIELDS.includes(field)) {
        violations.push(`unexpected_field:${field}`);
      }
    }
    if (String(parsed.todo_id) !== String(todoId)) {
      violations.push("todo_id_mismatch");
    }
    if (parsed.role !== role) violations.push("role_mismatch");
    if (!SAFE_CURRENT_STATUSES.has(parsed.current_status)) {
      violations.push("unsafe_current_status");
    }
    if (!SAFE_EVIDENCE_CLASSES.has(parsed.evidence_class)) {
      violations.push("unsafe_evidence_class");
    }
    const rightsGate = String(parsed.rights_gate || "").toLowerCase();
    if (
      !rightsGate.includes("output_training_rights_not_captured") &&
      !rightsGate.includes("evaluator_only_pending_terms")
    ) {
      violations.push("rights_gate_not_evaluator_only");
    }

    for (const field of [
      "reuse",
      "hypothesis",
      "mechanism",
      "implementation",
      "ablations",
      "metrics",
      "stop_rule",
      "rollback",
      "radeon_action",
      "rights_gate",
      "evidence_class",
      "external_blockers",
    ]) {
      if (!isVisibleValue(parsed[field])) {
        violations.push(`empty_field:${field}`);
      }
    }

    if (!Array.isArray(parsed.training_examples)) {
      violations.push("training_examples_not_array");
    } else {
      if (
        parsed.training_examples.length < 6 ||
        parsed.training_examples.length > 8
      ) {
        violations.push("training_examples_count");
      }
      parsed.training_examples.forEach((example, index) => {
        if (!isObject(example)) {
          violations.push(`training_example_not_object:${index}`);
          return;
        }
        for (const field of TRAINING_EXAMPLE_REQUIRED_FIELDS) {
          if (!Object.hasOwn(example, field)) {
            violations.push(`training_example_missing:${index}:${field}`);
          } else if (field !== "repair" && !isVisibleValue(example[field])) {
            violations.push(`training_example_empty:${index}:${field}`);
          }
        }
      });
    }
  }

  return {
    passed: violations.length === 0,
    violations: [...new Set(violations)],
    parsed,
    outputSha256: actualOutputSha256,
    parsedOutputSha256: parsed ? sha256(JSON.stringify(parsed)) : null,
  };
}


export function validateStoredOpenTodoRecord(record, expected) {
  const validation = validateOpenTodoResponse({
    result: record?.result,
    todoId: expected.todoId,
    role: expected.role,
    expectedOutputSha256: record?.output_sha256 || null,
  });
  const violations = [...validation.violations];

  if (record?.accepted_as_training_material !== false) {
    violations.push("training_admission_not_false");
  }
  if (record?.credential_persisted !== false) {
    violations.push("credential_persistence_not_false");
  }
  if (
    expected.inputFingerprint &&
    record?.input_fingerprint_sha256 !== expected.inputFingerprint
  ) {
    violations.push("input_fingerprint_mismatch");
  }
  if (
    record?.quality_protocol &&
    record.quality_protocol !== QUALITY_PROTOCOL_VERSION
  ) {
    violations.push("quality_protocol_mismatch");
  }
  if (
    record?.derivative_generation_allowed !== undefined &&
    record.derivative_generation_allowed !== false
  ) {
    violations.push("derivative_generation_not_false");
  }

  return {
    ...validation,
    passed: violations.length === 0,
    violations: [...new Set(violations)],
  };
}


export function redactedRepairHints(violations) {
  return [...new Set(violations || [])]
    .filter((value) => !containsCredential(value))
    .slice(0, 32);
}
