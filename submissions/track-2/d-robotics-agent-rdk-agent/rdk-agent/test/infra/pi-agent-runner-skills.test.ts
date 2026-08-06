import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import type { AgentProfile } from "../../src/domain/agent-profile.ts";
import {
	configuredSkillSelectionRetryPrompt,
	createAgentResourceLoader,
	enforceApplicationSkillSelection,
	exceedsToolCallLimit,
	needsConfiguredSkillSelectionRetry,
	selectedSkillFromRead,
	toolCallSummary,
} from "../../src/infra/pi-agent-runner.ts";
import type { AgentRunRequest } from "../../src/shared/agent-runner.ts";

const profile: AgentProfile = {
	id: "application",
	name: "Application",
	description: "test",
	tools: ["read"],
	skills: ["configured-skill"],
	systemPrompt: "test",
	writePaths: [],
	timeoutSeconds: 60,
	maxToolCalls: 5,
};

test("Pi resource loading uses the configured Skill list as a strict allowlist", async (context) => {
	const directory = mkdtempSync(join(tmpdir(), "rdk-agent-skills-"));
	context.after(() => rmSync(directory, { recursive: true, force: true }));
	const skillDirectory = join(directory, "skills", "configured-skill");
	mkdirSync(skillDirectory, { recursive: true });
	writeFileSync(
		join(skillDirectory, "SKILL.md"),
		"---\nname: configured-skill\ndescription: configured only\n---\n\n# Configured\n",
	);
	const request: AgentRunRequest = {
		profile,
		userRequest: "test",
		workspaceRoot: directory,
		skillDirectory: join(directory, "skills"),
		expectation: "application",
		previousDeliveries: [],
		locale: "en",
		onEvent: () => undefined,
	};
	const loader = createAgentResourceLoader(request);
	await loader.reload();
	const loaded = loader.getSkills().skills;

	assert.deepEqual(loaded.map((skill) => skill.name), ["configured-skill"]);
	assert.equal(loader.getSkills().diagnostics.length, 0);
	assert.match(loader.getAppendSystemPrompt().join("\n"), /All user-facing prose, including summaries, feedback, and questions, must be in English/);
	assert.equal(selectedSkillFromRead("read", { path: loaded[0]!.filePath }, directory, loaded)?.name, "configured-skill");
	assert.equal(selectedSkillFromRead("read", { path: "README.md" }, directory, loaded), undefined);
	assert.equal(selectedSkillFromRead("bash", { path: loaded[0]!.filePath }, directory, loaded), undefined);
});

test("application cannot report completion without reading a configured Skill", () => {
	const completed = { summary: "done", outcome: "completed" } as const;
	assert.equal(enforceApplicationSkillSelection(completed, "application", 1, 1), completed);
	assert.equal(enforceApplicationSkillSelection(completed, "coding", 1, 0), completed);
	assert.deepEqual(enforceApplicationSkillSelection(completed, "application", 1, 0), {
		summary: "done",
		outcome: "needs-human",
		question: "机器人应用 Agent 未读取任何白名单 Skill，无法证明本次用户指令经过 Skill 选择与约束。请补充用户指令后重试，或输入 /abort 终止。",
	});
	const english = enforceApplicationSkillSelection(completed, "application", 1, 0, "en");
	assert.match(english.question ?? "", /did not read an allowlisted Skill/);
	assert.doesNotMatch(english.question ?? "", /[一-鿿]/u);
});

test("any completed Skill-enabled stage gets one exact-path selection retry", () => {
	const completed = { summary: "done", outcome: "completed" as const };
	assert.equal(needsConfiguredSkillSelectionRetry(completed, 1, 0), true);
	assert.equal(needsConfiguredSkillSelectionRetry(completed, 1, 1), false);
	assert.equal(needsConfiguredSkillSelectionRetry({ summary: "retry", outcome: "revision" }, 1, 0), false);
	const prompt = configuredSkillSelectionRetryPrompt([
		{ name: "demo", filePath: "/config/skills/demo/SKILL.md" },
	]);
	assert.match(prompt, /\/config\/skills\/demo\/SKILL\.md/);
	assert.match(prompt, /不得在业务工作区猜路径/);
	const englishPrompt = configuredSkillSelectionRetryPrompt([
		{ name: "demo", filePath: "/config/skills/demo/SKILL.md" },
	], "en");
	assert.match(englishPrompt, /Do not guess a path in the business workspace/);
	assert.match(englishPrompt, /\/config\/skills\/demo\/SKILL\.md/);
	assert.doesNotMatch(englishPrompt, /[一-鿿]/u);
});

test("omitting maxToolCalls keeps tool calls unlimited", () => {
	assert.equal(exceedsToolCallLimit(10_000, undefined), false);
	assert.equal(exceedsToolCallLimit(10, 10), false);
	assert.equal(exceedsToolCallLimit(11, 10), true);
});

test("action-package tool logs expose the selected action id and side", () => {
	assert.equal(
		toolCallSummary("action-package", { operation: "scaffold", actionId: "wave-left-hand", start: "left" }),
		"scaffold · wave-left-hand · start=left",
	);
	assert.equal(toolCallSummary("action-package", { operation: "validate", actionId: "wave-left-hand" }), "validate · wave-left-hand");
});
