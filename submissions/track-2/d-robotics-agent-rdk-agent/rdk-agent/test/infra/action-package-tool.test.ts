import assert from "node:assert/strict";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import type { AgentProfile } from "../../src/domain/agent-profile.ts";
import {
	assertActionPackageDirectionConsistent,
	assertActionRegistryContentDirectionConsistent,
	assertActionPythonContentDirectionConsistent,
	createActionPackageToolDefinition,
	requestedActionDirection,
} from "../../src/infra/action-package-tool.ts";

const scaffoldProfile: AgentProfile = {
	id: "action-test",
	name: "Action test",
	description: "test",
	tools: ["action-package"],
	skills: [],
	systemPrompt: "test",
	writePaths: [],
	timeoutSeconds: 30,
	actionPackage: { operations: ["scaffold"] },
};

test("extracts only explicit and unambiguous requested action directions", () => {
	assert.equal(requestedActionDirection("开发一个挥动左手的功能"), "left");
	assert.equal(requestedActionDirection("Please wave the right hand"), "right");
	assert.equal(requestedActionDirection("同时抬起左右手"), "both");
	assert.equal(requestedActionDirection("把挥动右手改成挥动左手"), "left");
	assert.equal(requestedActionDirection("不要挥右手，只挥左手"), "left");
	assert.equal(requestedActionDirection("开发一个挥手功能"), undefined);
});

test("direction guard rejects every inconsistent scaffold metadata field", () => {
	const leftMetadata = {
		actionId: "wave-left-hand",
		description: "挥动左手",
		start: "left" as const,
		intentExamples: ["挥一下左手"],
	};
	assert.doesNotThrow(() => assertActionPackageDirectionConsistent("开发一个挥动左手的功能", leftMetadata));
	assert.throws(
		() => assertActionPackageDirectionConsistent("开发一个挥动左手的功能", { ...leftMetadata, actionId: "wave-right-hand" }),
		/ACTION-DIRECTION-001.*actionId/s,
	);
	assert.throws(
		() => assertActionPackageDirectionConsistent("开发一个挥动左手的功能", { ...leftMetadata, start: "right" }),
		/ACTION-DIRECTION-001.*start/s,
	);
	assert.throws(
		() => assertActionPackageDirectionConsistent("开发一个挥动左手的功能", { ...leftMetadata, description: "挥动右手" }),
		/ACTION-DIRECTION-001.*description/s,
	);
	assert.throws(
		() => assertActionPackageDirectionConsistent("开发一个挥动左手的功能", { ...leftMetadata, intentExamples: ["挥一下右手"] }),
		/ACTION-DIRECTION-001.*intentExamples/s,
	);
	assert.throws(
		() => assertActionPackageDirectionConsistent("开发一个挥动左手的功能", { ...leftMetadata, actionId: "wave-hand" }),
		/ACTION-DIRECTION-001.*actionId/s,
	);
});

test("non-directional requests remain compatible with existing scaffold metadata", () => {
	assert.doesNotThrow(() => assertActionPackageDirectionConsistent("开发一个点头功能", {
		actionId: "nod-head",
		description: "点头",
		start: "none",
		intentExamples: ["点一下头"],
	}));
});

test("Python content guard rejects only real opposite-side context bridge calls", () => {
	const leftRequest = "开发一个挥动左手的功能";
	const leftPath = "examples/plugins/servo/servo_actions/wave-left-hand/action.py";
	assert.doesNotThrow(() => assertActionPythonContentDirectionConsistent(
		leftRequest,
		leftPath,
		"def run(context, params):\n    context.lift_left()\n    context.lower_left()\n",
	));
	assert.throws(
		() => assertActionPythonContentDirectionConsistent(
			leftRequest,
			leftPath,
			"def run(context, params):\n    context.lift_right()\n",
		),
		/ACTION-DIRECTION-001.*context\.lift_right/s,
	);
	assert.throws(
		() => assertActionPythonContentDirectionConsistent(
			"开发一个挥动右手的功能",
			"examples/plugins/servo/servo_actions/wave-right-hand/action.py",
			"def run(context, params):\n    context.lower_left ()\n",
		),
		/ACTION-DIRECTION-001.*context\.lower_left/s,
	);
});

test("Python content guard ignores comments, strings and negative test assertions", () => {
	const content = `"""The forbidden example is context.lift_right()."""
# Never call context.lower_right().
EXPECTED = "context.lift_right()"

def test_left_only(context):
    assert "lift_right" not in context.calls
    other.context.lower_right()
`;
	assert.doesNotThrow(() => assertActionPythonContentDirectionConsistent(
		"开发一个挥动左手的功能",
		"examples/plugins/servo/servo_actions/wave-left-hand/tests/test_action.py",
		content,
	));
});

test("Python content guard keeps both-side, non-directional and non-Python writes compatible", () => {
	const rightCall = "def run(context, params):\n    context.lift_right()\n";
	assert.doesNotThrow(() => assertActionPythonContentDirectionConsistent(
		"开发一个挥动双手的功能",
		"examples/plugins/servo/servo_actions/wave-hands/action.py",
		rightCall,
	));
	assert.doesNotThrow(() => assertActionPythonContentDirectionConsistent(
		"开发一个点头功能",
		"examples/plugins/servo/servo_actions/nod-head/action.py",
		rightCall,
	));
	assert.doesNotThrow(() => assertActionPythonContentDirectionConsistent(
		"开发一个挥动左手的功能",
		"examples/plugins/servo/servo_actions/wave-left-hand/registry.json",
		'{"example":"context.lift_right()"}',
	));
});

test("registry content guard rejects rewritten metadata with the wrong direction", () => {
	const path = "examples/plugins/servo/servo_actions/wave-left-hand/registry.json";
	const registry = {
		schema: "rdk-servo-action/v1",
		id: "wave-left-hand",
		description: "挥动左手",
		entrypoint: "action.py:run",
		start: "left",
		skill: { intentExamples: ["挥一下左手"], risk: "motion" },
		arguments: [],
	};
	assert.doesNotThrow(() => assertActionRegistryContentDirectionConsistent(
		"开发一个挥动左手的功能",
		path,
		JSON.stringify(registry),
	));
	for (const [field, changed] of [
		["registry.json.id", { ...registry, id: "wave-right-hand" }],
		["registry.json.start", { ...registry, start: "right" }],
		["registry.json.description", { ...registry, description: "挥动右手" }],
		["registry.json.skill.intentExamples", { ...registry, skill: { ...registry.skill, intentExamples: ["挥一下右手"] } }],
	] as const) {
		assert.throws(
			() => assertActionRegistryContentDirectionConsistent("开发一个挥动左手的功能", path, JSON.stringify(changed)),
			new RegExp(`ACTION-DIRECTION-001.*${field.replaceAll(".", "\\.")}`, "s"),
		);
	}
});

test("action-package refuses a reversed scaffold before invoking the repository script", async (context) => {
	const workspace = mkdtempSync(join(tmpdir(), "rdk-agent-direction-guard-"));
	context.after(() => rmSync(workspace, { recursive: true, force: true }));
	mkdirSync(join(workspace, "tools"), { recursive: true });
	const invocation = join(workspace, "invocation.json");
	writeFileSync(
		join(workspace, "tools", "servo_action.py"),
		"import json, sys\nfrom pathlib import Path\nPath('invocation.json').write_text(json.dumps(sys.argv[1:]), encoding='utf-8')\nprint('{}')\n",
	);
	const tool = createActionPackageToolDefinition(workspace, scaffoldProfile, "开发一个挥动左手的功能");

	await assert.rejects(
		() => tool.execute("call", {
			operation: "scaffold",
			actionId: "wave-right-hand",
			description: "挥动右手",
			start: "right",
			intentExamples: ["挥一下右手"],
		}, undefined, undefined, {} as never),
		/ACTION-DIRECTION-001.*actionId/s,
	);
	assert.equal(existsSync(invocation), false);
});

test("original request is used only by the guard and is never forwarded to the subprocess", async (context) => {
	const workspace = mkdtempSync(join(tmpdir(), "rdk-agent-direction-context-"));
	context.after(() => rmSync(workspace, { recursive: true, force: true }));
	mkdirSync(join(workspace, "tools"), { recursive: true });
	writeFileSync(
		join(workspace, "tools", "servo_action.py"),
		"import json, sys\nfrom pathlib import Path\nPath('invocation.json').write_text(json.dumps(sys.argv[1:]), encoding='utf-8')\nprint('{}')\n",
	);
	const request = "开发一个挥动左手的功能; touch must-not-run";
	const tool = createActionPackageToolDefinition(workspace, scaffoldProfile, request);
	await tool.execute("call", {
		operation: "scaffold",
		actionId: "wave-left-hand",
		description: "挥动左手",
		start: "left",
		intentExamples: ["挥一下左手"],
	}, undefined, undefined, {} as never);

	const invocation = JSON.parse(readFileSync(join(workspace, "invocation.json"), "utf8")) as string[];
	assert.equal(invocation.includes(request), false);
	assert.deepEqual(invocation, [
		"new",
		"wave-left-hand",
		"--description",
		"挥动左手",
		"--start",
		"left",
		"--intent",
		"挥一下左手",
	]);
});

test("fresh scaffold mode is a fixed tool option rather than model-controlled input", async (context) => {
	const workspace = mkdtempSync(join(tmpdir(), "rdk-agent-fresh-scaffold-"));
	context.after(() => rmSync(workspace, { recursive: true, force: true }));
	mkdirSync(join(workspace, "tools"), { recursive: true });
	writeFileSync(
		join(workspace, "tools", "servo_action.py"),
		"import json, sys\nfrom pathlib import Path\nPath('invocation.json').write_text(json.dumps(sys.argv[1:]), encoding='utf-8')\nprint('{}')\n",
	);
	const tool = createActionPackageToolDefinition(
		workspace,
		scaffoldProfile,
		"Implement a feature for waving the right hand",
		{ freshExisting: true },
	);
	await tool.execute("call", {
		operation: "scaffold",
		actionId: "wave-right-hand",
		description: "Wave the right hand",
		start: "right",
		intentExamples: ["Wave the right hand"],
	}, undefined, undefined, {} as never);

	const invocation = JSON.parse(readFileSync(join(workspace, "invocation.json"), "utf8")) as string[];
	assert.deepEqual(invocation, [
		"new",
		"wave-right-hand",
		"--fresh",
		"--description",
		"Wave the right hand",
		"--start",
		"right",
		"--intent",
		"Wave the right hand",
	]);
});
