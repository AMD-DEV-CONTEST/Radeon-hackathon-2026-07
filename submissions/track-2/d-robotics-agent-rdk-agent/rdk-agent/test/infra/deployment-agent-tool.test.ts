import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import type { AgentProfile } from "../../src/domain/agent-profile.ts";
import { createDeploymentToolDefinition, validateSkillPackage } from "../../src/infra/deployment-agent-tool.ts";

test("skill package validation requires loadable Pi metadata", () => {
	assert.doesNotThrow(() => validateSkillPackage("---\nname: servo-control\ndescription: test\n---\n# Body\n", "servo-control"));
	assert.throws(() => validateSkillPackage("# Body\n", "servo-control"), /frontmatter/);
	assert.throws(
		() => validateSkillPackage("---\nname: other\ndescription: test\n---\n# Body\n", "servo-control"),
		/name 必须是 servo-control/,
	);
});

test("skill deployment installs a verified workspace delivery outside the source tree", async (context) => {
	const workspace = mkdtempSync(join(tmpdir(), "rdk-agent-workspace-"));
	const config = mkdtempSync(join(tmpdir(), "rdk-agent-config-"));
	context.after(() => {
		rmSync(workspace, { recursive: true, force: true });
		rmSync(config, { recursive: true, force: true });
	});
	const source = join(workspace, ".rdk-agent", "deliveries", "skills", "servo-control");
	mkdirSync(source, { recursive: true });
	writeFileSync(join(source, "SKILL.md"), "---\nname: servo-control\ndescription: test\n---\nnew skill\n");
	writeFileSync(join(source, "acceptance.md"), "acceptance\n");
	const skillDirectory = join(config, "skills");
	mkdirSync(join(skillDirectory, "servo-control"), { recursive: true });
	writeFileSync(join(skillDirectory, "servo-control", "SKILL.md"), "old skill\n");
	writeFileSync(join(skillDirectory, "servo-control", "acceptance.md"), "installed acceptance\n");
	const profile: AgentProfile = {
		id: "skill-deploy",
		name: "Skill deploy",
		description: "deploy",
		tools: ["deploy"],
		skills: [],
		systemPrompt: "deploy",
		writePaths: [],
		timeoutSeconds: 60,
		deployment: {
			kind: "skill",
			source: ".rdk-agent/deliveries/skills/servo-control",
			skillName: "servo-control",
			runtimeFiles: ["SKILL.md"],
		},
	};
	const tool = createDeploymentToolDefinition(workspace, skillDirectory, profile);
	const result = await tool.execute("call", {}, undefined, undefined, {} as never);

	assert.match(result.content[0]?.type === "text" ? result.content[0].text : "", /部署成功/);
	assert.match(readFileSync(join(skillDirectory, "servo-control", "SKILL.md"), "utf8"), /new skill/);
	assert.equal(readFileSync(join(skillDirectory, "servo-control", "acceptance.md"), "utf8"), "installed acceptance\n");
	assert.match(result.content[0]?.type === "text" ? result.content[0].text : "", /runtimeFiles=SKILL\.md/);
});

test("deployment receipt uses the selected English locale", async (context) => {
	const workspace = mkdtempSync(join(tmpdir(), "rdk-agent-deploy-locale-workspace-"));
	const skillDirectory = mkdtempSync(join(tmpdir(), "rdk-agent-deploy-locale-config-"));
	context.after(() => {
		rmSync(workspace, { recursive: true, force: true });
		rmSync(skillDirectory, { recursive: true, force: true });
	});
	const source = join(workspace, "release", "skill");
	mkdirSync(source, { recursive: true });
	writeFileSync(join(source, "SKILL.md"), "---\nname: demo-skill\ndescription: Demo\n---\n\n# Demo\n");
	const profile: AgentProfile = {
		id: "deploy",
		name: "Deploy",
		description: "Deploy",
		tools: ["deploy"],
		skills: [],
		systemPrompt: "Deploy",
		writePaths: [],
		timeoutSeconds: 10,
		deployment: { kind: "skill", source: "release/skill", skillName: "demo-skill" },
	};
	const tool = createDeploymentToolDefinition(workspace, skillDirectory, profile, "en");
	const result = await tool.execute("call", {}, undefined, undefined, {} as never);
	assert.match(result.content[0]?.type === "text" ? result.content[0].text : "", /Deployment succeeded/);
});

test("invalid skill delivery is rejected before replacing the installed Skill", async (context) => {
	const workspace = mkdtempSync(join(tmpdir(), "rdk-agent-invalid-skill-"));
	const config = mkdtempSync(join(tmpdir(), "rdk-agent-invalid-config-"));
	context.after(() => {
		rmSync(workspace, { recursive: true, force: true });
		rmSync(config, { recursive: true, force: true });
	});
	const source = join(workspace, ".rdk-agent", "deliveries", "skills", "servo-control");
	const installed = join(config, "skills", "servo-control");
	mkdirSync(source, { recursive: true });
	mkdirSync(installed, { recursive: true });
	writeFileSync(join(source, "SKILL.md"), "# missing metadata\n");
	writeFileSync(join(installed, "SKILL.md"), "installed\n");
	const invalidProfile: AgentProfile = {
		id: "skill-deploy",
		name: "Skill deploy",
		description: "deploy",
		tools: ["deploy"],
		skills: [],
		systemPrompt: "deploy",
		writePaths: [],
		timeoutSeconds: 60,
		deployment: { kind: "skill", source: ".rdk-agent/deliveries/skills/servo-control", skillName: "servo-control" },
	};
	const tool = createDeploymentToolDefinition(workspace, join(config, "skills"), invalidProfile);
	await assert.rejects(() => tool.execute("call", {}, undefined, undefined, {} as never), /frontmatter/);
	assert.equal(readFileSync(join(installed, "SKILL.md"), "utf8"), "installed\n");
});

test("SSH deployment validates staged artifacts before swapping and never rolls back an untouched target", async (context) => {
	const workspace = mkdtempSync(join(tmpdir(), "rdk-agent-ssh-workspace-"));
	const fakeBin = mkdtempSync(join(tmpdir(), "rdk-agent-ssh-bin-"));
	const source = join(workspace, "servo.py");
	const log = join(fakeBin, "commands.log");
	writeFileSync(source, "print('servo')\n");
	writeFileSync(
		join(fakeBin, "ssh"),
		"#!/bin/sh\nprintf '%s\\n' \"ssh $*\" >> \"$RDK_TEST_DEPLOY_LOG\"\ncase \"${2:-}\" in sha256sum*) printf '%s  remote\\n' \"$RDK_TEST_REMOTE_HASH\" ;; esac\n",
	);
	writeFileSync(
		join(fakeBin, "scp"),
		"#!/bin/sh\nprintf '%s\\n' \"scp $*\" >> \"$RDK_TEST_DEPLOY_LOG\"\nif [ \"${RDK_TEST_FAIL_SCP:-0}\" = 1 ]; then echo 'simulated scp failure' >&2; exit 9; fi\n",
	);
	chmodSync(join(fakeBin, "ssh"), 0o755);
	chmodSync(join(fakeBin, "scp"), 0o755);
	const previousPath = process.env.PATH;
	const previousLog = process.env.RDK_TEST_DEPLOY_LOG;
	const previousHash = process.env.RDK_TEST_REMOTE_HASH;
	const previousFailure = process.env.RDK_TEST_FAIL_SCP;
	process.env.PATH = `${fakeBin}:${previousPath ?? ""}`;
	process.env.RDK_TEST_DEPLOY_LOG = log;
	process.env.RDK_TEST_REMOTE_HASH = createHash("sha256").update(readFileSync(source)).digest("hex");
	context.after(() => {
		process.env.PATH = previousPath;
		if (previousLog === undefined) delete process.env.RDK_TEST_DEPLOY_LOG;
		else process.env.RDK_TEST_DEPLOY_LOG = previousLog;
		if (previousHash === undefined) delete process.env.RDK_TEST_REMOTE_HASH;
		else process.env.RDK_TEST_REMOTE_HASH = previousHash;
		if (previousFailure === undefined) delete process.env.RDK_TEST_FAIL_SCP;
		else process.env.RDK_TEST_FAIL_SCP = previousFailure;
		rmSync(workspace, { recursive: true, force: true });
		rmSync(fakeBin, { recursive: true, force: true });
	});

	const profile: AgentProfile = {
		id: "board-deploy",
		name: "Board deploy",
		description: "deploy",
		tools: ["deploy"],
		skills: [],
		systemPrompt: "deploy",
		writePaths: [],
		timeoutSeconds: 60,
		deployment: {
			kind: "ssh",
			host: "board",
			restartService: "probe-daemon.service",
			artifacts: [{ source: "servo.py", target: "/srv/servo.py", mode: "0755", owner: "probe:probe" }],
		},
	};
	const tool = createDeploymentToolDefinition(workspace, join(workspace, "skills"), profile);
	await tool.execute("call", {}, undefined, undefined, {} as never);
	const successfulLog = readFileSync(log, "utf8");
	const prepareIndex = successfulLog.indexOf("chown -R probe:probe /srv/servo.py.rdk-agent-");
	const swapIndex = successfulLog.indexOf("had_existing=0");
	assert.ok(prepareIndex >= 0 && prepareIndex < swapIndex, successfulLog);
	assert.match(successfulLog, /python3 -m py_compile \/srv\/servo\.py\.rdk-agent-.*\.tmp/);
	assert.match(successfulLog, /systemctl restart probe-daemon\.service && systemctl is-active --quiet probe-daemon\.service/);

	writeFileSync(log, "");
	process.env.RDK_TEST_FAIL_SCP = "1";
	await assert.rejects(() => tool.execute("call", {}, undefined, undefined, {} as never), /simulated scp failure/);
	const failedLog = readFileSync(log, "utf8");
	assert.doesNotMatch(failedLog, /rm -f \/srv\/servo\.py(?:\s|$)/);
	assert.doesNotMatch(failedLog, /rm -rf \/srv\/servo\.py(?:\s|$)/);
	assert.doesNotMatch(failedLog, /systemctl restart probe-daemon\.service/);
});
