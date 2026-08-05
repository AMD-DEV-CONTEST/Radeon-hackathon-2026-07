import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const root = new URL("../", import.meta.url);
const [html, app, styles, testsText] = await Promise.all([
  readFile(new URL("index.html", root), "utf8"),
  readFile(new URL("app.js", root), "utf8"),
  readFile(new URL("styles.css", root), "utf8"),
  readFile(new URL("data/tests.json", root), "utf8"),
]);
const catalogText = await readFile(new URL("local-library/catalog.json", root), "utf8")
  .catch(() => readFile(new URL("content-packs/library-catalog.json", root), "utf8"));

assert.match(html, /data-practice-search/);
assert.match(html, /data-practice-difficulty/);
assert.match(html, /data-practice-status="收藏"/);
assert.match(html, /data-practice-result-count/);
assert.match(html, /data-practice-empty/);
assert.match(html, /data-practice-tab="资料库"/);
assert.match(html, /class="[^"]*\bpractice-filter-panel\b[^"]*"/);
assert.match(html, /data-practice-reset/);
assert.match(html, /<h1>学习中心<\/h1>/);
assert.match(html, /data-learning-route-stage/);
assert.match(html, /data-learning-route-action/);
assert.match(html, /data-learning-resume/);
assert.match(html, /class="learning-module-grid"/);
assert.equal((html.match(/data-practice-module-next="(?:听力|阅读|写作|口语)"/g) || []).length, 4);
assert.match(html, /data-learning-subject-next/);
assert.match(html, /data-learning-subject-action/);
assert.match(html, /<button data-go="practice">学习<\/button>\s*<button data-go="ai">AI<\/button>/);
assert.equal((html.match(/<button[^>]+data-practice-tab="(?:听力|阅读|写作|口语)"/g) || []).length, 4);
assert.match(html, /data-open-library/);
assert.match(app, /PRACTICE_FAVORITES_KEY/);
assert.match(app, /function practiceCatalog/);
assert.match(app, /cloudOnly/);
assert.match(app, /CloudLibrary/);
assert.match(app, /folder_not_selected/);
assert.match(app, /await plugin\.selectFolder\(\);\s*await plugin\.openFile\(\{ relativePath: item\.sourceId \}\);/);
assert.doesNotMatch(html, /data-import-demo/);
assert.match(app, /function togglePracticeFavorite/);
assert.match(app, /state\.practiceSearch/);
assert.match(app, /state\.practiceDifficulty/);
assert.match(app, /state\.practiceStatus/);
assert.match(app, /state\.practiceBook = books\.includes\(Number\(state\.practiceBook\)\) \? String\(state\.practiceBook\) : "全部"/);
assert.match(app, /state\.practiceTest = tests\.includes\(Number\(state\.practiceTest\)\) \? String\(state\.practiceTest\) : "全部"/);
assert.ok((app.match(/state\.practiceResourceAvailability = "全部"/g) || []).length >= 3, "all practice reset paths must clear resource availability");
assert.match(app, /data-practice-reset/);
assert.match(app, /data-practice-module-count/);
assert.match(app, /function renderLearningRoute/);
assert.match(app, /function renderLearningSubjectNext/);
assert.match(app, /nextTask \? recommendedPractice\(nextTask\)/);
assert.match(app, /!calibrated \|\| band < 5 \? "foundation"/);
assert.match(styles, /\.catalog-card/);
assert.match(styles, /\.library-status/);
assert.match(styles, /\.learning-module-grid/);
assert.match(styles, /\.learning-route-card/);
assert.match(styles, /\.learning-subject-next/);
const catalog = JSON.parse(catalogText);
const cloudPaths = new Set((catalog.items || catalog.modules?.flatMap((module) => module.resources) || []).map((item) => item.path));
const testItems = JSON.parse(testsText).collections.flatMap((collection) => collection.items);
for (const item of testItems.filter((item) => item.cloudOnly)) assert.ok(cloudPaths.has(item.sourceId), `missing iCloud source: ${item.sourceId}`);
// Original sample collections only; commercial test papers are personal imports.
assert.ok(testItems.length >= 3, "sample practice items should exist");
assert.match(app, /state\.activeWritingTaskId = task\.id/);
assert.match(app, /SPEAKING_CARDS\.findIndex/);

console.log("Practice library checks passed.");
