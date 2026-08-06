#!/usr/bin/env node
// Replays the frozen synthetic native-Pi trace fixture through the real
// exporter (src/native_pi_export.mjs) and writes sample.jsonl, audit.json and
// a rows/bytes/SHA-256 manifest. Fully offline and deterministic.

import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { exportNativePiSample } from "../src/native_pi_export.mjs";

const PROJECT_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function parseArgs(argv) {
  const values = {};
  for (let index = 0; index < argv.length; index += 1) {
    const flag = argv[index];
    if (!["--fixture", "--output"].includes(flag)) {
      throw new Error(`Unknown argument: ${flag}`);
    }
    values[flag] = argv[index + 1];
    index += 1;
  }
  if (!values["--fixture"] || !values["--output"]) {
    throw new Error("Usage: node scripts/export_agentic_fixture.mjs --fixture FILE --output DIR");
  }
  return { fixturePath: values["--fixture"], outputDir: values["--output"] };
}

export async function exportAgenticFixture({ fixturePath, outputDir }) {
  const fixtureBody = await readFile(resolve(PROJECT_ROOT, fixturePath));
  const fixture = JSON.parse(fixtureBody.toString("utf8"));
  const { sample, audit } = exportNativePiSample({
    task: fixture.task,
    providerPayloads: fixture.providerPayloads,
    piMessages: fixture.piMessages,
    piEvents: fixture.piEvents,
    policyAudit: fixture.policyAudit,
    boardEvidence: fixture.boardEvidence,
    metadata: fixture.metadata,
  });

  const destination = resolve(PROJECT_ROOT, outputDir);
  await mkdir(destination, { recursive: true });
  const sampleBody = `${JSON.stringify(sample)}\n`;
  const auditBody = `${JSON.stringify(audit, null, 2)}\n`;
  await writeFile(resolve(destination, "sample.jsonl"), sampleBody, "utf8");
  await writeFile(resolve(destination, "audit.json"), auditBody, "utf8");

  const manifest = {
    schema_version: "magicbox_example_agentic_manifest.v1",
    fixture: { path: fixturePath, sha256: sha256(fixtureBody), bytes: fixtureBody.byteLength },
    artifacts: [
      { path: "sample.jsonl", rows: 1, sha256: sha256(sampleBody), bytes: Buffer.byteLength(sampleBody) },
      { path: "audit.json", sha256: sha256(auditBody), bytes: Buffer.byteLength(auditBody) },
    ],
  };
  await writeFile(resolve(destination, "manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
  return { sample, audit, manifest };
}

async function main() {
  const { manifest } = await exportAgenticFixture(parseArgs(process.argv.slice(2)));
  process.stdout.write(`${JSON.stringify(manifest, null, 2)}\n`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  await main();
}
