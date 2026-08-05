import assert from "node:assert/strict";
import fs from "node:fs";

function sentences(text) {
  return String(text).match(/[^.!?]+[.!?]+|[^.!?]+$/g)?.map((sentence) => sentence.trim()).filter(Boolean) || [];
}

function accuracy(expectedText, actualText) {
  const words = (text) => String(text).toLowerCase().match(/[a-z0-9]+/g) || [];
  const expected = words(expectedText);
  const actual = words(actualText);
  return Math.round(expected.filter((word, index) => actual[index] === word).length / Math.max(1, expected.length) * 100);
}

assert.deepEqual(sentences("Good morning. Bring your ID!"), ["Good morning.", "Bring your ID!"]);
assert.equal(accuracy("Bring your student ID.", "bring your student id"), 100);
assert.equal(accuracy("Bring your student ID.", "Bring student ID"), 25);

const html = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");
const app = fs.readFileSync(new URL("../app.js", import.meta.url), "utf8");
const wordbook = JSON.parse(fs.readFileSync(new URL("../data/wordbook.json", import.meta.url), "utf8"));
const listening = JSON.parse(fs.readFileSync(new URL("../data/listening.json", import.meta.url), "utf8"));
const activeListening = listening.items.find((item) => item.id === listening.activeItemId);
const listeningWords = wordbook.words.filter((item) => item.source?.includes("听力核心场景词汇"));

assert.match(html, /data-screen="listeningVocab"/);
assert.match(html, /data-listening-vocab-scene/);
assert.match(html, /data-listening-vocab-answer/);
assert.match(html, /data-listening-mode="study"/);
assert.match(html, /data-listening-mode="test"/);
assert.match(html, /data-listening-panel="test"/);
assert.match(html, /data-listening-rights/);
assert.match(app, /function checkListeningVocabulary\(\)/);
assert.match(app, /function renderListeningMode\(\)/);
assert.match(app, /function hasReliableEvidence\(value\)/);
assert.match(app, /function markListeningSentenceHint\(\)/);
assert.match(app, /本句仍加入复练/);
assert.match(app, /暂无中文翻译/);
assert.match(app, /state\.listeningMode = trigger\?\.classList\?\.contains\("catalog-main"\) \? "study" : "test"/);
assert.match(app, /addWrongQuestion\(\{/);
assert.match(app, /优先练习薄弱场景/);
assert.equal(listeningWords.length, 647);
assert.ok(listeningWords.every((item) => item.topic && item.definition));
assert.ok(listening.items.every((item) => !item.vocabularyTopic || listeningWords.some((word) => word.topic === item.vocabularyTopic)));
assert.ok(activeListening.questions.length >= 5, "active listening item should have questions");
assert.ok(activeListening.questions.every((question) => activeListening.audioScript.includes(question.evidence)));
assert.match(html, /data-listening-related-words/);
// Original sample items only; commercial listening content stays personal.
assert.ok(listening.items.length >= 3, "sample listening items should exist");
assert.ok(listening.items.every((item) => item.questions.length >= 4));
assert.ok(listening.items.flatMap((item) => item.questions).every((question) => !/\d+\s*[–-]\s*\d+\s+\d+\s*[–-]\s*\d+/.test(question.answer)), "score-band text leaked into a listening answer");
assert.match(app, /class="listening-paper"/);

console.log("Listening sentence lab and scene vocabulary checks passed.");
