#!/usr/bin/env node

import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";

const MIN_GOLD_CASES = 100;

function numberOrUndefined(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function isRecord(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (isRecord(value)) {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonicalize(value[key])]));
  }
  return value;
}

export function computeCasesChecksum(cases) {
  return createHash("sha256")
    .update(JSON.stringify(canonicalize(cases)))
    .digest("hex");
}

export function computeAnnotationsChecksum(annotations) {
  return createHash("sha256")
    .update(JSON.stringify(canonicalize(annotations)))
    .digest("hex");
}

function getAnnotationRows(document) {
  if (Array.isArray(document.annotations)) return document.annotations;
  if (Array.isArray(document.annotation?.records)) return document.annotation.records;
  return [];
}

function validateAnnotationBatches(annotations, annotators, maxCasesPerBatch) {
  if (!Array.isArray(annotations)) return "human Gold Set must include annotation records";
  const batches = new Map();
  for (const row of annotations) {
    if (!isRecord(row) || typeof row.annotator_id !== "string" || typeof row.batch_id !== "string" || row.batch_id.length === 0) {
      return "every annotation record must include a non-empty batch_id";
    }
    if (!annotators.includes(row.annotator_id)) continue;
    const key = `${row.annotator_id}\u0000${row.batch_id}`;
    const ids = batches.get(key) || new Set();
    ids.add(row.case_id);
    batches.set(key, ids);
    if (ids.size > maxCasesPerBatch) return `annotation batch ${row.batch_id} exceeds max_cases_per_batch for ${row.annotator_id}`;
  }
  return null;
}

function wilsonInterval(successes, total) {
  if (total <= 0) return null;
  const z = 1.959963984540054;
  const p = successes / total;
  const denominator = 1 + (z ** 2) / total;
  const centre = p + (z ** 2) / (2 * total);
  const spread = z * Math.sqrt((p * (1 - p) / total) + (z ** 2) / (4 * total ** 2));
  return { low: (centre - spread) / denominator, high: (centre + spread) / denominator };
}

export function computeIndependentAgreement(cases, annotations, annotators) {
  const selected = annotators.slice(0, 2);
  if (selected.length < 2) return { error: "at least two annotators are required" };
  const caseIds = new Set(cases.map((item) => item.id));
  const rows = new Map();
  for (const row of annotations) {
    if (!isRecord(row) || typeof row.case_id !== "string" || typeof row.annotator_id !== "string"
      || typeof row.label !== "string" || row.label.length === 0) {
      return { error: "every annotation record must contain case_id, annotator_id, and a non-empty string label" };
    }
    if (!caseIds.has(row.case_id)) return { error: `annotation references unknown case ${row.case_id}` };
    if (!annotators.includes(row.annotator_id)) return { error: `annotation references undeclared annotator ${row.annotator_id}` };
    if (!selected.includes(row.annotator_id)) continue;
    const key = `${row.case_id}\u0000${row.annotator_id}`;
    if (rows.has(key)) return { error: `duplicate annotation record for ${row.case_id}/${row.annotator_id}` };
    rows.set(key, row.label);
  }

  const pairs = [];
  for (const item of cases) {
    const first = rows.get(`${item.id}\u0000${selected[0]}`);
    const second = rows.get(`${item.id}\u0000${selected[1]}`);
    if (first === undefined || second === undefined) {
      return { error: `missing independent annotation for case ${item.id}` };
    }
    pairs.push([first, second]);
  }
  const total = pairs.length;
  const agreements = pairs.filter(([first, second]) => first === second).length;
  const observed = agreements / total;
  const firstCounts = new Map();
  const secondCounts = new Map();
  for (const [first, second] of pairs) {
    firstCounts.set(first, (firstCounts.get(first) || 0) + 1);
    secondCounts.set(second, (secondCounts.get(second) || 0) + 1);
  }
  const labels = new Set([...firstCounts.keys(), ...secondCounts.keys()]);
  const expected = [...labels].reduce((sum, label) => sum + ((firstCounts.get(label) || 0) / total) * ((secondCounts.get(label) || 0) / total), 0);
  const kappa = expected === 1 ? (observed === 1 ? 1 : 0) : (observed - expected) / (1 - expected);
  return { score: kappa, observedAgreement: observed, sampleSize: total, wilsonCi: wilsonInterval(agreements, total) };
}

function isGoldSet(document) {
  const provenance = document.provenance || {};
  return document.dataset_type === "gold"
    || document.type === "gold"
    || document.gold_set === true
    || document.split === "gold"
    || document.set === "gold"
    || provenance.label_status === "human-gold";
}

function getAnnotators(document) {
  if (Array.isArray(document.annotators)) return document.annotators;
  if (Array.isArray(document.provenance?.annotators)) return document.provenance.annotators;
  if (Array.isArray(document.annotation?.annotators)) return document.annotation.annotators;
  return [];
}

function getAgreement(document) {
  return numberOrUndefined(document.agreement)
    ?? numberOrUndefined(document.agreement_score)
    ?? numberOrUndefined(document.provenance?.agreement)
    ?? numberOrUndefined(document.provenance?.agreement_score)
    ?? numberOrUndefined(document.annotation?.agreement)
    ?? numberOrUndefined(document.annotation?.agreement_score)
    ?? numberOrUndefined(document.agreement?.score)
    ?? numberOrUndefined(document.agreement?.value)
    ?? numberOrUndefined(document.provenance?.agreement?.score)
    ?? numberOrUndefined(document.annotation?.agreement?.score);
}

function getAgreementRecord(document) {
  const candidates = [document.agreement, document.provenance?.agreement, document.annotation?.agreement];
  return candidates.find(isRecord);
}

/** Validate metadata without manufacturing labels or annotator evidence. */
export function validateDataset(document) {
  const errors = [];
  if (!document || typeof document !== "object" || Array.isArray(document)) {
    return { valid: false, errors: ["dataset must be a JSON object"], warnings: [] };
  }

  const cases = Array.isArray(document.cases)
    ? document.cases
    : Array.isArray(document.items) ? document.items : [];
  const declaredCount = numberOrUndefined(document.case_count);
  const caseCount = cases.length > 0 ? cases.length : (declaredCount ?? 0);
  const gold = isGoldSet(document);
  const provenance = document.provenance || {};

  if (caseCount === 0) errors.push("dataset must contain cases or a positive case_count");
  if (!gold) {
    if (provenance.label_status && provenance.label_status !== "fixture-only") {
      errors.push("non-Gold dataset must declare provenance.label_status=fixture-only");
    }
    return {
      valid: errors.length === 0,
      errors,
      warnings: ["fixture-only dataset: labels are deterministic fixtures, not human Gold Set annotations"],
      case_count: caseCount,
      source: "fixture-only",
    };
  }

  if (caseCount < MIN_GOLD_CASES) {
    errors.push(`human Gold Set requires at least ${MIN_GOLD_CASES} cases (received ${caseCount})`);
  }
  if (caseCount > 150 && provenance.risk_profile !== "catastrophic") {
    errors.push(`human Gold Set should contain at most 150 cases (received ${caseCount}); use a separate catastrophic set for oversampling`);
  }
  if (cases.length === 0) errors.push("human Gold Set must include case rows, not only case_count");
  if (declaredCount !== undefined && declaredCount !== cases.length) {
    errors.push(`case_count (${declaredCount}) must match the number of case rows (${cases.length})`);
  }
  const caseIds = cases.map((item) => item && item.id);
  if (caseIds.some((id) => typeof id !== "string" || id.length === 0)) {
    errors.push("every human Gold Set case must have a non-empty id");
  }
  if (new Set(caseIds).size !== caseIds.length) errors.push("human Gold Set case ids must be unique");
  const annotators = getAnnotators(document);
  if (annotators.length < 2) errors.push("human Gold Set must include at least two independent annotators");
  if (new Set(annotators).size !== annotators.length) errors.push("annotator identifiers must be unique");
  const annotationRows = getAnnotationRows(document);
  if (annotationRows.length === 0) errors.push("human Gold Set must include independent annotation records, not only annotator metadata");
  const computedAgreement = computeIndependentAgreement(cases, annotationRows, annotators);
  if (computedAgreement.error) errors.push(computedAgreement.error);
  if (provenance.independent_annotation !== true) errors.push("human Gold Set must attest to independent annotation");
  if (provenance.arbitration_completed !== true) errors.push("human Gold Set must record completed disagreement arbitration");
  if (provenance.disagreements_recorded !== true) errors.push("human Gold Set must record boundary disagreements");
  if (provenance.frozen !== true) errors.push("human Gold Set must be explicitly frozen");
  if (provenance.few_shot_excluded !== true) errors.push("frozen Gold Set must be excluded from Few-shot data");
  const maxCasesPerBatch = numberOrUndefined(provenance.max_cases_per_batch);
  if (maxCasesPerBatch === undefined || maxCasesPerBatch <= 0 || maxCasesPerBatch > 20) {
    errors.push("human Gold Set must declare max_cases_per_batch between 1 and 20");
  } else {
    const batchError = validateAnnotationBatches(annotationRows, annotators, maxCasesPerBatch);
    if (batchError) errors.push(batchError);
  }
  const agreement = getAgreement(document);
  if (agreement === undefined) errors.push("human Gold Set must include inter-annotator agreement");
  if (agreement !== undefined && (agreement < 0 || agreement > 1)) {
    errors.push("inter-annotator agreement must be between 0 and 1");
  }
  const agreementRecord = getAgreementRecord(document);
  if (agreementRecord?.metric !== "cohen_kappa") errors.push("human Gold Set agreement must declare metric=cohen_kappa");
  if (computedAgreement.score !== undefined && agreement !== undefined && Math.abs(computedAgreement.score - agreement) > 0.005) {
    errors.push(`reported Cohen's kappa (${agreement}) does not match independent annotation records (${computedAgreement.score})`);
  }
  if (computedAgreement.observedAgreement !== undefined && agreementRecord?.observed_agreement !== undefined
    && Math.abs(computedAgreement.observedAgreement - agreementRecord.observed_agreement) > 0.005) {
    errors.push("reported observed agreement does not match independent annotation records");
  }
  if (computedAgreement.sampleSize !== undefined && agreementRecord?.sample_size !== undefined
    && computedAgreement.sampleSize !== agreementRecord.sample_size) {
    errors.push("reported agreement sample_size does not match independent annotation records");
  }
  const wilson = agreementRecord?.wilson_ci;
  if (!isRecord(wilson) || typeof wilson.low !== "number" || typeof wilson.high !== "number"
    || wilson.low < 0 || wilson.high > 1 || wilson.low > wilson.high) {
    errors.push("human Gold Set must include a valid Wilson confidence interval for agreement");
  } else if (computedAgreement.wilsonCi
    && (Math.abs(wilson.low - computedAgreement.wilsonCi.low) > 0.005 || Math.abs(wilson.high - computedAgreement.wilsonCi.high) > 0.005)) {
    errors.push("reported Wilson confidence interval does not match independent annotation records");
  }
  const checksum = provenance.cases_checksum_sha256;
  if (typeof checksum !== "string" || !/^[a-f0-9]{64}$/.test(checksum)) {
    errors.push("human Gold Set must include a 64-character cases_checksum_sha256");
  } else if (cases.length > 0 && checksum !== computeCasesChecksum(cases)) {
    errors.push("cases_checksum_sha256 does not match the canonical case rows");
  }
  const annotationChecksum = provenance.annotations_checksum_sha256;
  if (typeof annotationChecksum !== "string" || !/^[a-f0-9]{64}$/.test(annotationChecksum)) {
    errors.push("human Gold Set must include a 64-character annotations_checksum_sha256");
  } else if (annotationRows.length > 0 && annotationChecksum !== computeAnnotationsChecksum(annotationRows)) {
    errors.push("annotations_checksum_sha256 does not match the canonical annotation records");
  }
  if (provenance.risk_profile === "catastrophic" && caseCount < 200) {
    errors.push(`catastrophic risk set requires at least 200 cases (received ${caseCount})`);
  }
  if (provenance.label_status === "fixture-only" || document.source_type === "fixture") {
    errors.push("fixture data cannot be presented as a human Gold Set");
  }
  if (document.source_type !== "human-annotated" || provenance.label_status !== "human-gold") {
    errors.push("human Gold Set must declare source_type=human-annotated and provenance.label_status=human-gold");
  }
  return {
    valid: errors.length === 0,
    errors,
    warnings: [],
    case_count: caseCount,
    source: "human-gold",
  };
}

async function main() {
  const file = process.argv[2];
  if (!file) {
    console.error("Usage: node evals/validate-dataset.mjs <dataset.json>");
    process.exitCode = 2;
    return;
  }
  let document;
  try {
    document = JSON.parse(await readFile(file, "utf8"));
  } catch (error) {
    console.error(`Unable to read dataset: ${error instanceof Error ? error.message : String(error)}`);
    process.exitCode = 2;
    return;
  }
  const result = validateDataset(document);
  for (const warning of result.warnings) console.warn(`WARNING: ${warning}`);
  if (!result.valid) {
    for (const error of result.errors) console.error(`ERROR: ${error}`);
    process.exitCode = 1;
    return;
  }
  console.log(`Valid ${result.source} dataset (${result.case_count} cases)`);
}

if (import.meta.url === `file://${process.argv[1]}`) main();
