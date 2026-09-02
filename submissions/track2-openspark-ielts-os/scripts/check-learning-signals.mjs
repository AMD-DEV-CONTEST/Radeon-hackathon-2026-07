import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const root = new URL("../", import.meta.url);
const [app, remote] = await Promise.all(["app.js", "remote-update.js"].map((file) => readFile(new URL(file, root), "utf8")));
const core = createRequire(import.meta.url)(fileURLToPath(new URL("../learning-core.js", import.meta.url)));
assert.equal(typeof core.migrateStreak, "function", "migrateStreak missing");

const today = "2026-07-27";
const event = (module, date, score, maxScore, extra = {}) => ({ module, createdAt: `${date}T12:00:00Z`, durationMinutes: 10, score, maxScore, ...extra });
assert.deepEqual(core.migrateStreak({ count: 4, lastActiveDate: today }, [], today), { count: 4, lastActiveDate: today });
assert.equal(core.migrateStreak({ count: 4, lastActiveDate: "2026-99-99" }, [], today), null);
assert.deepEqual(core.migrateStreak(null, [event("Reading", today), event("Reading", "2026-07-26"), event("Reading", "2026-07-25"), event("Reading", "2026-07-24", null, null, { activity: "首次基线诊断" })], today), { count: 3, lastActiveDate: today });
assert.equal(core.migrateStreak(null, [], today), null);
assert.deepEqual(core.advanceStreak({ count: 2, lastActiveDate: today }, today), { count: 2, lastActiveDate: today });
assert.deepEqual(core.advanceStreak({ count: 2, lastActiveDate: "2026-07-26" }, today), { count: 3, lastActiveDate: today });
assert.deepEqual(core.advanceStreak({ count: 8, lastActiveDate: "2026-07-20" }, today), { count: 1, lastActiveDate: today });

assert.equal(core.explicitAverage({ Listening: 6, Reading: 7, Writing: 6.5, Speaking: 7.5 }), 7);
assert.equal(core.explicitAverage({ Listening: 6, Reading: 7 }), null);
assert.equal(core.explicitAverage({ Listening: 6, Reading: 7, Writing: null, Speaking: 7 }), null);
const calibrationEvents = [
  event("Listening", "2026-07-27", 7, 9, { evidenceType: "objective" }),
  event("Listening", "2026-07-26", 5, 9, { evidenceType: "objective" }),
  event("Listening", "2026-07-25", 9, 10, { evidenceType: "objective" }),
  event("Listening", "2026-07-24", 1, 1, { evidenceType: "objective" }),
];
const direct = core.calibration(calibrationEvents, "Listening");
assert.equal(direct.ready, true);
assert.equal(direct.score, 6.5, "direct band events must ignore ratio events and weight newest first");
assert.equal(core.calibration([event("Reading", today, 8, 10, { sourceId: "reading-19-1-1" }), event("Reading", "2026-07-26", 7, 10, { evidenceType: "objective" })], "Reading").score, 6.5);
assert.equal(core.calibration([event("Writing", today, 7, 9, { evidenceType: "practice" }), event("Writing", "2026-07-26", 6, 9, { evidenceType: "verified" })], "Writing").ready, false);

const readyEvents = ["Listening", "Reading", "Writing", "Speaking"].flatMap((module) => [event(module, today, 7, module === "Listening" || module === "Reading" ? 10 : 9, { evidenceType: module === "Listening" || module === "Reading" ? "objective" : "verified" }), event(module, "2026-07-26", 6, module === "Listening" || module === "Reading" ? 10 : 9, { evidenceType: module === "Listening" || module === "Reading" ? "objective" : "verified" })]);
assert.deepEqual([0, 1, 2, 4].map((count) => core.learningSignals(readyEvents.filter((event) => ["Listening", "Reading", "Writing", "Speaking"].indexOf(event.module) < count)).readyModules), [0, 1, 2, 4]);
assert.equal(core.learningSignals(readyEvents).band, 6.5);

assert.deepEqual(core.queueCounts({ words: ["a", "b", "c"], fresh: ["a"], progress: { a: { reviewDate: today }, b: {}, c: { reviewDate: today } }, today }), { fresh: 1, review: 2, total: 3, pendingFresh: 0, pendingReview: 1, pending: 1, complete: false });
assert.deepEqual(core.promoteFocus(["Listening", "Reading", "Writing"], "Speaking"), ["Listening", "Reading", "Speaking"]);
assert.deepEqual(core.promoteFocus(["Listening", "Reading"], "Speaking"), ["Listening", "Reading"]);
assert.deepEqual(core.promoteFocus(["Listening", "Reading", "Writing"], "invalid"), ["Listening", "Reading", "Writing"]);

assert.match(app, /IELTSLearning\.(migrateStreak|advanceStreak|calibration|learningSignals|queueCounts|promoteFocus)/);
assert.match(app, /state\.streak = loadStoredJson\(STREAK_KEY[\s\S]*?migrateLegacySampleState\(\)/);
assert.match(app, /if \(!persistLearningEvents\(\)\)[\s\S]*?state\.learningEvents = previous/);
assert.match(app, /activity !== "首次基线诊断" && durationMinutes > 0\) updateLearningStreak/);
assert.match(app, /previousReflection = state\.dailyReflections\[localIsoDate\(offsetDays - 1\)\][\s\S]*?promoteFocus/);
assert.match(app, /signals\.readyModules \? signals\.band : hasBaseline \? IELTSLearning\.explicitAverage/);
assert.doesNotMatch(app, /function accuracyToBand|ratio >= 0?\.9/);
assert.match(remote, /IELTSLearning\.learningSignals/);
assert.doesNotMatch(remote, /readyModules === 4 \? "高可信度"/);
assert.doesNotMatch(`${app}\n${remote}`, /\.at\(/, "iOS 15 production code must avoid Array.prototype.at");
assert.match(remote, /if \(!persistValue\(key, JSON\.stringify\(manifest\)\)\)[\s\S]*?manifest = previous/);
console.log("Shared streak, calibration, queue and focus signal checks passed.");
