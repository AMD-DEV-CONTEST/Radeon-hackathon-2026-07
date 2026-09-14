import assert from "node:assert/strict";
import test from "node:test";
import { DeliveryWorkflow } from "../../src/domain/workflow.ts";

test("workflow requires each preceding hand-off to succeed", () => {
	const workflow = new DeliveryWorkflow(["code-author", "cli-delivery", "skill-delivery", "acceptance"]);
	assert.throws(() => workflow.start("cli-delivery"), /code-author/);
	workflow.start("code-author");
	workflow.succeed("code-author", "command ready");
	workflow.start("cli-delivery");
	assert.equal(workflow.snapshot()[1]?.status, "running");
});

test("failed hand-off is preserved in the workflow snapshot", () => {
	const workflow = new DeliveryWorkflow(["code-author", "cli-delivery", "skill-delivery", "acceptance"]);
	workflow.start("code-author");
	workflow.fail("code-author", "missing atomic capability");
	assert.deepEqual(workflow.snapshot()[0], {
		id: "code-author",
		status: "failed",
		detail: "missing atomic capability",
	});
});
