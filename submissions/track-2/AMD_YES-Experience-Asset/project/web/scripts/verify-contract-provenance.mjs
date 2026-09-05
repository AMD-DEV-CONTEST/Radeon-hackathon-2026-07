#!/usr/bin/env node
// Fails if any vendored contract file drifts from the recorded provenance hash.
// This is the offline guarantee that Lane B did not silently fork the Lane A
// contract. Run with `npm run verify:contracts`.
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const contractsDir = join(here, '..', 'contracts');

// Each vendored contract source has its own provenance manifest bound to its
// true source commit, so a reviewer can confirm no file was silently forked:
//   provenance.json              — final E1-A contracts on main (merged PR #7)
//   rag-contract-provenance.json — public RAG retrieval-phase contract (main, PR #9)
//   e5-contract-provenance.json  — E5 contract freeze; source commit is an
//                                  unmerged branch head and says so, so the
//                                  manifest never claims a merge that has not
//                                  happened.
const MANIFESTS = [
  'provenance.json',
  'rag-contract-provenance.json',
  'e5-contract-provenance.json',
];

let failed = 0;
let total = 0;
for (const manifestName of MANIFESTS) {
  const manifest = JSON.parse(await readFile(join(contractsDir, manifestName), 'utf8'));
  const entries = Object.entries(manifest.sha256);
  total += entries.length;
  for (const [rel, expected] of entries) {
    let actual;
    try {
      const buf = await readFile(join(contractsDir, rel));
      actual = createHash('sha256').update(buf).digest('hex');
    } catch (err) {
      console.error(`MISSING  ${rel} (${err.code ?? err.message})`);
      failed += 1;
      continue;
    }
    if (actual !== expected) {
      console.error(`DRIFT    ${rel}\n  expected ${expected}\n  actual   ${actual}`);
      failed += 1;
    } else {
      console.log(`OK       ${rel}`);
    }
  }
  console.log(
    `  ↳ ${manifestName}: source ${manifest.source_commit} — ` +
      `${entries.length} file(s).`,
  );
}

console.log(`\nContract provenance: ${total - failed}/${total} vendored files match.`);

if (failed > 0) {
  console.error(`FAIL: ${failed} vendored contract file(s) drifted from provenance.`);
  process.exit(1);
}
console.log('PASS: all vendored contracts match their recorded source commits.');
