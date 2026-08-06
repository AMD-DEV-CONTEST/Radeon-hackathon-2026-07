import assert from "node:assert/strict";
import test from "node:test";

import {
  QUALITY_PROTOCOL_VERSION,
  inputFingerprint,
  sha256,
  validateOpenTodoResponse,
  validateStoredOpenTodoRecord,
} from "../scripts/tokenfactory_open_todo_quality.mjs";


const TODO_ID = "1207";
const ROLE = "system_architect";


function validPayload(overrides = {}) {
  return {
    todo_id: TODO_ID,
    role: ROLE,
    reuse: ["existing causal-twin benchmark"],
    hypothesis: "A bounded intervention policy improves the acceptance metric.",
    mechanism: "Compare the proposed policy with a frozen negative control.",
    implementation: ["compile fixtures", "run the temporal holdout"],
    training_examples: Array.from({ length: 6 }, (_, index) => ({
      state: `state-${index}`,
      action: `action-${index}`,
      observation: `observation-${index}`,
      repair: `repair-${index}`,
      acceptance_target: `acceptance-${index}`,
    })),
    ablations: ["remove the intervention", "remove the repair step"],
    metrics: ["task_success", "calibration_error"],
    stop_rule: "Stop if the holdout metric regresses by more than one point.",
    rollback: "Restore the frozen pre-intervention policy.",
    radeon_action: "Run the final bounded inference on a Radeon GPU.",
    rights_gate: "evaluator_only_pending_terms; output_training_rights_not_captured",
    evidence_class: "planned_official_advisory",
    external_blockers: ["Radeon instance verification"],
    current_status: "in_progress",
    ...overrides,
  };
}


function validResult(payload = validPayload(), overrides = {}) {
  return {
    http_status: 200,
    ok: true,
    finish_reason: "stop",
    content: JSON.stringify(payload),
    ...overrides,
  };
}


function fingerprintInput(overrides = {}) {
  return {
    todoId: TODO_ID,
    requirement: "Prove the bounded intervention mechanism.",
    role: ROLE,
    roleInstruction: "Return the required strict JSON object.",
    model: "Qwen3.6-35B-A3B",
    temperature: 0.2,
    maxTokens: 4096,
    derivativeGenerationAllowed: false,
    priorOutputSha256s: ["a".repeat(64)],
    ...overrides,
  };
}


test("valid official-advisory response passes every quality gate", () => {
  const result = validResult();
  const validation = validateOpenTodoResponse({
    result,
    todoId: TODO_ID,
    role: ROLE,
    expectedOutputSha256: sha256(result.content),
  });

  assert.equal(validation.passed, true);
  assert.deepEqual(validation.violations, []);
  assert.equal(validation.parsed.todo_id, TODO_ID);
});


test("invalid JSON fails closed", () => {
  const validation = validateOpenTodoResponse({
    result: validResult(undefined, { content: "{not-json" }),
    todoId: TODO_ID,
    role: ROLE,
  });

  assert.equal(validation.passed, false);
  assert.ok(validation.violations.includes("invalid_json"));
});


test("only three training examples are rejected", () => {
  const payload = validPayload();
  payload.training_examples = payload.training_examples.slice(0, 3);
  const validation = validateOpenTodoResponse({
    result: validResult(payload),
    todoId: TODO_ID,
    role: ROLE,
  });

  assert.equal(validation.passed, false);
  assert.ok(validation.violations.includes("training_examples_count"));
});


test("a response for the wrong TODO id is rejected", () => {
  const validation = validateOpenTodoResponse({
    result: validResult(validPayload({ todo_id: "9999" })),
    todoId: TODO_ID,
    role: ROLE,
  });

  assert.equal(validation.passed, false);
  assert.ok(validation.violations.includes("todo_id_mismatch"));
});


test("a missing required field is rejected", () => {
  const payload = validPayload();
  delete payload.rollback;
  const validation = validateOpenTodoResponse({
    result: validResult(payload),
    todoId: TODO_ID,
    role: ROLE,
  });

  assert.equal(validation.passed, false);
  assert.ok(validation.violations.includes("missing_field:rollback"));
});


test("a corrupted stored output hash is rejected", () => {
  const result = validResult();
  const validation = validateOpenTodoResponse({
    result,
    todoId: TODO_ID,
    role: ROLE,
    expectedOutputSha256: "0".repeat(64),
  });

  assert.equal(validation.passed, false);
  assert.ok(validation.violations.includes("output_sha256_mismatch"));
});


test("a length-truncated completion is rejected", () => {
  const validation = validateOpenTodoResponse({
    result: validResult(validPayload(), { finish_reason: "length" }),
    todoId: TODO_ID,
    role: ROLE,
  });

  assert.equal(validation.passed, false);
  assert.ok(validation.violations.includes("finish_reason_not_stop"));
});


test("unsafe output rights and evidence claims are rejected", () => {
  const payload = validPayload({
    rights_gate: "approved for unrestricted model training",
    evidence_class: "observed_production_effect",
  });
  const validation = validateOpenTodoResponse({
    result: validResult(payload),
    todoId: TODO_ID,
    role: ROLE,
  });

  assert.equal(validation.passed, false);
  assert.ok(validation.violations.includes("rights_gate_not_evaluator_only"));
  assert.ok(validation.violations.includes("unsafe_evidence_class"));
});


test("a credential canary in model output fails the secret gate", () => {
  const payload = validPayload({
    mechanism: "Never persist rc-TESTCREDENTIALCANARY1234 in an artifact.",
  });
  const validation = validateOpenTodoResponse({
    result: validResult(payload),
    todoId: TODO_ID,
    role: ROLE,
  });

  assert.equal(validation.passed, false);
  assert.ok(validation.violations.includes("credential_pattern_present"));
});


test("the input fingerprint changes when a material input changes", () => {
  const original = inputFingerprint(fingerprintInput());
  const same = inputFingerprint(fingerprintInput());
  const changed = inputFingerprint(
    fingerprintInput({ requirement: "A materially changed requirement." }),
  );

  assert.equal(original, same);
  assert.notEqual(original, changed);
});


test("stored-record admission and credential persistence flags are enforced", () => {
  const result = validResult();
  const fingerprint = inputFingerprint(fingerprintInput());
  const baseRecord = {
    result,
    output_sha256: sha256(result.content),
    input_fingerprint_sha256: fingerprint,
    quality_protocol: QUALITY_PROTOCOL_VERSION,
    accepted_as_training_material: false,
    credential_persisted: false,
    derivative_generation_allowed: false,
  };
  const expected = {
    todoId: TODO_ID,
    role: ROLE,
    inputFingerprint: fingerprint,
  };

  const valid = validateStoredOpenTodoRecord(baseRecord, expected);
  assert.equal(valid.passed, true);
  assert.deepEqual(valid.violations, []);

  const unsafe = validateStoredOpenTodoRecord(
    {
      ...baseRecord,
      accepted_as_training_material: true,
      credential_persisted: true,
    },
    expected,
  );
  assert.equal(unsafe.passed, false);
  assert.ok(unsafe.violations.includes("training_admission_not_false"));
  assert.ok(unsafe.violations.includes("credential_persistence_not_false"));
});
