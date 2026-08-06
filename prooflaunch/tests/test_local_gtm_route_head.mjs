import assert from "node:assert/strict";
import test from "node:test";

import {
  extractOutputContractTokens,
  outputContractEvidence,
  sanitizeEpisodeInput,
  scoreOutputContract,
  stratifiedSplit,
  trainCentroids,
  trainOutputContractHead,
} from "../scripts/train_local_gtm_route_head.mjs";

function rows() {
  const output = [];
  for (const stage of ["strategy", "production"]) {
    for (let index = 0; index < 20; index += 1) {
      output.push({
        stage,
        scenario_family_id: `${stage}-${index}`,
        content_sha256: String(index).padStart(64, stage === "strategy" ? "a" : "b"),
      });
    }
  }
  return output;
}

test("sanitizer removes direct label and unique family leakage", () => {
  const result = sanitizeEpisodeInput({
    system_prompt: "Route the bounded task.",
    user_prompt: "Scenario family: family-001\nStage: strategy\nReturn outputs: channel, claim.",
  });
  assert.equal(result.includes("family-001"), false);
  assert.equal(result.includes("Stage: strategy"), false);
  assert.equal(result.includes("Return outputs: channel, claim."), true);
});

test("split is deterministic, stratified and keeps an untouched test partition", () => {
  const corpus = rows();
  const first = stratifiedSplit(corpus, "seed");
  const second = stratifiedSplit(corpus, "seed");
  assert.deepEqual(first, second);
  for (const label of ["strategy", "production"]) {
    const values = corpus.map((row, index) => row.stage === label ? first[index] : null).filter(Boolean);
    assert.equal(values.filter((value) => value === "train").length, 16);
    assert.equal(values.filter((value) => value === "validation").length, 2);
    assert.equal(values.filter((value) => value === "test").length, 2);
  }
});

test("prototype training uses train rows only and normalizes class weights", () => {
  const embeddings = new Float32Array([
    1, 0,
    0.8, 0.2,
    0, 1,
    0.2, 0.8,
  ]);
  const trained = trainCentroids(
    embeddings,
    2,
    ["a", "a", "b", "b"],
    ["train", "validation", "train", "test"],
    ["a", "b"],
  );
  assert.deepEqual(trained.counts, [1, 1]);
  assert.ok(Math.abs(trained.centroids[0][0] - 1) < 1e-9);
  assert.ok(Math.abs(trained.centroids[1][1] - 1) < 1e-9);
});

test("output-contract head learns only from train rows and ignores held-out-only tokens", () => {
  const inputs = [
    "Return outputs: smp, rtb, offer.",
    "Return outputs: hidden_validation_token.",
    "Return outputs: asset_spec, render_checks.",
    "Return outputs: hidden_test_token.",
  ];
  assert.deepEqual(extractOutputContractTokens(inputs[0]), ["offer", "rtb", "smp"]);
  const head = trainOutputContractHead(
    inputs,
    ["strategy", "strategy", "production", "production"],
    ["train", "validation", "train", "test"],
    ["production", "strategy"],
  );
  assert.equal("hidden_validation_token" in head.token_counts, false);
  assert.equal("hidden_test_token" in head.token_counts, false);
  const scores = scoreOutputContract(inputs[0], head);
  assert.ok(scores[1] > scores[0]);
  assert.deepEqual(outputContractEvidence(inputs[0], head).supported_labels, ["strategy"]);
  assert.equal(outputContractEvidence("Write a viral post.", head).unambiguous, false);
  assert.equal(outputContractEvidence(
    "Return outputs: smp, asset_spec.",
    head,
  ).unambiguous, false);
});
