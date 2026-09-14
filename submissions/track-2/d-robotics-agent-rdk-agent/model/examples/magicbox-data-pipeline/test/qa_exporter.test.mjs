import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import test from "node:test";

import {
  GENERATION_METHOD,
  QA_SYSTEM,
  QaExporterError,
  exportQaDataset,
} from "../scripts/export_qa_dataset.mjs";

function hash(value) {
  return createHash("sha256").update(value).digest("hex");
}

function writeJsonl(path, rows) {
  const body = rows.map((row) => JSON.stringify(row)).join("\n");
  writeFileSync(path, body ? `${body}\n` : "", "utf8");
}

function makeSnapshot(root) {
  const snapshot = resolve(root, "snapshot");
  mkdirSync(snapshot, { recursive: true });
  const pages = `${JSON.stringify({
    schema_version: "magicbox_knowledge_page.v1",
    url: "https://docs.example.test/page-a",
    text: "Alpha",
  })}\n`;
  const chunks = `${JSON.stringify({
    schema_version: "magicbox_knowledge_chunk.v1",
    url: "https://docs.example.test/page-b",
    text: "Beta",
  })}\n`;
  writeFileSync(resolve(snapshot, "pages.jsonl"), pages, "utf8");
  writeFileSync(resolve(snapshot, "chunks.jsonl"), chunks, "utf8");
  writeFileSync(
    resolve(snapshot, "manifest.json"),
    `${JSON.stringify({
      schema_version: "magicbox_knowledge_snapshot.v1",
      snapshot_id: "snapshot-fixture-v1",
      start_url: "https://docs.example.test/page-c",
      pages_jsonl: "pages.jsonl",
      pages_jsonl_sha256: hash(pages),
      chunks_jsonl: "chunks.jsonl",
      chunks_jsonl_sha256: hash(chunks),
    }, null, 2)}\n`,
    "utf8",
  );
  return snapshot;
}

function qaTask({
  id,
  split,
  group,
  url = "https://docs.example.test/page-a",
  context = "答案包含 Alpha。",
  terms = ["Alpha"],
}) {
  return {
    schema_version: "rdk_collection_task.v1",
    task_id: id,
    profile: "qa",
    split,
    instruction: `请回答 ${id}。`,
    context,
    allowed_tools: [],
    verifier: { checks: [{ type: "answer_terms", all: terms }] },
    metadata: {
      source: "doc_grounded_qa",
      semantic_group_id: group,
      source_url: url,
      category: "fixture-only",
    },
  };
}

function readJson(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

function readJsonl(path) {
  return readFileSync(path, "utf8")
    .split(/\r?\n/u)
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

test("deterministically exports QA context as a canonical three-message sample", async () => {
  const root = mkdtempSync(resolve(tmpdir(), "qa-exporter-happy-"));
  try {
    const snapshot = makeSnapshot(root);
    const taskFile = resolve(root, "tasks.jsonl");
    const tasks = [
      qaTask({ id: "qa_000001", split: "train", group: "group-a" }),
      qaTask({
        id: "qa_000002",
        split: "validation",
        group: "group-b",
        url: "https://docs.example.test/page-b/",
        context: "答案包含 Beta。",
        terms: ["Beta"],
      }),
      qaTask({
        id: "qa_000003",
        split: "test",
        group: "group-c",
        url: "https://docs.example.test/page-c",
        context: "答案包含 Gamma。",
        terms: ["Gamma"],
      }),
      {
        schema_version: "rdk_collection_task.v1",
        task_id: "agent_000001",
        profile: "agentic",
      },
    ];
    writeJsonl(taskFile, tasks);
    const output = resolve(root, "dataset");

    const result = await exportQaDataset({
      taskFile,
      snapshotPath: snapshot,
      outputDir: output,
      expectedQaCount: 3,
    });

    assert.equal(result.valid, true);
    const train = readJsonl(resolve(output, "train.jsonl"));
    assert.equal(train.length, 1);
    assert.deepEqual(train[0].messages, [
      { role: "system", content: QA_SYSTEM },
      { role: "user", content: tasks[0].instruction },
      { role: "assistant", content: tasks[0].context },
    ]);
    assert.deepEqual(train[0].tools, []);
    assert.deepEqual(train[0].outcome, { status: "success", final_answer: tasks[0].context });
    assert.deepEqual(Object.keys(train[0].metadata), [
      "source",
      "semantic_group_id",
      "source_url",
      "generation_method",
      "task_sha256",
      "context_sha256",
      "knowledge_snapshot_id",
      "snapshot_sha256",
    ]);
    assert.equal(train[0].metadata.generation_method, GENERATION_METHOD);
    assert.match(train[0].metadata.task_sha256, /^[a-f0-9]{64}$/u);
    assert.equal(train[0].metadata.context_sha256, hash(tasks[0].context));
    assert.equal(readJsonl(resolve(output, "validation.jsonl")).length, 1);
    assert.equal(readJsonl(resolve(output, "test.jsonl")).length, 1);
    assert.deepEqual(readJsonl(resolve(output, "rejected.jsonl")), []);

    const audit = readJson(resolve(output, "validation_audit.json"));
    assert.equal(audit.valid, true);
    assert.deepEqual(audit.counts, {
      input_rows: 4,
      qa_candidates: 3,
      skipped_non_qa: 1,
      accepted: 3,
      rejected: 0,
      train: 1,
      validation: 1,
      test: 1,
    });
    assert.equal(audit.canonical_dataset_validation.valid, true);
    const manifest = readJson(resolve(output, "manifest.json"));
    assert.equal(manifest.valid, true);
    assert.equal(manifest.inputs.knowledge_snapshot.snapshot_id, "snapshot-fixture-v1");
    assert.equal(manifest.artifacts.length, 5);
    assert.deepEqual(
      manifest.artifacts.map((artifact) => artifact.path),
      ["train.jsonl", "validation.jsonl", "test.jsonl", "rejected.jsonl", "validation_audit.json"],
    );

    const secondOutput = resolve(root, "dataset-second-pass");
    const secondResult = await exportQaDataset({
      taskFile,
      snapshotPath: snapshot,
      outputDir: secondOutput,
      expectedQaCount: 3,
    });
    assert.equal(secondResult.valid, true);
    for (const name of [
      "train.jsonl",
      "validation.jsonl",
      "test.jsonl",
      "rejected.jsonl",
      "validation_audit.json",
      "manifest.json",
    ]) {
      assert.deepEqual(readFileSync(resolve(output, name)), readFileSync(resolve(secondOutput, name)));
    }
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("rejects answer, provenance, duplicate, split-leakage, and secret failures without leaking secrets", async () => {
  const root = mkdtempSync(resolve(tmpdir(), "qa-exporter-reject-"));
  try {
    const snapshot = makeSnapshot(root);
    const taskFile = resolve(root, "tasks.jsonl");
    const tasks = [
      qaTask({ id: "qa_000011", split: "train", group: "good" }),
      qaTask({
        id: "qa_000012",
        split: "validation",
        group: "bad-answer",
        context: "这里没有要求的词。",
      }),
      qaTask({
        id: "qa_000013",
        split: "test",
        group: "bad-url",
        url: "https://docs.example.test/not-frozen",
      }),
      qaTask({ id: "qa_000014", split: "train", group: "duplicate-a" }),
      qaTask({ id: "qa_000014", split: "train", group: "duplicate-b" }),
      qaTask({
        id: "qa_000015",
        split: "train",
        group: "secret",
        context: "答案包含 Alpha，api_key=sk-supersecretfixture000000。",
      }),
      qaTask({ id: "qa_000016", split: "train", group: "cross-split" }),
      qaTask({ id: "qa_000017", split: "test", group: "cross-split" }),
    ];
    writeJsonl(taskFile, tasks);
    const output = resolve(root, "dataset");
    const result = await exportQaDataset({
      taskFile,
      snapshotPath: snapshot,
      outputDir: output,
      expectedQaCount: 8,
    });

    assert.equal(result.valid, false);
    assert.equal(readJsonl(resolve(output, "train.jsonl")).length, 1);
    assert.equal(readJsonl(resolve(output, "validation.jsonl")).length, 0);
    assert.equal(readJsonl(resolve(output, "test.jsonl")).length, 0);
    const rejectedBody = readFileSync(resolve(output, "rejected.jsonl"), "utf8");
    assert.equal(rejectedBody.includes("supersecretfixture"), false);
    const rejected = readJsonl(resolve(output, "rejected.jsonl"));
    assert.equal(rejected.length, 7);
    const reasonCodes = new Set(rejected.flatMap((row) => row.reasons.map((reason) => reason.code)));
    assert.equal(reasonCodes.has("answer_terms_missing"), true);
    assert.equal(reasonCodes.has("source_url_not_in_snapshot"), true);
    assert.equal(reasonCodes.has("duplicate_task_id"), true);
    assert.equal(reasonCodes.has("secret_detected"), true);
    assert.equal(reasonCodes.has("semantic_group_crosses_splits"), true);
    const audit = readJson(resolve(output, "validation_audit.json"));
    assert.equal(audit.valid, false);
    assert.equal(audit.checks.expected_qa_count.passed, true);
    assert.equal(audit.canonical_dataset_validation.valid, true);
    assert.equal(readJson(resolve(output, "manifest.json")).valid, false);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("fails atomically on a tampered snapshot and refuses an existing output directory", async () => {
  const root = mkdtempSync(resolve(tmpdir(), "qa-exporter-atomic-"));
  try {
    const snapshot = makeSnapshot(root);
    const taskFile = resolve(root, "tasks.jsonl");
    writeJsonl(taskFile, [qaTask({ id: "qa_000021", split: "train", group: "group-a" })]);

    writeFileSync(resolve(snapshot, "chunks.jsonl"), "tampered\n", "utf8");
    const tamperedOutput = resolve(root, "tampered-output");
    await assert.rejects(
      exportQaDataset({
        taskFile,
        snapshotPath: snapshot,
        outputDir: tamperedOutput,
        expectedQaCount: 1,
      }),
      (error) => error instanceof QaExporterError && error.code === "snapshot_hash_mismatch",
    );
    assert.throws(() => readFileSync(resolve(tamperedOutput, "manifest.json")), { code: "ENOENT" });

    const existingOutput = resolve(root, "already-there");
    mkdirSync(existingOutput);
    await assert.rejects(
      exportQaDataset({
        taskFile,
        snapshotPath: snapshot,
        outputDir: existingOutput,
        expectedQaCount: 1,
      }),
      (error) => error instanceof QaExporterError && error.code === "output_exists",
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
