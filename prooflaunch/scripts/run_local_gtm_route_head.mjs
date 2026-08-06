#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

import {
  canonical,
  outputContractEvidence,
  scoreOutputContract,
  sha256,
} from "./train_local_gtm_route_head.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const DEFAULT_MODEL = path.join(ROOT, "artifacts/local-gtm-route-head-v3/model.json");
const DEFAULT_RECEIPT = path.join(ROOT, "artifacts/local-gtm-route-head-v3/training-receipt.json");
const LOCAL_OLLAMA = "http://127.0.0.1:11434";

function parseArgs(argv) {
  const options = { model: DEFAULT_MODEL, receipt: DEFAULT_RECEIPT, text: null };
  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (value === "--model") options.model = path.resolve(argv[++index]);
    else if (value === "--receipt") options.receipt = path.resolve(argv[++index]);
    else if (value === "--text") options.text = argv[++index];
    else if (value === "--input-file") options.text = fs.readFileSync(path.resolve(argv[++index]), "utf8");
    else throw new Error(`unknown argument: ${value}`);
  }
  if (!options.text?.trim()) throw new Error("provide --text or --input-file");
  return options;
}

function verifyContentHash(value, field) {
  const expected = value[field];
  const core = structuredClone(value);
  delete core[field];
  const observed = sha256(Buffer.from(canonical(core)));
  if (observed !== expected) throw new Error(`${field} verification failed`);
}

function normalize(values) {
  let normSquared = 0;
  for (const value of values) normSquared += value * value;
  const norm = Math.sqrt(normSquared);
  if (!(norm > 0)) throw new Error("embedding norm is zero");
  return values.map((value) => value / norm);
}

function dot(left, right) {
  let total = 0;
  for (let index = 0; index < left.length; index += 1) total += left[index] * right[index];
  return total;
}

function softmax(scores, temperature) {
  const scaled = scores.map((score) => score / temperature);
  const maximum = Math.max(...scaled);
  const exponents = scaled.map((score) => Math.exp(score - maximum));
  const total = exponents.reduce((sum, value) => sum + value, 0);
  return exponents.map((value) => value / total);
}

function bestIndex(values) {
  let index = 0;
  for (let candidate = 1; candidate < values.length; candidate += 1) {
    if (values[candidate] > values[index]) index = candidate;
  }
  return index;
}

export function routeFromEmbedding(text, rawEmbedding, model, receipt) {
  if (rawEmbedding.length !== model.dimensions) throw new Error("embedding dimensions do not match the trained head");
  const embedding = normalize(rawEmbedding);
  const denseScores = model.centroids.map((centroid) => dot(embedding, centroid));
  const contractScores = scoreOutputContract(text, model.output_contract_head);
  const hybridScores = denseScores.map((score, index) => score + model.contract_weight * contractScores[index]);
  const probabilities = softmax(hybridScores, model.temperature);
  const predictedIndex = bestIndex(probabilities);
  const denseIndex = bestIndex(denseScores);
  const evidence = outputContractEvidence(text, model.output_contract_head);
  const gates = {
    recognized_output_contract: evidence.recognized_tokens.length > 0,
    unambiguous_output_contract: evidence.unambiguous,
    dense_semantic_corroboration: evidence.unambiguous
      && model.labels[denseIndex] === evidence.supported_labels[0],
    calibrated_confidence: probabilities[predictedIndex] >= model.abstention_threshold,
    offline_promotion_gate_passed: receipt.promotion_gate_passed === true,
  };
  const accepted = Object.values(gates).every(Boolean);
  return {
    schema: "ProofLaunchLocalGTMRouteDecisionV1",
    decision: accepted ? "route" : "abstain",
    route: accepted ? model.labels[predictedIndex] : null,
    shadow_suggestion: model.labels[predictedIndex],
    confidence: Number(probabilities[predictedIndex].toFixed(8)),
    dense_semantic_route: model.labels[denseIndex],
    contract_evidence: evidence,
    gates,
    model_sha256: model.model_sha256,
    base_model_digest: model.base_embedding_model.digest,
    promoted: model.promoted === true,
    automatic_external_action_enabled: false,
    localhost_only: true,
    cloud_api_calls: 0,
    network_download_performed: false,
  };
}

async function requestJson(route, options = {}) {
  const response = await fetch(`${LOCAL_OLLAMA}${route}`, {
    ...options,
    signal: AbortSignal.timeout(180_000),
  });
  const body = await response.text();
  if (!response.ok) throw new Error(`local Ollama ${route} returned ${response.status}: ${body.slice(0, 400)}`);
  return JSON.parse(body);
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const model = JSON.parse(fs.readFileSync(options.model, "utf8"));
  const receipt = JSON.parse(fs.readFileSync(options.receipt, "utf8"));
  verifyContentHash(model, "model_sha256");
  verifyContentHash(receipt, "receipt_sha256");
  if (receipt.model_sha256 !== model.model_sha256) throw new Error("receipt does not bind the selected model");
  const tags = await requestJson("/api/tags");
  const local = tags.models?.find((item) => item.digest === model.base_embedding_model.digest);
  if (!local) throw new Error("the pinned base embedding model is not installed locally; automatic pull is disabled");
  const embedded = await requestJson("/api/embed", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model: local.name, input: [options.text], truncate: false }),
  });
  const result = routeFromEmbedding(options.text, embedded.embeddings?.[0] ?? [], model, receipt);
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    process.stderr.write(`${error.stack ?? error.message ?? error}\n`);
    process.exitCode = 1;
  });
}
