#!/usr/bin/env node
// One-command reproducibility check:
//   1. re-export the QA dataset and the agentic fixture from frozen inputs
//   2. re-validate schema / tool-call causality / split isolation
//   3. byte-compare everything against expected/
//   4. run the unit + negative test suite
//   5. secret / local-path scan over the whole package
// Exits non-zero on the first failure.

import { spawnSync } from "node:child_process";
import { readFileSync, readdirSync, rmSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { exportQaDataset } from "./export_qa_dataset.mjs";
import { exportAgenticFixture } from "./export_agentic_fixture.mjs";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const OUT = resolve(ROOT, "out");

function step(name) {
  process.stdout.write(`\n=== ${name} ===\n`);
}

function run(command, args) {
  const result = spawnSync(command, args, { cwd: ROOT, encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
  if (result.status !== 0) {
    process.stdout.write(result.stdout ?? "");
    process.stderr.write(result.stderr ?? "");
    throw new Error(`${command} ${args.join(" ")} exited with ${result.status}`);
  }
  return result;
}

function listFiles(root, prefix = "") {
  const entries = [];
  for (const entry of readdirSync(join(root, prefix), { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
    const rel = join(prefix, entry.name);
    if (entry.isDirectory()) entries.push(...listFiles(root, rel));
    else entries.push(rel);
  }
  return entries;
}

function compareTrees(actualRoot, expectedRoot) {
  const actual = listFiles(actualRoot);
  const expected = listFiles(expectedRoot);
  const missing = expected.filter((file) => !actual.includes(file));
  const extra = actual.filter((file) => !expected.includes(file));
  if (missing.length || extra.length) {
    throw new Error(`output tree differs from expected/ (missing: ${missing.join(", ") || "none"}; extra: ${extra.join(", ") || "none"})`);
  }
  for (const file of expected) {
    const actualBody = readFileSync(join(actualRoot, file));
    const expectedBody = readFileSync(join(expectedRoot, file));
    if (!actualBody.equals(expectedBody)) {
      throw new Error(`byte mismatch against expected/: ${file}`);
    }
  }
  return expected.length;
}

step("1/5 regenerate outputs from frozen fixtures");
rmSync(OUT, { recursive: true, force: true });
const qa = await exportQaDataset({
  taskFile: resolve(ROOT, "fixtures/qa_tasks.jsonl"),
  snapshotPath: resolve(ROOT, "fixtures/knowledge"),
  outputDir: resolve(OUT, "qa"),
  expectedQaCount: 3,
});
if (!qa.valid) throw new Error("QA export reported valid=false");
process.stdout.write(`qa: ${JSON.stringify(qa.counts)}\n`);
await exportAgenticFixture({
  fixturePath: "fixtures/native_pi_trace.fixture.json",
  outputDir: "out/agentic",
});
process.stdout.write("agentic: 1 sample exported\n");

step("2/5 independent re-validation");
run("scripts/python.sh", [
  "scripts/validate_dataset.py",
  "out/qa/train.jsonl", "out/qa/validation.jsonl", "out/qa/test.jsonl",
  "--audit", "out/qa/independent_revalidation.json",
]);
run("scripts/python.sh", [
  "scripts/validate_native_pi_dataset.py",
  "out/agentic/sample.jsonl",
  "--schema", "schemas/rdk_sft_sample.v1.schema.json",
  "--scan-root", "out/agentic",
  "--audit", "out/agentic/validation_audit.json",
]);
process.stdout.write("validators: OK\n");

step("3/5 byte-for-byte comparison against expected/");
const compared = compareTrees(OUT, resolve(ROOT, "expected"));
process.stdout.write(`deterministic: ${compared} files identical\n`);

step("4/5 unit + negative tests");
const testFiles = readdirSync(resolve(ROOT, "test"))
  .filter((name) => name.endsWith(".test.mjs"))
  .sort()
  .map((name) => join("test", name));
run(process.execPath, ["--test", ...testFiles]);
process.stdout.write("tests: OK\n");

step("5/5 secret / local-path scan");
run("scripts/python.sh", [
  "scripts/scan_tree.py", ".",
  // The scanner defines the forbidden literals; the tests inject fake
  // credentials on purpose to prove the fail-closed path. Nothing else is exempt.
  "--allow-file", "scripts/scan_tree.py",
  "--allow-file", "test/qa_exporter.test.mjs",
  "--allow-file", "test/demo.test.mjs",
]);
process.stdout.write("scan: clean\n");

process.stdout.write("\nALL CHECKS PASSED\n");
