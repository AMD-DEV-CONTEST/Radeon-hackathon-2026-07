import assert from "node:assert/strict";
import test from "node:test";
import { isNewCapabilityRequest } from "../../src/domain/development-intent.ts";

test("detects explicit new-capability requests without treating maintenance as creation", () => {
	for (const request of [
		"开发一个挥动右手的功能",
		"新增点头动作",
		"Implement a feature for waving the right hand",
		"Create a new nod action",
	]) {
		assert.equal(isNewCapabilityRequest(request), true, request);
	}

	for (const request of [
		"修复挥动右手动作",
		"测试现有的点头功能",
		"Fix the wave-right-hand action",
		"Test the existing nod capability",
	]) {
		assert.equal(isNewCapabilityRequest(request), false, request);
	}
});
