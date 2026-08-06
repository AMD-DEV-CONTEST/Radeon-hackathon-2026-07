import assert from "node:assert/strict";
import test from "node:test";
import fixture from "./configs/fixture-only.json" with { type: "json" };
import template from "./configs/gold-set-template.json" with { type: "json" };
import { computeAnnotationsChecksum, computeCasesChecksum, computeIndependentAgreement, validateDataset } from "./validate-dataset.mjs";

test("fixture metadata remains explicitly fixture-only", () => {
  const result = validateDataset(fixture);
  assert.equal(result.valid, true);
  assert.equal(result.source, "fixture-only");
});

test("gold template cannot pass without human evidence", () => {
  const result = validateDataset(template);
  assert.equal(result.valid, false);
  assert.match(result.errors.join("\n"), /independent annotators/);
  assert.match(result.errors.join("\n"), /checksum/);
});

test("gold contract checks the frozen metadata and checksum", () => {
  const cases = Array.from({ length: 100 }, (_, index) => ({
    id: `human-${index + 1}`,
    conversation: `conversation-${index + 1}`,
    expected: { risk_level: index % 2 ? "low" : "high", decision: index % 2 ? "pass" : "review" },
    tags: [index % 2 ? "normal" : "risk"],
  }));
  const annotations = cases.flatMap((item) => [
    { case_id: item.id, annotator_id: "annotator-a", batch_id: `batch-${Math.floor(Number(item.id.split("-")[1]) / 20)}`, label: item.expected.decision },
    { case_id: item.id, annotator_id: "annotator-b", batch_id: `batch-${Math.floor(Number(item.id.split("-")[1]) / 20)}`, label: item.expected.decision },
  ]);
  const agreement = computeIndependentAgreement(cases, annotations, ["annotator-a", "annotator-b"]);
  assert.equal(agreement.error, undefined);
  const dataset = {
    dataset_version: "qa-gold-test-v1",
    dataset_type: "gold",
    source_type: "human-annotated",
    provenance: {
      label_status: "human-gold",
      annotators: ["annotator-a", "annotator-b"],
      independent_annotation: true,
      arbitration_completed: true,
      disagreements_recorded: true,
      frozen: true,
      few_shot_excluded: true,
      max_cases_per_batch: 20,
      cases_checksum_sha256: computeCasesChecksum(cases),
      annotations_checksum_sha256: computeAnnotationsChecksum(annotations),
      agreement: {
        metric: "cohen_kappa",
        score: agreement.score,
        observed_agreement: agreement.observedAgreement,
        sample_size: agreement.sampleSize,
        wilson_ci: agreement.wilsonCi,
      },
    },
    case_count: cases.length,
    cases,
    annotations,
  };
  assert.equal(validateDataset(dataset).valid, true);
  dataset.provenance.cases_checksum_sha256 = "0".repeat(64);
  assert.equal(validateDataset(dataset).valid, false);
});

test("Gold metadata cannot pass when independent annotation rows are missing", () => {
  const cases = Array.from({ length: 100 }, (_, index) => ({ id: `case-${index}`, expected: { decision: "pass" } }));
  const dataset = {
    dataset_type: "gold",
    source_type: "human-annotated",
    provenance: {
      label_status: "human-gold",
      annotators: ["a", "b"],
      independent_annotation: true,
      arbitration_completed: true,
      disagreements_recorded: true,
      frozen: true,
      few_shot_excluded: true,
      max_cases_per_batch: 20,
      cases_checksum_sha256: computeCasesChecksum(cases),
      annotations_checksum_sha256: computeAnnotationsChecksum([]),
      agreement: { metric: "cohen_kappa", score: 1, observed_agreement: 1, sample_size: 100, wilson_ci: { low: 0.96, high: 1 } },
    },
    case_count: cases.length,
    cases,
    annotations: [],
  };
  const result = validateDataset(dataset);
  assert.equal(result.valid, false);
  assert.match(result.errors.join("\n"), /independent annotation records/);
});

test("Gold validator enforces the declared per-annotator batch limit", () => {
  const cases = Array.from({ length: 100 }, (_, index) => ({ id: `batch-case-${index}`, expected: { decision: "pass" } }));
  const annotations = cases.flatMap((item) => [
    { case_id: item.id, annotator_id: "a", batch_id: "one-batch", label: "pass" },
    { case_id: item.id, annotator_id: "b", batch_id: "one-batch", label: "pass" },
  ]);
  const agreement = computeIndependentAgreement(cases, annotations, ["a", "b"]);
  const dataset = {
    dataset_type: "gold",
    source_type: "human-annotated",
    provenance: {
      label_status: "human-gold", annotators: ["a", "b"], independent_annotation: true,
      arbitration_completed: true, disagreements_recorded: true, frozen: true, few_shot_excluded: true,
      max_cases_per_batch: 20, cases_checksum_sha256: computeCasesChecksum(cases),
      annotations_checksum_sha256: computeAnnotationsChecksum(annotations),
      agreement: { metric: "cohen_kappa", score: agreement.score, observed_agreement: agreement.observedAgreement, sample_size: agreement.sampleSize, wilson_ci: agreement.wilsonCi },
    },
    case_count: 100, cases, annotations,
  };
  const result = validateDataset(dataset);
  assert.equal(result.valid, false);
  assert.match(result.errors.join("\n"), /exceeds max_cases_per_batch/);
});
