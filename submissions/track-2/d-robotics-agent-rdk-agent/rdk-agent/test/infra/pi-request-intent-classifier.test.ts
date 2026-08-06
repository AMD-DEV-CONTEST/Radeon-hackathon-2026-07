import assert from "node:assert/strict";
import test from "node:test";
import { parseIntentClassifierResult } from "../../src/infra/pi-request-intent-classifier.ts";

test("parses every supported intent result with strict fields", () => {
	assert.deepEqual(
		parseIntentClassifierResult('RDK_INTENT_RESULT: {"kind":"development","confidence":0.96,"normalizedRequest":"新增挥手动作","reasonCode":"explicit"}'),
		{ kind: "development", confidence: 0.96, normalizedRequest: "新增挥手动作", reasonCode: "explicit" },
	);
	assert.deepEqual(
		parseIntentClassifierResult('RDK_INTENT_RESULT: {"kind":"conversation","confidence":1,"category":"greeting","reasonCode":"hello"}'),
		{ kind: "conversation", confidence: 1, category: "greeting", reasonCode: "hello" },
	);
	assert.deepEqual(
		parseIntentClassifierResult('RDK_INTENT_RESULT: {"kind":"clarification","confidence":0.5,"question":"是否修改动作？","reasonCode":"ambiguous"}'),
		{ kind: "clarification", confidence: 0.5, question: "是否修改动作？", reasonCode: "ambiguous" },
	);
	assert.deepEqual(
		parseIntentClassifierResult('RDK_INTENT_RESULT: {"kind":"unsupported-development","confidence":0.92,"reason":"不属于动作包","reasonCode":"outside"}'),
		{ kind: "unsupported-development", confidence: 0.92, reason: "不属于动作包", reasonCode: "outside" },
	);
});

test("rejects malformed, unknown, or incomplete classifier output", () => {
	for (const output of [
		"没有结构化标记",
		"RDK_INTENT_RESULT: not-json",
		'RDK_INTENT_RESULT: {"kind":"development","confidence":2,"normalizedRequest":"x","reasonCode":"x"}',
		'RDK_INTENT_RESULT: {"kind":"development","confidence":0.9,"reasonCode":"x"}',
		'RDK_INTENT_RESULT: {"kind":"conversation","confidence":0.9,"category":"invalid","reasonCode":"x"}',
		'RDK_INTENT_RESULT: {"kind":"invented","confidence":0.9,"reasonCode":"x"}',
	]) {
		assert.throws(() => parseIntentClassifierResult(output), { name: "Error" }, output);
	}
});

test("English classifier values and parse failures remain English without changing the marker", () => {
	assert.deepEqual(
		parseIntentClassifierResult(
			'RDK_INTENT_RESULT: {"kind":"clarification","confidence":0.5,"question":"Should I change the action?","reasonCode":"ambiguous"}',
			"en",
		),
		{ kind: "clarification", confidence: 0.5, question: "Should I change the action?", reasonCode: "ambiguous" },
	);
	assert.throws(
		() => parseIntentClassifierResult("missing marker", "en"),
		(error: unknown) => error instanceof Error && /returned no structured result/.test(error.message) && !/[一-鿿]/u.test(error.message),
	);
});
