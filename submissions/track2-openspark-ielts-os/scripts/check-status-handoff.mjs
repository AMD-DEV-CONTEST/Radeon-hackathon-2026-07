import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const root = new URL("../", import.meta.url);
const [status, html, worker, app] = await Promise.all([
  readFile(new URL("PROJECT_STATUS.md", root), "utf8"),
  readFile(new URL("index.html", root), "utf8"),
  readFile(new URL("service-worker.js", root), "utf8"),
  readFile(new URL("app.js", root), "utf8"),
]);

const todayParts = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date());
const part = (type) => todayParts.find((item) => item.type === type)?.value;
const today = `${part("year")}-${part("month")}-${part("day")}`;
const batches = {
  "A-consistency": { app: "73", cache: "90", phone: "NOT PERFORMED", breakpoint: "consistency/version contract", next: "Batch B — storage/export/startup recovery" },
  "B-storage-startup": { app: "74", cache: "91", phone: "NOT PERFORMED", breakpoint: "storage/export/startup recovery", next: "Batch C — vocabulary scheduler/workload" },
  "C-word-scheduler": { app: "75", cache: "92", phone: "NOT PERFORMED", breakpoint: "vocabulary scheduler/workload", next: "Batch D — learning signals" },
  "D-learning-signals": { app: "76", cache: "93", phone: "NOT PERFORMED", breakpoint: "learning signals", next: "Real-device verification and remaining content/audio work" },
  "E-navigation-scroll": { app: "77", cache: "94", phone: "v77 INSTALLED; launch verification pending device unlock", breakpoint: "navigation scroll behavior", next: "Finish v77 launch verification, then remaining real-device and content/audio work" },
  "F-production-polish": { app: "78", cache: "95", remote: "18", styles: "60", phone: "NOT PERFORMED (device offline)", breakpoint: "production polish", next: "Real-device v78 verification, then remaining content/audio work" },
};
const batch = status.match(/^Optimization batch: (.+)$/m)?.[1];
const expected = batches[batch];
assert.ok(expected, "Optimization batch marker is absent or invalid");
assert.match(status, new RegExp(`^Last verified: ${today} \\(Asia/Shanghai\\)$`, "m"), "Last verified is stale");
assert.match(status, new RegExp(`^Phone installation: ${expected.phone.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`, "m"), "phone installation marker is missing or stale");

const appVersion = html.match(/app\.js\?v=(\d+)/)?.[1];
const remoteVersion = html.match(/remote-update\.js\?v=(\d+)/)?.[1];
const stylesVersion = html.match(/styles\.css\?v=(\d+)/)?.[1];
const cacheVersion = worker.match(/ielts-os-demo-v(\d+)/)?.[1];
const registrationVersion = app.match(/service-worker\.js\?v=(\d+)/)?.[1];
assert.deepEqual({ appVersion, cacheVersion }, { appVersion: expected.app, cacheVersion: expected.cache }, "status batch does not match source release versions");
if (expected.remote) assert.equal(remoteVersion, expected.remote, "status batch does not match remote release version");
if (expected.styles) assert.equal(stylesVersion, expected.styles, "status batch does not match styles release version");
assert.equal(registrationVersion, cacheVersion, "service-worker registration/cache version mismatch");
assert.match(status, new RegExp(`^Current release versions: app v${appVersion} / remote v${remoteVersion} / styles v${stylesVersion} / shell cache v${cacheVersion}$`, "m"), "current release version line is missing or stale");

for (const command of ["npm run check", "npm run build", "npx cap sync ios"]) {
  assert.match(status, new RegExp(`^${command.replace(/[.*+?^${}()|[\\]\\]/g, "\\$&")} — PASSED ${today} \\(Batch ${batch[0]} `, "m"), `${command} release evidence is missing`);
}
assert.match(status, new RegExp(`^source / dist / ios public checksums — MATCHED ${today} \\(Batch ${batch[0]} `, "m"), "release parity evidence is missing");

const breakpointSection = status.match(/## Current breakpoint\n([\s\S]*?)(?=\n## )/)?.[1] || "";
assert.ok(breakpointSection.includes(expected.breakpoint), "Current breakpoint completed label is missing");
const nextSection = status.match(/## Next concrete task\n([\s\S]*?)(?=\n## )/)?.[1] || "";
assert.equal(nextSection.trim().split(/\n+/)[0], expected.next, "Next concrete task does not match the active batch");

for (const marker of [
  "npm run check — PASSED 2026-07-25 (speaking native transcribe + word mixed-quiz release",
  "scripts/reinstall-phone.sh created — 2026-07-25",
  "git baseline commit 7a416ff — 2026-07-25",
  "sign + CDHash verification via reinstall-phone.sh — PASSED 2026-07-25",
]) assert.ok(status.includes(marker), `historical handoff marker was removed: ${marker}`);

console.log(`Project handoff status matches ${batch}.`);
