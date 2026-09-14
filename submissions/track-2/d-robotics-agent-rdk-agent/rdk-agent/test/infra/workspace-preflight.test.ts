import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { inspectDevelopmentWorkspace } from "../../src/infra/workspace-preflight.ts";

test("development workspace preflight suggests the sibling business repository", (context) => {
	const root = mkdtempSync(join(tmpdir(), "rdk-agent-workspace-preflight-"));
	context.after(() => rmSync(root, { recursive: true, force: true }));
	const agentRoot = join(root, "rdk-agent");
	const businessRoot = join(root, "rdk-sophon");
	mkdirSync(agentRoot);
	mkdirSync(join(businessRoot, "examples", "plugins", "servo"), { recursive: true });
	writeFileSync(join(businessRoot, "examples", "plugins", "servo", "servo_ctrl.py"), "");

	const required = ["examples/plugins/servo/servo_ctrl.py"];
	assert.deepEqual(inspectDevelopmentWorkspace(agentRoot, required), {
		root: agentRoot,
		missingPaths: required,
		suggestedRoot: businessRoot,
	});
	assert.equal(inspectDevelopmentWorkspace(businessRoot, required), undefined);
});
