import assert from "node:assert/strict";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import test from "node:test";
import type { AgentProfile } from "../../src/domain/agent-profile.ts";
import {
	WorkspaceWritePolicy,
	assertApplicationShellAllowed,
	assertNewCapabilityTestBaseline,
	assertReadOnlyShell,
	scopedAgentTools,
} from "../../src/infra/scoped-agent-tools.ts";

test("workspace write policy only accepts files matching the agent allowlist", () => {
	const policy = new WorkspaceWritePolicy("/tmp/workspace", ["rdk-agent/config/skills/*/SKILL.md"]);
	assert.doesNotThrow(() => policy.assertFileAllowed("/tmp/workspace/rdk-agent/config/skills/servo/SKILL.md"));
	assert.throws(() => policy.assertFileAllowed("/tmp/workspace/rdk-agent/config/skills/servo/acceptance.md"), /写入被拒绝/);
	assert.throws(() => policy.assertFileAllowed("/tmp/outside/SKILL.md"), /不在工作目录内/);
});

test("CLI test allowlist cannot overwrite Python or Skill deliverables", () => {
	const policy = new WorkspaceWritePolicy("/tmp/workspace", ["rdk-sophon/examples/plugins/*/tests/test_cli*.py"]);
	assert.doesNotThrow(() => policy.assertFileAllowed("rdk-sophon/examples/plugins/servo/tests/test_cli_contract.py"));
	assert.throws(() => policy.assertFileAllowed("rdk-sophon/examples/plugins/servo/tests/test_wave_hands.py"), /写入被拒绝/);
	assert.throws(() => policy.assertFileAllowed("rdk-agent/config/skills/servo-control/SKILL.md"), /写入被拒绝/);
});

test("Python test allowlist excludes files owned by the CLI loop", () => {
	const policy = new WorkspaceWritePolicy("/tmp/workspace", [
		"rdk-sophon/examples/plugins/*/tests/test_*.py",
		"!rdk-sophon/examples/plugins/*/tests/test_cli*.py",
	]);
	assert.doesNotThrow(() => policy.assertFileAllowed("rdk-sophon/examples/plugins/servo/tests/test_wave_hands.py"));
	assert.throws(() => policy.assertFileAllowed("rdk-sophon/examples/plugins/servo/tests/test_cli_contract.py"), /写入被拒绝/);
});

test("agent bash policy allows tests but blocks shell file mutation", () => {
	assert.doesNotThrow(() => assertReadOnlyShell("python3 -m unittest discover -s tests"));
	assert.doesNotThrow(() => assertReadOnlyShell("rg wave-hands examples/plugins/servo | head"));
	assert.doesNotThrow(() => assertReadOnlyShell("ls -1 missing.json 2>/dev/null"));
	assert.throws(() => assertReadOnlyShell("printf x > tests/result.txt"), /策略拒绝/);
	assert.throws(() => assertReadOnlyShell("printf x 2>/tmp/result.txt"), /策略拒绝/);
	assert.throws(() => assertReadOnlyShell("sed -i '' s/a/b/ file"), /策略拒绝/);
	assert.throws(() => assertReadOnlyShell("git checkout -- file"), /策略拒绝/);
	assert.throws(
		() => assertReadOnlyShell("printf x > tests/result.txt", "en"),
		(error: unknown) => error instanceof Error && /read-only checks.*command rejected/i.test(error.message) && !/[一-鿿]/u.test(error.message),
	);
});

test("new-capability unittest is blocked before launch until this session scaffolds it", () => {
	const command = "python3 -m unittest discover -s examples/plugins/servo/servo_actions/wave-right-hand/tests -v";
	const state = { scaffoldSucceeded: false };
	assert.throws(
		() => assertNewCapabilityTestBaseline(command, {
			expectation: "test",
			userRequest: "Implement a feature for waving the right hand",
			iteration: 1,
			locale: "en",
			testBaseline: state,
		}),
		(error: unknown) => error instanceof Error && /before launch.*historical state/i.test(error.message) && !/[一-鿿]/u.test(error.message),
	);
	assert.doesNotThrow(() => assertNewCapabilityTestBaseline(command, {
		expectation: "test",
		userRequest: "Fix the existing right-hand wave action",
		iteration: 1,
		testBaseline: state,
	}));
	state.scaffoldSucceeded = true;
	assert.doesNotThrow(() => assertNewCapabilityTestBaseline(command, {
		expectation: "test",
		userRequest: "Implement a feature for waving the right hand",
		iteration: 1,
		testBaseline: state,
	}));
});

test("read-only application requests cannot invoke robot action commands", () => {
	const query = "当前加载了哪些 Skill？";
	assert.doesNotThrow(() => assertApplicationShellAllowed("sophonctl plugins list", "application", query));
	assert.doesNotThrow(() => assertApplicationShellAllowed("sophonctl --board x5 servo --help", "application", query));
	assert.throws(
		() => assertApplicationShellAllowed("sophonctl servo shake-ears", "application", query),
		/只读查询.*命令被拒绝/,
	);
	assert.throws(() => assertApplicationShellAllowed("ssh x5-root python3 servo.py", "application", query), /命令被拒绝/);
	assert.doesNotThrow(() => assertApplicationShellAllowed("sophonctl servo shake-ears", "application", "摇一下耳朵"));
	assert.doesNotThrow(() => assertApplicationShellAllowed("sophonctl servo shake-ears", "coding", query));
	assert.throws(
		() => assertApplicationShellAllowed("sophonctl servo shake-ears", "application", "Show available actions", "en"),
		/read-only.*command rejected/i,
	);
});

test("action-package tooling fails closed without the original user request context", () => {
	const profile: AgentProfile = {
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
	assert.throws(
		() => scopedAgentTools("/tmp/workspace", "/tmp/skills", profile),
		/action-package.*原始用户指令上下文/,
	);
	assert.doesNotThrow(() => scopedAgentTools("/tmp/workspace", "/tmp/skills", profile, {
		expectation: "test",
		userRequest: "开发一个挥动左手的功能",
	}));
});

test("first-iteration new capability uses a fresh scaffold and records only a new baseline", async (context) => {
	const workspace = mkdtempSync(join(tmpdir(), "rdk-agent-scoped-fresh-scaffold-"));
	context.after(() => rmSync(workspace, { recursive: true, force: true }));
	mkdirSync(join(workspace, "tools"), { recursive: true });
	writeFileSync(
		join(workspace, "tools", "servo_action.py"),
		"import json, sys\nfrom pathlib import Path\nPath('invocation.json').write_text(json.dumps(sys.argv[1:]), encoding='utf-8')\nprint(json.dumps({'status': 'scaffolded'}))\n",
	);
	const profile: AgentProfile = {
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
	const baseline = { scaffoldSucceeded: false };
	const [tool] = scopedAgentTools(workspace, join(workspace, "skills"), profile, {
		expectation: "test",
		userRequest: "Implement a feature for waving the right hand",
		iteration: 1,
		testBaseline: baseline,
	});
	await tool!.execute("call", {
		operation: "scaffold",
		actionId: "wave-right-hand",
		description: "Wave the right hand",
		start: "right",
		intentExamples: ["Wave the right hand"],
	}, undefined, undefined, {} as never);

	const invocation = JSON.parse(readFileSync(join(workspace, "invocation.json"), "utf8")) as string[];
	assert.deepEqual(invocation.slice(0, 3), ["new", "wave-right-hand", "--fresh"]);
	assert.equal(baseline.scaffoldSucceeded, true);
});

test("workspace mutation policy binds servo action paths to the requested direction", () => {
	const paths = ["examples/plugins/servo/servo_actions/*/action.py"];
	const left = new WorkspaceWritePolicy("/tmp/workspace", paths, "开发一个挥动左手的功能");
	assert.doesNotThrow(() => left.assertFileAllowed("examples/plugins/servo/servo_actions/wave-left-hand/action.py"));
	assert.throws(
		() => left.assertFileAllowed("examples/plugins/servo/servo_actions/wave-right-hand/action.py"),
		/ACTION-DIRECTION-001.*actionId/s,
	);
	assert.throws(
		() => left.assertFileAllowed("examples/plugins/servo/servo_actions/wave-hand/action.py"),
		/ACTION-DIRECTION-001.*actionId/s,
	);

	const right = new WorkspaceWritePolicy("/tmp/workspace", paths, "开发一个挥动右手的功能");
	assert.doesNotThrow(() => right.assertFileAllowed("examples/plugins/servo/servo_actions/wave-right-hand/action.py"));
	assert.throws(() => right.assertFileAllowed("examples/plugins/servo/servo_actions/wave-left-hand/action.py"), /ACTION-DIRECTION-001/);

	const both = new WorkspaceWritePolicy("/tmp/workspace", paths, "开发一个挥动双手的功能");
	assert.doesNotThrow(() => both.assertFileAllowed("examples/plugins/servo/servo_actions/wave-hands/action.py"));
	assert.throws(() => both.assertFileAllowed("examples/plugins/servo/servo_actions/wave-left-hand/action.py"), /ACTION-DIRECTION-001/);
});

test("direction-aware mutation policy leaves unrelated paths and non-directional requests compatible", () => {
	const unrelated = new WorkspaceWritePolicy("/tmp/workspace", ["notes/*"], "开发一个挥动左手的功能");
	assert.doesNotThrow(() => unrelated.assertFileAllowed("notes/wave-right-hand.txt"));

	const nonDirectional = new WorkspaceWritePolicy(
		"/tmp/workspace",
		["examples/plugins/servo/servo_actions/*/action.py"],
		"开发一个点头功能",
	);
	assert.doesNotThrow(() => nonDirectional.assertFileAllowed("examples/plugins/servo/servo_actions/nod-head/action.py"));
	assert.doesNotThrow(() => nonDirectional.assertFileAllowed("examples/plugins/servo/servo_actions/wave-right-hand/action.py"));
});

test("scoped write and edit reject a wrong-side action path before mutating files", async (context) => {
	const workspace = mkdtempSync(join(tmpdir(), "rdk-agent-direction-write-"));
	context.after(() => rmSync(workspace, { recursive: true, force: true }));
	const existingWrongFile = join(workspace, "examples/plugins/servo/servo_actions/wave-right-hand/action.py");
	mkdirSync(dirname(existingWrongFile), { recursive: true });
	writeFileSync(existingWrongFile, "old right-hand implementation\n");
	const profile: AgentProfile = {
		id: "action-coding",
		name: "Action coding",
		description: "test",
		tools: ["write", "edit"],
		skills: [],
		systemPrompt: "test",
		writePaths: ["examples/plugins/servo/servo_actions/*/action.py"],
		timeoutSeconds: 30,
	};
	const tools = scopedAgentTools(workspace, join(workspace, "skills"), profile, {
		expectation: "coding",
		userRequest: "开发一个挥动左手的功能",
	});
	const byName = new Map(tools.map((tool) => [tool.name, tool]));
	const neutralPath = "examples/plugins/servo/servo_actions/wave-hand/action.py";

	await assert.rejects(
		() => byName.get("write")!.execute("call", { path: neutralPath, content: "new\n" }, undefined, undefined, {} as never),
		/ACTION-DIRECTION-001.*actionId/s,
	);
	assert.equal(existsSync(join(workspace, "examples/plugins/servo/servo_actions/wave-hand")), false);

	await assert.rejects(
		() => byName.get("edit")!.execute("call", {
			path: "examples/plugins/servo/servo_actions/wave-right-hand/action.py",
			edits: [{
				oldText: "old right-hand implementation",
				newText: "new right-hand implementation",
			}],
		}, undefined, undefined, {} as never),
		/ACTION-DIRECTION-001.*actionId/s,
	);
	assert.equal(readFileSync(existingWrongFile, "utf8"), "old right-hand implementation\n");
});

test("scoped write validates full Python content before creating a file", async (context) => {
	const workspace = mkdtempSync(join(tmpdir(), "rdk-agent-direction-content-write-"));
	context.after(() => rmSync(workspace, { recursive: true, force: true }));
	const profile: AgentProfile = {
		id: "action-coding",
		name: "Action coding",
		description: "test",
		tools: ["write"],
		skills: [],
		systemPrompt: "test",
		writePaths: ["examples/plugins/servo/servo_actions/*/action.py"],
		timeoutSeconds: 30,
	};
	const [writeTool] = scopedAgentTools(workspace, join(workspace, "skills"), profile, {
		expectation: "coding",
		userRequest: "开发一个挥动左手的功能",
	});
	const actionPath = "examples/plugins/servo/servo_actions/wave-left-hand/action.py";

	await assert.rejects(
		() => writeTool!.execute("call", {
			path: actionPath,
			content: "def run(context, params):\n    context.lift_right()\n",
		}, undefined, undefined, {} as never),
		/ACTION-DIRECTION-001.*context\.lift_right/s,
	);
	assert.equal(existsSync(dirname(join(workspace, actionPath))), false);
});

test("scoped edit validates the complete edited Python before overwriting", async (context) => {
	const workspace = mkdtempSync(join(tmpdir(), "rdk-agent-direction-content-edit-"));
	context.after(() => rmSync(workspace, { recursive: true, force: true }));
	const actionPath = "examples/plugins/servo/servo_actions/wave-left-hand/action.py";
	const absolutePath = join(workspace, actionPath);
	const original = "def run(context, params):\n    context.lift_left()\n    context.lower_left()\n";
	mkdirSync(dirname(absolutePath), { recursive: true });
	writeFileSync(absolutePath, original);
	const profile: AgentProfile = {
		id: "action-coding",
		name: "Action coding",
		description: "test",
		tools: ["edit"],
		skills: [],
		systemPrompt: "test",
		writePaths: ["examples/plugins/servo/servo_actions/*/action.py"],
		timeoutSeconds: 30,
	};
	const [editTool] = scopedAgentTools(workspace, join(workspace, "skills"), profile, {
		expectation: "coding",
		userRequest: "开发一个挥动左手的功能",
	});

	await assert.rejects(
		() => editTool!.execute("call", {
			path: actionPath,
			edits: [{ oldText: "context.lift_left()", newText: "context.lift_right()" }],
		}, undefined, undefined, {} as never),
		/ACTION-DIRECTION-001.*context\.lift_right/s,
	);
	assert.equal(readFileSync(absolutePath, "utf8"), original);
});

test("scoped write and edit validate complete registry metadata before overwriting", async (context) => {
	const workspace = mkdtempSync(join(tmpdir(), "rdk-agent-direction-registry-"));
	context.after(() => rmSync(workspace, { recursive: true, force: true }));
	const actionRoot = "examples/plugins/servo/servo_actions/wave-left-hand";
	const registryPath = `${actionRoot}/registry.json`;
	const absolutePath = join(workspace, registryPath);
	const original = `${JSON.stringify({
		schema: "rdk-servo-action/v1",
		id: "wave-left-hand",
		description: "挥动左手",
		entrypoint: "action.py:run",
		start: "left",
		skill: { intentExamples: ["挥一下左手"], risk: "motion" },
		arguments: [],
	}, null, 2)}\n`;
	mkdirSync(dirname(absolutePath), { recursive: true });
	writeFileSync(absolutePath, original);
	const profile: AgentProfile = {
		id: "action-test",
		name: "Action test",
		description: "test",
		tools: ["write", "edit"],
		skills: [],
		systemPrompt: "test",
		writePaths: ["examples/plugins/servo/servo_actions/*/registry.json"],
		timeoutSeconds: 30,
	};
	const tools = scopedAgentTools(workspace, join(workspace, "skills"), profile, {
		expectation: "test",
		userRequest: "开发一个挥动左手的功能",
	});
	const byName = new Map(tools.map((tool) => [tool.name, tool]));

	await assert.rejects(
		() => byName.get("write")!.execute("call", {
			path: registryPath,
			content: original.replaceAll("左", "右").replace('"start": "left"', '"start": "right"'),
		}, undefined, undefined, {} as never),
		/ACTION-DIRECTION-001/,
	);
	await assert.rejects(
		() => byName.get("edit")!.execute("call", {
			path: registryPath,
			edits: [{ oldText: '"start": "left"', newText: '"start": "right"' }],
		}, undefined, undefined, {} as never),
		/ACTION-DIRECTION-001.*registry\.json\.start/s,
	);
	assert.equal(readFileSync(absolutePath, "utf8"), original);
});
