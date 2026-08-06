#!/usr/bin/env node
import { createHash } from "node:crypto";
import { readFile, writeFile, readdir, stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../../", import.meta.url));
const fixturesRoot = path.join(root, "fixtures");

const SKIP = new Set(["MANIFEST.json"]);

async function listFiles(dir, relBase = "") {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    if (entry.name.startsWith(".")) continue;
    const abs = path.join(dir, entry.name);
    const rel = path.join(relBase, entry.name);
    if (entry.isDirectory()) {
      files.push(...(await listFiles(abs, rel)));
    } else if (entry.isFile() && !SKIP.has(entry.name)) {
      files.push(rel.split(path.sep).join("/"));
    }
  }
  return files;
}

const relativeFiles = (await listFiles(fixturesRoot)).sort();
const fileEntries = [];

for (const rel of relativeFiles) {
  const abs = path.join(fixturesRoot, rel);
  const bytes = await readFile(abs);
  const sha256 = createHash("sha256").update(bytes).digest("hex");
  const size = (await stat(abs)).size;
  fileEntries.push({
    path: `fixtures/${rel}`,
    sha256,
    bytes: size
  });
}

const manifest = {
  schemaVersion: "1.0.0",
  generatedAtUtc: new Date().toISOString(),
  claimBoundary:
    "Checksums for offline fixture integrity. Synthetic demo data only; not clinical datasets.",
  licenses: [
    {
      id: "lic-privateplate-synthetic-1",
      name: "PrivatePlate Synthetic Demo License 1.0",
      path: "fixtures/LICENSES/PRIVATEPLATE_SYNTHETIC_DEMO_1.0.txt",
      allowsPublicRedistribution: true,
      notes: "Original synthetic demo fixtures authored for this hackathon repository."
    }
  ],
  sources: [
    {
      id: "src-synthetic-demo",
      author: "PrivatePlate hackathon team",
      description: "Synthetic household, foods, templates, and knowledge cards for P0 demo.",
      modified: false,
      allowsPublicRedistribution: true
    }
  ],
  files: fileEntries
};

const outPath = path.join(fixturesRoot, "MANIFEST.json");
await writeFile(outPath, JSON.stringify(manifest, null, 2) + "\n", "utf8");
console.log(
  JSON.stringify(
    {
      wrote: "fixtures/MANIFEST.json",
      fileCount: fileEntries.length
    },
    null,
    2
  )
);
