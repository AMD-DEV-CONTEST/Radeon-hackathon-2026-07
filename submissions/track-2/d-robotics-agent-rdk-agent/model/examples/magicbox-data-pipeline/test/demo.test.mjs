// Negative-path tests over the frozen demo fixtures: prove the pipeline
// fails closed on tampered snapshots, missing evidence, orphan tool results
// and injected secrets, and that the blessed outputs equal expected/.

import assert from "node:assert/strict";
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { QaExporterError, exportQaDataset } from "../scripts/export_qa_dataset.mjs";
import { NativePiExportError, exportNativePiSample } from "../src/native_pi_export.mjs";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function loadFixture() {
  return JSON.parse(readFileSync(resolve(ROOT, "fixtures/native_pi_trace.fixture.json"), "utf8"));
}

function exportFromFixture(fixture) {
  return exportNativePiSample({
    task: fixture.task,
    providerPayloads: fixture.providerPayloads,
    piMessages: fixture.piMessages,
    policyAudit: fixture.policyAudit,
    boardEvidence: fixture.boardEvidence,
    metadata: fixture.metadata,
  });
}

test("the frozen agentic fixture exports to exactly the blessed expected sample", () => {
  const { sample } = exportFromFixture(loadFixture());
  const expected = JSON.parse(readFileSync(resolve(ROOT, "expected/agentic/sample.jsonl"), "utf8"));
  assert.deepEqual(sample, expected);
});

test("a tampered knowledge snapshot is rejected before any QA row is exported", async (t) => {
  const temporary = mkdtempSync(resolve(tmpdir(), "magicbox-demo-tamper-"));
  t.after(() => rmSync(temporary, { recursive: true, force: true }));
  const snapshot = resolve(temporary, "knowledge");
  cpSync(resolve(ROOT, "fixtures/knowledge"), snapshot, { recursive: true });
  const chunksPath = resolve(snapshot, "chunks.jsonl");
  writeFileSync(chunksPath, `${readFileSync(chunksPath, "utf8")}{"tampered":true}\n`, "utf8");
  await assert.rejects(
    exportQaDataset({
      taskFile: resolve(ROOT, "fixtures/qa_tasks.jsonl"),
      snapshotPath: snapshot,
      outputDir: resolve(temporary, "out"),
      expectedQaCount: 3,
    }),
    (error) => error instanceof QaExporterError && error.code === "snapshot_hash_mismatch",
  );
});

test("a QA task whose source_url is outside the frozen snapshot is rejected", async (t) => {
  const temporary = mkdtempSync(resolve(tmpdir(), "magicbox-demo-url-"));
  t.after(() => rmSync(temporary, { recursive: true, force: true }));
  const lines = readFileSync(resolve(ROOT, "fixtures/qa_tasks.jsonl"), "utf8").trim().split("\n");
  const first = JSON.parse(lines[0]);
  first.metadata.source_url = "https://example.invalid/not-in-snapshot";
  const tasksPath = resolve(temporary, "tasks.jsonl");
  writeFileSync(tasksPath, [JSON.stringify(first), ...lines.slice(1)].join("\n") + "\n", "utf8");
  const result = await exportQaDataset({
    taskFile: tasksPath,
    snapshotPath: resolve(ROOT, "fixtures/knowledge"),
    outputDir: resolve(temporary, "out"),
    expectedQaCount: 3,
  });
  assert.equal(result.valid, false);
  assert.equal(result.counts.rejected, 1);
  assert.equal(result.counts.accepted, 2);
});

test("a bash call without independent board evidence is rejected", () => {
  const fixture = loadFixture();
  fixture.boardEvidence = [];
  assert.throws(
    () => exportFromFixture(fixture),
    (error) => error instanceof NativePiExportError && error.code === "board_evidence_count",
  );
});

test("an orphan tool result in provider history is rejected", () => {
  const fixture = loadFixture();
  fixture.providerPayloads.at(-1).messages.push({
    role: "tool",
    tool_call_id: "call_orphan_999",
    content: "orphan output",
  });
  assert.throws(
    () => exportFromFixture(fixture),
    (error) => error instanceof NativePiExportError && error.code === "orphan_tool_result",
  );
});

test("an injected credential anywhere in the trace is rejected", () => {
  const fixture = loadFixture();
  fixture.metadata.note = "api_key=sk-" + "a".repeat(24);
  assert.throws(
    () => exportFromFixture(fixture),
    (error) => error instanceof NativePiExportError && error.code === "secret_detected",
  );
});
