import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

function average(values) {
  return Math.round(values.reduce((sum, value) => sum + value, 0) / values.length * 2) / 2;
}

function recordingMetrics(transcript, duration) {
  const words = (String(transcript).match(/[A-Za-z]+/g) || []).length;
  return { words, duration, wordsPerMinute: Math.round(words / Math.max(1, duration) * 60) };
}

assert.equal(average([5.5, 6, 5.5, 6]), 6);
assert.deepEqual(recordingMetrics("I like it because public transport is reliable.", 30), { words: 8, duration: 30, wordsPerMinute: 16 });

const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
const app = readFileSync(new URL("../app.js", import.meta.url), "utf8");
const remote = readFileSync(new URL("../remote-update.js", import.meta.url), "utf8");
assert.match(html, /data-speaking-mode="conversation"/);
assert.match(html, /data-speaking-mode="review"/);
assert.match(html, /data-speaking-mode="history"/);
assert.match(html, /data-ai-memory/);
assert.match(html, /data-ai-live/);
assert.match(html, /data-ai-live-cloud/);
assert.match(html, /data-ai-live-finish/);
assert.match(app, /data-speaking-export-record/);
assert.match(app, /function exportSpeakingRecording\(recording\)/);
assert.match(app, /data-speaking-edit-record/);
assert.match(app, /function saveSpeakingTranscript\(recording, value\)/);
assert.match(app, /data-speaking-save-transcript/);
assert.match(app, /recording\.audio\.type\.includes\("mp4"\)/);
assert.match(app, /function renderSpeakingMode\(\)/);
assert.match(app, /const AI_MEMORY_KEY = "ielts-os\.aiMemory\.v1"/);
assert.match(app, /function learningMemorySnapshot\(\)/);
assert.match(app, /结束并复盘/);
assert.match(app, /window\.SpeechRecognition \|\| window\.webkitSpeechRecognition/);
assert.match(app, /recognition\.lang = "en-US"/);
assert.match(app, /native\.speak\(\{ text, language: "en-US", wait: true \}\)/);
assert.match(app, /utterance\.lang = "en-US"/);
assert.match(app, /return beginAiListening\(\)/);
assert.match(app, /sendAiChatTurn\(text\)/);
assert.match(app, /requestAI\("speaking_debrief"/);
assert.match(app, /activity: "AI 实时对练与复盘"/);
assert.match(app, /function renderAiLive\(\)/);
assert.match(app, /sessionMeta: \{ durationSeconds, answerTurns: userTurns\.length \}/);
assert.match(app, /classList\.toggle\("ai-live-open", aiChat\.live\)/);
assert.match(app, /showOutputDebrief\?\.\(\{ module: "口语"/);
assert.match(app, /actionLabel: "回听并自评", target: "speaking", audio: recording\.audio/);
assert.match(remote, /const mountSpeakingRoundReview/);
assert.match(remote, /data-speaking-round-review/);
assert.match(remote, /时长与转写词数只用于复盘，不等于雅思分数/);

console.log("Speaking self-review and comparison check passed.");
