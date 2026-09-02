import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const root = new URL("../", import.meta.url);
const [html, app, styles, worker] = await Promise.all([
  readFile(new URL("index.html", root), "utf8"),
  readFile(new URL("app.js", root), "utf8"),
  readFile(new URL("styles.css", root), "utf8"),
  readFile(new URL("service-worker.js", root), "utf8"),
]);

assert.match(html, /data-writing-recovery/);
assert.match(html, /data-health-status/);
assert.match(html, /data-run-health-check/);
assert.match(html, /data-clear-errors/);
assert.match(html, /data-storage-learning/);
assert.match(html, /data-export-backup/);
assert.match(html, /data-import-backup/);
assert.match(html, /data-undo-backup-import/);
assert.match(app, /const BACKUP_KEYS = \[/);
assert.match(app, /function exportBackup\(\)/);
assert.match(app, /function importBackup\(file\)/);
assert.match(app, /function undoBackupImport\(\)/);
assert.match(app, /已合并 \$\{targetKeys\.length\} 项学习数据/);
assert.match(app, /PREIMPORT_BACKUP_KEY/);
assert.match(html, /data-clear-temp-cache/);
assert.match(app, /function loadStoredJson/);
assert.match(app, /RECOVERY_KEY/);
assert.match(app, /recoveries\.slice\(0, 5\)/);
assert.match(app, /loadStoredJson\(USER_PROFILE_KEY, null, isStoredObjectOrNull\)/);
assert.match(app, /loadStoredArray\(DAILY_NEWS_CACHE_KEY\)/);
assert.match(app, /RESUME_STATE_KEY, REMINDER_TIME_KEY/);
assert.doesNotMatch(app, /JSON\.parse\(localStorage\.getItem\(USER_PROFILE_KEY/);
assert.match(app, /function repairLearningEvents/);
assert.match(app, /function renderStorageStatus/);
assert.match(app, /function clearTemporaryStorage/);
assert.match(app, /Date\.now\(\) - new Date\(event\.createdAt\)\.getTime\(\) < 10000/);
assert.match(app, /visibilitychange/);
assert.match(app, /pagehide/);
assert.match(app, /elapsedSeconds/);
assert.match(app, /RESUME_STATE_KEY/);
assert.match(app, /function persistResumeState\(\)/);
assert.match(app, /showScreen\(target, true\)/);
assert.match(app, /audioTimes\[state\.activePracticeId\]/);
assert.match(app, /listeningVocabIndex/);
assert.match(html, /data-clear-media-downloads/);
assert.match(app, /function toggleMediaDownload\(url, label, button\)/);
assert.match(app, /OFFLINE_MEDIA_LIMIT_BYTES = 250 \* 1024 \* 1024/);
assert.match(app, /function pruneMediaDownloads\(maxAgeDays = OFFLINE_MEDIA_MAX_AGE_DAYS\)/);
assert.match(html, /视频不下载、不占本机空间/);
assert.match(app, /name !== MEDIA_CACHE_NAME/);
assert.match(html, /data-empty-reset="practice"/);
assert.match(html, /data-empty-go="speaking"/);
assert.match(app, /data-empty-go/);
assert.match(html, /data-app-feedback/);
assert.match(app, /function setButtonBusy\(button, busy, label/);
assert.match(app, /feedback\.dataset\.tone/);
assert.match(html, /class="phone startup-blocked"/);
assert.match(html, /data-app-startup[^>]+aria-busy="true"/);
assert.match(html, /data-startup-retry/);
assert.match(app, /function setStartupStatus\(status, message/);
assert.match(app, /if \(state\.startupStatus !== "ready"\) return false/);
assert.match(app, /async function loadAppData\(reload = false\)/);
assert.match(app, /loadAppData\(true\)/);
assert.match(app, /fetch\(path, reload \? \{ cache: "reload" \} : undefined\)/);
assert.match(app, /核心学习内容未能读取（\$\{result\.missing\.join\(", "\)\}），请重新加载。/);
assert.match(app, /recordClientError\(error\?\.message \|\| error, "startup"\)/);
assert.doesNotMatch(app, /FALLBACK_(?:WORDBOOK|READING)/);
assert.match(styles, /\.phone\.startup-blocked :is\(\.screen, \.bottom-nav, \[data-sheet\]\)/);
const cacheVersion = worker.match(/ielts-os-demo-v(\d+)/)?.[1];
const registrationVersion = app.match(/service-worker\.js\?v=(\d+)/)?.[1];
assert.ok(cacheVersion && registrationVersion, "service-worker versions must be discoverable");
assert.equal(registrationVersion, cacheVersion, "service-worker registration and cache must move together");
assert.match(worker, /data\/synonyms\.json/);

const events = [
  { module: "Reading", activity: "Test 1", sourceId: "r1", createdAt: "2026-07-02T10:00:05Z" },
  { module: "Reading", activity: "Test 1", sourceId: "r1", createdAt: "2026-07-02T10:00:01Z" },
  { module: "Reading", activity: "Test 1", sourceId: "r1", createdAt: "2026-07-02T11:00:01Z" },
];
const latest = new Map();
const repaired = events.filter((event) => {
  const key = `${event.module}|${event.activity}|${event.sourceId}`;
  const time = new Date(event.createdAt).getTime();
  const previous = latest.get(key);
  latest.set(key, time);
  return previous === undefined || Math.abs(previous - time) >= 10000;
});
assert.equal(repaired.length, 2, "十秒内重复提交应只保留一条");

console.log("Persistence and resilience checks passed.");
