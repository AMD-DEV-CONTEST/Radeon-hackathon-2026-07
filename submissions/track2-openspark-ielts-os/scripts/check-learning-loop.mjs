import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const root = new URL("../", import.meta.url);
const [html, app, styles] = await Promise.all([
  readFile(new URL("index.html", root), "utf8"),
  readFile(new URL("app.js", root), "utf8"),
  readFile(new URL("styles.css", root), "utf8"),
]);

assert.match(html, /data-tomorrow-plan/);
assert.match(html, /data-wrong-question-type/);
assert.match(html, /data-ai-subject-coaches/);
assert.equal((html.match(/data-module-coach-review=/g) || []).length, 3, "听力、阅读、写作都应显示科目 AI 复盘");
assert.match(html, /class="today-plan-progress"/);
assert.match(html, /class="today-word-card"[^>]+aria-busy="true"[^>]+data-today-card/);
assert.match(html, /data-today-next-action disabled>正在准备/);
assert.match(html, /class="today-status"/);
assert.match(html, /class="plan-card plan-next-card"/);
assert.match(html, /data-plan-next-action/);
assert.equal((html.match(/class="plan-disclosure"/g) || []).length, 2, "计划页的次级规划工具应分为两个展开区");
assert.doesNotMatch(html, /class="streak-hero"/);
assert.doesNotMatch(html, /class="summary-card compact-book"/);
assert.match(app, /function refreshLearningSurfaces/);
assert.match(app, /moduleReviews: \[\]/);
assert.match(app, /function rememberModuleReview\(module, summary, evidence/);
assert.match(app, /requestAI\("listening_review"/);
assert.match(app, /requestAI\("reading_review"/);
assert.match(app, /rememberModuleReview\("Writing", aiText/);
assert.match(app, /rememberModuleReview\("Speaking", summary/);
assert.match(app, /function renderSubjectCoaches\(\)/);
assert.match(app, /examWeek: \{ checklist: \{\}, reflection: "", reflectionSavedAt: null \}/);
assert.match(app, /state\.examWeek = loadStoredJson\(EXAM_MODE_KEY/);
assert.doesNotMatch(app, /state\.examMode = loadStoredJson\(EXAM_MODE_KEY/);
assert.match(app, /function adjustPlanMinutes/);
assert.match(app, /PLAN_ADJUSTMENTS_KEY/);
assert.match(app, /PLAN_MODULES_KEY/);
assert.match(app, /state\.planModules\[date\]/);
assert.match(app, /function moduleWrongFocus\(module\)/);
assert.match(app, /function modulePlanSummary\(module\)/);
assert.match(app, /function activeContentCourse\(\)/);
assert.match(app, /course\.books\.includes\(practiceIndex\(item\)\.book\)/);
assert.match(app, /courseItems\.length \? courseItems : available/);
assert.match(app, /function moduleProgressToday\(module, plannedMinutes = 0\)/);
assert.match(app, /event\.activity !== "首次基线诊断"/);
assert.match(app, /actualMinutes >= requiredMinutes/);
assert.doesNotMatch(app, /function completedModuleToday\(module\)/);
assert.match(app, /dailyPlan\(1\)/);
assert.match(app, /setText\("\[data-plan-next-title\]"/);
assert.match(app, /nextAction\.onclick = \(event\) => nextTask \? startPlanTask/);
assert.match(app, /generatedPlan\.filter\(\(task\) => task\.complete\)\.length/);
assert.match(app, /nextTask \? `开始\$\{MODULE_LABELS\[nextTask\.module\]/);
assert.match(app, /nextAction\.disabled = false/);
assert.match(app, /data-today-card.+aria-busy.+false/);
assert.match(app, /: "自由练习"/);
assert.match(app, /wrongQuestionTypeFilter/);
assert.match(app, /refreshLearningSurfaces\(\);/);
assert.match(styles, /\.tomorrow-plan/);
assert.match(styles, /\.plan-item-actions/);
assert.match(styles, /screen\.active\[data-screen="today"\]/);
assert.match(styles, /scroll-padding-bottom/);
assert.doesNotMatch(html, /class="icon-btn" data-go="[^"]+">‹<\/button>/);

console.log("Adaptive learning loop checks passed.");
