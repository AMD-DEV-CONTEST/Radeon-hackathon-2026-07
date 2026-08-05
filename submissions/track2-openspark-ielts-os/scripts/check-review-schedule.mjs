import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const intervals = [0, 1, 3, 7, 14, 30];
function schedule(stage, rating) {
  const nextStage = rating === "again" ? 0 : Math.min(5, stage + (rating === "easy" ? 2 : rating === "good" ? 1 : 0));
  return { stage: nextStage, interval: rating === "hard" ? 1 : intervals[nextStage], mastered: nextStage >= 5 };
}

assert.deepEqual(schedule(3, "again"), { stage: 0, interval: 0, mastered: false });
assert.deepEqual(schedule(2, "hard"), { stage: 2, interval: 1, mastered: false });
assert.deepEqual(schedule(2, "good"), { stage: 3, interval: 7, mastered: false });
assert.deepEqual(schedule(3, "easy"), { stage: 5, interval: 30, mastered: true });

const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
const app = readFileSync(new URL("../app.js", import.meta.url), "utf8");
assert.match(html, /data-wrong-mode="today"/);
assert.match(html, /data-wrong-mode="library"/);
assert.match(html, /data-wrong-mode="detail"/);
assert.match(html, /data-wrong-library/);
assert.match(html, /data-wrong-next/);
assert.match(html, /class="wrong-insights"/);
assert.match(html, /aria-label="题型掌握地图"/);
assert.match(html, />今日待复盘</);
assert.match(html, />全部错题</);
assert.match(app, /pendingItems\[0\]/);
assert.match(app, /nextButton\.textContent = pendingCount/);
assert.match(app, /const nextDue = wrongReviewQueue\(state\.userWrongQuestions\)\[0\]/);
assert.match(app, /state\.wrongMode = nextDue \? "detail" : "today"/);
assert.match(app, /state\.wrongMode = nextDue \? "detail" : "today";\s*persistResumeState\(\)/);
assert.match(app, /function renderWrongMode\(\)/);
assert.match(app, /function objectiveQuestionMastery\(\)/);
assert.match(app, /if \(!attempt\?\.submitted\) continue/);
assert.match(app, /listeningAnswerCorrect\(question, answer, item, attempt\.answers\) : readingAnswerCorrect\(question, answer, item, attempt\.answers\)/);
assert.match(app, /听力、阅读按已提交答案计算；写作、口语只显示复盘信号，不生成分数/);
assert.match(app, /data-mastery-practice/);
assert.match(app, /data-mastery-output/);
assert.match(html, /data-word-session-summary/);
assert.match(app, /function renderWordSessionSummary\(\)/);
assert.match(app, /if \(nextIndex < 0\) renderWordSessionSummary\(\)/);

console.log("Wrong-question review schedule check passed.");
