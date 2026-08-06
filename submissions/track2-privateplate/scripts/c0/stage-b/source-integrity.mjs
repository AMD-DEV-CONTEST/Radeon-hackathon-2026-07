#!/usr/bin/env node
import { createHash } from "node:crypto";
import { execFile } from "node:child_process";
import {
  lstat,
  readFile,
  readdir,
  realpath,
  writeFile
} from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const MANIFEST_NAME = "PRIVATEPLATE_SOURCE_MANIFEST.json";
/** Legacy fixed evidence root (still protected/excluded). */
const LEGACY_EVIDENCE_ROOT = "benchmarks/c0/stage-b/privateplate-v2";
/**
 * All formal C0-B run directories use PRIVATEPLATE_RUN_ID under this prefix.
 * Dynamic runs (privateplate-gemma4-..., privateplate-qwen14-..., etc.) must
 * not dirty git provenance checks mid-collection.
 */
const EVIDENCE_RUN_PREFIX = "benchmarks/c0/stage-b/privateplate-";
const LEGACY_STAGE_B_RAW = "benchmarks/c0/stage-b/raw";

export async function createSourceManifest(root, gitCommit) {
  assertCommit(gitCommit);
  const files = await collectSourceFiles(root);
  const entries = await Promise.all(
    files.map(async (relativePath) => ({
      path: relativePath,
      sha256: sha256(await readFile(path.join(root, relativePath)))
    }))
  );
  const manifest = {
    schema_version: "1.0",
    git_commit: gitCommit,
    files: entries
  };
  const manifestText = `${JSON.stringify(manifest, null, 2)}\n`;
  await writeFile(path.join(root, MANIFEST_NAME), manifestText, "utf8");
  return summarizeManifest(manifestText, manifest, "packed_manifest");
}

export async function verifySourceIntegrity({
  root,
  expectedCommit,
  mode
}) {
  assertCommit(expectedCommit);
  if (mode === "git") {
    return verifyGitSource(root, expectedCommit);
  }
  if (mode === "packed_clean_commit") {
    return verifyPackedSource(root, expectedCommit);
  }
  throw new Error(`Unsupported source provenance mode: ${mode}`);
}

export async function verifyRecordedSource(root, environmentPath) {
  const environment = JSON.parse(await readFile(environmentPath, "utf8"));
  if (environment.source_integrity_verified !== true) {
    throw new Error("Environment evidence has no verified source integrity.");
  }
  const result = await verifySourceIntegrity({
    root,
    expectedCommit: environment.git_commit,
    mode: environment.source_provenance
  });
  const matchesRecordedEvidence =
    result.mode === environment.source_integrity_mode &&
    result.file_count === environment.source_file_count &&
    result.manifest_sha256 ===
      (environment.source_manifest_sha256 ?? null);
  if (!matchesRecordedEvidence) {
    throw new Error("Current source no longer matches environment evidence.");
  }
  return result;
}

/**
 * True for generated C0-B evidence trees that must not affect source cleanliness.
 * Matches legacy privateplate-v2, attempt archives, and any privateplate-* run id.
 */
export function isGeneratedEvidencePath(relativePath) {
  const normalized = relativePath.split(path.sep).join("/");
  if (
    normalized === LEGACY_EVIDENCE_ROOT ||
    normalized.startsWith(`${LEGACY_EVIDENCE_ROOT}/`)
  ) {
    return true;
  }
  if (
    normalized === LEGACY_STAGE_B_RAW ||
    normalized.startsWith(`${LEGACY_STAGE_B_RAW}/`)
  ) {
    return true;
  }
  if (
    normalized === EVIDENCE_RUN_PREFIX.slice(0, -1) ||
    normalized.startsWith(EVIDENCE_RUN_PREFIX)
  ) {
    // Only the run directories themselves, not scripts under stage-b.
    // EVIDENCE_RUN_PREFIX is benchmarks/c0/stage-b/privateplate-
    // so scripts/c0/stage-b/*.mjs are NOT matched.
    return true;
  }
  return false;
}

async function verifyGitSource(root, expectedCommit) {
  const [{ stdout: topLevel }, { stdout: head }, { stdout: status }] =
    await Promise.all([
      execFileAsync("git", ["-C", root, "rev-parse", "--show-toplevel"]),
      execFileAsync("git", ["-C", root, "rev-parse", "HEAD"]),
      execFileAsync("git", [
        "-C",
        root,
        "status",
        "--porcelain",
        "--untracked-files=all",
        "--",
        ".",
        // Legacy fixed tree
        `:(exclude)${LEGACY_EVIDENCE_ROOT}`,
        `:(exclude)${LEGACY_EVIDENCE_ROOT}/**`,
        // Any dynamic privateplate-* run id under stage-b
        ":(exclude)benchmarks/c0/stage-b/privateplate-*",
        ":(exclude)benchmarks/c0/stage-b/privateplate-*/**",
        // Legacy raw capture dir
        `:(exclude)${LEGACY_STAGE_B_RAW}`,
        `:(exclude)${LEGACY_STAGE_B_RAW}/**`
      ])
    ]);
  const [resolvedRoot, resolvedTopLevel] = await Promise.all([
    realpath(root),
    realpath(topLevel.trim())
  ]);
  if (resolvedRoot !== resolvedTopLevel) {
    throw new Error("Git provenance must belong to the PrivatePlate project root.");
  }
  if (head.trim() !== expectedCommit) {
    throw new Error("Git HEAD changed after the source provenance check.");
  }
  if (status.trim()) {
    throw new Error("Git source tree changed after the source provenance check.");
  }
  const { stdout: trackedFiles } = await execFileAsync("git", [
    "-C",
    root,
    "ls-files",
    "-z"
  ]);
  return {
    verified: true,
    mode: "git",
    git_commit: expectedCommit,
    manifest_sha256: null,
    file_count: trackedFiles.split("\0").filter(Boolean).length
  };
}

async function verifyPackedSource(root, expectedCommit) {
  const manifestPath = path.join(root, MANIFEST_NAME);
  const manifestText = await readFile(manifestPath, "utf8");
  const manifest = JSON.parse(manifestText);
  validateManifest(manifest, expectedCommit);

  const currentFiles = await collectSourceFiles(root);
  const expectedPaths = manifest.files.map((entry) => entry.path);
  if (
    currentFiles.length !== expectedPaths.length ||
    currentFiles.some((file, index) => file !== expectedPaths[index])
  ) {
    throw new Error(
      "Packed source file set changed after the archive was created."
    );
  }

  for (const entry of manifest.files) {
    const actualHash = sha256(await readFile(path.join(root, entry.path)));
    if (actualHash !== entry.sha256) {
      throw new Error(`Packed source changed: ${entry.path}`);
    }
  }
  return summarizeManifest(manifestText, manifest, "packed_manifest");
}

async function collectSourceFiles(root) {
  const files = [];
  await walk(root, "", files);
  return files.sort(comparePaths);
}

async function walk(root, relativeDirectory, files) {
  const absoluteDirectory = path.join(root, relativeDirectory);
  const entries = await readdir(absoluteDirectory, { withFileTypes: true });
  entries.sort((left, right) => comparePaths(left.name, right.name));

  for (const entry of entries) {
    const relativePath = path.posix.join(relativeDirectory, entry.name);
    if (isExcluded(relativePath)) continue;

    const absolutePath = path.join(root, relativePath);
    const stats = await lstat(absolutePath);
    if (stats.isDirectory()) {
      await walk(root, relativePath, files);
      continue;
    }
    if (!stats.isFile()) {
      throw new Error(`Unsupported source entry: ${relativePath}`);
    }
    files.push(relativePath);
  }
}

function isExcluded(relativePath) {
  const segments = relativePath.split("/");
  return (
    relativePath === MANIFEST_NAME ||
    isGeneratedEvidencePath(relativePath) ||
    segments.includes(".git") ||
    segments.includes("node_modules") ||
    segments.includes("dist") ||
    segments.includes("coverage") ||
    relativePath.endsWith(".tsbuildinfo")
  );
}

function validateManifest(manifest, expectedCommit) {
  if (
    manifest?.schema_version !== "1.0" ||
    manifest.git_commit !== expectedCommit ||
    !Array.isArray(manifest.files) ||
    manifest.files.length === 0
  ) {
    throw new Error("Invalid packed source manifest.");
  }

  let previousPath = null;
  for (const entry of manifest.files) {
    const validPath =
      typeof entry?.path === "string" &&
      entry.path.length > 0 &&
      !path.posix.isAbsolute(entry.path) &&
      !entry.path.split("/").includes("..");
    const validHash =
      typeof entry?.sha256 === "string" &&
      /^[0-9a-f]{64}$/i.test(entry.sha256);
    if (!validPath || !validHash || entry.path <= (previousPath ?? "")) {
      throw new Error("Invalid or unsorted packed source manifest entry.");
    }
    previousPath = entry.path;
  }
}

function summarizeManifest(manifestText, manifest, mode) {
  return {
    verified: true,
    mode,
    git_commit: manifest.git_commit,
    manifest_sha256: sha256(manifestText),
    file_count: manifest.files.length
  };
}

function assertCommit(value) {
  if (!/^[0-9a-f]{40}$/i.test(value ?? "")) {
    throw new Error("Source provenance requires an exact 40-character commit.");
  }
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function comparePaths(left, right) {
  if (left === right) return 0;
  return left < right ? -1 : 1;
}

async function main() {
  const [command, rootArg, commitArg, modeArg] = process.argv.slice(2);
  if (command === "generate" && rootArg && commitArg && !modeArg) {
    console.log(
      JSON.stringify(await createSourceManifest(path.resolve(rootArg), commitArg))
    );
    return;
  }
  if (command === "verify" && rootArg && commitArg && modeArg) {
    console.log(
      JSON.stringify(
        await verifySourceIntegrity({
          root: path.resolve(rootArg),
          expectedCommit: commitArg,
          mode: modeArg
        })
      )
    );
    return;
  }
  if (command === "verify-environment" && rootArg && commitArg && !modeArg) {
    console.log(
      JSON.stringify(
        await verifyRecordedSource(
          path.resolve(rootArg),
          path.resolve(commitArg)
        )
      )
    );
    return;
  }
  throw new Error(
    "Usage: source-integrity.mjs generate <root> <commit> | verify <root> <commit> <git|packed_clean_commit> | verify-environment <root> <environment.json>"
  );
}

if (
  process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  await main();
}
