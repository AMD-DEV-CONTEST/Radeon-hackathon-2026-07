import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { promisify } from "node:util";
import {
  createSourceManifest,
  verifyRecordedSource,
  verifySourceIntegrity
} from "./source-integrity.mjs";

const COMMIT = "0123456789abcdef0123456789abcdef01234567";
const execFileAsync = promisify(execFile);

test("packed source manifest detects source changes but ignores build and evidence trees", async () => {
  const root = await createFixture();
  try {
    const created = await createSourceManifest(root, COMMIT);
    const verified = await verifySourceIntegrity({
      root,
      expectedCommit: COMMIT,
      mode: "packed_clean_commit"
    });
    assert.deepEqual(verified, created);

    await mkdir(path.join(root, "packages/demo/dist"), { recursive: true });
    await writeFile(path.join(root, "packages/demo/dist/index.js"), "built\n");
    await mkdir(
      path.join(root, "benchmarks/c0/stage-b/privateplate-v2/raw"),
      { recursive: true }
    );
    await mkdir(
      path.join(
        root,
        "benchmarks/c0/stage-b/privateplate-gemma4-20260726T120000Z/raw"
      ),
      { recursive: true }
    );
    await writeFile(
      path.join(
        root,
        "benchmarks/c0/stage-b/privateplate-gemma4-20260726T120000Z/tool-calling.jsonl"
      ),
      "{}\n"
    );
    const environmentPath = path.join(
      root,
      "benchmarks/c0/stage-b/privateplate-v2/environment.json"
    );
    await writeFile(
      environmentPath,
      `${JSON.stringify({
        git_commit: COMMIT,
        source_provenance: "packed_clean_commit",
        source_integrity_verified: true,
        source_integrity_mode: created.mode,
        source_manifest_sha256: created.manifest_sha256,
        source_file_count: created.file_count
      })}\n`
    );
    assert.equal(
      (await verifyRecordedSource(root, environmentPath)).verified,
      true
    );

    await writeFile(path.join(root, "packages/demo/src.ts"), "changed\n");
    await assert.rejects(
      verifyRecordedSource(root, environmentPath),
      /Packed source changed/
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("packed source manifest rejects added source files", async () => {
  const root = await createFixture();
  try {
    await createSourceManifest(root, COMMIT);
    await writeFile(path.join(root, "unexpected.ts"), "export {};\n");
    await assert.rejects(
      verifySourceIntegrity({
        root,
        expectedCommit: COMMIT,
        mode: "packed_clean_commit"
      }),
      /file set changed/
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("git source verification ignores legacy and dynamic privateplate-* evidence dirs", async () => {
  const root = await createFixture();
  try {
    await execFileAsync("git", ["init", "--quiet"], { cwd: root });
    await execFileAsync("git", ["add", "."], { cwd: root });
    await execFileAsync(
      "git",
      [
        "-c",
        "user.name=PrivatePlate Test",
        "-c",
        "user.email=privateplate@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "fixture"
      ],
      { cwd: root }
    );
    const { stdout } = await execFileAsync("git", ["rev-parse", "HEAD"], {
      cwd: root
    });
    const commit = stdout.trim();
    assert.equal(
      (
        await verifySourceIntegrity({
          root,
          expectedCommit: commit,
          mode: "git"
        })
      ).verified,
      true
    );

    const legacyDir = path.join(
      root,
      "benchmarks/c0/stage-b/privateplate-v2"
    );
    const dynamicDir = path.join(
      root,
      "benchmarks/c0/stage-b/privateplate-gemma4-20260726T000000Z"
    );
    await mkdir(path.join(legacyDir, "raw"), { recursive: true });
    await mkdir(path.join(dynamicDir, "raw"), { recursive: true });
    await writeFile(path.join(legacyDir, "environment.json"), "{}\n");
    await writeFile(path.join(dynamicDir, "environment.json"), "{}\n");
    await writeFile(path.join(dynamicDir, "tool-calling.jsonl"), "{}\n");
    assert.equal(
      (
        await verifySourceIntegrity({
          root,
          expectedCommit: commit,
          mode: "git"
        })
      ).verified,
      true
    );

    await writeFile(path.join(root, "packages/demo/src.ts"), "changed\n");
    await assert.rejects(
      verifySourceIntegrity({
        root,
        expectedCommit: commit,
        mode: "git"
      }),
      /Git source tree changed/
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

async function createFixture() {
  const root = await mkdtemp(path.join(os.tmpdir(), "privateplate-source-"));
  await mkdir(path.join(root, "packages/demo"), { recursive: true });
  await writeFile(path.join(root, "packages/demo/src.ts"), "export {};\n");
  await writeFile(
    path.join(root, "PRIVATEPLATE_SOURCE_PROVENANCE.json"),
    `${JSON.stringify({ git_commit: COMMIT, git_dirty: false })}\n`
  );
  return root;
}
