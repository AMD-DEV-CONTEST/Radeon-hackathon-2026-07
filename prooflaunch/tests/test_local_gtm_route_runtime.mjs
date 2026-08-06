import assert from "node:assert/strict";
import test from "node:test";

import { routeFromEmbedding } from "../scripts/run_local_gtm_route_head.mjs";

const model = {
  dimensions: 2,
  labels: ["production", "strategy"],
  centroids: [[1, 0], [0, 1]],
  output_contract_head: {
    labels: ["production", "strategy"],
    token_counts: { asset_spec: [10, 0], smp: [0, 10] },
    smoothing: 1,
  },
  contract_weight: 0.1,
  temperature: 0.1,
  abstention_threshold: 0,
  model_sha256: "model-sha",
  base_embedding_model: { digest: "base-sha" },
  promoted: false,
};
const receipt = { promotion_gate_passed: true };

test("runtime routes only when contract and dense semantics corroborate", () => {
  const result = routeFromEmbedding("Return outputs: smp.", [0, 1], model, receipt);
  assert.equal(result.decision, "route");
  assert.equal(result.route, "strategy");
  assert.equal(result.automatic_external_action_enabled, false);
});

test("runtime abstains on missing, ambiguous, or semantically conflicting contracts", () => {
  assert.equal(routeFromEmbedding("Write a campaign.", [0, 1], model, receipt).decision, "abstain");
  assert.equal(routeFromEmbedding("Return outputs: smp, asset_spec.", [0, 1], model, receipt).decision, "abstain");
  assert.equal(routeFromEmbedding("Return outputs: smp.", [1, 0], model, receipt).decision, "abstain");
});
