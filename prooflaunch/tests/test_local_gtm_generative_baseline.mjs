import assert from "node:assert/strict";
import test from "node:test";

import {
  gradeOutput,
  normalizeSingleContractWrapper,
  parseJsonObject,
  requiredOutputKeys,
} from "../scripts/run_local_gtm_generative_baseline.mjs";

test("generative baseline extracts the bounded output contract", () => {
  assert.deepEqual(
    requiredOutputKeys("Return outputs: smp, rtb, offer. Keep evidence bounded."),
    ["offer", "rtb", "smp"],
  );
});

test("generative baseline accepts fenced JSON but rejects missing keys", () => {
  assert.deepEqual(parseJsonObject("```json\n{\"smp\":\"x\"}\n```"), { smp: "x" });
  const result = gradeOutput('{"smp":"x","rtb":"y"}', ["smp", "rtb", "offer"]);
  assert.equal(result.valid_json_object, true);
  assert.equal(result.all_required_keys_present, false);
  assert.equal(result.required_key_coverage, 2 / 3);
});

test("generative baseline rejects prose as invalid output", () => {
  assert.equal(gradeOutput("Here is the answer", ["headline"]).valid_json_object, false);
});

test("Harness flattens only a complete recognized stage_outputs wrapper", () => {
  const normalized = normalizeSingleContractWrapper(
    '{"stage_outputs":{"smp":"x","rtb":"y","offer":"z"}}',
    ["smp", "rtb", "offer"],
  );
  assert.equal(normalized.applied, true);
  assert.deepEqual(JSON.parse(normalized.content), { smp: "x", rtb: "y", offer: "z" });
  assert.equal(normalizeSingleContractWrapper(
    '{"stage_outputs":{"smp":"x"}}',
    ["smp", "rtb"],
  ).applied, false);
});
