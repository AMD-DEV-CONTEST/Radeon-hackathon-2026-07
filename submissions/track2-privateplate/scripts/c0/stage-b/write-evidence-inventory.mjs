#!/usr/bin/env node
/**
 * Walk the current C0-B evidence directory and write a SHA-256 inventory.
 * Independent of the collector's own PASS claim.
 */
import { createHash } from "node:crypto";
import {
  access,
  mkdir,
  readdir,
  readFile,
  stat,
  writeFile
} from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { resolveC0bOutDir } from "./resolve-out-dir.mjs";

const root = fileURLToPath(new URL("../../../", import.meta.url));
const outDir = resolveC0bOutDir(root);
const rawDir = path.join(outDir, "raw");
await mkdir(rawDir, { recursive: true });

async function walk(dir, base = dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const abs = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...(await walk(abs, base)));
      continue;
    }
    if (!entry.isFile()) continue;
    const rel = path.relative(base, abs).split(path.sep).join("/");
    // These two files seal the catalog and must not become stale inputs when
    // the inventory command is re-run.
    if (
      rel === "raw/evidence-inventory.json" ||
      rel === "raw/evidence-inventory.sha256.json"
    ) {
      continue;
    }
    const st = await stat(abs);
    const buf = await readFile(abs);
    const sha256 = createHash("sha256").update(buf).digest("hex");
    files.push({
      path: rel,
      size_bytes: st.size,
      sha256,
      mtime_utc: st.mtime.toISOString()
    });
  }
  return files;
}

let files = [];
try {
  await access(outDir);
  files = await walk(outDir);
} catch (error) {
  files = [];
  console.error(`evidence inventory walk failed: ${error?.message ?? error}`);
}

files.sort((a, b) => a.path.localeCompare(b.path));

const catalogSha = createHash("sha256")
  .update(
    files.map((f) => `${f.path}\t${f.size_bytes}\t${f.sha256}`).join("\n")
  )
  .digest("hex");

const requiredHints = [
  "environment.json",
  "raw/failure-summary.json",
  "raw/vllm-stop.json",
  "raw/run-all.log"
];
const present = new Set(files.map((f) => f.path));
const missing_recommended = requiredHints.filter((p) => !present.has(p));

const payload = {
  schema_version: "1.0",
  stage: "C0-B",
  phase: "EVIDENCE_INVENTORY",
  run_id: process.env.PRIVATEPLATE_RUN_ID ?? path.basename(outDir),
  out_dir: outDir,
  written_at_utc: new Date().toISOString(),
  file_count: files.length,
  total_bytes: files.reduce((sum, f) => sum + f.size_bytes, 0),
  catalog_sha256: catalogSha,
  missing_recommended,
  files,
  destroy_reminder:
    "Inventory records collected files and checksums. The current Global free-instance workflow does not require Destroy or credit receipts.",
  claim_boundary:
    "This inventory only hashes files on disk for the current run directory. It does not score tools or invent PASS."
};

const outPath = path.join(rawDir, "evidence-inventory.json");
await writeFile(outPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");

// Second pass including inventory itself for final sealed catalog is optional;
// write a sidecar digest for the inventory file alone.
const invBuf = await readFile(outPath);
const invSha = createHash("sha256").update(invBuf).digest("hex");
const seal = {
  schema_version: "1.0",
  inventory_path: "raw/evidence-inventory.json",
  inventory_sha256: invSha,
  inventory_size_bytes: invBuf.length,
  catalog_sha256_excluding_self: catalogSha,
  sealed_at_utc: new Date().toISOString()
};
await writeFile(
  path.join(rawDir, "evidence-inventory.sha256.json"),
  `${JSON.stringify(seal, null, 2)}\n`,
  "utf8"
);

console.log(
  JSON.stringify(
    {
      status: "PASS",
      wrote: outPath,
      file_count: payload.file_count,
      total_bytes: payload.total_bytes,
      catalog_sha256: catalogSha,
      inventory_sha256: invSha,
      missing_recommended
    },
    null,
    2
  )
);
