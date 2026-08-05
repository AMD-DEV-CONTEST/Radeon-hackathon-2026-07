import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const root = new URL("../", import.meta.url);
const app = await readFile(new URL("app.js", root), "utf8");
const require = createRequire(import.meta.url);
const reliability = require(fileURLToPath(new URL("../app-reliability.js", import.meta.url)));

const sources = reliability.APP_DATA_SOURCES;
assert.equal(sources.length, 13);
assert.deepEqual(sources.filter((item) => item.critical).map((item) => item.key), ["wordbook", "practice", "reading", "tests", "listening", "writing"]);
const expectedFallbacks = {
  wrongQuestions: { items: [], notes: [] },
  synonyms: { groups: [], source: "", title: "" },
  contentManifest: { version: 0, records: [], description: "" },
  contentRoadmap: { schemaVersion: 0, books: [], stages: [], gaps: [], reservations: [] },
  audioMap: { version: 0, items: [], policy: "" },
  libraryCatalog: { schemaVersion: 0, modules: [], personalCollections: [], totalResources: 0, status: "partial" },
  studyPaths: { version: 0, paths: [] },
};
assert.deepEqual(Object.fromEntries(sources.filter((item) => !item.critical).map((item) => [item.key, item.fallback])), expectedFallbacks);

const successValue = (item) => ({ key: item.key });
for (const optional of sources.filter((item) => !item.critical)) {
  const result = await reliability.loadDataSources(sources, (item) => item.key === optional.key ? Promise.reject(new Error(item.key)) : Promise.resolve(successValue(item)));
  assert.equal(result.ok, true);
  assert.deepEqual(result.missing, [optional.key]);
  assert.deepEqual(result.values[optional.key], optional.fallback);
}
for (const critical of sources.filter((item) => item.critical)) {
  const result = await reliability.loadDataSources(sources, (item) => item.key === critical.key ? Promise.reject(new Error(item.key)) : Promise.resolve(successValue(item)));
  assert.equal(result.ok, false);
  assert.deepEqual(result.missing, [critical.key]);
  assert.equal(result.values, null);
}
const mixedMissing = new Set(["wordbook", "synonyms", "audioMap"]);
const mixed = await reliability.loadDataSources(sources, (item) => mixedMissing.has(item.key) ? Promise.reject(new Error(item.key)) : Promise.resolve(successValue(item)));
assert.equal(mixed.ok, false);
assert.deepEqual(mixed.missing, sources.filter((item) => mixedMissing.has(item.key)).map((item) => item.key));
assert.equal(mixed.values, null, "mixed critical failure must not commit optional fallbacks");

function node() {
  const attributes = new Map([["inert", ""]]);
  return {
    hidden: false,
    classList: { toggle() {} },
    setAttribute: (key, value) => attributes.set(key, value),
    removeAttribute: (key) => attributes.delete(key),
    toggleAttribute: (key, force) => force ? attributes.set(key, "") : attributes.delete(key),
    hasAttribute: (key) => attributes.has(key),
  };
}
const phone = node();
const overlay = node();
const nav = node();
const screens = [node(), node()];
reliability.applyStartupDomState({ status: "ready", phone, overlay, nav, screens });
assert.equal(overlay.hidden, true);
assert.equal(nav.hasAttribute("inert"), false);
assert.equal(nav.hasAttribute("aria-hidden"), false);
assert.ok(screens.every((item) => !item.hasAttribute("inert")));

assert.match(app, /const APP_DATA_SOURCES = IELTSReliability\.APP_DATA_SOURCES/);
assert.match(app, /核心学习内容未能读取（\$\{result\.missing\.join\(", "\)\}），请重新加载。/);
assert.match(app, /\$\{result\.missing\.length\} 项扩展内容未加载，其余功能可正常使用。/);
assert.equal((app.match(/bindNavigation\(\);/g) || []).length, 1, "navigation handlers must bind once from init");
assert.equal((app.match(/loadAppData\(true\)/g) || []).length, 1, "retry must call only loadAppData(true)");

console.log("Critical/optional startup and retry cleanup checks passed.");
