import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const root = new URL("../", import.meta.url);
const [html, app, styles] = await Promise.all([
  readFile(new URL("index.html", root), "utf8"),
  readFile(new URL("app.js", root), "utf8"),
  readFile(new URL("styles.css", root), "utf8"),
]);

assert.match(html, /data-dashboard-range="7"/);
assert.match(html, /data-dashboard-range="30"/);
assert.match(html, /data-dashboard-kpis/);
assert.match(html, /data-dashboard-trend/);
assert.match(html, /data-dashboard-mix/);
assert.match(html, /data-dashboard-movement/);
assert.match(html, /data-weekly-report/);
assert.equal((html.match(/data-weekly-report/g) || []).length, 1, "周报只应有一个渲染目标");
assert.match(html, /class="profile-grid profile-action-grid"/);
assert.match(html, /class="profile-disclosure"/);
assert.match(html, />详细学习分析</);
assert.match(html, />题库与内容状态</);
assert.match(app, /function dashboardSnapshot/);
assert.match(app, /function renderLearningDashboard/);
assert.match(app, /wrongReviewQueue\(reviewItems\)/);
assert.match(app, /renderLearningDashboard\(\)/);
assert.match(styles, /\.dashboard-kpis/);
assert.match(styles, /\.dashboard-trend/);

const fixture = [
  { module: "Listening", durationMinutes: 18 },
  { module: "Reading", durationMinutes: 22 },
  { module: "Listening", durationMinutes: 12 },
];
const total = fixture.reduce((sum, event) => sum + event.durationMinutes, 0);
const byModule = fixture.reduce((result, event) => ({ ...result, [event.module]: (result[event.module] || 0) + event.durationMinutes }), {});
assert.equal(total, 52);
assert.equal(Object.values(byModule).reduce((sum, value) => sum + value, 0), total, "科目分布必须与总投入对账");

console.log("Dashboard checks passed.");
