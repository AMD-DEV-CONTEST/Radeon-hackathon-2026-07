import assert from "node:assert/strict";
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";

const projectDirectory = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const repositoryDirectory = resolve(projectDirectory, "..");

test("installer help explains the safe config refresh option", () => {
	const result = spawnSync("bash", [join(projectDirectory, "deploy", "install-rdk-agent.sh"), "--help"], {
		encoding: "utf8",
	});

	assert.equal(result.status, 0, result.stderr);
	assert.match(result.stdout, /--refresh-config/);
	assert.match(result.stdout, /备份后覆盖包内同名静态配置/);
	assert.match(result.stdout, /不删除额外文件/);
	assert.match(result.stdout, /保留运行时 servo-control/);
});

test("installer upgrades an unchanged default config while ignoring its generated migration example", (context) => {
	const temporaryDirectory = mkdtempSync(join(tmpdir(), "rdk-agent-installer-"));
	context.after(() => rmSync(temporaryDirectory, { recursive: true, force: true }));

	const installDirectory = join(temporaryDirectory, "app");
	const binaryDirectory = join(temporaryDirectory, "bin");
	const configDirectory = join(temporaryDirectory, "config");
	const fakeBinaryDirectory = join(temporaryDirectory, "fake-bin");
	mkdirSync(join(installDirectory, "config"), { recursive: true });
	mkdirSync(configDirectory, { recursive: true });
	mkdirSync(fakeBinaryDirectory, { recursive: true });

	writeFileSync(join(installDirectory, "config", "agents.yaml"), "old-default\n");
	writeFileSync(join(configDirectory, "agents.yaml"), "old-default\n");
	writeFileSync(join(configDirectory, "agents.yaml.v2.example"), "generated-example\n");

	const fakeNode = join(fakeBinaryDirectory, "node");
	const fakeNpm = join(fakeBinaryDirectory, "npm");
	writeFileSync(fakeNode, '#!/bin/sh\nif [ "${1:-}" = "--version" ]; then echo v22.23.2; fi\nexit 0\n');
	writeFileSync(fakeNpm, "#!/bin/sh\nexit 0\n");
	chmodSync(fakeNode, 0o755);
	chmodSync(fakeNpm, 0o755);

	const result = spawnSync(
		"bash",
		[
			join(projectDirectory, "deploy", "install-rdk-agent.sh"),
			"--install-dir",
			installDirectory,
			"--bin-dir",
			binaryDirectory,
			"--config-dir",
			configDirectory,
		],
		{
			encoding: "utf8",
			env: { ...process.env, PATH: `${fakeBinaryDirectory}:/usr/bin:/bin` },
		},
	);

	assert.equal(result.status, 0, result.stderr || result.stdout);
	assert.match(result.stdout, /未修改的默认配置已升级到最新版本/);
	assert.equal(
		readFileSync(join(configDirectory, "agents.yaml"), "utf8"),
		readFileSync(join(projectDirectory, "config", "agents.yaml"), "utf8"),
	);
	assert.equal(
		readdirSync(join(installDirectory, "config", "skills")).some((name) => name.startsWith(".servo-control.rdk-agent-")),
		false,
	);
	assert.equal(
		readFileSync(join(installDirectory, "config", "templates", "magicbox-servo", "examples", "plugins", "servo", "plugin.toml"), "utf8"),
		readFileSync(join(projectDirectory, "config", "templates", "magicbox-servo", "examples", "plugins", "servo", "plugin.toml"), "utf8"),
	);
});

test("installer upgrades an unchanged agents config despite runtime config directory changes", (context) => {
	const temporaryDirectory = mkdtempSync(join(tmpdir(), "rdk-agent-installer-runtime-files-"));
	context.after(() => rmSync(temporaryDirectory, { recursive: true, force: true }));

	const installDirectory = join(temporaryDirectory, "app");
	const binaryDirectory = join(temporaryDirectory, "bin");
	const configDirectory = join(temporaryDirectory, "config");
	const fakeBinaryDirectory = join(temporaryDirectory, "fake-bin");
	mkdirSync(join(installDirectory, "config", "skills", "servo-control"), { recursive: true });
	mkdirSync(join(configDirectory, "skills", "servo-control"), { recursive: true });
	mkdirSync(join(configDirectory, "skills", ".servo-control.rdk-agent-runtime.bak"), { recursive: true });
	mkdirSync(join(installDirectory, "config", "templates", "magicbox-servo", "tools"), { recursive: true });
	mkdirSync(join(configDirectory, "templates", "magicbox-servo", "tools", "__pycache__"), { recursive: true });
	mkdirSync(fakeBinaryDirectory, { recursive: true });

	writeFileSync(join(installDirectory, "config", "agents.yaml"), "old-default\n");
	writeFileSync(join(configDirectory, "agents.yaml"), "old-default\n");
	writeFileSync(join(installDirectory, "config", "skills", "servo-control", "SKILL.md"), "installed skill\n");
	writeFileSync(join(configDirectory, "skills", "servo-control", "SKILL.md"), "runtime-updated skill\n");
	writeFileSync(
		join(configDirectory, "skills", ".servo-control.rdk-agent-runtime.bak", "SKILL.md"),
		"runtime backup\n",
	);
	writeFileSync(
		join(installDirectory, "config", "templates", "magicbox-servo", "tools", "servo_action.py"),
		"static tool\n",
	);
	writeFileSync(
		join(configDirectory, "templates", "magicbox-servo", "tools", "servo_action.py"),
		"static tool\n",
	);
	writeFileSync(
		join(configDirectory, "templates", "magicbox-servo", "tools", "__pycache__", "servo_action.pyc"),
		"runtime bytecode\n",
	);

	const fakeNode = join(fakeBinaryDirectory, "node");
	const fakeNpm = join(fakeBinaryDirectory, "npm");
	writeFileSync(fakeNode, '#!/bin/sh\nif [ "${1:-}" = "--version" ]; then echo v22.23.2; fi\nexit 0\n');
	writeFileSync(fakeNpm, "#!/bin/sh\nexit 0\n");
	chmodSync(fakeNode, 0o755);
	chmodSync(fakeNpm, 0o755);

	const result = spawnSync(
		"bash",
		[
			join(projectDirectory, "deploy", "install-rdk-agent.sh"),
			"--install-dir",
			installDirectory,
			"--bin-dir",
			binaryDirectory,
			"--config-dir",
			configDirectory,
		],
		{
			encoding: "utf8",
			env: { ...process.env, PATH: `${fakeBinaryDirectory}:/usr/bin:/bin` },
		},
	);

	assert.equal(result.status, 0, result.stderr || result.stdout);
	assert.match(result.stdout, /未修改的默认配置已升级到最新版本/);
	assert.equal(
		readFileSync(join(configDirectory, "agents.yaml"), "utf8"),
		readFileSync(join(projectDirectory, "config", "agents.yaml"), "utf8"),
	);
	assert.equal(readFileSync(join(configDirectory, "skills", "servo-control", "SKILL.md"), "utf8"), "runtime-updated skill\n");
	assert.equal(
		readFileSync(join(configDirectory, "skills", ".servo-control.rdk-agent-runtime.bak", "SKILL.md"), "utf8"),
		"runtime backup\n",
	);
	assert.match(result.stdout, /已保留运行时 servo-control Skill/);
});

test("installer migrates the byte-identical retired default actions registry during a default upgrade", (context) => {
	const temporaryDirectory = mkdtempSync(join(tmpdir(), "rdk-agent-installer-retired-actions-"));
	context.after(() => rmSync(temporaryDirectory, { recursive: true, force: true }));

	const installDirectory = join(temporaryDirectory, "app");
	const binaryDirectory = join(temporaryDirectory, "bin");
	const configDirectory = join(temporaryDirectory, "config");
	const fakeBinaryDirectory = join(temporaryDirectory, "fake-bin");
	const actionsRegistry = join(
		"templates",
		"magicbox-servo",
		"examples",
		"plugins",
		"servo",
		"servo_actions",
		"actions.json",
	);
	const retiredDefault = '{\n  "version": 1,\n  "actions": {}\n}\n';

	for (const directory of [
		join(installDirectory, "config", dirname(actionsRegistry)),
		join(configDirectory, dirname(actionsRegistry)),
		fakeBinaryDirectory,
	]) {
		mkdirSync(directory, { recursive: true });
	}
	writeFileSync(join(installDirectory, "config", "agents.yaml"), "old-default\n");
	writeFileSync(join(configDirectory, "agents.yaml"), "old-default\n");
	writeFileSync(join(installDirectory, "config", actionsRegistry), retiredDefault);
	writeFileSync(join(configDirectory, actionsRegistry), retiredDefault);

	const fakeNode = join(fakeBinaryDirectory, "node");
	const fakeNpm = join(fakeBinaryDirectory, "npm");
	writeFileSync(fakeNode, '#!/bin/sh\nif [ "${1:-}" = "--version" ]; then echo v22.23.2; fi\nexit 0\n');
	writeFileSync(fakeNpm, "#!/bin/sh\nexit 0\n");
	chmodSync(fakeNode, 0o755);
	chmodSync(fakeNpm, 0o755);

	const result = spawnSync(
		"bash",
		[
			join(projectDirectory, "deploy", "install-rdk-agent.sh"),
			"--install-dir",
			installDirectory,
			"--bin-dir",
			binaryDirectory,
			"--config-dir",
			configDirectory,
		],
		{
			encoding: "utf8",
			env: { ...process.env, PATH: `${fakeBinaryDirectory}:/usr/bin:/bin` },
		},
	);

	assert.equal(result.status, 0, result.stderr || result.stdout);
	assert.match(result.stdout, /未修改的默认配置已升级到最新版本/);
	assert.match(result.stdout, /已移除旧版默认空 actions\.json/);
	assert.equal(existsSync(join(configDirectory, actionsRegistry)), false);
});

test("installer preserves a byte-modified actions registry as customized config", (context) => {
	const temporaryDirectory = mkdtempSync(join(tmpdir(), "rdk-agent-installer-custom-actions-"));
	context.after(() => rmSync(temporaryDirectory, { recursive: true, force: true }));

	const installDirectory = join(temporaryDirectory, "app");
	const binaryDirectory = join(temporaryDirectory, "bin");
	const configDirectory = join(temporaryDirectory, "config");
	const fakeBinaryDirectory = join(temporaryDirectory, "fake-bin");
	const actionsRegistry = join(
		"templates",
		"magicbox-servo",
		"examples",
		"plugins",
		"servo",
		"servo_actions",
		"actions.json",
	);
	const retiredDefault = '{\n  "version": 1,\n  "actions": {}\n}\n';
	const customizedRegistry = '{\n "version": 1,\n "actions": {}\n}\n';

	for (const directory of [
		join(installDirectory, "config", dirname(actionsRegistry)),
		join(configDirectory, dirname(actionsRegistry)),
		fakeBinaryDirectory,
	]) {
		mkdirSync(directory, { recursive: true });
	}
	writeFileSync(join(installDirectory, "config", "agents.yaml"), "old-default\n");
	writeFileSync(join(configDirectory, "agents.yaml"), "old-default\n");
	writeFileSync(join(installDirectory, "config", actionsRegistry), retiredDefault);
	writeFileSync(join(configDirectory, actionsRegistry), customizedRegistry);

	const fakeNode = join(fakeBinaryDirectory, "node");
	const fakeNpm = join(fakeBinaryDirectory, "npm");
	writeFileSync(fakeNode, '#!/bin/sh\nif [ "${1:-}" = "--version" ]; then echo v22.23.2; fi\nexit 0\n');
	writeFileSync(fakeNpm, "#!/bin/sh\nexit 0\n");
	chmodSync(fakeNode, 0o755);
	chmodSync(fakeNpm, 0o755);

	const result = spawnSync(
		"bash",
		[
			join(projectDirectory, "deploy", "install-rdk-agent.sh"),
			"--install-dir",
			installDirectory,
			"--bin-dir",
			binaryDirectory,
			"--config-dir",
			configDirectory,
		],
		{
			encoding: "utf8",
			env: { ...process.env, PATH: `${fakeBinaryDirectory}:/usr/bin:/bin` },
		},
	);

	assert.equal(result.status, 0, result.stderr || result.stdout);
	assert.match(result.stdout, /保留已有配置/);
	assert.equal(readFileSync(join(configDirectory, actionsRegistry), "utf8"), customizedRegistry);
	assert.equal(readFileSync(join(configDirectory, "agents.yaml"), "utf8"), "old-default\n");
	assert.equal(
		readFileSync(join(configDirectory, "agents.yaml.v2.example"), "utf8"),
		readFileSync(join(projectDirectory, "config", "agents.yaml"), "utf8"),
	);
});

test("installer preserves real static template and authoring skill customizations", (context) => {
	const staticPaths = [
		join("skills", "magicbox-command-authoring", "SKILL.md"),
		join("templates", "magicbox-servo", "custom-contract.md"),
	];

	for (const [index, customizedPath] of staticPaths.entries()) {
		const temporaryDirectory = mkdtempSync(join(tmpdir(), `rdk-agent-installer-static-${index}-`));
		context.after(() => rmSync(temporaryDirectory, { recursive: true, force: true }));

		const installDirectory = join(temporaryDirectory, "app");
		const binaryDirectory = join(temporaryDirectory, "bin");
		const configDirectory = join(temporaryDirectory, "config");
		const fakeBinaryDirectory = join(temporaryDirectory, "fake-bin");
		mkdirSync(join(installDirectory, "config", dirname(customizedPath)), { recursive: true });
		mkdirSync(join(configDirectory, dirname(customizedPath)), { recursive: true });
		mkdirSync(fakeBinaryDirectory, { recursive: true });

		writeFileSync(join(installDirectory, "config", "agents.yaml"), "old-default\n");
		writeFileSync(join(configDirectory, "agents.yaml"), "old-default\n");
		writeFileSync(join(installDirectory, "config", customizedPath), "static default\n");
		writeFileSync(join(configDirectory, customizedPath), "user customization\n");

		const fakeNode = join(fakeBinaryDirectory, "node");
		const fakeNpm = join(fakeBinaryDirectory, "npm");
		writeFileSync(fakeNode, '#!/bin/sh\nif [ "${1:-}" = "--version" ]; then echo v22.23.2; fi\nexit 0\n');
		writeFileSync(fakeNpm, "#!/bin/sh\nexit 0\n");
		chmodSync(fakeNode, 0o755);
		chmodSync(fakeNpm, 0o755);

		const result = spawnSync(
			"bash",
			[
				join(projectDirectory, "deploy", "install-rdk-agent.sh"),
				"--install-dir",
				installDirectory,
				"--bin-dir",
				binaryDirectory,
				"--config-dir",
				configDirectory,
			],
			{
				encoding: "utf8",
				env: { ...process.env, PATH: `${fakeBinaryDirectory}:/usr/bin:/bin` },
			},
		);

		assert.equal(result.status, 0, result.stderr || result.stdout);
		assert.match(result.stdout, /保留已有配置/);
		assert.equal(readFileSync(join(configDirectory, customizedPath), "utf8"), "user customization\n");
		assert.equal(readFileSync(join(configDirectory, "agents.yaml"), "utf8"), "old-default\n");
		assert.equal(
			readFileSync(join(configDirectory, "agents.yaml.v2.example"), "utf8"),
			readFileSync(join(projectDirectory, "config", "agents.yaml"), "utf8"),
		);
	}
});

test("refresh-config backs up and refreshes customized static config while preserving runtime servo files", (context) => {
	const temporaryDirectory = mkdtempSync(join(tmpdir(), "rdk-agent-installer-refresh-config-"));
	context.after(() => rmSync(temporaryDirectory, { recursive: true, force: true }));

	const installDirectory = join(temporaryDirectory, "app");
	const binaryDirectory = join(temporaryDirectory, "bin");
	const configDirectory = join(temporaryDirectory, "config");
	const fakeBinaryDirectory = join(temporaryDirectory, "fake-bin");
	const authoringSkill = join("skills", "magicbox-command-authoring", "SKILL.md");
	const runtimeSkill = join("skills", "servo-control", "SKILL.md");
	const runtimeRollback = join("skills", ".servo-control.rdk-agent-runtime.bak", "SKILL.md");
	const templateTool = join("templates", "magicbox-servo", "tools", "servo_action.py");
	const extraStaticFile = join("templates", "local-extra.md");

	for (const directory of [
		join(installDirectory, "config", dirname(authoringSkill)),
		join(installDirectory, "config", dirname(runtimeSkill)),
		join(installDirectory, "config", dirname(templateTool)),
		join(configDirectory, dirname(authoringSkill)),
		join(configDirectory, dirname(runtimeSkill)),
		join(configDirectory, dirname(runtimeRollback)),
		join(configDirectory, dirname(templateTool)),
		join(configDirectory, dirname(extraStaticFile)),
		fakeBinaryDirectory,
	]) {
		mkdirSync(directory, { recursive: true });
	}

	writeFileSync(join(installDirectory, "config", "agents.yaml"), "old bundled agents\n");
	writeFileSync(join(installDirectory, "config", authoringSkill), "old bundled authoring\n");
	writeFileSync(join(installDirectory, "config", runtimeSkill), "old bundled runtime\n");
	writeFileSync(join(installDirectory, "config", templateTool), "old bundled template\n");
	writeFileSync(join(configDirectory, "agents.yaml"), "custom agents\n");
	writeFileSync(join(configDirectory, authoringSkill), "custom authoring\n");
	writeFileSync(join(configDirectory, runtimeSkill), "runtime servo-control\n");
	writeFileSync(join(configDirectory, runtimeRollback), "runtime rollback\n");
	writeFileSync(join(configDirectory, templateTool), "custom template\n");
	writeFileSync(join(configDirectory, extraStaticFile), "local extra static file\n");

	const fakeNode = join(fakeBinaryDirectory, "node");
	const fakeNpm = join(fakeBinaryDirectory, "npm");
	writeFileSync(fakeNode, '#!/bin/sh\nif [ "${1:-}" = "--version" ]; then echo v22.23.2; fi\nexit 0\n');
	writeFileSync(fakeNpm, "#!/bin/sh\nexit 0\n");
	chmodSync(fakeNode, 0o755);
	chmodSync(fakeNpm, 0o755);

	const result = spawnSync(
		"bash",
		[
			join(projectDirectory, "deploy", "install-rdk-agent.sh"),
			"--install-dir",
			installDirectory,
			"--bin-dir",
			binaryDirectory,
			"--config-dir",
			configDirectory,
			"--refresh-config",
		],
		{
			encoding: "utf8",
			env: { ...process.env, PATH: `${fakeBinaryDirectory}:/usr/bin:/bin` },
		},
	);

	assert.equal(result.status, 0, result.stderr || result.stdout);
	assert.match(result.stdout, /刷新前配置已完整备份/);
	assert.match(result.stdout, /已覆盖包内同名静态配置/);
	assert.equal(
		readFileSync(join(configDirectory, "agents.yaml"), "utf8"),
		readFileSync(join(projectDirectory, "config", "agents.yaml"), "utf8"),
	);
	assert.equal(
		readFileSync(join(configDirectory, authoringSkill), "utf8"),
		readFileSync(join(projectDirectory, "config", authoringSkill), "utf8"),
	);
	assert.equal(
		readFileSync(join(configDirectory, templateTool), "utf8"),
		readFileSync(join(projectDirectory, "config", templateTool), "utf8"),
	);
	assert.equal(readFileSync(join(configDirectory, runtimeSkill), "utf8"), "runtime servo-control\n");
	assert.equal(readFileSync(join(configDirectory, runtimeRollback), "utf8"), "runtime rollback\n");
	assert.equal(readFileSync(join(configDirectory, extraStaticFile), "utf8"), "local extra static file\n");

	const configBackups = readdirSync(temporaryDirectory).filter((name) => name.startsWith("config.backup."));
	assert.equal(configBackups.length, 1);
	assert.match(configBackups[0]!, /^config\.backup\.\d{8}-\d{6}(?:\.\d+)?$/);
	const configBackup = join(temporaryDirectory, configBackups[0]!);
	assert.equal(readFileSync(join(configBackup, "agents.yaml"), "utf8"), "custom agents\n");
	assert.equal(readFileSync(join(configBackup, authoringSkill), "utf8"), "custom authoring\n");
	assert.equal(readFileSync(join(configBackup, templateTool), "utf8"), "custom template\n");
	assert.equal(readFileSync(join(configBackup, runtimeSkill), "utf8"), "runtime servo-control\n");
	assert.equal(readFileSync(join(configBackup, runtimeRollback), "utf8"), "runtime rollback\n");
	assert.equal(readFileSync(join(configBackup, extraStaticFile), "utf8"), "local extra static file\n");
});

test("refresh-config rolls back the application and config when command registration fails", (context) => {
	const temporaryDirectory = mkdtempSync(join(tmpdir(), "rdk-agent-installer-refresh-rollback-"));
	context.after(() => rmSync(temporaryDirectory, { recursive: true, force: true }));

	const installDirectory = join(temporaryDirectory, "app");
	const binaryDirectory = join(temporaryDirectory, "bin");
	const configDirectory = join(temporaryDirectory, "config");
	const fakeBinaryDirectory = join(temporaryDirectory, "fake-bin");
	const authoringSkill = join("skills", "magicbox-command-authoring", "SKILL.md");
	const runtimeSkill = join("skills", "servo-control", "SKILL.md");
	const runtimeRollback = join("skills", ".servo-control.rdk-agent-runtime.bak", "SKILL.md");
	const templateTool = join("templates", "magicbox-servo", "tools", "servo_action.py");

	for (const directory of [
		join(installDirectory, "config"),
		join(configDirectory, dirname(authoringSkill)),
		join(configDirectory, dirname(runtimeSkill)),
		join(configDirectory, dirname(runtimeRollback)),
		join(configDirectory, dirname(templateTool)),
		binaryDirectory,
		fakeBinaryDirectory,
	]) {
		mkdirSync(directory, { recursive: true });
	}

	writeFileSync(join(installDirectory, "installed-version.txt"), "previous application\n");
	writeFileSync(join(installDirectory, "config", "agents.yaml"), "previous bundled agents\n");
	writeFileSync(join(configDirectory, "agents.yaml"), "custom agents before failed refresh\n");
	writeFileSync(join(configDirectory, authoringSkill), "custom authoring before failed refresh\n");
	writeFileSync(join(configDirectory, runtimeSkill), "runtime skill before failed refresh\n");
	writeFileSync(join(configDirectory, runtimeRollback), "runtime rollback before failed refresh\n");
	writeFileSync(join(configDirectory, templateTool), "custom template before failed refresh\n");

	const fakeNode = join(fakeBinaryDirectory, "node");
	const fakeNpm = join(fakeBinaryDirectory, "npm");
	const fakeLn = join(fakeBinaryDirectory, "ln");
	writeFileSync(fakeNode, '#!/bin/sh\nif [ "${1:-}" = "--version" ]; then echo v22.23.2; fi\nexit 0\n');
	writeFileSync(fakeNpm, "#!/bin/sh\nexit 0\n");
	writeFileSync(fakeLn, "#!/bin/sh\necho 'forced command registration failure' >&2\nexit 73\n");
	chmodSync(fakeNode, 0o755);
	chmodSync(fakeNpm, 0o755);
	chmodSync(fakeLn, 0o755);

	const result = spawnSync(
		"bash",
		[
			join(projectDirectory, "deploy", "install-rdk-agent.sh"),
			"--install-dir",
			installDirectory,
			"--bin-dir",
			binaryDirectory,
			"--config-dir",
			configDirectory,
			"--refresh-config",
		],
		{
			encoding: "utf8",
			env: { ...process.env, PATH: `${fakeBinaryDirectory}:/usr/bin:/bin` },
		},
	);

	assert.equal(result.status, 73, result.stderr || result.stdout);
	assert.match(result.stderr, /forced command registration failure/);
	assert.match(result.stderr, /自动恢复配置/);
	assert.equal(readFileSync(join(installDirectory, "installed-version.txt"), "utf8"), "previous application\n");
	assert.equal(readFileSync(join(configDirectory, "agents.yaml"), "utf8"), "custom agents before failed refresh\n");
	assert.equal(
		readFileSync(join(configDirectory, authoringSkill), "utf8"),
		"custom authoring before failed refresh\n",
	);
	assert.equal(readFileSync(join(configDirectory, runtimeSkill), "utf8"), "runtime skill before failed refresh\n");
	assert.equal(
		readFileSync(join(configDirectory, runtimeRollback), "utf8"),
		"runtime rollback before failed refresh\n",
	);
	assert.equal(
		readFileSync(join(configDirectory, templateTool), "utf8"),
		"custom template before failed refresh\n",
	);

	const configBackups = readdirSync(temporaryDirectory).filter((name) => name.startsWith("config.backup."));
	assert.equal(configBackups.length, 1);
	const configBackup = join(temporaryDirectory, configBackups[0]!);
	assert.equal(readFileSync(join(configBackup, "agents.yaml"), "utf8"), "custom agents before failed refresh\n");
	assert.equal(readFileSync(join(configBackup, runtimeSkill), "utf8"), "runtime skill before failed refresh\n");
	assert.equal(
		readdirSync(temporaryDirectory).some((name) => name.startsWith("app.backup.")),
		false,
	);
});

test("automatic default config upgrade rolls back the full config and application when command registration fails", (context) => {
	const temporaryDirectory = mkdtempSync(join(tmpdir(), "rdk-agent-installer-default-upgrade-rollback-"));
	context.after(() => rmSync(temporaryDirectory, { recursive: true, force: true }));

	const installDirectory = join(temporaryDirectory, "app");
	const binaryDirectory = join(temporaryDirectory, "bin");
	const configDirectory = join(temporaryDirectory, "config");
	const fakeBinaryDirectory = join(temporaryDirectory, "fake-bin");
	const runtimeSkill = join("skills", "servo-control", "SKILL.md");
	const legacyActionsRegistry = join(
		"templates",
		"magicbox-servo",
		"examples",
		"plugins",
		"servo",
		"servo_actions",
		"actions.json",
	);
	const retiredDefault = '{\n  "version": 1,\n  "actions": {}\n}\n';

	for (const directory of [
		join(installDirectory, "config", dirname(runtimeSkill)),
		join(installDirectory, "config", dirname(legacyActionsRegistry)),
		join(configDirectory, dirname(runtimeSkill)),
		join(configDirectory, dirname(legacyActionsRegistry)),
		binaryDirectory,
		fakeBinaryDirectory,
	]) {
		mkdirSync(directory, { recursive: true });
	}

	writeFileSync(join(installDirectory, "installed-version.txt"), "previous application\n");
	writeFileSync(join(installDirectory, "config", "agents.yaml"), "previous default agents\n");
	writeFileSync(join(installDirectory, "config", runtimeSkill), "previous bundled runtime skill\n");
	writeFileSync(join(installDirectory, "config", legacyActionsRegistry), retiredDefault);
	writeFileSync(join(configDirectory, "agents.yaml"), "previous default agents\n");
	writeFileSync(join(configDirectory, runtimeSkill), "runtime-updated skill\n");
	writeFileSync(join(configDirectory, legacyActionsRegistry), retiredDefault);

	const fakeNode = join(fakeBinaryDirectory, "node");
	const fakeNpm = join(fakeBinaryDirectory, "npm");
	const fakeLn = join(fakeBinaryDirectory, "ln");
	writeFileSync(fakeNode, '#!/bin/sh\nif [ "${1:-}" = "--version" ]; then echo v22.23.2; fi\nexit 0\n');
	writeFileSync(fakeNpm, "#!/bin/sh\nexit 0\n");
	writeFileSync(fakeLn, "#!/bin/sh\necho 'forced automatic upgrade registration failure' >&2\nexit 74\n");
	chmodSync(fakeNode, 0o755);
	chmodSync(fakeNpm, 0o755);
	chmodSync(fakeLn, 0o755);

	const result = spawnSync(
		"bash",
		[
			join(projectDirectory, "deploy", "install-rdk-agent.sh"),
			"--install-dir",
			installDirectory,
			"--bin-dir",
			binaryDirectory,
			"--config-dir",
			configDirectory,
		],
		{
			encoding: "utf8",
			env: { ...process.env, PATH: `${fakeBinaryDirectory}:/usr/bin:/bin` },
		},
	);

	assert.equal(result.status, 74, result.stderr || result.stdout);
	assert.match(result.stderr, /forced automatic upgrade registration failure/);
	assert.match(result.stderr, /已自动恢复升级前的默认配置/);
	assert.equal(readFileSync(join(installDirectory, "installed-version.txt"), "utf8"), "previous application\n");
	assert.equal(readFileSync(join(configDirectory, "agents.yaml"), "utf8"), "previous default agents\n");
	assert.equal(readFileSync(join(configDirectory, runtimeSkill), "utf8"), "runtime-updated skill\n");
	assert.equal(readFileSync(join(configDirectory, legacyActionsRegistry), "utf8"), retiredDefault);
	assert.equal(
		readdirSync(temporaryDirectory).some((name) => name.startsWith("app.backup.")),
		false,
	);
});

test("installer recognizes its prior automatic agents migration as an unchanged default", (context) => {
	const temporaryDirectory = mkdtempSync(join(tmpdir(), "rdk-agent-installer-auto-migration-"));
	context.after(() => rmSync(temporaryDirectory, { recursive: true, force: true }));

	const installDirectory = join(temporaryDirectory, "app");
	const binaryDirectory = join(temporaryDirectory, "bin");
	const configDirectory = join(temporaryDirectory, "config");
	const fakeBinaryDirectory = join(temporaryDirectory, "fake-bin");
	mkdirSync(join(installDirectory, "config"), { recursive: true });
	mkdirSync(configDirectory, { recursive: true });
	mkdirSync(fakeBinaryDirectory, { recursive: true });

	const previousDefault = `version: 2
agents:
  - id: python-test
    validation:
      kind: servo-python-test
    systemPrompt: Default prompt
`;
	const automaticallyMigratedDefault = `version: 2
agents:
  - id: python-test
    systemPrompt: Default prompt
`;
	writeFileSync(join(installDirectory, "config", "agents.yaml"), previousDefault);
	writeFileSync(join(configDirectory, "agents.yaml"), automaticallyMigratedDefault);
	writeFileSync(join(configDirectory, "agents.yaml.before-servo-python-test-migration"), previousDefault);

	const fakeNode = join(fakeBinaryDirectory, "node");
	const fakeNpm = join(fakeBinaryDirectory, "npm");
	writeFileSync(fakeNode, '#!/bin/sh\nif [ "${1:-}" = "--version" ]; then echo v22.23.2; fi\nexit 0\n');
	writeFileSync(fakeNpm, "#!/bin/sh\nexit 0\n");
	chmodSync(fakeNode, 0o755);
	chmodSync(fakeNpm, 0o755);

	const result = spawnSync(
		"bash",
		[
			join(projectDirectory, "deploy", "install-rdk-agent.sh"),
			"--install-dir",
			installDirectory,
			"--bin-dir",
			binaryDirectory,
			"--config-dir",
			configDirectory,
		],
		{
			encoding: "utf8",
			env: { ...process.env, PATH: `${fakeBinaryDirectory}:/usr/bin:/bin` },
		},
	);

	assert.equal(result.status, 0, result.stderr || result.stdout);
	assert.match(result.stdout, /未修改的默认配置已升级到最新版本/);
	assert.equal(
		readFileSync(join(configDirectory, "agents.yaml"), "utf8"),
		readFileSync(join(projectDirectory, "config", "agents.yaml"), "utf8"),
	);
});

test("installer removes retired servo Python validation without overwriting customized configuration", (context) => {
	const temporaryDirectory = mkdtempSync(join(tmpdir(), "rdk-agent-installer-migration-"));
	context.after(() => rmSync(temporaryDirectory, { recursive: true, force: true }));

	const installDirectory = join(temporaryDirectory, "app");
	const binaryDirectory = join(temporaryDirectory, "bin");
	const configDirectory = join(temporaryDirectory, "config");
	const fakeBinaryDirectory = join(temporaryDirectory, "fake-bin");
	mkdirSync(join(installDirectory, "config"), { recursive: true });
	mkdirSync(configDirectory, { recursive: true });
	mkdirSync(fakeBinaryDirectory, { recursive: true });

	writeFileSync(join(installDirectory, "config", "agents.yaml"), "previous-default\n");
	const customizedConfiguration = `version: 2
agents:
  - id: python-test
    validation:
      kind: servo-python-test
    systemPrompt: Customized prompt
`;
	writeFileSync(join(configDirectory, "agents.yaml"), customizedConfiguration);

	const fakeNode = join(fakeBinaryDirectory, "node");
	const fakeNpm = join(fakeBinaryDirectory, "npm");
	writeFileSync(fakeNode, '#!/bin/sh\nif [ "${1:-}" = "--version" ]; then echo v22.23.2; fi\nexit 0\n');
	writeFileSync(fakeNpm, "#!/bin/sh\nexit 0\n");
	chmodSync(fakeNode, 0o755);
	chmodSync(fakeNpm, 0o755);

	const result = spawnSync(
		"bash",
		[
			join(projectDirectory, "deploy", "install-rdk-agent.sh"),
			"--install-dir",
			installDirectory,
			"--bin-dir",
			binaryDirectory,
			"--config-dir",
			configDirectory,
		],
		{
			encoding: "utf8",
			env: { ...process.env, PATH: `${fakeBinaryDirectory}:/usr/bin:/bin` },
		},
	);

	assert.equal(result.status, 0, result.stderr || result.stdout);
	assert.match(result.stdout, /保留已有配置/);
	assert.match(result.stdout, /已迁移旧版 servo-python-test 配置/);
	const migratedConfiguration = readFileSync(join(configDirectory, "agents.yaml"), "utf8");
	assert.doesNotMatch(migratedConfiguration, /servo-python-test/);
	assert.match(migratedConfiguration, /systemPrompt: Customized prompt/);
	assert.equal(
		readFileSync(join(configDirectory, "agents.yaml.before-servo-python-test-migration"), "utf8"),
		customizedConfiguration,
	);
});

test("stack installer covers board and development-machine deployment", () => {
	const stackInstaller = join(projectDirectory, "deploy", "install-rdk-agent-stack.sh");
	const boardInstaller = join(repositoryDirectory, "rdk-sophon", "deploy", "scripts", "deploy-to-board.sh");
	const stackHelp = spawnSync("bash", [stackInstaller, "--help"], { encoding: "utf8" });
	const boardHelp = spawnSync("bash", [boardInstaller, "--help"], { encoding: "utf8" });

	assert.equal(stackHelp.status, 0, stackHelp.stderr);
	assert.match(stackHelp.stdout, /--board-address/);
	assert.match(stackHelp.stdout, /--board-only/);
	assert.match(stackHelp.stdout, /--development-only/);
	assert.match(stackHelp.stdout, /--preflight-only/);
	assert.match(stackHelp.stdout, /--skip-servo-bootstrap/);
	assert.equal(boardHelp.status, 0, boardHelp.stderr);
	assert.match(boardHelp.stdout, /--enable-plugins/);

	const source = readFileSync(stackInstaller, "utf8");
	assert.match(source, /deploy-to-board\.sh.*--enable-plugins/s);
	assert.match(source, /install-sophonctl\.sh/);
	assert.match(source, /podman pull docker\.io\/library\/python:3\.12-slim/);
	assert.match(source, /install-rdk-agent\.sh/);
	assert.match(source, /sophonctl --board x5 plugins list/);
	assert.doesNotMatch(source, /servo_actions\/actions\.json/);
	assert.match(source, /systemctl restart probe-daemon\.service/);
	assert.match(source, /\[rdk-sophon\] 部署服务端/);
	assert.match(source, /\[rdk-agent\] 安装 MagicBox servo 运行文件/);
	assert.match(source, /\[rdk-sophon\] 安装 sophonctl/);
	assert.match(source, /\[rdk-agent\] 安装 TUI 编排器/);
});

test("stack installer preflight handles variables next to Chinese punctuation", (context) => {
	const temporaryDirectory = mkdtempSync(join(tmpdir(), "rdk-agent-stack-preflight-"));
	context.after(() => rmSync(temporaryDirectory, { recursive: true, force: true }));

	const fakeBinaryDirectory = join(temporaryDirectory, "bin");
	mkdirSync(fakeBinaryDirectory, { recursive: true });
	for (const commandName of ["ssh", "scp", "cargo"]) {
		const commandPath = join(fakeBinaryDirectory, commandName);
		writeFileSync(commandPath, commandName === "ssh" ? "#!/bin/sh\necho aarch64\n" : "#!/bin/sh\nexit 0\n");
		chmodSync(commandPath, 0o755);
	}

	const stackInstaller = join(projectDirectory, "deploy", "install-rdk-agent-stack.sh");
	const result = spawnSync(
		"bash",
		[
			stackInstaller,
			"--ssh-host",
			"x5-root",
			"--board-address",
			"192.168.128.10:7777",
			"--skip-podman",
			"--preflight-only",
		],
		{
			encoding: "utf8",
			env: { ...process.env, PATH: `${fakeBinaryDirectory}:${process.env.PATH ?? ""}` },
		},
	);

	assert.equal(result.status, 0, result.stderr || result.stdout);
	assert.match(result.stdout, /SSH 可用：x5-root；sophonctl 地址：192\.168\.128\.10:7777/);
	assert.match(result.stdout, /预检完成（目标：all），未执行任何安装或部署/);
});

test("development-only preflight does not require board SSH", (context) => {
	const temporaryDirectory = mkdtempSync(join(tmpdir(), "rdk-agent-development-preflight-"));
	context.after(() => rmSync(temporaryDirectory, { recursive: true, force: true }));

	const fakeBinaryDirectory = join(temporaryDirectory, "bin");
	mkdirSync(fakeBinaryDirectory, { recursive: true });
	const fakeSsh = join(fakeBinaryDirectory, "ssh");
	writeFileSync(fakeSsh, "#!/bin/sh\necho 'development-only must not use ssh' >&2\nexit 86\n");
	chmodSync(fakeSsh, 0o755);
	const fakeCargo = join(fakeBinaryDirectory, "cargo");
	writeFileSync(fakeCargo, "#!/bin/sh\nexit 0\n");
	chmodSync(fakeCargo, 0o755);

	const stackInstaller = join(projectDirectory, "deploy", "install-rdk-agent-stack.sh");
	const result = spawnSync(
		"bash",
		[
			stackInstaller,
			"--development-only",
			"--board-address",
			"192.168.128.10:7777",
			"--skip-podman",
			"--preflight-only",
		],
		{
			encoding: "utf8",
			env: { ...process.env, PATH: `${fakeBinaryDirectory}:${process.env.PATH ?? ""}` },
		},
	);

	assert.equal(result.status, 0, result.stderr || result.stdout);
	assert.doesNotMatch(result.stderr, /development-only must not use ssh/);
	assert.match(result.stdout, /开发机预检通过/);
	assert.match(result.stdout, /预检完成（目标：development）/);
});

test("stack installer rejects conflicting deployment targets", () => {
	const stackInstaller = join(projectDirectory, "deploy", "install-rdk-agent-stack.sh");
	const result = spawnSync("bash", [stackInstaller, "--board-only", "--development-only"], { encoding: "utf8" });

	assert.equal(result.status, 2);
	assert.match(result.stderr, /不能与.*同时使用/);
});
