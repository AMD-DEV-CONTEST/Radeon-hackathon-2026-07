import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const root = new URL("../", import.meta.url);
const [html, app, styles] = await Promise.all([
  readFile(new URL("index.html", root), "utf8"),
  readFile(new URL("app.js", root), "utf8"),
  readFile(new URL("styles.css", root), "utf8"),
]);

assert.match(html, /data-screen="onboarding"/);
assert.match(html, /data-screen="baseline"/);
assert.match(html, /data-onboarding-target/);
assert.match(html, /data-onboarding-date/);
assert.match(html, /data-onboarding-budget="60"/);
assert.match(html, /data-onboarding-wordbook/);
assert.match(html, /data-onboarding-new-words/);
assert.match(html, /name="baseline-listening"/);
assert.match(html, /name="baseline-reading"/);
assert.match(html, /name="baseline-writing"/);
assert.match(html, /name="baseline-speaking"/);
assert.match(html, /data-profile-target/);
assert.match(app, /USER_PROFILE_KEY/);
assert.match(app, /BASELINE_RESULT_KEY/);
assert.match(app, /function submitBaseline/);
assert.match(app, /maxScore: 9/);
assert.match(app, /showScreen\(state\.userProfile \? "today" : "onboarding"\)/);
assert.match(app, /DAILY_WORD_QUEUE_KEY/);
assert.match(app, /function newWordsPerDay/);
assert.match(styles, /\.phone\.setup-mode \.bottom-nav/);
assert.match(styles, /\.baseline-result/);

console.log("Onboarding and baseline checks passed.");
