import assert from "node:assert/strict";
import test from "node:test";
import type { AgentProfile } from "../../../src/domain/agent-profile.ts";
import type { RobotApplicationMode, RobotDevelopmentMode } from "../../../src/domain/orchestration-mode.ts";
import {
	shouldDisplayAgentLifecycle,
	shouldDisplayWorkflowProgress,
	workflowProgressReport,
	workflowStageLabel,
} from "../../../src/api/tui/workflow-progress.ts";

const profiles: readonly AgentProfile[] = ["test", "coding", "verification", "deploy"].map((id) => ({
	id,
	name: `${id} Agent`,
	description: id,
	tools: [],
	skills: [],
	systemPrompt: id,
	writePaths: [],
	timeoutSeconds: 60,
}));

const mode: RobotDevelopmentMode = {
	id: "development",
	name: "研发模式",
	type: "robot-development",
	loops: [{
		id: "action-package",
		name: "动作包 TDD",
		deliverable: "动作包",
		testAgentId: "test",
		codingAgentId: "coding",
		verificationAgentId: "verification",
		maxIterations: 3,
	}],
	deliveryAgentIds: ["deploy"],
	acceptanceAgentIds: [],
};

const applicationMode: RobotApplicationMode = {
	id: "application",
	name: "应用模式",
	type: "robot-application",
	agentId: "deploy",
};

test("application mode never displays a workflow progress panel for its single execution step", () => {
	assert.equal(shouldDisplayWorkflowProgress(applicationMode, false), false);
	assert.equal(shouldDisplayWorkflowProgress(applicationMode, true), false);
	assert.equal(shouldDisplayAgentLifecycle(applicationMode), false);
	assert.equal(shouldDisplayWorkflowProgress(mode, false), false);
	assert.equal(shouldDisplayWorkflowProgress(mode, true), true);
	assert.equal(shouldDisplayAgentLifecycle(mode), true);
});

test("progress report makes the active loop, agent, iteration, and total progress explicit", () => {
	const report = workflowProgressReport({
		mode,
		profiles,
		statuses: new Map([
			["action-package", "running"],
			["test", "succeeded"],
			["coding", "running"],
			["verification", "pending"],
			["deploy", "pending"],
		]),
		loopIteration: { loopId: "action-package", loopName: "动作包 TDD", iteration: 2, maxIterations: 3 },
	});

	assert.match(report, /研发工作进展/);
	assert.match(report, /整体进度[\s\S]*0\/2 节点 · 0%/);
	assert.match(report, /当前节点  动作包 TDD · 第 2\/3 轮/);
	assert.match(report, /当前 Agent  coding Agent/);
	assert.match(report, /本轮 Agent 进度[\s\S]*1\/3 Agent/);
	assert.match(report, /✓ test Agent/);
	assert.match(report, /▶ coding Agent/);
	assert.match(report, /○ 2\. deploy Agent/);
});

test("progress report renders deterministic labels in English", () => {
	const englishMode: RobotDevelopmentMode = {
		...mode,
		name: "Development Mode",
		loops: [{ ...mode.loops[0]!, name: "Action Package TDD", deliverable: "action package" }],
	};
	const report = workflowProgressReport({
		mode: englishMode,
		profiles,
		statuses: new Map([
			["action-package", "running"],
			["test", "succeeded"],
			["coding", "running"],
			["verification", "pending"],
			["deploy", "pending"],
		]),
		loopIteration: { loopId: "action-package", loopName: "Action Package TDD", iteration: 2, maxIterations: 3 },
		locale: "en",
	});

	assert.match(report, /Development Progress/);
	assert.match(report, /Overall progress[\s\S]*0\/2 nodes · 0%/);
	assert.match(report, /Current node  Action Package TDD · iteration 2\/3/);
	assert.match(report, /Current Agent  coding Agent/);
	assert.match(report, /Iteration Agent progress[\s\S]*1\/3 Agent/);
	assert.match(report, /Execution path/);
	assert.doesNotMatch(report, /研发工作进展|整体进度|当前节点|执行路径/);
});

test("compact progress keeps the overall and current status visible without the long execution path", () => {
	const report = workflowProgressReport({
		mode,
		profiles,
		statuses: new Map([
			["action-package", "succeeded"],
			["deploy", "running"],
		]),
		compact: true,
	});

	assert.match(report, /整体[\s\S]*1\/2 节点 · 50%/);
	assert.match(report, /节点  deploy Agent/);
	assert.match(report, /Agent  deploy Agent/);
	assert.doesNotMatch(report, /执行路径/);
	assert.ok(report.split("\n").length <= 5);
});

test("a stopped workflow reports the failed node instead of the next pending node", () => {
	const report = workflowProgressReport({
		mode,
		profiles,
		statuses: new Map([
			["action-package", "failed"],
			["verification", "failed"],
			["deploy", "pending"],
		]),
		compact: true,
	});

	assert.match(report, /节点  动作包 TDD（失败）/);
	assert.match(report, /Agent  verification Agent（失败）/);
	assert.doesNotMatch(report, /节点  deploy Agent/);
});

test("loop ids are rendered as human-readable workflow nodes", () => {
	assert.equal(workflowStageLabel(mode, profiles, "action-package"), "动作包 TDD");
	assert.equal(workflowStageLabel(mode, profiles, "deploy"), "deploy Agent");
});
