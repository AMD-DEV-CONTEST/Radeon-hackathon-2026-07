import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const root = new URL("../", import.meta.url);
const app = await readFile(new URL("app.js", root), "utf8");
assert.match(app, /beginAppearance\(item\.word, `card:\$\{wordSessionId\}:\$\{\+\+wordAppearanceSerial\}`\)/, "word modes do not create scheduler appearance IDs");
assert.match(app, /beginAppearance\(question\.word\.word, `quiz:\$\{quiz\.sessionId\}:\$\{quiz\.index\}`\)/);
assert.match(app, /renderListeningSentence[\s\S]*?dictationAppearances\[state\.listeningSentenceIndex\] \|\|= IELTSLearning\.beginAppearance/);
assert.match(app, /const appearance = attempt\.dictationAppearances\[state\.listeningSentenceIndex\]/);
assert.doesNotMatch(app, /accuracy < 100 \|\| hinted\)[\s\S]{0,180}delete attempt\.dictationAppearances/);
assert.match(app, /；另有 \$\{queue\.deferredReview\} 个到期复习延后/, "word plan does not expose deferred review");

const queueSource = app.slice(app.indexOf("function dailyWordQueue()"), app.indexOf("\nfunction queueWords()"));
let storedQueue = null;
let buildCount = 0;
const productionQueue = Function("selectedBookWords", "localIsoDate", "state", "newWordsPerDay", "loadStoredJson", "IELTSLearning", "persistValue", "DAILY_WORD_QUEUE_KEY", "volatileWordQueue", `${queueSource}; return dailyWordQueue;`)(() => [{ word: "a" }, { word: "b" }], () => "2026-01-01", { userProfile: {}, wordProgress: {} }, () => 1, () => storedQueue, { buildDailyQueue: () => (++buildCount, { words: ["a"], fresh: ["a"], review: [], cap: 40 }) }, (_, value) => (storedQueue = JSON.parse(value), true), "queue", null);
assert.deepEqual(productionQueue().words, ["a"]);
assert.deepEqual(productionQueue().fresh, ["a"]);
assert.equal(buildCount, 1, "the production adapter must reuse today's stored queue");
assert.match(app, /function renderWordDetail\(\)[\s\S]*?!beginCurrentWordAppearance\(item\)/);
assert.match(app, /queue\.presented >= queue\.cap/);
assert.match(app, /quiz\.questions\.length < 120\) quiz\.questions\.push\(\{ \.\.\.question, appearance: null \}\)/, "wrong quiz words must re-enter the same session with a new appearance");
assert.match(app, /delete currentAttempt\(\)\?\.dictationAppearances\?\.\[state\.listeningSentenceIndex\][\s\S]*?renderListeningSentence/, "leaving a dictation sentence must allocate a new presentation on return");

const require = createRequire(import.meta.url);
const core = require(fileURLToPath(new URL("../learning-core.js", import.meta.url)));
const day = "2026-01-01";
const appearance = core.beginAppearance("word", "card:s:1");
const legacy = core.normalizeProgress({ reviewCount: 2 });
assert.equal(legacy.stage, 0);
assert.equal(core.normalizeProgress({ reviewCount: 0 }).stage, -1);
assert.equal(core.normalizeProgress({ reviewCount: 3 }).stage, 1);
const failed = core.recordFailure({ reviewDate: "2025-12-31", nextReviewDate: "2026-01-10", ease: 1.4, lapses: 5 }, appearance, day);
assert.deepEqual({ state: failed.learningState, stage: failed.stage, ease: failed.ease, lapses: failed.lapses, due: failed.relearningDueDate, leech: failed.leech }, { state: "relearning", stage: 0, ease: 1.3, lapses: 6, due: day, leech: true });
assert.equal(failed.nextReviewDate, "2026-01-10");
assert.equal(core.recordFailure(failed, appearance, day).lapses, 6, "same appearance must fail once");
const relearned = core.recordSuccess(failed, core.beginAppearance("word", "card:s:2"), day, () => 0.5);
assert.equal(relearned.stage, 0);
assert.equal(relearned.nextReviewDate, "2026-01-02");
assert.equal(relearned.relearningDueDate, undefined);
const learned = core.recordSuccess({}, core.beginAppearance("new", "card:s:3"), day, () => 0.5);
assert.equal(learned.stage, 0);
assert.equal(learned.nextReviewDate, "2026-01-02");

const sampleWords = [
  { word: "a", bookIndex: 1 },
  { word: "b", bookIndex: 2 },
  { word: "c", bookIndex: 3 },
  { word: "d", bookIndex: 4, memoryState: "due" },
];
const progress = {
  a: { learningState: "relearning", lapses: 2, nextReviewDate: "2025-12-30" },
  b: { learningState: "review", lapses: 4, nextReviewDate: day },
};
const before = JSON.stringify(progress);
const sampleQueue = core.buildDailyQueue({ words: sampleWords, progress, today: day, daily: 1 });
assert.deepEqual(sampleQueue.words.slice(0, 3), ["a", "b", "d"]);
assert.equal(sampleQueue.cap, 40);
assert.equal(JSON.stringify(progress), before, "queue construction must not mutate due dates");
assert.equal(core.projectionDays({ remainingUnseen: 8000, daily: 20, deferredReview: 0, reviewSlots: 96 }), 400);
assert.equal(core.normalizeDaily(0), 8);
const pressureWords = Array.from({ length: 140 }, (_, index) => ({ word: `p${index}`, bookIndex: index }));
const pressureProgress = Object.fromEntries(pressureWords.slice(0, 100).map((item) => [item.word, { nextReviewDate: day, reviewCount: 1 }]));
const pressureQueue = core.buildDailyQueue({ words: pressureWords, progress: pressureProgress, today: day, daily: 20 });
assert.equal(pressureQueue.review.length, 96);
assert.equal(pressureQueue.fresh.length, 20, "fresh allocation must be reserved under review pressure");
assert.equal(pressureQueue.deferredReview, 4);

const words = Array.from({ length: 8000 }, (_, index) => ({ word: `w${index + 1}`, bookIndex: index + 1 }));
const simulationProgress = {};
const introduced = new Set();
const deferredHistory = [];
let attemptIndex = 0;
let maxPresented = 0;
const addDays = (date, days) => { const value = new Date(`${date}T12:00:00Z`); value.setUTCDate(value.getUTCDate() + days); return value.toISOString().slice(0, 10); };
for (let dayIndex = 0; dayIndex < 3000; dayIndex += 1) {
  const today = addDays(day, dayIndex);
  const queue = core.buildDailyQueue({ words, progress: simulationProgress, today, daily: 20 });
  const attempts = [...queue.words];
  let presented = 0;
  while (attempts.length && presented < queue.cap) {
    const name = attempts.shift();
    const token = core.beginAppearance(name, `card:${dayIndex}:${presented}`);
    attemptIndex += 1;
    presented += 1;
    if (introduced.size < words.length && [5, 11, 17].includes(attemptIndex % 20)) {
      simulationProgress[name] = core.recordFailure(simulationProgress[name], token, today);
      attempts.push(name);
    } else {
      simulationProgress[name] = core.recordSuccess(simulationProgress[name], token, today, () => 0.5);
      introduced.add(name);
    }
  }
  maxPresented = Math.max(maxPresented, presented);
  const remaining = core.buildDailyQueue({ words, progress: simulationProgress, today, daily: 20 }).deferredReview;
  if (dayIndex === 729) assert.equal(introduced.size, 8000, "all words must receive a first successful introduction by day 730");
  if (introduced.size === words.length) deferredHistory.push(remaining);
  if (introduced.size === words.length && remaining <= 120 && deferredHistory.length >= 30 && deferredHistory.slice(-30).every((value, index, list) => index === 0 || value <= list[index - 1])) break;
}
assert.equal(introduced.size, 8000);
assert.ok(maxPresented <= 120);
assert.ok(deferredHistory.at(-1) <= 120, `review-only deferred backlog ${deferredHistory.at(-1)} exceeds 120 by day 3000`);
const final30 = deferredHistory.slice(-30);
assert.ok(final30.every((value, index) => index === 0 || value <= final30[index - 1]), "deferred backlog must not increase over final 30 days");

console.log(`Vocabulary scheduler checks passed in ${deferredHistory.length} simulated days.`);
