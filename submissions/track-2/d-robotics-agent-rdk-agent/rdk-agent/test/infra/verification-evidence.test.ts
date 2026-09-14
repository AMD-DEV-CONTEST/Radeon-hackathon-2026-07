import assert from "node:assert/strict";
import test from "node:test";
import {
	enforceTestExecutionEvidence,
	enforceVerificationEvidence,
	needsTestExecutionEvidenceRetry,
	testExecutionEvidenceRetryPrompt,
	testExecutionEvidenceRetryPromptForLocale,
	needsVerificationEvidenceRetry,
	verificationEvidenceRetryPrompt,
	verificationEvidenceRetryPromptForLocale,
	type BashExecutionEvidence,
} from "../../src/infra/verification-evidence.ts";

const completed = { summary: "looks good", outcome: "completed" } as const;
const passingTest: BashExecutionEvidence = {
	command: "python3 -m unittest discover -s examples/plugins/servo/servo_actions/wave-right-hand/tests -v",
	output: "Ran 2 tests in 0.1s\n\nOK",
	failed: false,
};
const validRedTest: BashExecutionEvidence = {
	...passingTest,
	output: "NotImplementedError: implement wave-right-hand\nRan 2 tests in 0.1s\nFAILED (errors=1)",
	failed: true,
};
const rejectedLookup: BashExecutionEvidence = {
	command: "ls -1 registry.json 2>/dev/null",
	output: "bash policy rejected command",
	failed: true,
};

test("verification requires a real successful test command", () => {
	assert.equal(enforceVerificationEvidence(completed, "verification", { bash: [] }).outcome, "revision");
	assert.equal(enforceVerificationEvidence(completed, "verification", { bash: [rejectedLookup] }).outcome, "revision");
	assert.equal(enforceVerificationEvidence(completed, "verification", { bash: [passingTest] }), completed);
});

test("a textual verification pass without a test command gets one in-session retry", () => {
	assert.equal(needsVerificationEvidenceRetry(completed, "verification", { bash: [] }), true);
	assert.match(verificationEvidenceRetryPrompt, /必须立即调用 bash 工具/);
	assert.equal(needsVerificationEvidenceRetry(completed, "verification", { bash: [rejectedLookup] }), true);
	assert.equal(needsVerificationEvidenceRetry(completed, "verification", { bash: [passingTest] }), false);
});

test("verification cannot hide an earlier failed test behind a later successful command", () => {
	const result = enforceVerificationEvidence(completed, "verification", {
		bash: [validRedTest, passingTest],
	});
	assert.equal(result.outcome, "revision");
	assert.match(result.feedback ?? "", /测试命令出现失败/);
});

test("test stage requires a relevant test command rather than arbitrary Bash", () => {
	assert.equal(needsTestExecutionEvidenceRetry(completed, "test", true, { bash: [] }), true);
	assert.equal(needsTestExecutionEvidenceRetry(completed, "test", true, { bash: [rejectedLookup] }), true);
	assert.match(testExecutionEvidenceRetryPrompt, /有效红测/);
	assert.equal(enforceTestExecutionEvidence(completed, "test", true, { bash: [] }).outcome, "needs-human");
	assert.equal(enforceTestExecutionEvidence(completed, "test", true, { bash: [validRedTest] }), completed);
});

test("new capability must be scaffolded and red before implementation", () => {
	const context = { userRequest: "Implement a feature for waving the right hand", iteration: 1 };
	const staleGreen = enforceTestExecutionEvidence(
		completed,
		"test",
		true,
		{ bash: [passingTest], scaffoldSucceeded: false },
		context,
	);
	assert.equal(staleGreen.outcome, "needs-human");
	assert.match(staleGreen.question ?? "", /scaffold|历史动作/);

	const unexpectedGreen = enforceTestExecutionEvidence(
		completed,
		"test",
		true,
		{ bash: [passingTest], scaffoldSucceeded: true },
		context,
	);
	assert.equal(unexpectedGreen.outcome, "needs-human");
	assert.match(unexpectedGreen.question ?? "", /意外通过/);

	assert.equal(
		enforceTestExecutionEvidence(
			completed,
			"test",
			true,
			{ bash: [validRedTest], scaffoldSucceeded: true },
			context,
		),
		completed,
	);

	const implicitNewUnexpectedGreen = enforceTestExecutionEvidence(
		completed,
		"test",
		true,
		{ bash: [passingTest], scaffoldSucceeded: true },
		{ userRequest: "让机器人挥动右手", iteration: 1 },
	);
	assert.equal(implicitNewUnexpectedGreen.outcome, "needs-human");
	assert.match(implicitNewUnexpectedGreen.question ?? "", /意外通过/);
});

test("green regression remains valid for maintenance and later iterations", () => {
	assert.equal(
		enforceTestExecutionEvidence(
			completed,
			"test",
			true,
			{ bash: [passingTest], scaffoldSucceeded: false },
			{ userRequest: "Fix the existing wave action", iteration: 1 },
		),
		completed,
	);
	assert.equal(
		enforceTestExecutionEvidence(
			completed,
			"test",
			true,
			{ bash: [passingTest], scaffoldSucceeded: false },
			{ userRequest: "Implement a feature for waving the right hand", iteration: 2 },
		),
		completed,
	);
});

test("a declarative test stage without Bash is not forced to invent an executable check", () => {
	assert.equal(needsTestExecutionEvidenceRetry(completed, "test", false, { bash: [] }), false);
	assert.equal(enforceTestExecutionEvidence(completed, "test", false, { bash: [] }), completed);
});

test("English evidence feedback contains no Chinese prose", () => {
	const testRetry = testExecutionEvidenceRetryPromptForLocale("en");
	const verificationRetry = verificationEvidenceRetryPromptForLocale("en");
	assert.match(testRetry, /Call the bash tool now/);
	assert.match(verificationRetry, /single-line RDK_AGENT_RESULT/);

	const unexpectedGreen = enforceTestExecutionEvidence(
		completed,
		"test",
		true,
		{ bash: [passingTest], scaffoldSucceeded: true },
		{ locale: "en", userRequest: "Implement a new wave action", iteration: 1 },
	);
	const failedVerification = enforceVerificationEvidence(
		completed,
		"verification",
		{ bash: [validRedTest, passingTest] },
		"en",
	);
	assert.match(unexpectedGreen.question ?? "", /passed before implementation/i);
	assert.match(failedVerification.feedback ?? "", /test command failed/i);
	assert.doesNotMatch(`${testRetry}${verificationRetry}${unexpectedGreen.question}${failedVerification.feedback}`, /[一-鿿]/u);
});
