#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  lstat,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  rename,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
import { basename, dirname, isAbsolute, relative, resolve, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

export const QA_SYSTEM = "你是 RDK 技术问答助手。";
export const GENERATION_METHOD = "deterministic_task_context_v1";

const PROJECT_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const SPLITS = Object.freeze(["train", "validation", "test"]);
const SPLIT_SET = new Set(SPLITS);
const SECRET_PATTERNS = [
  { code: "private_key", pattern: /-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----/i },
  { code: "openai_style_key", pattern: /\b(?:sk|rk|pk)-[A-Za-z0-9_-]{16,}\b/ },
  { code: "bearer_token", pattern: /\bBearer\s+[A-Za-z0-9._~+\/-]{12,}={0,2}\b/i },
  {
    code: "credential_assignment",
    pattern:
      /["']?(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|secret)["']?\s*[:=]\s*["']?[^\s"',}\]]{4,}/i,
  },
];

export class QaExporterError extends Error {
  constructor(code, message, details = undefined) {
    super(message);
    this.name = "QaExporterError";
    this.code = code;
    if (details !== undefined) this.details = details;
  }
}

function fail(code, message, details = undefined) {
  throw new QaExporterError(code, message, details);
}

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function canonicalize(value) {
  if (value === null || typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) fail("non_json_value", "Non-finite numbers are not valid JSON");
    return value;
  }
  if (Array.isArray(value)) return value.map(canonicalize);
  if (!isPlainObject(value)) fail("non_json_value", "Only plain JSON values can be canonicalized");
  const result = {};
  for (const key of Object.keys(value).sort()) {
    if (value[key] !== undefined) result[key] = canonicalize(value[key]);
  }
  return result;
}

export function stableJson(value) {
  return JSON.stringify(canonicalize(value));
}

export function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function sha256Canonical(value) {
  return sha256(stableJson(value));
}

function normalizeText(value) {
  return value.normalize("NFKC").replace(/\s+/gu, " ").trim().toLocaleLowerCase("en-US");
}

function normalizeUrl(value) {
  try {
    const parsed = new URL(value);
    parsed.hash = "";
    if (parsed.pathname.length > 1) parsed.pathname = parsed.pathname.replace(/\/+$/u, "");
    return parsed.toString();
  } catch {
    return null;
  }
}

function matchingSecretCodes(value) {
  const serialized = typeof value === "string" ? value : stableJson(value);
  return SECRET_PATTERNS.filter(({ pattern }) => pattern.test(serialized)).map(({ code }) => code);
}

async function pathExists(path) {
  try {
    await lstat(path);
    return true;
  } catch (error) {
    if (error?.code === "ENOENT") return false;
    throw error;
  }
}

function resolveContained(root, relativePath, label) {
  if (typeof relativePath !== "string" || relativePath.trim() === "" || isAbsolute(relativePath)) {
    fail("invalid_snapshot_path", `${label} must be a non-empty relative path`);
  }
  const candidate = resolve(root, relativePath);
  const remainder = relative(root, candidate);
  if (remainder === ".." || remainder.startsWith(`..${sep}`) || isAbsolute(remainder)) {
    fail("snapshot_path_escape", `${label} escapes the knowledge snapshot directory`);
  }
  return candidate;
}

function collectUrls(value, urls, key = "") {
  if (Array.isArray(value)) {
    for (const item of value) collectUrls(item, urls, key);
    return;
  }
  if (!isPlainObject(value)) {
    if (typeof value === "string" && /(?:^|_)url$/iu.test(key)) {
      const normalized = normalizeUrl(value);
      if (normalized) urls.add(normalized);
    }
    return;
  }
  for (const [childKey, childValue] of Object.entries(value)) {
    collectUrls(childValue, urls, childKey);
  }
}

function parseJsonLines(body, label) {
  const rows = [];
  for (const [index, line] of body.toString("utf8").split(/\r?\n/u).entries()) {
    if (!line.trim()) continue;
    try {
      rows.push(JSON.parse(line));
    } catch (error) {
      fail("invalid_snapshot_jsonl", `${label} line ${index + 1} is invalid JSON`, {
        cause: error.message,
      });
    }
  }
  return rows;
}

async function readSnapshotJsonl({ root, manifest, kind, urls, files }) {
  const pathField = `${kind}_jsonl`;
  const hashFields = [`${kind}_jsonl_sha256`, `${kind}_sha256`];
  let relativePath = manifest[pathField];
  if (!relativePath) {
    const conventionalPath = resolve(root, `${kind}.jsonl`);
    if (await pathExists(conventionalPath)) relativePath = `${kind}.jsonl`;
  }
  if (!relativePath) return false;

  const path = resolveContained(root, relativePath, pathField);
  const body = await readFile(path);
  const actualHash = sha256(body);
  const expectedHash = hashFields.map((field) => manifest[field]).find(Boolean);
  if (expectedHash && expectedHash !== actualHash) {
    fail("snapshot_hash_mismatch", `${pathField} does not match its frozen manifest hash`, {
      artifact: pathField,
      expected_sha256: expectedHash,
      actual_sha256: actualHash,
    });
  }
  const rows = parseJsonLines(body, pathField);
  for (const row of rows) collectUrls(row, urls);
  files.push({ role: pathField, sha256: actualHash, bytes: body.byteLength });
  return true;
}

async function readJsonDirectory({ root, directoryName, urls, files }) {
  const directory = resolve(root, directoryName);
  if (!(await pathExists(directory))) return;
  const info = await stat(directory);
  if (!info.isDirectory()) fail("invalid_snapshot_directory", `${directoryName} is not a directory`);
  const entries = (await readdir(directory, { withFileTypes: true }))
    .filter((entry) => entry.isFile() && entry.name.endsWith(".json"))
    .sort((left, right) => left.name.localeCompare(right.name));
  for (const entry of entries) {
    const body = await readFile(resolve(directory, entry.name));
    let value;
    try {
      value = JSON.parse(body.toString("utf8"));
    } catch (error) {
      fail("invalid_snapshot_json", `${directoryName}/${entry.name} is invalid JSON`, {
        cause: error.message,
      });
    }
    collectUrls(value, urls);
    files.push({
      role: `${directoryName}/${entry.name}`,
      sha256: sha256(body),
      bytes: body.byteLength,
    });
  }
}

async function resolveSnapshotManifest(snapshotInput) {
  const input = resolve(snapshotInput);
  const info = await stat(input).catch((error) => {
    if (error?.code === "ENOENT") fail("snapshot_not_found", `Knowledge snapshot does not exist: ${input}`);
    throw error;
  });
  if (info.isDirectory()) return { manifestPath: resolve(input, "manifest.json"), root: input };
  if (!info.isFile()) fail("invalid_snapshot_input", "Knowledge snapshot must be a directory or JSON file");

  const initial = JSON.parse(await readFile(input, "utf8"));
  if (initial?.schema_version === "magicbox_knowledge_current.v1") {
    const manifestPath = resolve(dirname(input), initial.manifest_path);
    return { manifestPath, root: dirname(manifestPath) };
  }
  return { manifestPath: input, root: dirname(input) };
}

export async function loadKnowledgeSnapshot(snapshotInput) {
  const { manifestPath, root } = await resolveSnapshotManifest(snapshotInput);
  const manifestBody = await readFile(manifestPath).catch((error) => {
    if (error?.code === "ENOENT") fail("snapshot_manifest_not_found", `Missing manifest: ${manifestPath}`);
    throw error;
  });
  let manifest;
  try {
    manifest = JSON.parse(manifestBody.toString("utf8"));
  } catch (error) {
    fail("invalid_snapshot_manifest", "Knowledge snapshot manifest is invalid JSON", {
      cause: error.message,
    });
  }
  if (!isPlainObject(manifest) || typeof manifest.snapshot_id !== "string" || !manifest.snapshot_id) {
    fail("invalid_snapshot_manifest", "Knowledge snapshot manifest must contain snapshot_id");
  }

  const urls = new Set();
  const files = [
    { role: "manifest", sha256: sha256(manifestBody), bytes: manifestBody.byteLength },
  ];
  collectUrls(manifest, urls);
  const hasPagesJsonl = await readSnapshotJsonl({ root, manifest, kind: "pages", urls, files });
  const hasChunksJsonl = await readSnapshotJsonl({ root, manifest, kind: "chunks", urls, files });
  if (!hasPagesJsonl) await readJsonDirectory({ root, directoryName: "pages", urls, files });
  if (!hasChunksJsonl) await readJsonDirectory({ root, directoryName: "chunks", urls, files });
  if (urls.size === 0) fail("snapshot_has_no_urls", "Knowledge snapshot contains no source URLs");

  files.sort((left, right) => left.role.localeCompare(right.role));
  return {
    snapshotId: manifest.snapshot_id,
    snapshotSha256: sha256Canonical({ snapshot_id: manifest.snapshot_id, files }),
    manifestSha256: sha256(manifestBody),
    urls,
    urlCount: urls.size,
    files,
  };
}

async function readTaskRows(taskFile) {
  const body = await readFile(taskFile);
  const rows = [];
  for (const [index, line] of body.toString("utf8").split(/\r?\n/u).entries()) {
    if (!line.trim()) continue;
    try {
      rows.push({ line: index + 1, task: JSON.parse(line), rawError: null });
    } catch {
      rows.push({ line: index + 1, task: null, rawError: "invalid_json" });
    }
  }
  return { rows, body, sha256: sha256(body) };
}

function addReason(row, code, message) {
  if (!row.reasons.some((reason) => reason.code === code)) row.reasons.push({ code, message });
}

function validateQaTask(row, snapshotUrls) {
  const { task } = row;
  if (!isPlainObject(task)) {
    addReason(row, "invalid_task", "Task row is not a JSON object");
    return;
  }
  if (task.schema_version !== "rdk_collection_task.v1") {
    addReason(row, "invalid_task_schema_version", "Task schema_version is not rdk_collection_task.v1");
  }
  if (!/^qa_[0-9]{6}$/u.test(task.task_id || "")) {
    addReason(row, "invalid_task_id", "QA task_id must match qa_NNNNNN");
  }
  if (!SPLIT_SET.has(task.split)) addReason(row, "invalid_split", "QA task has an invalid split");
  if (typeof task.instruction !== "string" || !task.instruction.trim()) {
    addReason(row, "invalid_instruction", "QA instruction must be a non-empty string");
  }
  if (typeof task.context !== "string" || !task.context.trim()) {
    addReason(row, "invalid_context", "QA context must be a non-empty string");
  }
  if (!Array.isArray(task.allowed_tools) || task.allowed_tools.length !== 0) {
    addReason(row, "qa_tools_not_empty", "QA task allowed_tools must be empty");
  }
  if (!isPlainObject(task.metadata)) {
    addReason(row, "invalid_metadata", "QA task metadata must be an object");
  } else {
    if (typeof task.metadata.source !== "string" || !task.metadata.source.trim()) {
      addReason(row, "missing_source", "QA metadata.source must be a non-empty string");
    }
    if (typeof task.metadata.semantic_group_id !== "string" || !task.metadata.semantic_group_id.trim()) {
      addReason(row, "missing_semantic_group", "QA metadata.semantic_group_id must be a non-empty string");
    }
    const normalizedSourceUrl = normalizeUrl(task.metadata.source_url);
    if (!normalizedSourceUrl) {
      addReason(row, "invalid_source_url", "QA metadata.source_url must be an absolute URL");
    } else if (!snapshotUrls.has(normalizedSourceUrl)) {
      addReason(row, "source_url_not_in_snapshot", "QA source_url is absent from the frozen snapshot");
    }
  }

  const answerChecks = task.verifier?.checks?.filter((check) => check?.type === "answer_terms");
  if (!Array.isArray(answerChecks) || answerChecks.length !== 1) {
    addReason(row, "invalid_answer_terms_check", "QA task must contain exactly one answer_terms check");
  } else {
    const terms = answerChecks[0].all;
    if (!Array.isArray(terms) || terms.length === 0 || terms.some((term) => typeof term !== "string" || !term.trim())) {
      addReason(row, "invalid_answer_terms", "answer_terms.all must contain non-empty strings");
    } else if (typeof task.context === "string") {
      const normalizedContext = normalizeText(task.context);
      const missing = terms.filter((term) => !normalizedContext.includes(normalizeText(term)));
      if (missing.length > 0) {
        addReason(row, "answer_terms_missing", "QA context does not contain every required answer term");
      }
    }
  }
}

function addGlobalQaReasons(rows) {
  const taskIds = new Map();
  const groupSplits = new Map();
  const groupRows = new Map();
  for (const row of rows) {
    const taskId = row.task?.task_id;
    if (typeof taskId === "string") {
      const members = taskIds.get(taskId) || [];
      members.push(row);
      taskIds.set(taskId, members);
    }
    const group = row.task?.metadata?.semantic_group_id;
    const split = row.task?.split;
    if (typeof group === "string" && SPLIT_SET.has(split)) {
      const splits = groupSplits.get(group) || new Set();
      splits.add(split);
      groupSplits.set(group, splits);
      const members = groupRows.get(group) || [];
      members.push(row);
      groupRows.set(group, members);
    }
  }
  for (const members of taskIds.values()) {
    if (members.length > 1) {
      for (const row of members) addReason(row, "duplicate_task_id", "QA task_id is not unique");
    }
  }
  for (const [group, splits] of groupSplits.entries()) {
    if (splits.size > 1) {
      for (const row of groupRows.get(group)) {
        addReason(row, "semantic_group_crosses_splits", "QA semantic_group_id crosses dataset splits");
      }
    }
  }
}

function buildSample(task, snapshot) {
  const taskSha256 = sha256Canonical(task);
  const contextSha256 = sha256(task.context);
  return {
    schema_version: "rdk_sft_sample.v1",
    task_id: task.task_id,
    profile: "qa",
    split: task.split,
    messages: [
      { role: "system", content: QA_SYSTEM },
      { role: "user", content: task.instruction },
      { role: "assistant", content: task.context },
    ],
    tools: [],
    outcome: { status: "success", final_answer: task.context },
    metadata: {
      source: task.metadata.source,
      semantic_group_id: task.metadata.semantic_group_id,
      source_url: task.metadata.source_url,
      generation_method: GENERATION_METHOD,
      task_sha256: taskSha256,
      context_sha256: contextSha256,
      knowledge_snapshot_id: snapshot.snapshotId,
      snapshot_sha256: snapshot.snapshotSha256,
    },
  };
}

function safeRejectedRow(row) {
  const taskId = /^qa_[0-9]{6}$/u.test(row.task?.task_id || "") ? row.task.task_id : undefined;
  return {
    schema_version: "rdk_qa_export_rejection.v1",
    line: row.line,
    ...(taskId ? { task_id: taskId } : {}),
    ...(row.task ? { task_sha256: sha256Canonical(row.task) } : {}),
    reasons: row.reasons.map(({ code, message }) => ({ code, message })),
  };
}

async function writeAtomic(path, body) {
  const temporary = `${path}.tmp-${process.pid}`;
  await writeFile(temporary, body, { encoding: "utf8", flag: "wx" });
  await rename(temporary, path);
}

async function writeJson(path, value) {
  await writeAtomic(path, `${JSON.stringify(value, null, 2)}\n`);
}

async function writeJsonl(path, rows) {
  const body = rows.map((row) => JSON.stringify(row)).join("\n");
  await writeAtomic(path, body ? `${body}\n` : "");
}

function validateWithCanonicalValidator(paths) {
  const validator = resolve(PROJECT_ROOT, "scripts/validate_dataset.py");
  const python = resolve(PROJECT_ROOT, "scripts/python.sh");
  const result = spawnSync(python, [validator, ...paths], {
    cwd: PROJECT_ROOT,
    encoding: "utf8",
    maxBuffer: 16 * 1024 * 1024,
  });
  let audit;
  try {
    audit = JSON.parse(result.stdout);
  } catch {
    fail("schema_validator_failed", "Canonical dataset validator did not return JSON", {
      status: result.status,
      stderr: result.stderr.trim(),
    });
  }
  if (result.status !== 0 || !audit.valid) {
    fail("exported_schema_invalid", "Canonical schema/semantic validation rejected exported QA rows", audit);
  }
  return audit;
}

async function artifactDescriptor(path, rowCount) {
  const body = await readFile(path);
  return {
    path: basename(path),
    sha256: sha256(body),
    bytes: body.byteLength,
    ...(rowCount === undefined ? {} : { rows: rowCount }),
  };
}

function countReasonCodes(rejectedRows) {
  const counts = {};
  for (const row of rejectedRows) {
    for (const reason of row.reasons) counts[reason.code] = (counts[reason.code] || 0) + 1;
  }
  return Object.fromEntries(Object.entries(counts).sort(([left], [right]) => left.localeCompare(right)));
}

export async function exportQaDataset({
  taskFile,
  snapshotPath,
  outputDir,
  expectedQaCount,
}) {
  if (!Number.isInteger(expectedQaCount) || expectedQaCount < 0) {
    fail("invalid_expected_count", "expectedQaCount must be a non-negative integer");
  }
  const tasksPath = resolve(taskFile);
  const destination = resolve(outputDir);
  if (await pathExists(destination)) {
    fail("output_exists", `Refusing to overwrite existing output directory: ${destination}`);
  }

  const snapshot = await loadKnowledgeSnapshot(snapshotPath);
  const taskInput = await readTaskRows(tasksPath);
  const malformedRows = taskInput.rows
    .filter((row) => row.rawError)
    .map((row) => ({ ...row, reasons: [{ code: "invalid_json", message: "Task line is invalid JSON" }] }));
  const qaRows = taskInput.rows
    .filter((row) => !row.rawError && row.task?.profile === "qa")
    .map((row) => ({ ...row, reasons: [] }));
  const unknownProfileRows = taskInput.rows
    .filter((row) => !row.rawError && !["qa", "agentic"].includes(row.task?.profile))
    .map((row) => ({
      ...row,
      reasons: [{ code: "invalid_profile", message: "Task profile is neither qa nor agentic" }],
    }));
  const skippedNonQa = taskInput.rows.filter((row) => row.task?.profile === "agentic").length;

  for (const row of qaRows) validateQaTask(row, snapshot.urls);
  addGlobalQaReasons(qaRows);

  const rejectedSourceRows = [...malformedRows, ...unknownProfileRows, ...qaRows.filter((row) => row.reasons.length)]
    .sort((left, right) => left.line - right.line);
  const acceptedSourceRows = qaRows.filter((row) => row.reasons.length === 0);
  const accepted = Object.fromEntries(SPLITS.map((split) => [split, []]));
  for (const row of acceptedSourceRows) {
    const sample = buildSample(row.task, snapshot);
    const secretCodes = matchingSecretCodes(sample);
    if (secretCodes.length > 0) {
      for (const code of secretCodes) {
        addReason(row, "secret_detected", `Exported QA sample matched secret rule ${code}`);
      }
      rejectedSourceRows.push(row);
    } else {
      accepted[row.task.split].push(sample);
    }
  }
  rejectedSourceRows.sort((left, right) => left.line - right.line);
  const rejected = rejectedSourceRows.map(safeRejectedRow);
  if (matchingSecretCodes(rejected).length > 0) {
    fail("rejection_secret_detected", "Sanitized rejected rows still contain a possible secret");
  }

  await mkdir(dirname(destination), { recursive: true });
  const staging = await mkdtemp(resolve(dirname(destination), `.${basename(destination)}.tmp-`));
  let published = false;
  try {
    const splitPaths = Object.fromEntries(SPLITS.map((split) => [split, resolve(staging, `${split}.jsonl`)]));
    for (const split of SPLITS) await writeJsonl(splitPaths[split], accepted[split]);
    const rejectedPath = resolve(staging, "rejected.jsonl");
    await writeJsonl(rejectedPath, rejected);

    const schemaAudit = validateWithCanonicalValidator(SPLITS.map((split) => splitPaths[split]));
    const acceptedCount = SPLITS.reduce((sum, split) => sum + accepted[split].length, 0);
    const reasonCounts = countReasonCodes(rejected);
    const expectedCountPassed = qaRows.length === expectedQaCount;
    const validationAudit = {
      schema_version: "rdk_qa_export_validation_audit.v1",
      valid: rejected.length === 0 && expectedCountPassed && schemaAudit.valid,
      generation_method: GENERATION_METHOD,
      counts: {
        input_rows: taskInput.rows.length,
        qa_candidates: qaRows.length,
        skipped_non_qa: skippedNonQa,
        accepted: acceptedCount,
        rejected: rejected.length,
        train: accepted.train.length,
        validation: accepted.validation.length,
        test: accepted.test.length,
      },
      checks: {
        expected_qa_count: {
          passed: expectedCountPassed,
          expected: expectedQaCount,
          actual: qaRows.length,
        },
        answer_terms: { passed: !reasonCounts.answer_terms_missing && !reasonCounts.invalid_answer_terms },
        source_urls_in_snapshot: {
          passed: !reasonCounts.source_url_not_in_snapshot && !reasonCounts.invalid_source_url,
        },
        unique_task_ids: { passed: !reasonCounts.duplicate_task_id },
        semantic_group_split_isolation: { passed: !reasonCounts.semantic_group_crosses_splits },
        schema_and_canonical_semantics: { passed: schemaAudit.valid },
        secret_scan: { passed: !reasonCounts.secret_detected },
      },
      rejection_reasons: reasonCounts,
      canonical_dataset_validation: schemaAudit,
    };
    const validationAuditPath = resolve(staging, "validation_audit.json");
    await writeJson(validationAuditPath, validationAudit);

    const artifacts = [];
    for (const split of SPLITS) {
      artifacts.push(await artifactDescriptor(splitPaths[split], accepted[split].length));
    }
    artifacts.push(await artifactDescriptor(rejectedPath, rejected.length));
    artifacts.push(await artifactDescriptor(validationAuditPath));
    const manifest = {
      schema_version: "rdk_qa_dataset_manifest.v1",
      valid: validationAudit.valid,
      generation_method: GENERATION_METHOD,
      inputs: {
        task_file: {
          name: basename(tasksPath),
          sha256: taskInput.sha256,
          bytes: taskInput.body.byteLength,
        },
        knowledge_snapshot: {
          snapshot_id: snapshot.snapshotId,
          snapshot_sha256: snapshot.snapshotSha256,
          manifest_sha256: snapshot.manifestSha256,
          url_count: snapshot.urlCount,
          files: snapshot.files,
        },
      },
      counts: validationAudit.counts,
      artifacts,
    };
    await writeJson(resolve(staging, "manifest.json"), manifest);

    if (await pathExists(destination)) {
      fail("output_exists", `Output directory appeared during export: ${destination}`);
    }
    await rename(staging, destination);
    published = true;
    return {
      valid: validationAudit.valid,
      outputDir: destination,
      counts: validationAudit.counts,
      manifest,
    };
  } finally {
    if (!published) await rm(staging, { recursive: true, force: true });
  }
}

function usage() {
  return [
    "Usage:",
    "  node scripts/export_qa_dataset.mjs --tasks FILE --snapshot DIR --output DIR --expected-count N",
  ].join("\n");
}

function parseArgs(argv) {
  const values = {};
  for (let index = 0; index < argv.length; index += 1) {
    const flag = argv[index];
    if (!["--tasks", "--snapshot", "--output", "--expected-count"].includes(flag)) {
      fail("invalid_argument", `Unknown argument: ${flag}`);
    }
    const value = argv[index + 1];
    if (value === undefined) fail("missing_argument", `Missing value for ${flag}`);
    values[flag] = value;
    index += 1;
  }
  if (!values["--tasks"] || !values["--snapshot"] || !values["--output"] || values["--expected-count"] === undefined) {
    fail("missing_argument", usage());
  }
  const expectedQaCount = Number(values["--expected-count"]);
  return {
    taskFile: values["--tasks"],
    snapshotPath: values["--snapshot"],
    outputDir: values["--output"],
    expectedQaCount,
  };
}

async function main() {
  try {
    const result = await exportQaDataset(parseArgs(process.argv.slice(2)));
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
    if (!result.valid) process.exitCode = 2;
  } catch (error) {
    const payload = {
      status: "error",
      code: error instanceof QaExporterError ? error.code : "unexpected_error",
      message: error.message,
      ...(error instanceof QaExporterError && error.details !== undefined ? { details: error.details } : {}),
    };
    process.stderr.write(`${JSON.stringify(payload, null, 2)}\n`);
    process.exitCode = 1;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  await main();
}
