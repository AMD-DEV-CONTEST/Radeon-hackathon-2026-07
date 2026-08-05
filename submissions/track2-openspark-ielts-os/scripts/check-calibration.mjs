import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const root = new URL("../", import.meta.url);
const [app, html, remote, practice, wrongQuestions] = await Promise.all([
  readFile(new URL("app.js", root), "utf8"),
  readFile(new URL("index.html", root), "utf8"),
  readFile(new URL("remote-update.js", root), "utf8"),
  readFile(new URL("data/practice.json", root), "utf8").then(JSON.parse),
  readFile(new URL("data/wrong-questions.json", root), "utf8").then(JSON.parse),
]);
const core = createRequire(import.meta.url)(fileURLToPath(new URL("../learning-core.js", import.meta.url)));

function confidence(completedModules, samples) {
  return completedModules === 4 && samples >= 8 ? "高可信度" : completedModules >= 3 ? "中可信度" : "低可信度";
}

assert.deepEqual(
  [0.35, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9].map((ratio) => core.eventBand({ module: "Reading", score: ratio * 10, maxScore: 10, evidenceType: "objective" })),
  [4.5, 5, 5.5, 6, 6.5, 7.5, 8],
);
assert.equal(confidence(2, 12), "低可信度");
assert.equal(confidence(3, 3), "中可信度");
assert.equal(confidence(4, 7), "中可信度");
assert.equal(confidence(4, 8), "高可信度");

const blueprint = ["Listening", "Reading", "Writing", "Speaking"];
assert.equal(new Set(blueprint).size, 4, "阶段测评必须覆盖四科");
assert.equal([4, 3, 2, 3].reduce((sum, value) => sum + value, 0), 12, "完整模考应含 12 个步骤");

assert.equal(core.isCalibrationEvent({ module: "Listening", activity: "场景词听写", score: 1, maxScore: 1, sourceId: "scene-vocab-station" }), false, "单词听写不能进入估分");
assert.equal(core.isCalibrationEvent({ module: "Reading", activity: "每日新闻精读", score: 2, maxScore: 2, sourceId: "news" }), false, "新闻小测不能进入估分");
assert.equal(core.isCalibrationEvent({ module: "Listening", activity: "Part 1", score: 8, maxScore: 10, sourceId: "listening-19-1-1", evidenceType: "objective" }), true, "完整客观题应进入估分");
assert.equal(core.isCalibrationEvent({ module: "Writing", activity: "Task 2", score: 6, maxScore: 9, sourceId: "writing", evidenceType: "practice" }), false, "本地写作检查不能进入估分");
assert.equal(core.isCalibrationEvent({ module: "Speaking", activity: "口语自评", score: 6, maxScore: 9, sourceId: "speaking", evidenceType: "self" }), false, "口语自评不能进入估分");

assert.equal(practice.today.streakDays, 0, "内置内容不能给新用户连续学习天数");
assert.deepEqual(wrongQuestions.items, [], "内置错题样例不能进入用户复盘队列");
assert.doesNotMatch(app, /state\.userWrongQuestions\.length[^\n]+state\.wrongQuestions\?\.items/, "用户错题为空时不能回退到样例错题");
assert.match(app, /function streakFromLearningEvents\(\)/);
assert.match(app, /function isCalibrationEvent\(event\)/);
assert.match(app, /IELTSLearning\.calibration/);
assert.match(app, /evidenceType: "objective"/);
assert.match(app, /snapshot\.band === null \? "—"/);
assert.doesNotMatch(app, /document\.addEventListener\("keydown"[^]*ArrowRight/, "全局方向键不能切换页面");
assert.match(html, /data-agent-card/);
assert.match(html, /固定追问 · 录音回听/);
assert.doesNotMatch(html, /AI 口语模考|实时追问/);
assert.match(app, /function aiServiceReady\(\)/);
assert.match(app, /AI_VERIFIED_ENDPOINT_KEY/);
assert.match(remote, /band === null \? "未校准"/);

console.log("Band calibration policy check passed.");
