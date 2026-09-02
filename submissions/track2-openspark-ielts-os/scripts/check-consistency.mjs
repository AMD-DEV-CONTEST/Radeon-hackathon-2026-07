import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const EXPECTED_DATA = new Map([
  ["wordbook", "./data/wordbook.json"],
  ["practice", "./data/practice.json"],
  ["wrong-questions", "./data/wrong-questions.json"],
  ["reading", "./data/reading.json"],
  ["tests", "./data/tests.json"],
  ["listening", "./data/listening.json"],
  ["writing", "./data/writing.json"],
  ["synonyms", "./data/synonyms.json"],
  ["content-manifest", "./data/content-manifest.json"],
  ["content-roadmap", "./data/content-roadmap.json"],
  ["audio-map", "./data/audio-map.json"],
  ["library-catalog", "./content-packs/library-catalog.json"],
  ["study-paths", "./data/study-paths.json"],
]);

function scriptVersions(html) {
  return new Map([...html.matchAll(/<script\s+src="\.\/([^"?]+)\?v=(\d+)"/g)].map((match) => [match[1], Number(match[2])]));
}

function shellPaths(worker) {
  const block = worker.match(/const APP_SHELL = \[([\s\S]*?)\];/)?.[1] || "";
  return [...block.matchAll(/"(\.\/[^"\n]+)"/g)].map((match) => match[1]);
}

function dataSources(app) {
  const found = new Map();
  for (const match of app.matchAll(/loadJson\("(\.\/[^"\n]+)"/g)) {
    const sourcePath = match[1];
    const base = path.basename(sourcePath, ".json");
    found.set(base, sourcePath);
  }
  for (const match of app.matchAll(/\{\s*key:\s*"([^"]+)"\s*,\s*path:\s*"(\.\/[^"\n]+)"\s*,\s*critical:\s*(?:true|false)[^}]*\}/g)) {
    found.set(path.basename(match[2], ".json"), match[2]);
  }
  return found;
}

function cleanAsset(asset) {
  return asset.split("?")[0].replace(/^\.\//, "");
}

async function validateConsistency({ html, worker, app, dependencySource = app, packageJson, exists = async () => true, mobileCheck = "", resilienceCheck = "" }) {
  const versions = scriptVersions(html);
  const shell = shellPaths(worker);
  const shellSet = new Set(shell);
  const sources = dataSources(dependencySource);
  assert.ok(sources.size > 0, "runtime data discovery found zero sources");
  assert.deepEqual([...sources.entries()].sort(), [...EXPECTED_DATA.entries()].sort(), "runtime data inventory must match the 13 declared sources");

  for (const [name, version] of versions) {
    assert.ok(shellSet.has(`./${name}?v=${version}`), `service-worker APP_SHELL version mismatch for ${name}`);
  }
  const cacheVersion = Number(worker.match(/const CACHE_NAME = "ielts-os-demo-v(\d+)"/)?.[1]);
  const registrationVersion = Number(app.match(/serviceWorker\.register\("\.\/service-worker\.js\?v=(\d+)"/)?.[1]);
  assert.ok(Number.isInteger(cacheVersion), "service-worker cache version is missing");
  assert.equal(registrationVersion, cacheVersion, "service-worker registration/cache version mismatch");

  for (const asset of shell) {
    if (asset === "./") continue;
    assert.ok(await exists(cleanAsset(asset)), `APP_SHELL file does not exist: ${asset}`);
  }
  for (const sourcePath of sources.values()) {
    assert.ok(shellSet.has(sourcePath), `runtime data source is absent from APP_SHELL: ${sourcePath}`);
    assert.ok(await exists(cleanAsset(sourcePath)), `runtime data source does not exist: ${sourcePath}`);
  }

  assert.equal(packageJson.scripts?.["check:consistency"], "node scripts/check-consistency.mjs", "missing exact check:consistency package command");
  assert.match(packageJson.scripts?.check || "", /(?:^|&&\s*)npm run check:consistency(?:\s*&&|$)/, "aggregate check must include check:consistency");
  assert.doesNotMatch(packageJson.scripts?.check || "", /check:status-handoff/, "status handoff must stay outside aggregate check");
  assert.doesNotMatch(mobileCheck, /ielts-os-demo-v\d+|app\\\.js\\\?v=\d+|service-worker\\\.js\\\?v=\d+/, "mobile check must not hard-code release versions");
  assert.doesNotMatch(resilienceCheck, /ielts-os-demo-v\d+|app\\\.js\\\?v=\d+|service-worker\\\.js\\\?v=\d+/, "resilience check must not hard-code release versions");
}

async function expectFailure(input, pattern) {
  await assert.rejects(() => validateConsistency(input), pattern);
}

const [html, worker, app, reliability, packageText, mobileCheck, resilienceCheck] = await Promise.all([
  readFile(path.join(root, "index.html"), "utf8"),
  readFile(path.join(root, "service-worker.js"), "utf8"),
  readFile(path.join(root, "app.js"), "utf8"),
  readFile(path.join(root, "app-reliability.js"), "utf8").catch(() => ""),
  readFile(path.join(root, "package.json"), "utf8"),
  readFile(path.join(root, "scripts/check-mobile.mjs"), "utf8"),
  readFile(path.join(root, "scripts/check-resilience.mjs"), "utf8"),
]);
const packageJson = JSON.parse(packageText);
const exists = async (relative) => access(path.join(root, relative)).then(() => true, () => false);
const realInput = { html, worker, app, dependencySource: `${app}\n${reliability}`, packageJson, exists, mobileCheck, resilienceCheck };

await validateConsistency(realInput);

await expectFailure({ ...realInput, html: html.replace(/app\.js\?v=\d+/, "app.js?v=999") }, /APP_SHELL version mismatch/);
await expectFailure({ ...realInput, worker: worker.replace('  "./manifest.json",', '  "./manifest.json",\n  "./missing-shell-fixture.json",') }, /APP_SHELL file does not exist/);
await expectFailure({ ...realInput, dependencySource: "const APP_DATA_SOURCES = [];" }, /zero sources/);
await expectFailure({ ...realInput, worker: worker.replace('  "./data/wordbook.json",\n', "") }, /absent from APP_SHELL/);

console.log("Asset, version and runtime-data consistency checks passed.");
