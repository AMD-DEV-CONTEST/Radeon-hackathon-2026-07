import assert from "node:assert/strict";
import test from "node:test";
import { runHeadless } from "../../../src/api/cli/headless-runner.ts";
import type { AgentProfile } from "../../../src/domain/agent-profile.ts";
import type { RobotApplicationMode, RobotDevelopmentMode } from "../../../src/domain/orchestration-mode.ts";
import type { AgentConfiguration } from "../../../src/shared/agent-configuration.ts";
import type { AgentRunner } from "../../../src/shared/agent-runner.ts";
import type { RequestIntentClassifier } from "../../../src/shared/request-intent-classifier.ts";

const profiles: readonly AgentProfile[] = ["test", "coding", "verification"].map((id) => ({
	id,
	name: id,
	description: id,
	tools: [],
	skills: [],
	systemPrompt: id,
	writePaths: [],
	timeoutSeconds: 30,
}));

const mode: RobotDevelopmentMode = {
	id: "development",
	name: "研发模式",
	type: "robot-development",
	loops: [{
		id: "action",
		name: "动作 TDD",
		deliverable: "动作包",
		testAgentId: "test",
		codingAgentId: "coding",
		verificationAgentId: "verification",
		maxIterations: 2,
	}],
	deliveryAgentIds: [],
	acceptanceAgentIds: [],
};

const applicationMode: RobotApplicationMode = {
	id: "application",
	name: "应用模式",
	type: "robot-application",
	agentId: "test",
};

const configuration: AgentConfiguration = {
	configDirectory: "/tmp/config",
	skillDirectory: "/tmp/skills",
	profiles,
	modes: [mode],
	defaultModeId: mode.id,
	workspace: { kind: "current-directory", requiredPaths: [] },
	intake: { autoStartConfidence: 0.9, timeoutSeconds: 10, developmentScope: "动作包" },
};

const workspace = { root: "/tmp", kind: "external" as const, description: "test", created: false };

test("headless greeting is handled without starting any development Agent", async () => {
	let agentCalls = 0;
	let classifierCalls = 0;
	let output = "";
	const agentRunner: AgentRunner = {
		async run() {
			agentCalls++;
			throw new Error("must not run");
		},
	};
	const intentClassifier: RequestIntentClassifier = {
		async classify() {
			classifierCalls++;
			throw new Error("exact greeting should use the deterministic fast path");
		},
	};
	const greetingConfiguration: AgentConfiguration = {
		...configuration,
		workspace: { kind: "current-directory", requiredPaths: ["definitely-missing-development-file"] },
	};
	const succeeded = await runHeadless(workspace, greetingConfiguration, mode.id, "你好", {
		agentRunner,
		intentClassifier,
		write: (text) => { output += text; },
	});
	assert.equal(succeeded, true);
	assert.equal(classifierCalls, 0);
	assert.equal(agentCalls, 0);
	assert.match(output, /非研发对话/);
	assert.match(output, /研发流程未启动/);
});

test("headless development starts the workflow only after semantic routing", async () => {
	const agentRequests: string[] = [];
	let output = "";
	const agentRunner: AgentRunner = {
		async run(request) {
			agentRequests.push(request.userRequest);
			return { summary: `${request.profile.id} done`, outcome: "completed" };
		},
	};
	const intentClassifier: RequestIntentClassifier = {
		async classify() {
			return {
				kind: "development",
				confidence: 0.98,
				// Deliberately contradictory: routing must never rewrite the user's authorized direction.
				normalizedRequest: "开发一个挥动右手的功能",
				reasonCode: "explicit-supported-change",
			};
		},
	};
	const originalRequest = "开发一个挥动左手的功能";
	const succeeded = await runHeadless(workspace, configuration, mode.id, originalRequest, {
		agentRunner,
		intentClassifier,
		write: (text) => { output += text; },
	});
	assert.equal(succeeded, true);
	assert.deepEqual(agentRequests, [originalRequest, originalRequest, originalRequest]);
	assert.match(output, /已确认该用户指令需要启动研发流程/);
	assert.match(output, /用户指令：开发一个挥动左手的功能/);
	assert.doesNotMatch(output, /(?:^|\n)需求：/);
});

test("headless clarification does not start the workflow", async () => {
	let agentCalls = 0;
	const agentRunner: AgentRunner = {
		async run() {
			agentCalls++;
			throw new Error("must not run");
		},
	};
	const intentClassifier: RequestIntentClassifier = {
		async classify() {
			return { kind: "clarification", confidence: 0.4, question: "要修改哪个动作？", reasonCode: "ambiguous" };
		},
	};
	const succeeded = await runHeadless(workspace, configuration, mode.id, "帮我优化一下", {
		agentRunner,
		intentClassifier,
		write: () => undefined,
	});
	assert.equal(succeeded, false);
	assert.equal(agentCalls, 0);
});

test("headless application mode labels input as a user instruction without single-step progress", async () => {
	let output = "";
	const agentRunner: AgentRunner = {
		async run(request) {
			request.onEvent({ type: "text", text: "应用执行结果\n" });
			return { summary: "应用执行完成", outcome: "completed" };
		},
	};
	const applicationConfiguration: AgentConfiguration = {
		...configuration,
		modes: [mode, applicationMode],
	};

	const succeeded = await runHeadless(workspace, applicationConfiguration, applicationMode.id, "站起来", {
		agentRunner,
		write: (text) => { output += text; },
	});

	assert.equal(succeeded, true);
	assert.match(output, /用户指令：站起来/);
	assert.match(output, /应用执行结果/);
	assert.match(output, /验收通过：机器人应用效果测试完成/);
	assert.doesNotMatch(output, /\[test\] (?:running|succeeded)/);
	assert.doesNotMatch(output, /工作进展|整体进度|当前节点/);
});

test("headless application mode renders deterministic wrappers in English and preserves Agent text", async () => {
	let output = "";
	const agentRunner: AgentRunner = {
		async run(request) {
			request.onEvent({ type: "text", text: "raw Agent output\n" });
			return { summary: "application completed", outcome: "completed" };
		},
	};
	const englishMode: RobotApplicationMode = {
		...applicationMode,
		name: "Robot Application Mode",
	};
	const applicationConfiguration: AgentConfiguration = {
		...configuration,
		locale: "en",
		modes: [mode, englishMode],
	};

	const succeeded = await runHeadless(workspace, applicationConfiguration, englishMode.id, "Stand up", {
		agentRunner,
		write: (text) => { output += text; },
	});

	assert.equal(succeeded, true);
	assert.match(output, /RDK Agent · Robot Application Mode/);
	assert.match(output, /User request: Stand up/);
	assert.match(output, /raw Agent output/);
	assert.match(output, /Acceptance passed:/);
	assert.doesNotMatch(output, /用户指令：|验收通过：/);
});
