import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

function versionDiff(currentText, previousText) {
  const words = (text) => String(text).toLowerCase().match(/[a-z]+/g) || [];
  const current = words(currentText);
  const previous = words(previousText);
  return {
    wordDelta: current.length - previous.length,
    added: [...new Set(current.filter((word) => !previous.includes(word)))],
    removed: [...new Set(previous.filter((word) => !current.includes(word)))],
  };
}

const diff = versionDiff("Public transport is more reliable.", "Public transport is useful.");
assert.equal(diff.wordDelta, 1);
assert.deepEqual(diff.added, ["more", "reliable"]);
assert.deepEqual(diff.removed, ["useful"]);

const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
const app = readFileSync(new URL("../app.js", import.meta.url), "utf8");
const remote = readFileSync(new URL("../remote-update.js", import.meta.url), "utf8");
const writing = JSON.parse(readFileSync(new URL("../data/writing.json", import.meta.url), "utf8"));
// Original sample tasks only; commercial prompts and figures stay personal.
assert.ok(writing.tasks.length >= 5, "sample writing tasks should exist");
assert.ok(writing.tasks.every((task) => task.prompt && task.minimumWords >= 150));
assert.match(html, /data-writing-mode="write"/);
assert.match(html, /data-writing-mode="feedback"/);
assert.match(html, /data-writing-mode="history"/);
assert.match(html, /data-writing-paper/);
assert.match(html, /data-writing-validation/);
assert.match(app, /function renderWritingMode\(\)/);
assert.match(app, /function bindWritingControls\(\)/);
assert.match(app, /function renderWritingSubmitState\(task, draft\)/);
assert.match(app, /查看写作提纲（计为辅助）/);
assert.match(app, /class="writing-paper"/);
assert.doesNotMatch(app, /analysis\.scores/);
assert.match(app, /copy\.innerHTML = renderAgentMarkdown\(aiText\)/);
assert.match(app, /showOutputDebrief\?\.\(\{ module: "写作"/);
assert.match(app, /actionLabel: "按重点修改下一稿", target: "writing"/);
assert.match(remote, /摘要只来自本轮可观察记录，不生成雅思分数/);
assert.match(remote, /data-writing-mode="write"/);

console.log("Writing version comparison check passed.");
