import assert from "node:assert/strict";
import test from "node:test";
import { agentEndBanner, agentLifecycleLogEntry, agentStartBanner } from "../../../src/api/tui/tui-style.ts";

test("Agent lifecycle banners expose distinct start/end markers, timestamps, and elapsed time", () => {
	const startedAt = new Date("2026-08-05T10:00:00+08:00").getTime();
	const finishedAt = startedAt + 65_000;
	const start = agentStartBanner("动作实现 Agent", startedAt);
	const end = agentEndBanner("动作实现 Agent", "succeeded", finishedAt, startedAt);
	assert.match(start, /▶▶ AGENT 开始 · 动作实现 Agent · \d{2}:\d{2}:\d{2}/);
	assert.match(end, /✓✓ AGENT 完成 · 动作实现 Agent · \d{2}:\d{2}:\d{2} · 用时 1分5秒/);
});

test("failed Agent lifecycle uses an unmistakable failure marker", () => {
	assert.match(agentEndBanner("动作验证 Agent", "failed", Date.now()), /✗✗ AGENT 失败/);
});

test("Agent lifecycle banners render labels and durations in English", () => {
	const startedAt = new Date("2026-08-05T10:00:00+08:00").getTime();
	const finishedAt = startedAt + 65_000;
	const start = agentStartBanner("Coding Agent", startedAt, false, "en");
	const end = agentEndBanner("Coding Agent", "succeeded", finishedAt, startedAt, false, "en");
	assert.match(start, /▶▶ AGENT STARTED · Coding Agent · \d{2}:\d{2}:\d{2}/);
	assert.match(end, /✓✓ AGENT COMPLETED · Coding Agent · \d{2}:\d{2}:\d{2} · elapsed 1m 5s/);
	assert.doesNotMatch(`${start}\n${end}`, /开始|完成|用时/);
});

test("Agent lifecycle banners use ANSI colors when the terminal supports them", () => {
	const coloredStart = agentStartBanner("动作实现 Agent", Date.now(), true);
	const coloredEnd = agentEndBanner("动作实现 Agent", "succeeded", Date.now(), undefined, true);
	assert.match(coloredStart, /\u001b\[/);
	assert.match(coloredEnd, /\u001b\[/);
});

test("Agent lifecycle log entries leave blank lines around start and end markers", () => {
	assert.equal(agentLifecycleLogEntry("▶▶ AGENT 开始"), "\n\n▶▶ AGENT 开始\n\n");
	assert.equal(agentLifecycleLogEntry("✓✓ AGENT 完成"), "\n\n✓✓ AGENT 完成\n\n");
});
