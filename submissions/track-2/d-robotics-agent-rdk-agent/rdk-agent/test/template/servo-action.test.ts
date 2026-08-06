import assert from "node:assert/strict";
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";

const template = join(import.meta.dirname, "../../config/templates/magicbox-servo");

function run(workspace: string, ...args: string[]) {
	return spawnSync("python3", [join(workspace, "tools/servo_action.py"), ...args], { cwd: workspace, encoding: "utf8" });
}

test("action-package scaffold validates and builds an isolated release", (context) => {
	const temporary = mkdtempSync(join(tmpdir(), "rdk-agent-action-package-"));
	context.after(() => rmSync(temporary, { recursive: true, force: true }));
	const workspace = join(temporary, "workspace");
	cpSync(template, workspace, { recursive: true });

	const scaffold = run(workspace, "new", "wave-left-hand");
	assert.equal(scaffold.status, 0, scaffold.stderr || scaffold.stdout);
	const packageRoot = join(workspace, "examples/plugins/servo/servo_actions/wave-left-hand");
	const manifestPath = join(packageRoot, "registry.json");
	const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
	manifest.description = "挥动左手";
	manifest.skill.intentExamples = ["挥一下左手"];
	writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
	writeFileSync(join(packageRoot, "action.py"), "def run(context, params):\n    context.lift_left()\n");

	const validated = run(workspace, "validate", "wave-left-hand");
	assert.equal(validated.status, 0, validated.stderr || validated.stdout);
	const release = run(workspace, "build");
	assert.equal(release.status, 0, release.stderr || release.stdout);
	const builtSkill = readFileSync(join(workspace, ".rdk-agent/releases/current/skill/SKILL.md"), "utf8");
	assert.match(builtSkill, /`sophonctl servo shake-ears`/);
	assert.match(builtSkill, /挥一下左手/);
	assert.match(readFileSync(join(workspace, ".rdk-agent/releases/current/servo_actions/wave-left-hand/action.py"), "utf8"), /context\.lift_left/);
});

test("action-package scaffold is idempotent across TDD revision rounds", (context) => {
	const temporary = mkdtempSync(join(tmpdir(), "rdk-agent-action-package-"));
	context.after(() => rmSync(temporary, { recursive: true, force: true }));
	const workspace = join(temporary, "workspace");
	cpSync(template, workspace, { recursive: true });

	const first = run(workspace, "new", "wave-left-hand", "--description", "挥动左手", "--start", "left", "--intent", "挥动左手");
	assert.equal(first.status, 0, first.stderr || first.stdout);
	const initialRed = spawnSync(
		"python3",
		["-m", "unittest", "discover", "-s", "examples/plugins/servo/servo_actions/wave-left-hand/tests", "-v"],
		{ cwd: workspace, encoding: "utf8" },
	);
	assert.notEqual(initialRed.status, 0);
	assert.match(initialRed.stderr + initialRed.stdout, /test_action_behavior.*FAIL/s);
	assert.doesNotMatch(initialRed.stderr + initialRed.stdout, /test_package_contract[^\n]*\.\.\. FAIL/);
	const actionPath = join(workspace, "examples/plugins/servo/servo_actions/wave-left-hand/action.py");
	const revisedSource = "def run(context, params):\n    context.lift_left()\n";
	writeFileSync(actionPath, revisedSource);

	const revision = run(workspace, "new", "wave-left-hand", "--description", "不得覆盖", "--start", "right", "--intent", "返工");
	assert.equal(revision.status, 0, revision.stderr || revision.stdout);
	assert.match(revision.stdout, /"status": "existing"/);
	assert.equal(readFileSync(actionPath, "utf8"), revisedSource);
});

test("fresh scaffold archives an existing action and recreates a red baseline", (context) => {
	const temporary = mkdtempSync(join(tmpdir(), "rdk-agent-action-package-"));
	context.after(() => rmSync(temporary, { recursive: true, force: true }));
	const workspace = join(temporary, "workspace");
	cpSync(template, workspace, { recursive: true });

	const first = run(workspace, "new", "wave-right-hand", "--description", "Wave right", "--start", "right", "--intent", "Wave right");
	assert.equal(first.status, 0, first.stderr || first.stdout);
	const actionPath = join(workspace, "examples/plugins/servo/servo_actions/wave-right-hand/action.py");
	const oldSource = "def run(context, params):\n    context.lift_right()\n";
	writeFileSync(actionPath, oldSource);

	const restarted = run(workspace, "new", "wave-right-hand", "--fresh", "--description", "Wave right", "--start", "right", "--intent", "Wave right");
	assert.equal(restarted.status, 0, restarted.stderr || restarted.stdout);
	assert.match(restarted.stdout, /"status": "scaffolded"/);
	assert.match(restarted.stdout, /"archived"/);
	assert.match(readFileSync(actionPath, "utf8"), /NotImplementedError/);
	assert.equal(
		readFileSync(join(workspace, ".rdk-agent/action-history/wave-right-hand/v1/action.py"), "utf8"),
		oldSource,
	);
});

test("action-package rejects direct hardware imports with a stable error code", (context) => {
	const temporary = mkdtempSync(join(tmpdir(), "rdk-agent-action-package-"));
	context.after(() => rmSync(temporary, { recursive: true, force: true }));
	const workspace = join(temporary, "workspace");
	cpSync(template, workspace, { recursive: true });
	run(workspace, "new", "unsafe-action");
	const actionPath = join(workspace, "examples/plugins/servo/servo_actions/unsafe-action/action.py");
	writeFileSync(actionPath, "import Hobot.GPIO\n\ndef run(context, params):\n    return None\n");

	const result = run(workspace, "validate", "unsafe-action");
	assert.notEqual(result.status, 0);
	assert.match(result.stdout, /ACTION-SAFETY-001/);
});

test("action-package rejects implementations coupled to a test spy", (context) => {
	const temporary = mkdtempSync(join(tmpdir(), "rdk-agent-action-package-"));
	context.after(() => rmSync(temporary, { recursive: true, force: true }));
	const workspace = join(temporary, "workspace");
	cpSync(template, workspace, { recursive: true });
	run(workspace, "new", "spy-action");
	const actionPath = join(workspace, "examples/plugins/servo/servo_actions/spy-action/action.py");
	writeFileSync(actionPath, "def run(context, params):\n    context.calls.append('not-a-bridge-call')\n");

	const result = run(workspace, "validate", "spy-action");
	assert.notEqual(result.status, 0);
	assert.match(result.stdout, /ACTION-BRIDGE-001/);
});

test("action-package rejects IDs reserved by built-in commands", (context) => {
	const temporary = mkdtempSync(join(tmpdir(), "rdk-agent-action-package-"));
	context.after(() => rmSync(temporary, { recursive: true, force: true }));
	const workspace = join(temporary, "workspace");
	cpSync(template, workspace, { recursive: true });

	const result = run(workspace, "new", "lift-left");
	assert.notEqual(result.status, 0);
	assert.match(result.stdout, /ACTION-ID-003/);
});

test("action-package rejects dynamic imports and private controller access", (context) => {
	const temporary = mkdtempSync(join(tmpdir(), "rdk-agent-action-package-"));
	context.after(() => rmSync(temporary, { recursive: true, force: true }));
	const workspace = join(temporary, "workspace");
	cpSync(template, workspace, { recursive: true });
	run(workspace, "new", "unsafe-action");
	const actionPath = join(workspace, "examples/plugins/servo/servo_actions/unsafe-action/action.py");

	writeFileSync(actionPath, "def run(context, params):\n    __import__('os').system('id')\n");
	const dynamicImport = run(workspace, "validate", "unsafe-action");
	assert.notEqual(dynamicImport.status, 0);
	assert.match(dynamicImport.stdout, /ACTION-SAFETY-002/);

	writeFileSync(actionPath, "def run(context, params):\n    context._set_right()\n");
	const privateBridge = run(workspace, "validate", "unsafe-action");
	assert.notEqual(privateBridge.status, 0);
	assert.match(privateBridge.stdout, /ACTION-BRIDGE-002/);
});

test("action-package v1 rejects runtime parameters and async entrypoints", (context) => {
	const temporary = mkdtempSync(join(tmpdir(), "rdk-agent-action-package-"));
	context.after(() => rmSync(temporary, { recursive: true, force: true }));
	const workspace = join(temporary, "workspace");
	cpSync(template, workspace, { recursive: true });
	run(workspace, "new", "parameterized-action");
	const packageRoot = join(workspace, "examples/plugins/servo/servo_actions/parameterized-action");
	const manifestPath = join(packageRoot, "registry.json");
	const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
	manifest.arguments = [{ name: "speed" }];
	writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
	writeFileSync(join(packageRoot, "action.py"), "def run(context, params):\n    context.lift_left()\n");
	const parameterized = run(workspace, "validate", "parameterized-action");
	assert.notEqual(parameterized.status, 0);
	assert.match(parameterized.stdout, /ACTION-ARGS-002/);

	manifest.arguments = [];
	writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
	writeFileSync(join(packageRoot, "action.py"), "async def run(context, params):\n    context.lift_left()\n");
	const asynchronous = run(workspace, "validate", "parameterized-action");
	assert.notEqual(asynchronous.status, 0);
	assert.match(asynchronous.stdout, /ACTION-ENTRYPOINT-003/);
});

test("servo entrypoint discovers a packaged action without changing ACTIONS", (context) => {
	const temporary = mkdtempSync(join(tmpdir(), "rdk-agent-action-package-"));
	context.after(() => rmSync(temporary, { recursive: true, force: true }));
	const workspace = join(temporary, "workspace");
	cpSync(template, workspace, { recursive: true });
	run(workspace, "new", "wave-left-hand");
	const packageRoot = join(workspace, "examples/plugins/servo/servo_actions/wave-left-hand");
	const manifestPath = join(packageRoot, "registry.json");
	const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
	manifest.description = "挥动左手";
	manifest.skill.intentExamples = ["挥一下左手"];
	manifest.start = "left";
	writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
	writeFileSync(join(packageRoot, "action.py"), "def run(context, params):\n    context.lift_left()\n");

	const source = join(workspace, "examples/plugins/servo/servo_ctrl.py");
	const probe = `
import os, sys, types
gpio = types.SimpleNamespace(setwarnings=lambda *_: None, setmode=lambda *_: None, cleanup=lambda *_: None, BOARD=1,
    PWM=lambda *_: types.SimpleNamespace(ChangeDutyCycle=lambda *_: None, start=lambda *_: None, stop=lambda: None))
sys.modules['Hobot'] = types.ModuleType('Hobot')
sys.modules['Hobot.GPIO'] = gpio
sys.path.insert(0, ${JSON.stringify(join(workspace, "examples/plugins/servo"))})
import servo_ctrl
sys.argv = ['servo_ctrl.py', 'wave-left-hand', '--hold', '0']
servo_ctrl.main()
`;
	const dispatched = spawnSync("python3", ["-c", probe], {
		cwd: workspace,
		encoding: "utf8",
		env: { ...process.env, MAGICBOX_SERVO_ACTIONS_DIR: join(workspace, "examples/plugins/servo/servo_actions") },
	});
	assert.equal(dispatched.status, 0, dispatched.stderr || dispatched.stdout);
	assert.doesNotMatch(readFileSync(source, "utf8"), /wave-left-hand/);
});

test("servo help lists discovered action packages from their local registry", (context) => {
	const temporary = mkdtempSync(join(tmpdir(), "rdk-agent-action-package-"));
	context.after(() => rmSync(temporary, { recursive: true, force: true }));
	const workspace = join(temporary, "workspace");
	cpSync(template, workspace, { recursive: true });
	run(workspace, "new", "wave-right-hand", "--description", "挥动右手", "--start", "right", "--intent", "挥动右手");
	const packageRoot = join(workspace, "examples/plugins/servo/servo_actions/wave-right-hand");
	writeFileSync(join(packageRoot, "action.py"), "def run(context, params):\n    context.lift_right()\n");

	const source = join(workspace, "examples/plugins/servo/servo_ctrl.py");
	const probe = `
import os, sys, types
gpio = types.SimpleNamespace(setwarnings=lambda *_: None, setmode=lambda *_: None, cleanup=lambda *_: None, BOARD=1,
    PWM=lambda *_: types.SimpleNamespace(ChangeDutyCycle=lambda *_: None, start=lambda *_: None, stop=lambda: None))
sys.modules['Hobot'] = types.ModuleType('Hobot')
sys.modules['Hobot.GPIO'] = gpio
sys.path.insert(0, ${JSON.stringify(join(workspace, "examples/plugins/servo"))})
import servo_ctrl
sys.argv = ['servo_ctrl.py', '--help']
try:
    servo_ctrl.main()
except SystemExit as error:
    raise SystemExit(0 if error.code == 0 else error.code)
`;
	const help = spawnSync("python3", ["-c", probe], {
		cwd: workspace,
		encoding: "utf8",
		env: { ...process.env, MAGICBOX_SERVO_ACTIONS_DIR: join(workspace, "examples/plugins/servo/servo_actions") },
	});
	assert.equal(help.status, 0, help.stderr || help.stdout);
	assert.match(help.stdout, /rdk-agent 托管动作（自动发现）/);
	assert.match(help.stdout, /wave-right-hand\s+挥动右手/);
});
