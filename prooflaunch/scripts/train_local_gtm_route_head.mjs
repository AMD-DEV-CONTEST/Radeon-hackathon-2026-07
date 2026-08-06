#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const DEFAULT_INPUT = path.join(ROOT, "data/v10_sft_corpus/episodes.jsonl");
const DEFAULT_OUTPUT = path.join(ROOT, "artifacts/local-gtm-route-head-v3");
const DEFAULT_CACHE_FROM = path.join(ROOT, "artifacts/local-gtm-route-head-v1");
const LOCAL_OLLAMA = "http://127.0.0.1:11434";
const TEMPERATURE_GRID = [0.03, 0.05, 0.08, 0.1, 0.15, 0.2, 0.3, 0.5, 0.75, 1.0];

function parseArgs(argv) {
  const options = {
    input: DEFAULT_INPUT,
    output: DEFAULT_OUTPUT,
    model: "bge-m3:latest",
    batchSize: 32,
    seed: "prooflaunch-local-route-head-v3-frozen-final",
    cacheFrom: DEFAULT_CACHE_FROM,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (value === "--input") options.input = path.resolve(argv[++index]);
    else if (value === "--output") options.output = path.resolve(argv[++index]);
    else if (value === "--model") options.model = argv[++index];
    else if (value === "--batch-size") options.batchSize = Number(argv[++index]);
    else if (value === "--seed") options.seed = argv[++index];
    else if (value === "--cache-from") options.cacheFrom = path.resolve(argv[++index]);
    else throw new Error(`unknown argument: ${value}`);
  }
  if (!Number.isInteger(options.batchSize) || options.batchSize < 1 || options.batchSize > 128) {
    throw new Error("--batch-size must be an integer in [1, 128]");
  }
  return options;
}

export function sha256(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

export function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

export function sanitizeEpisodeInput(row) {
  if (!row || typeof row !== "object") throw new Error("episode must be an object");
  if (typeof row.system_prompt !== "string" || typeof row.user_prompt !== "string") {
    throw new Error("episode lacks training prompts");
  }
  const user = row.user_prompt
    .replace(/^Scenario family:[^\n]*\n?/m, "")
    .replace(/^Stage:[^\n]*\n?/m, "")
    .trim();
  return `${row.system_prompt.trim()}\n\n${user}`;
}

export function extractOutputContractTokens(input) {
  const match = String(input).match(/Return outputs:\s*([^\n.]+)/i);
  if (!match) return [];
  return [...new Set(match[1].toLowerCase().match(/[a-z][a-z0-9_]*/g) ?? [])].sort();
}

export function trainOutputContractHead(inputs, labels, split, labelNames) {
  const labelIndex = new Map(labelNames.map((label, index) => [label, index]));
  const tokenCounts = new Map();
  labels.forEach((label, rowIndex) => {
    if (split[rowIndex] !== "train") return;
    for (const token of extractOutputContractTokens(inputs[rowIndex])) {
      if (!tokenCounts.has(token)) tokenCounts.set(token, labelNames.map(() => 0));
      tokenCounts.get(token)[labelIndex.get(label)] += 1;
    }
  });
  return {
    labels: labelNames,
    token_counts: Object.fromEntries([...tokenCounts.entries()].sort(([left], [right]) => left.localeCompare(right))),
    smoothing: 1,
  };
}

export function scoreOutputContract(input, contractHead) {
  const tokens = extractOutputContractTokens(input).filter((token) => contractHead.token_counts[token]);
  if (!tokens.length) return contractHead.labels.map(() => 0);
  return contractHead.labels.map((_, classIndex) => {
    let score = 0;
    for (const token of tokens) {
      const counts = contractHead.token_counts[token];
      const total = counts.reduce((sum, value) => sum + value, 0);
      score += Math.log((counts[classIndex] + contractHead.smoothing) /
        (total + contractHead.smoothing * contractHead.labels.length));
    }
    return score / tokens.length;
  });
}

export function outputContractEvidence(input, contractHead) {
  const recognizedTokens = extractOutputContractTokens(input).filter((token) => contractHead.token_counts[token]);
  const supported = new Set();
  for (const token of recognizedTokens) {
    contractHead.token_counts[token].forEach((count, classIndex) => {
      if (count > 0) supported.add(contractHead.labels[classIndex]);
    });
  }
  return {
    recognized_tokens: recognizedTokens,
    supported_labels: [...supported].sort(),
    unambiguous: recognizedTokens.length > 0 && supported.size === 1,
  };
}

export function stratifiedSplit(rows, seed) {
  const groups = new Map();
  rows.forEach((row, index) => {
    const label = row.stage;
    if (typeof label !== "string" || !label) throw new Error("episode stage is invalid");
    if (!groups.has(label)) groups.set(label, []);
    groups.get(label).push(index);
  });
  const split = new Array(rows.length);
  for (const [label, indices] of groups.entries()) {
    indices.sort((left, right) => {
      const leftKey = sha256(`${seed}:${label}:${rows[left].scenario_family_id}:${rows[left].content_sha256}`);
      const rightKey = sha256(`${seed}:${label}:${rows[right].scenario_family_id}:${rows[right].content_sha256}`);
      return leftKey.localeCompare(rightKey);
    });
    const testCount = Math.max(1, Math.floor(indices.length * 0.1));
    const validationCount = Math.max(1, Math.floor(indices.length * 0.1));
    indices.forEach((rowIndex, position) => {
      split[rowIndex] = position < testCount
        ? "test"
        : position < testCount + validationCount
          ? "validation"
          : "train";
    });
  }
  return split;
}

function readJsonl(filePath) {
  const source = fs.readFileSync(filePath, "utf8");
  const rows = source.split("\n").filter(Boolean).map((line, index) => {
    try {
      return JSON.parse(line);
    } catch (error) {
      throw new Error(`invalid JSONL row ${index + 1}: ${error.message}`);
    }
  });
  if (!rows.length) throw new Error("training corpus is empty");
  return { rows, fileSha256: sha256(Buffer.from(source)) };
}

async function requestJson(route, options = {}) {
  const response = await fetch(`${LOCAL_OLLAMA}${route}`, {
    ...options,
    signal: AbortSignal.timeout(180_000),
  });
  const text = await response.text();
  if (!response.ok) throw new Error(`Ollama ${route} returned ${response.status}: ${text.slice(0, 400)}`);
  return JSON.parse(text);
}

async function requireLocalModel(model) {
  const tags = await requestJson("/api/tags");
  const models = Array.isArray(tags.models) ? tags.models : [];
  const match = models.find((item) => item.name === model || item.model === model);
  if (!match || typeof match.digest !== "string") {
    throw new Error(`local model ${model} is absent; download is deliberately disabled`);
  }
  return {
    name: match.name ?? model,
    digest: match.digest,
    size_bytes: match.size,
    details: match.details ?? {},
    download_performed: false,
  };
}

function normalizeInto(values, target, offset, dimensions) {
  if (!Array.isArray(values) || values.length !== dimensions) throw new Error("embedding dimensions drifted");
  let normSquared = 0;
  for (const value of values) {
    if (typeof value !== "number" || !Number.isFinite(value)) throw new Error("embedding contains a non-finite value");
    normSquared += value * value;
  }
  const norm = Math.sqrt(normSquared);
  if (!(norm > 0)) throw new Error("embedding norm is zero");
  for (let dimension = 0; dimension < dimensions; dimension += 1) {
    target[offset + dimension] = values[dimension] / norm;
  }
}

async function embedAll(inputs, model, batchSize, onProgress) {
  let embeddings = null;
  let dimensions = null;
  for (let start = 0; start < inputs.length; start += batchSize) {
    const batch = inputs.slice(start, start + batchSize);
    const payload = await requestJson("/api/embed", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model, input: batch, truncate: false }),
    });
    if (!Array.isArray(payload.embeddings) || payload.embeddings.length !== batch.length) {
      throw new Error("Ollama returned an incomplete embedding batch");
    }
    if (dimensions === null) {
      dimensions = payload.embeddings[0]?.length;
      if (!Number.isInteger(dimensions) || dimensions < 8) throw new Error("embedding dimensions are invalid");
      embeddings = new Float32Array(inputs.length * dimensions);
    }
    payload.embeddings.forEach((values, localIndex) => {
      normalizeInto(values, embeddings, (start + localIndex) * dimensions, dimensions);
    });
    onProgress?.(Math.min(start + batch.length, inputs.length), inputs.length);
  }
  return { embeddings, dimensions };
}

function writeEmbeddingCache(outputDirectory, embeddings, metadata) {
  fs.mkdirSync(outputDirectory, { recursive: true });
  const dataPath = path.join(outputDirectory, "embeddings.f32");
  const bytes = Buffer.from(embeddings.buffer, embeddings.byteOffset, embeddings.byteLength);
  fs.writeFileSync(dataPath, bytes);
  const cache = {
    ...metadata,
    path: "embeddings.f32",
    bytes: bytes.length,
    sha256: sha256(bytes),
  };
  fs.writeFileSync(path.join(outputDirectory, "embedding-cache.json"), `${JSON.stringify(cache, null, 2)}\n`);
  return cache;
}

function loadEmbeddingCache(outputDirectory, expected) {
  const metadataPath = path.join(outputDirectory, "embedding-cache.json");
  if (!fs.existsSync(metadataPath)) return null;
  const metadata = JSON.parse(fs.readFileSync(metadataPath, "utf8"));
  for (const key of ["input_sha256", "model_digest", "record_count"]) {
    if (metadata[key] !== expected[key]) return null;
  }
  const dataPath = path.join(outputDirectory, metadata.path);
  if (!fs.existsSync(dataPath)) return null;
  const bytes = fs.readFileSync(dataPath);
  if (bytes.length !== metadata.bytes || sha256(bytes) !== metadata.sha256) return null;
  const copied = new Uint8Array(bytes.length);
  copied.set(bytes);
  return {
    embeddings: new Float32Array(copied.buffer),
    dimensions: metadata.dimensions,
    metadata,
  };
}

function dot(embeddings, rowOffset, centroid, dimensions) {
  let score = 0;
  for (let dimension = 0; dimension < dimensions; dimension += 1) {
    score += embeddings[rowOffset + dimension] * centroid[dimension];
  }
  return score;
}

export function trainCentroids(embeddings, dimensions, labels, split, labelNames) {
  const centroids = labelNames.map(() => new Float64Array(dimensions));
  const counts = labelNames.map(() => 0);
  const labelIndex = new Map(labelNames.map((label, index) => [label, index]));
  labels.forEach((label, rowIndex) => {
    if (split[rowIndex] !== "train") return;
    const classIndex = labelIndex.get(label);
    counts[classIndex] += 1;
    const offset = rowIndex * dimensions;
    for (let dimension = 0; dimension < dimensions; dimension += 1) {
      centroids[classIndex][dimension] += embeddings[offset + dimension];
    }
  });
  centroids.forEach((centroid, classIndex) => {
    if (!counts[classIndex]) throw new Error(`label ${labelNames[classIndex]} has no training rows`);
    let normSquared = 0;
    for (let dimension = 0; dimension < dimensions; dimension += 1) {
      centroid[dimension] /= counts[classIndex];
      normSquared += centroid[dimension] * centroid[dimension];
    }
    const norm = Math.sqrt(normSquared);
    for (let dimension = 0; dimension < dimensions; dimension += 1) centroid[dimension] /= norm;
  });
  return { centroids, counts };
}

function predictScores(embeddings, rowIndex, dimensions, centroids) {
  const offset = rowIndex * dimensions;
  return centroids.map((centroid) => dot(embeddings, offset, centroid, dimensions));
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

function nllForTemperature(rows, scoreRow, labelIndex, temperature) {
  let total = 0;
  for (const row of rows) {
    const probabilities = softmax(scoreRow(row.index), temperature);
    total -= Math.log(Math.max(probabilities[labelIndex.get(row.label)], 1e-12));
  }
  return total / rows.length;
}

function chooseAbstentionThreshold(rows, scoreRow, labelIndex, temperature, eligibleRow = () => true) {
  const predictions = rows.map((row) => {
    const probabilities = softmax(scoreRow(row.index), temperature);
    const predicted = bestIndex(probabilities);
    return { confidence: probabilities[predicted], correct: predicted === labelIndex.get(row.label), eligible: eligibleRow(row.index) };
  });
  const candidates = [...new Set([0, ...predictions.map((item) => item.confidence)])].sort((a, b) => a - b);
  let best = { threshold: 1, coverage: 0, accepted_accuracy: null };
  for (const threshold of candidates) {
    const accepted = predictions.filter((item) => item.eligible && item.confidence >= threshold);
    if (!accepted.length) continue;
    const accuracy = accepted.filter((item) => item.correct).length / accepted.length;
    const coverage = accepted.length / predictions.length;
    if (accuracy >= 0.9 && coverage > best.coverage) {
      best = { threshold, coverage, accepted_accuracy: accuracy };
    }
  }
  return best;
}

function evaluate(rows, scoreRow, labelNames, temperature, threshold, eligibleRow = () => true) {
  const labelIndex = new Map(labelNames.map((label, index) => [label, index]));
  const confusion = labelNames.map(() => labelNames.map(() => 0));
  let correct = 0;
  let accepted = 0;
  let acceptedCorrect = 0;
  for (const row of rows) {
    const probabilities = softmax(scoreRow(row.index), temperature);
    const predicted = bestIndex(probabilities);
    const truth = labelIndex.get(row.label);
    confusion[truth][predicted] += 1;
    if (predicted === truth) correct += 1;
    if (eligibleRow(row.index) && probabilities[predicted] >= threshold) {
      accepted += 1;
      if (predicted === truth) acceptedCorrect += 1;
    }
  }
  const perClass = labelNames.map((label, index) => {
    const truePositive = confusion[index][index];
    const falsePositive = confusion.reduce((sum, row, rowIndex) => sum + (rowIndex === index ? 0 : row[index]), 0);
    const falseNegative = confusion[index].reduce((sum, value, columnIndex) => sum + (columnIndex === index ? 0 : value), 0);
    const precision = truePositive + falsePositive ? truePositive / (truePositive + falsePositive) : 0;
    const recall = truePositive + falseNegative ? truePositive / (truePositive + falseNegative) : 0;
    return {
      label,
      precision,
      recall,
      f1: precision + recall ? (2 * precision * recall) / (precision + recall) : 0,
      support: confusion[index].reduce((sum, value) => sum + value, 0),
    };
  });
  return {
    count: rows.length,
    accuracy: correct / rows.length,
    macro_f1: perClass.reduce((sum, item) => sum + item.f1, 0) / perClass.length,
    accepted_coverage: accepted / rows.length,
    accepted_accuracy: accepted ? acceptedCorrect / accepted : null,
    abstention_count: rows.length - accepted,
    per_class: perClass,
    confusion_matrix: { labels: labelNames, values: confusion },
  };
}

function rawAccuracy(rows, scoreRow, labelIndex) {
  let correct = 0;
  for (const row of rows) {
    if (bestIndex(scoreRow(row.index)) === labelIndex.get(row.label)) correct += 1;
  }
  return correct / rows.length;
}

function splitRows(rows, split) {
  const output = { train: [], validation: [], test: [] };
  rows.forEach((row, index) => output[split[index]].push({ index, label: row.stage }));
  return output;
}

function roundMetrics(value) {
  if (Array.isArray(value)) return value.map(roundMetrics);
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, roundMetrics(item)]));
  return typeof value === "number" && Number.isFinite(value) ? Number(value.toFixed(8)) : value;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const startedAt = new Date().toISOString();
  const { rows, fileSha256 } = readJsonl(options.input);
  for (const row of rows) {
    if (row.training_allowed !== true || row.rights_verified !== true || row.external_side_effect !== false) {
      throw new Error(`episode ${row.episode_id} is not admitted for local training`);
    }
  }
  const inputs = rows.map(sanitizeEpisodeInput);
  const labels = rows.map((row) => row.stage);
  const labelNames = [...new Set(labels)].sort();
  const split = stratifiedSplit(rows, options.seed);
  const partitions = splitRows(rows, split);
  const inputSha256 = sha256(Buffer.from(inputs.join("\n\u0000\n")));
  const modelInventory = await requireLocalModel(options.model);
  fs.mkdirSync(options.output, { recursive: true });
  const expectedCache = {
    input_sha256: inputSha256,
    model_digest: modelInventory.digest,
    record_count: rows.length,
  };
  let cache = loadEmbeddingCache(options.output, expectedCache)
    ?? loadEmbeddingCache(options.cacheFrom, expectedCache);
  let embeddings;
  let dimensions;
  let cacheReused = false;
  if (cache) {
    ({ embeddings, dimensions } = cache);
    cacheReused = true;
    process.stdout.write(`Reused ${rows.length} cached local embeddings.\n`);
  } else {
    let lastReported = 0;
    ({ embeddings, dimensions } = await embedAll(inputs, options.model, options.batchSize, (complete, total) => {
      if (complete === total || complete - lastReported >= Math.max(options.batchSize, 256)) {
        process.stdout.write(`Embedded ${complete}/${total} with local ${options.model}.\n`);
        lastReported = complete;
      }
    }));
    cache = {
      metadata: writeEmbeddingCache(options.output, embeddings, {
        schema: "ProofLaunchLocalEmbeddingCacheV1",
        input_sha256: inputSha256,
        model_name: modelInventory.name,
        model_digest: modelInventory.digest,
        record_count: rows.length,
        dimensions,
        normalized: true,
        localhost_only: true,
        network_download_performed: false,
      }),
    };
  }
  if (embeddings.length !== rows.length * dimensions) throw new Error("embedding cache shape is invalid");
  const { centroids, counts } = trainCentroids(embeddings, dimensions, labels, split, labelNames);
  const labelIndex = new Map(labelNames.map((label, index) => [label, index]));
  const contractHead = trainOutputContractHead(inputs, labels, split, labelNames);
  const denseScoreRow = (rowIndex) => predictScores(embeddings, rowIndex, dimensions, centroids);
  const blendTrials = [0, 0.02, 0.05, 0.1, 0.2, 0.4].map((contractWeight) => {
    const scoreRow = (rowIndex) => {
      const dense = denseScoreRow(rowIndex);
      if (contractWeight === 0) return dense;
      const contract = scoreOutputContract(inputs[rowIndex], contractHead);
      return dense.map((score, classIndex) => score + contractWeight * contract[classIndex]);
    };
    return {
      contract_weight: contractWeight,
      validation_accuracy: rawAccuracy(partitions.validation, scoreRow, labelIndex),
    };
  });
  blendTrials.sort((left, right) => right.validation_accuracy - left.validation_accuracy
    || left.contract_weight - right.contract_weight);
  const contractWeight = blendTrials[0].contract_weight;
  const scoreRow = (rowIndex) => {
    const dense = denseScoreRow(rowIndex);
    const contract = scoreOutputContract(inputs[rowIndex], contractHead);
    return dense.map((score, classIndex) => score + contractWeight * contract[classIndex]);
  };
  const eligibleRow = (rowIndex) => {
    const evidence = outputContractEvidence(inputs[rowIndex], contractHead);
    if (!evidence.unambiguous) return false;
    const densePrediction = labelNames[bestIndex(denseScoreRow(rowIndex))];
    return densePrediction === evidence.supported_labels[0];
  };
  const temperatureTrials = TEMPERATURE_GRID.map((temperature) => ({
    temperature,
    validation_nll: nllForTemperature(partitions.validation, scoreRow, labelIndex, temperature),
  }));
  temperatureTrials.sort((left, right) => left.validation_nll - right.validation_nll || left.temperature - right.temperature);
  const temperature = temperatureTrials[0].temperature;
  const abstention = chooseAbstentionThreshold(partitions.validation, scoreRow, labelIndex, temperature, eligibleRow);
  const metrics = {
    schema: "ProofLaunchLocalGTMRouteHeadMetricsV3",
    majority_baseline_accuracy: 1 / labelNames.length,
    training: evaluate(partitions.train, scoreRow, labelNames, temperature, abstention.threshold, eligibleRow),
    validation: evaluate(partitions.validation, scoreRow, labelNames, temperature, abstention.threshold, eligibleRow),
    test: evaluate(partitions.test, scoreRow, labelNames, temperature, abstention.threshold, eligibleRow),
    calibration: {
      selected_contract_weight: contractWeight,
      acceptance_policy: "recognized output contract must be unambiguous and independently corroborated by the dense semantic head",
      blend_trials: blendTrials,
      selected_temperature: temperature,
      selected_abstention_threshold: abstention.threshold,
      validation_accepted_coverage: abstention.coverage,
      validation_accepted_accuracy: abstention.accepted_accuracy,
      trials: temperatureTrials,
    },
  };
  const splitManifest = {
    schema: "ProofLaunchLocalGTMRouteSplitV1",
    seed: options.seed,
    source_file_sha256: fileSha256,
    sanitized_input_sha256: inputSha256,
    strategy: "per-stage deterministic SHA-256 ordering; 80% train, 10% validation, 10% untouched test",
    direct_stage_line_removed_from_input: true,
    counts: Object.fromEntries(Object.entries(partitions).map(([name, values]) => [name, values.length])),
    episode_ids: Object.fromEntries(Object.entries(partitions).map(([name, values]) => [name, values.map((item) => rows[item.index].episode_id)])),
  };
  splitManifest.content_sha256 = sha256(Buffer.from(canonical(splitManifest)));
  const modelCore = {
    schema: "ProofLaunchLocalGTMRouteHeadV3",
    role: "14-class deterministic Graph node router",
    base_embedding_model: modelInventory,
    training_algorithm: "hybrid L2-normalized semantic prototypes plus train-only output-contract likelihoods, with validation-selected blend, temperature scaling and semantic-corroboration abstention",
    dimensions,
    labels: labelNames,
    training_counts: Object.fromEntries(labelNames.map((label, index) => [label, counts[index]])),
    centroids: centroids.map((centroid) => Array.from(centroid, (value) => Number(value.toFixed(9)))),
    output_contract_head: contractHead,
    contract_weight: contractWeight,
    acceptance_policy: {
      recognized_output_contract_required: true,
      unambiguous_contract_required: true,
      dense_semantic_corroboration_required: true,
    },
    temperature,
    abstention_threshold: abstention.threshold,
    input_contract: {
      source: path.relative(ROOT, options.input),
      source_file_sha256: fileSha256,
      sanitized_input_sha256: inputSha256,
      completion_used_as_input: false,
      direct_stage_line_removed: true,
      rights_verified_required: true,
      external_side_effect_examples_allowed: false,
    },
    split_manifest_sha256: splitManifest.content_sha256,
    automatic_external_action_enabled: false,
    truth_boundary: "This locally trained route head selects a bounded GTM Graph node or abstains. It is not a generative foundation model, creative-quality proof, Radeon evidence, causal lift or permission to publish/spend.",
  };
  modelCore.model_sha256 = sha256(Buffer.from(canonical(modelCore)));
  const roundedMetrics = roundMetrics(metrics);
  roundedMetrics.content_sha256 = sha256(Buffer.from(canonical(roundedMetrics)));
  const receipt = {
    schema: "ProofLaunchLocalGTMRouteTrainingReceiptV3",
    started_at: startedAt,
    completed_at: new Date().toISOString(),
    execution_host: {
      architecture: process.arch,
      platform: process.platform,
      accelerator: "Apple Metal through local Ollama embedding runtime",
    },
    base_model: modelInventory,
    record_count: rows.length,
    label_count: labelNames.length,
    dimensions,
    split_counts: splitManifest.counts,
    embedding_cache_reused: cacheReused,
    localhost_only: true,
    cloud_api_calls: 0,
    network_download_performed: false,
    model_sha256: modelCore.model_sha256,
    metrics_sha256: roundedMetrics.content_sha256,
    split_manifest_sha256: splitManifest.content_sha256,
    test_accuracy: roundedMetrics.test.accuracy,
    test_macro_f1: roundedMetrics.test.macro_f1,
    test_accepted_coverage: roundedMetrics.test.accepted_coverage,
    test_accepted_accuracy: roundedMetrics.test.accepted_accuracy,
    majority_baseline_accuracy: roundedMetrics.majority_baseline_accuracy,
    promotion_gate: {
      test_accuracy_minimum: 0.7,
      test_macro_f1_minimum: 0.7,
      accepted_accuracy_minimum: 0.9,
      accepted_coverage_minimum: 0.25,
    },
    promoted: false,
    truth_boundary: "Training and evaluation are observed locally for this frozen embedding route head only. No new base model was downloaded. This does not prove LLM SFT, multimodal generation training, 4A quality, business lift or Radeon-local execution.",
  };
  receipt.promotion_gate_passed = Boolean(
    receipt.test_accuracy >= receipt.promotion_gate.test_accuracy_minimum
    && receipt.test_macro_f1 >= receipt.promotion_gate.test_macro_f1_minimum
    && receipt.test_accepted_accuracy >= receipt.promotion_gate.accepted_accuracy_minimum
    && receipt.test_accepted_coverage >= receipt.promotion_gate.accepted_coverage_minimum
  );
  receipt.receipt_sha256 = sha256(Buffer.from(canonical(receipt)));
  fs.writeFileSync(path.join(options.output, "model.json"), `${JSON.stringify(modelCore, null, 2)}\n`);
  fs.writeFileSync(path.join(options.output, "metrics.json"), `${JSON.stringify(roundedMetrics, null, 2)}\n`);
  fs.writeFileSync(path.join(options.output, "split-manifest.json"), `${JSON.stringify(splitManifest, null, 2)}\n`);
  fs.writeFileSync(path.join(options.output, "training-receipt.json"), `${JSON.stringify(receipt, null, 2)}\n`);
  process.stdout.write(`${JSON.stringify({ output: options.output, ...receipt }, null, 2)}\n`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    process.stderr.write(`${error.stack ?? error.message ?? error}\n`);
    process.exitCode = 1;
  });
}
