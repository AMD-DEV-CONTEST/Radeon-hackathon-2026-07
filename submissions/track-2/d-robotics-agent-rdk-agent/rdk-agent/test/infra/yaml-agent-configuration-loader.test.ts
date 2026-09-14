import assert from "node:assert/strict";
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { YamlAgentConfigurationLoader } from "../../src/infra/yaml-agent-configuration-loader.ts";

test("loads ordered agent profiles, prompts, tools and skills from YAML", (context) => {
	const directory = mkdtempSync(join(tmpdir(), "rdk-agent-config-"));
	context.after(() => rmSync(directory, { recursive: true, force: true }));
	mkdirSync(join(directory, "skills", "test-skill"), { recursive: true });
	writeFileSync(join(directory, "skills", "test-skill", "SKILL.md"), "---\nname: test-skill\ndescription: test\n---\n");
	writeFileSync(
		join(directory, "agents.yaml"),
		`version: 2
defaultMode: development
workspace:
  requiredPaths: [examples/plugin.toml]
agents:
  - id: author
    name: Author
    description: Writes code
    tools: [read, write]
    writePaths: [tests/*.ts]
    skills: [test-skill]
    timeoutSeconds: 45
    maxToolCalls: 7
    sandbox:
      kind: podman
      image: docker.io/library/python:3.12-slim
      network: none
    systemPrompt: |
      Follow the project conventions.
modes:
  - id: development
    name: Development
    type: robot-development
    loops:
      - id: python
        name: Python
        deliverable: script
        testAgent: author
        codingAgent: author
        verificationAgent: author
        maxIterations: 2
`,
	);

	const configuration = new YamlAgentConfigurationLoader().load(directory);
	assert.equal(configuration.locale, "zh-CN");
	assert.equal(configuration.profiles[0]?.id, "author");
	assert.deepEqual(configuration.profiles[0]?.tools, ["read", "write"]);
	assert.deepEqual(configuration.profiles[0]?.skills, ["test-skill"]);
	assert.deepEqual(configuration.profiles[0]?.writePaths, ["tests/*.ts"]);
	assert.equal(configuration.profiles[0]?.systemPrompt, "Follow the project conventions.");
	assert.equal(configuration.profiles[0]?.timeoutSeconds, 45);
	assert.equal(configuration.profiles[0]?.maxToolCalls, 7);
	assert.deepEqual(configuration.profiles[0]?.sandbox, {
		kind: "podman",
		image: "docker.io/library/python:3.12-slim",
		network: "none",
	});
	assert.deepEqual(configuration.workspace, { kind: "current-directory", requiredPaths: ["examples/plugin.toml"] });
	assert.deepEqual(configuration.intake, {
		autoStartConfidence: 0.9,
		timeoutSeconds: 30,
		developmentScope: "只有用户指令明确要求新增、修改、修复、测试或部署当前机器人能力时，才启动受支持的研发流程。",
	});
	assert.equal(configuration.defaultModeId, "development");
	assert.equal(configuration.modes[0]?.type, "robot-development");
	if (configuration.modes[0]?.type === "robot-development") {
		assert.deepEqual(configuration.modes[0].acceptanceAgentIds, []);
	}
});

test("selects English configuration metadata with per-field Chinese fallback", (context) => {
	const directory = mkdtempSync(join(tmpdir(), "rdk-agent-config-locale-"));
	context.after(() => rmSync(directory, { recursive: true, force: true }));
	writeFileSync(
		join(directory, "agents.yaml"),
		`version: 2
defaultMode: development
intake:
  developmentScope: 中文研发范围
  developmentScopeEn: English development scope
agents:
  - id: author
    name: 中文 Agent
    nameEn: English Agent
    description: 中文描述
    tools: []
    skills: []
    systemPrompt: Test
modes:
  - id: development
    name: 中文模式
    nameEn: English Mode
    type: robot-development
    loops:
      - id: localized-loop
        name: 中文循环
        nameEn: English Loop
        deliverable: 中文交付物
        testAgent: author
        codingAgent: author
        verificationAgent: author
        maxIterations: 2
      - id: fallback-loop
        name: 回退循环
        deliverable: 中文交付物二
        deliverableEn: English Deliverable
        testAgent: author
        codingAgent: author
        verificationAgent: author
        maxIterations: 2
`,
	);

	const loader = new YamlAgentConfigurationLoader();
	const chinese = loader.load(directory);
	assert.equal(chinese.locale, "zh-CN");
	assert.equal(chinese.intake.developmentScope, "中文研发范围");
	assert.equal(chinese.profiles[0]?.name, "中文 Agent");
	assert.equal(chinese.modes[0]?.name, "中文模式");

	const english = loader.load(directory, "en");
	assert.equal(english.locale, "en");
	assert.equal(english.intake.developmentScope, "English development scope");
	assert.equal(english.profiles[0]?.name, "English Agent");
	assert.equal(english.profiles[0]?.description, "中文描述");
	assert.equal(english.modes[0]?.name, "English Mode");
	if (english.modes[0]?.type === "robot-development") {
		assert.equal(english.modes[0].loops[0]?.name, "English Loop");
		assert.equal(english.modes[0].loops[0]?.deliverable, "中文交付物");
		assert.equal(english.modes[0].loops[1]?.name, "回退循环");
		assert.equal(english.modes[0].loops[1]?.deliverable, "English Deliverable");
	}
});

test("loads an independent no-tool intake configuration", (context) => {
	const directory = mkdtempSync(join(tmpdir(), "rdk-agent-config-"));
	context.after(() => rmSync(directory, { recursive: true, force: true }));
	writeFileSync(
		join(directory, "agents.yaml"),
		`version: 2
defaultMode: application
intake:
  autoStartConfidence: 0.95
  timeoutSeconds: 12
  developmentScope: Only robot action packages.
agents:
  - id: author
    name: Author
    description: Test
    tools: []
    skills: []
    systemPrompt: Test
modes:
  - id: application
    name: Application
    type: robot-application
    agent: author
`,
	);
	const configuration = new YamlAgentConfigurationLoader().load(directory);
	assert.deepEqual(configuration.intake, {
		autoStartConfidence: 0.95,
		timeoutSeconds: 12,
		developmentScope: "Only robot action packages.",
	});
	assert.equal(configuration.profiles.some((profile) => profile.id === "intake"), false);
});

test("rejects unsafe intake thresholds", (context) => {
	const directory = mkdtempSync(join(tmpdir(), "rdk-agent-config-"));
	context.after(() => rmSync(directory, { recursive: true, force: true }));
	writeFileSync(
		join(directory, "agents.yaml"),
		"version: 2\ndefaultMode: application\nintake:\n  autoStartConfidence: 1.5\nagents:\n  - id: author\n    name: Author\n    description: Test\n    tools: []\n    skills: []\n    systemPrompt: Test\nmodes:\n  - id: application\n    name: Application\n    type: robot-application\n    agent: author\n",
	);
	assert.throws(() => new YamlAgentConfigurationLoader().load(directory), /autoStartConfidence/);
});

test("rejects a configured skill that does not exist", (context) => {
	const directory = mkdtempSync(join(tmpdir(), "rdk-agent-config-"));
	context.after(() => rmSync(directory, { recursive: true, force: true }));
	writeFileSync(
		join(directory, "agents.yaml"),
		"version: 2\ndefaultMode: application\nagents:\n  - id: author\n    name: Author\n    description: Test\n    tools: []\n    skills: [missing]\n    systemPrompt: Test\nmodes:\n  - id: application\n    name: Application\n    type: robot-application\n    agent: author\n",
	);
	assert.throws(() => new YamlAgentConfigurationLoader().load(directory), /Skill 不存在/);
});

test("loads a customized v2 configuration with the retired servo Python validation", (context) => {
	const directory = mkdtempSync(join(tmpdir(), "rdk-agent-config-"));
	context.after(() => rmSync(directory, { recursive: true, force: true }));
	writeFileSync(
		join(directory, "agents.yaml"),
		"version: 2\ndefaultMode: application\nagents:\n  - id: author\n    name: Author\n    description: Test\n    tools: []\n    skills: []\n    validation:\n      kind: servo-python-test\n    systemPrompt: Customized prompt\nmodes:\n  - id: application\n    name: Application\n    type: robot-application\n    agent: author\n",
	);

	const configuration = new YamlAgentConfigurationLoader().load(directory);
	assert.equal(configuration.profiles[0]?.validation, undefined);
	assert.equal(configuration.profiles[0]?.systemPrompt, "Customized prompt");
});

test("rejects write-capable agents without a path allowlist", (context) => {
	const directory = mkdtempSync(join(tmpdir(), "rdk-agent-config-"));
	context.after(() => rmSync(directory, { recursive: true, force: true }));
	writeFileSync(
		join(directory, "agents.yaml"),
		"version: 2\ndefaultMode: application\nagents:\n  - id: author\n    name: Author\n    description: Test\n    tools: [write]\n    skills: []\n    systemPrompt: Test\nmodes:\n  - id: application\n    name: Application\n    type: robot-application\n    agent: author\n",
	);
	assert.throws(() => new YamlAgentConfigurationLoader().load(directory), /writePaths/);
});

test("rejects a development sandbox with host networking", (context) => {
	const directory = mkdtempSync(join(tmpdir(), "rdk-agent-config-"));
	context.after(() => rmSync(directory, { recursive: true, force: true }));
	writeFileSync(
		join(directory, "agents.yaml"),
		"version: 2\ndefaultMode: application\nagents:\n  - id: author\n    name: Author\n    description: Test\n    tools: [bash]\n    skills: []\n    sandbox:\n      kind: podman\n      image: python:3.12-slim\n      network: host\n    systemPrompt: Test\nmodes:\n  - id: application\n    name: Application\n    type: robot-application\n    agent: author\n",
	);
	assert.throws(() => new YamlAgentConfigurationLoader().load(directory), /network 当前必须为 none/);
});

test("bundled robot application mode loads the servo control skill", () => {
	const configuration = new YamlAgentConfigurationLoader().load(join(import.meta.dirname, "../../config"));
	const application = configuration.profiles.find((profile) => profile.id === "robot-application");
	assert.equal(configuration.defaultModeId, "robot-application");
	assert.deepEqual(application?.skills, ["servo-control"]);
	assert.match(application?.systemPrompt ?? "", /动作式用户指令即已授权执行该动作一次/);
	assert.match(application?.systemPrompt ?? "", /不得只做帮助检查就返回 completed/);
	assert.equal(configuration.modes.find((mode) => mode.id === "robot-application")?.type, "robot-application");
});

test("bundled English metadata covers intake, agents, modes, loops and deliverables", () => {
	const configuration = new YamlAgentConfigurationLoader().load(join(import.meta.dirname, "../../config"), "en");
	assert.equal(configuration.locale, "en");
	assert.match(configuration.intake.developmentScope, /current development workflow/i);
	for (const profile of configuration.profiles) {
		assert.doesNotMatch(profile.name, /[一-龥]/u, `${profile.id} is missing nameEn`);
		assert.doesNotMatch(profile.description, /[一-龥]/u, `${profile.id} is missing descriptionEn`);
	}
	for (const mode of configuration.modes) {
		assert.doesNotMatch(mode.name, /[一-龥]/u, `${mode.id} is missing nameEn`);
		if (mode.type === "robot-development") {
			for (const loop of mode.loops) {
				assert.doesNotMatch(loop.name, /[一-龥]/u, `${loop.id} is missing nameEn`);
				assert.doesNotMatch(loop.deliverable, /[一-龥]/u, `${loop.id} is missing deliverableEn`);
			}
		}
	}
});

test("bundled development workflow uses action-package TDD and deterministic release delivery", () => {
	const configuration = new YamlAgentConfigurationLoader().load(join(import.meta.dirname, "../../config"));
	const byId = new Map(configuration.profiles.map((profile) => [profile.id, profile]));
	assert.equal(configuration.intake.autoStartConfidence, 0.9);
	assert.equal(configuration.intake.timeoutSeconds, 30);
	assert.match(configuration.intake.developmentScope, /动作包/);
	assert.equal(configuration.workspace.kind, "managed-template");
	if (configuration.workspace.kind === "managed-template") {
		for (const requiredPath of configuration.workspace.requiredPaths) {
			assert.equal(
				existsSync(join(configuration.workspace.templateDirectory, requiredPath)),
				true,
				`bundled workspace template is missing ${requiredPath}`,
			);
		}
	}
	assert.deepEqual(configuration.workspace.requiredPaths, [
		"examples/plugins/servo/servo_ctrl.py",
		"examples/plugins/servo/plugin.toml",
		"examples/plugins/servo/servo_actions/README.md",
		"skills/servo-control/SKILL.md",
		"tools/servo_action.py",
	]);
	if (configuration.workspace.kind === "managed-template") {
		assert.equal(configuration.workspace.id, "magicbox-servo");
	assert.equal(configuration.workspace.version, 7);
		assert.match(configuration.workspace.templateDirectory, /config\/templates\/magicbox-servo$/);
	}
	for (const profile of configuration.profiles) assert.equal(profile.maxToolCalls, undefined);
	for (const id of ["action-test", "action-coding"]) {
		const profile = byId.get(id);
		assert.ok(profile, `${id} should exist`);
		assert.equal(profile.maxToolCalls, undefined);
		assert.ok(profile.timeoutSeconds <= 300);
		assert.ok(profile.tools.includes("write"));
	}
	for (const id of ["action-verification"]) {
		const profile = byId.get(id);
		assert.ok(profile, `${id} should exist`);
		assert.equal(profile.tools.includes("write"), false);
		assert.equal(profile.tools.includes("edit"), false);
	}
	for (const id of ["action-test", "action-coding", "action-verification"]) {
		assert.deepEqual(byId.get(id)?.sandbox, {
			kind: "podman",
			image: "docker.io/library/python:3.12-slim",
			network: "none",
		});
	}
	for (const id of ["release-deploy", "skill-deploy", "cli-live-acceptance", "skill-live-acceptance", "robot-application"]) {
		assert.equal(byId.get(id)?.sandbox, undefined);
	}
	assert.match(byId.get("action-test")?.systemPrompt ?? "", /action-package/);
	assert.match(byId.get("action-test")?.systemPrompt ?? "", /挥动左手.*wave-left-hand/);
	assert.match(byId.get("action-test")?.systemPrompt ?? "", /挥动右手.*wave-right-hand/);
	assert.match(byId.get("action-test")?.systemPrompt ?? "", /actionId、description、start、intentExamples.*方向一致/);
	assert.doesNotMatch(byId.get("action-test")?.systemPrompt ?? "", /对“开发一个挥动右手的功能”/);
	assert.doesNotMatch(byId.get("action-test")?.systemPrompt ?? "", /start\s*=\s*`?(?:left|right)`?/);
	assert.doesNotMatch(byId.get("action-test")?.systemPrompt ?? "", /lift_(?:left|right).*lower_(?:left|right)/);
	assert.match(byId.get("action-test")?.systemPrompt ?? "", /修改、修复、测试既有功能或返工轮时绝不能再次 scaffold/);
	assert.match(byId.get("action-test")?.systemPrompt ?? "", /v1 只支持无参数动作/);
	assert.match(byId.get("action-coding")?.systemPrompt ?? "", /run\(context, params\)/);
	assert.match(byId.get("action-verification")?.systemPrompt ?? "", /错误码/);
	assert.deepEqual(byId.get("action-test")?.actionPackage, { operations: ["scaffold"] });
	assert.deepEqual(byId.get("action-verification")?.actionPackage, { operations: ["validate"] });
	for (const id of ["release-deploy", "skill-deploy"]) {
		const profile = byId.get(id);
		assert.ok(profile?.tools.includes("deploy"), `${id} should expose deploy`);
		assert.ok(profile?.deployment, `${id} should have a deterministic deployment plan`);
	}
	assert.deepEqual(byId.get("release-deploy")?.deployment, {
		kind: "ssh",
		host: "x5-root",
		restartService: "probe-daemon.service",
		artifacts: [
			{
				source: "examples/plugins/servo/servo_ctrl.py",
				target: "/userdata/magicbox/scripts/servo_ctrl.py",
				mode: "0755",
				recursive: false,
			},
			{
				source: ".rdk-agent/releases/current/servo_actions",
				target: "/userdata/magicbox/scripts/servo_actions",
				mode: "0755",
				recursive: true,
				owner: "probe:probe",
			},
		],
	});
	assert.deepEqual(byId.get("skill-deploy")?.deployment, {
		kind: "skill",
		source: ".rdk-agent/releases/current/skill",
		skillName: "servo-control",
		runtimeFiles: ["SKILL.md", "skill-catalog.json"],
	});
	const development = configuration.modes.find((mode) => mode.id === "robot-development");
	assert.equal(development?.type, "robot-development");
	if (development?.type === "robot-development") {
		assert.deepEqual(development.loops.map((loop) => loop.deploymentAgentId), ["release-deploy"]);
		assert.deepEqual(development.deliveryAgentIds, ["skill-deploy"]);
		assert.deepEqual(development.acceptanceAgentIds, ["cli-live-acceptance", "skill-live-acceptance"]);
	}
});
