import assert from "node:assert/strict";
import test from "node:test";
import { RouteUserRequest } from "../../src/application/route-user-request.ts";
import type { RequestIntentClassifier } from "../../src/shared/request-intent-classifier.ts";
import type { RobotDevelopmentMode } from "../../src/domain/orchestration-mode.ts";

const mode: RobotDevelopmentMode = {
	id: "development",
	name: "机器人研发模式",
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
	deliveryAgentIds: [],
	acceptanceAgentIds: [],
};

const configuration = {
	autoStartConfidence: 0.9,
	timeoutSeconds: 10,
	developmentScope: "只支持机器人动作包研发",
};

test("an exact greeting is answered without invoking the classifier Agent", async () => {
	let classifierCalls = 0;
	const classifier: RequestIntentClassifier = {
		async classify() {
			classifierCalls++;
			throw new Error("must not be called");
		},
	};
	const decision = await new RouteUserRequest(classifier, configuration).execute({ request: "你好", mode });
	assert.equal(classifierCalls, 0);
	assert.equal(decision.kind, "conversation");
	assert.match(decision.userMessage ?? "", /研发流程未启动|机器人研发模式/);
});

test("English fast-path conversation replies stay English without invoking the classifier", async () => {
	let classifierCalls = 0;
	const classifier: RequestIntentClassifier = {
		async classify() {
			classifierCalls++;
			throw new Error("must not be called");
		},
	};
	const greeting = await new RouteUserRequest(classifier, configuration, "en").execute({ request: "Hello", mode });
	const thanks = await new RouteUserRequest(classifier, configuration, "en").execute({ request: "Thank you", mode });
	assert.equal(classifierCalls, 0);
	assert.match(greeting.userMessage ?? "", /robot development mode/i);
	assert.match(thanks.userMessage ?? "", /workflow was started/i);
	assert.doesNotMatch(`${greeting.userMessage}${thanks.userMessage}`, /[一-鿿]/u);
});

test("a mixed greeting and explicit change is routed by semantic intent instead of greeting keywords", async () => {
	let seenRequest = "";
	const classifier: RequestIntentClassifier = {
		async classify(input) {
			seenRequest = input.request;
			return {
				kind: "development",
				confidence: 0.97,
				normalizedRequest: "新增挥动右手动作",
				reasonCode: "explicit-supported-change",
			};
		},
	};
	const decision = await new RouteUserRequest(classifier, configuration).execute({
		request: "你好，帮我增加一个挥右手动作",
		mode,
	});
	assert.equal(seenRequest, "你好，帮我增加一个挥右手动作");
	assert.equal(decision.kind, "development");
	if (decision.kind === "development") assert.equal(decision.normalizedRequest, "新增挥动右手动作");
});

test("low-confidence development intent asks before granting workflow authority", async () => {
	const classifier: RequestIntentClassifier = {
		async classify() {
			return {
				kind: "development",
				confidence: 0.7,
				normalizedRequest: "优化动作",
				reasonCode: "possible-change",
			};
		},
	};
	const decision = await new RouteUserRequest(classifier, configuration).execute({ request: "帮我优化一下", mode });
	assert.equal(decision.kind, "clarification");
	assert.equal(decision.reasonCode, "development-confidence-below-threshold");
});

test("classifier failures fail closed as clarification", async () => {
	const events: string[] = [];
	const classifier: RequestIntentClassifier = { async classify() { throw new Error("model unavailable"); } };
	const decision = await new RouteUserRequest(classifier, configuration).execute({
		request: "处理一下",
		mode,
		onEvent: (event) => events.push(event.type),
	});
	assert.equal(decision.kind, "clarification");
	assert.equal(decision.reasonCode, "classifier-failed");
	assert.deepEqual(events, ["intent-classification-started", "intent-classification-failed"]);
});

test("English routing passes locale to the classifier and localizes fallback questions", async () => {
	let seenLocale: string | undefined;
	let seenCapability = "";
	const classifier: RequestIntentClassifier = {
		async classify(input) {
			seenLocale = input.locale;
			seenCapability = input.capabilities[0]?.description ?? "";
			throw new Error("model unavailable");
		},
	};
	const decision = await new RouteUserRequest(classifier, configuration, "en").execute({
		request: "Handle this",
		mode,
	});
	assert.equal(seenLocale, "en");
	assert.match(seenCapability, /Deliverable:/);
	assert.equal(decision.kind, "clarification");
	if (decision.kind === "clarification") {
		assert.match(decision.question, /Do you want to add, change, or fix/i);
		assert.doesNotMatch(decision.question, /[一-鿿]/u);
	}
});

test("low-confidence English development intent asks an English confirmation question", async () => {
	const classifier: RequestIntentClassifier = {
		async classify() {
			return {
				kind: "development",
				confidence: 0.7,
				normalizedRequest: "Improve the action",
				reasonCode: "possible-change",
			};
		},
	};
	const decision = await new RouteUserRequest(classifier, configuration, "en").execute({ request: "Improve it", mode });
	assert.equal(decision.kind, "clarification");
	if (decision.kind === "clarification") {
		assert.match(decision.question, /start the development workflow/i);
		assert.doesNotMatch(decision.question, /[一-鿿]/u);
	}
});

test("explicit development override bypasses classification", async () => {
	let classifierCalls = 0;
	const classifier: RequestIntentClassifier = {
		async classify() {
			classifierCalls++;
			throw new Error("must not be called");
		},
	};
	const decision = await new RouteUserRequest(classifier, configuration).execute({
		request: "新增点头动作",
		mode,
		forceDevelopment: true,
	});
	assert.equal(classifierCalls, 0);
	assert.equal(decision.kind, "development");
	assert.equal(decision.reasonCode, "explicit-development-override");
});
