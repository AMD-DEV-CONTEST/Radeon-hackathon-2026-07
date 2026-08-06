import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {
  assertLoopbackProvider,
  assertVerifiedRadeonEnvironment
} from "./evidence-guard.mjs";

test("vLLM evidence endpoint must use HTTP loopback", () => {
  assert.equal(assertLoopbackProvider("http://127.0.0.1:8000/v1"), "127.0.0.1");
  assert.equal(assertLoopbackProvider("http://localhost:8000/v1"), "localhost");
  assert.equal(assertLoopbackProvider("http://[::1]:8000/v1"), "[::1]");
  assert.throws(
    () => assertLoopbackProvider("http://0.0.0.0:8000/v1"),
    /HTTP loopback/
  );
  assert.throws(
    () => assertLoopbackProvider("https://127.0.0.1:8000/v1"),
    /HTTP loopback/
  );
});

test("Radeon environment requires re-checkable source integrity", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "privateplate-env-"));
  const environmentPath = path.join(directory, "environment.json");
  const environment = {
    evidence_eligible: true,
    gpu_name: "AMD Radeon Graphics",
    driver: "6.14.14",
    rocm_verified: true,
    node_preflight: "PASS",
    node_version: "v22.13.0",
    git_commit: "0123456789abcdef0123456789abcdef01234567",
    git_dirty: false,
    source_provenance: "packed_clean_commit",
    source_integrity_verified: true,
    source_integrity_mode: "packed_manifest",
    source_manifest_sha256: "a".repeat(64),
    source_file_count: 42
  };
  try {
    await writeFile(environmentPath, `${JSON.stringify(environment)}\n`);
    assert.equal(
      (await assertVerifiedRadeonEnvironment(environmentPath)).gpu_name,
      "AMD Radeon Graphics"
    );

    await writeFile(
      environmentPath,
      `${JSON.stringify({
        ...environment,
        source_integrity_verified: false
      })}\n`
    );
    await assert.rejects(
      assertVerifiedRadeonEnvironment(environmentPath),
      /re-checkable source integrity/
    );
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
