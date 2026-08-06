import assert from "node:assert/strict";
import test from "node:test";
import type { AgentProfile } from "../../../src/domain/agent-profile.ts";
import { profileSkillStatus, skillReport } from "../../../src/api/tui/skill-view.ts";
import type { AgentSkillInfo } from "../../../src/shared/agent-runner.ts";

const profile: AgentProfile = {
	id: "application",
	name: "机器人应用 Agent",
	description: "test",
	tools: ["read", "bash"],
	skills: ["servo-control", "lamp-control"],
	systemPrompt: "test",
	writePaths: [],
	timeoutSeconds: 60,
	maxToolCalls: 5,
};

const servo: AgentSkillInfo = {
	name: "servo-control",
	description: "servo",
	filePath: "/config/skills/servo-control/SKILL.md",
};

test("Skill status separates configured, loaded and selected Skills", () => {
	assert.equal(
		profileSkillStatus(profile, [servo], [servo]),
		"Skills：配置 servo-control, lamp-control · 已加载 servo-control · 本次选择 servo-control",
	);
	assert.match(profileSkillStatus(profile) ?? "", /已加载 尚未创建会话 · 本次选择 尚未选择/);
});

test("/skills report includes loaded paths and the current selection", () => {
	const report = skillReport(
		[profile],
		new Map([[profile.id, [servo]]]),
		new Map([[profile.id, [servo]]]),
	);
	assert.match(report, /配置：servo-control, lamp-control/);
	assert.match(report, /实际加载：servo-control \(\/config\/skills\/servo-control\/SKILL.md\)/);
	assert.match(report, /本次选择：servo-control/);
});

test("Skill status and report render deterministic labels in English", () => {
	assert.equal(
		profileSkillStatus(profile, [servo], [servo], "en"),
		"Skills: configured servo-control, lamp-control · loaded servo-control · selected servo-control",
	);
	assert.match(profileSkillStatus(profile, undefined, undefined, "en") ?? "", /loaded session not created · selected not selected/);

	const report = skillReport(
		[profile],
		new Map([[profile.id, [servo]]]),
		new Map([[profile.id, [servo]]]),
		"en",
	);
	assert.match(report, /Configured: servo-control, lamp-control/);
	assert.match(report, /Loaded: servo-control \(\/config\/skills\/servo-control\/SKILL\.md\)/);
	assert.match(report, /Selected: servo-control/);
	assert.doesNotMatch(report, /配置：|实际加载：|本次选择：/);
});
