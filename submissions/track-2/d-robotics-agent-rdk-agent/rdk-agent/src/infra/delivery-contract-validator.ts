import { readFile } from "node:fs/promises";
import { basename, join, relative, resolve, sep } from "node:path";
import type { AgentRunResult } from "../shared/agent-runner.ts";
import type { DeliveryValidationPlan } from "../domain/agent-profile.ts";
import { validateSkillPackage } from "./deployment-agent-tool.ts";

function workspacePath(workspaceRoot: string, configuredPath: string): string {
	const root = resolve(workspaceRoot);
	const absolute = resolve(root, configuredPath);
	const pathFromRoot = relative(root, absolute);
	if (pathFromRoot === "" || pathFromRoot === ".." || pathFromRoot.startsWith(`..${sep}`)) {
		throw new Error(`交付校验路径越出工作区：${configuredPath}`);
	}
	return absolute;
}

function manifestPluginId(contents: string): string {
	const match = contents.match(/^id\s*=\s*["']([a-z][a-z0-9-]*)["']\s*$/m);
	if (!match?.[1]) throw new Error("plugin.toml 缺少合法 id");
	return match[1];
}

function pythonContract(contents: string): { actions: ReadonlySet<string>; options: readonly string[] } {
	const actions = new Set<string>();
	const actionBlock = contents.match(/^ACTIONS\s*=\s*\{([\s\S]*?)^\}/m)?.[1] ?? "";
	for (const match of actionBlock.matchAll(/["']([a-z][a-z0-9-]*)["']\s*:/g)) actions.add(match[1]!);
	if (/args\.action\s*==\s*["']servo["']/.test(contents)) actions.add("servo");
	if (actions.size === 0) throw new Error("入口源码中未找到 ACTIONS 动作契约");
	const options = [...contents.matchAll(/add_argument\(\s*["'](--[a-z][a-z0-9-]*)["']/g)].map((match) => match[1]!);
	return { actions, options: [...new Set(options)] };
}

function normalizedPluginCommands(contents: string, pluginId: string): ReadonlySet<string> {
	const commands = new Set<string>();
	for (const match of contents.matchAll(/sophonctl\s+(?:--board\s+\S+\s+)?([a-z][a-z0-9-]*)(?:\s+([^`\n|]+))?/g)) {
		if (match[1] !== pluginId) continue;
		commands.add(`${pluginId} ${(match[2] ?? "").trim().replace(/\s+/g, " ")}`.trim());
	}
	return commands;
}

function validateCommands(contents: string, label: string, pluginId: string, actions: ReadonlySet<string>): void {
	const commands = [...contents.matchAll(/`(sophonctl\s+[^`\n]+)`/g)].map((match) => match[1]!);
	if (commands.length === 0) throw new Error(`${label} 未包含任何可核对的 sophonctl 命令`);
	for (const command of commands) {
		const tokens = command.trim().split(/\s+/);
		let index = 1;
		if (tokens[index] === "--board") index += 2;
		const rootCommand = tokens[index];
		if (rootCommand === "plugins") continue;
		if (rootCommand !== pluginId) {
			throw new Error(`${label} 的命令缺少插件名 ${pluginId}：${command}`);
		}
		const action = tokens[index + 1];
		if (!action || action === "--help") continue;
		if (!actions.has(action)) throw new Error(`${label} 引用了入口源码不存在的动作 ${action}：${command}`);
	}
}

function validateEvidenceReferences(acceptance: string, evidence: ReadonlyMap<string, string>): void {
	const allEvidence = [...evidence.values()].join("\n");
	const testReferences = (contents: string): string[] => [...contents.matchAll(/\b(test_[a-zA-Z0-9_]+)\b/g)]
		.filter((match) => contents.slice((match.index ?? 0) + match[1]!.length, (match.index ?? 0) + match[1]!.length + 3) !== ".py")
		.map((match) => match[1]!);
	const referencedTests = testReferences(acceptance);
	for (const testName of new Set(referencedTests)) {
		if (!new RegExp(`\\b${testName}\\b`).test(allEvidence)) {
			throw new Error(`acceptance.md 引用了不存在的测试：${testName}`);
		}
	}
	for (const line of acceptance.split(/\r?\n/)) {
		const testsOnLine = testReferences(line);
		const mentionedFiles = [...evidence.keys()].filter((file) => line.includes(file));
		if (testsOnLine.length === 0 || mentionedFiles.length === 0) continue;
		const namedEvidence = mentionedFiles.map((file) => evidence.get(file) ?? "").join("\n");
		for (const testName of testsOnLine) {
			if (!new RegExp(`\\b${testName}\\b`).test(namedEvidence)) {
				throw new Error(`acceptance.md 把 ${testName} 错误归属到 ${mentionedFiles.join(", ")}`);
			}
		}
	}
}

function validateRequiredServoAcceptance(acceptance: string, _evidence: ReadonlyMap<string, string>): void {
	const errors: string[] = [];
	if (!/动作式[^\n]*(?:不需要|无需|不得[^\n]*再次)[^\n]*(?:二次确认|再次确认)/.test(acceptance)) {
		errors.push("缺少动作式自然语言无需二次确认的验收边界");
	}
	if (!/实际(?:物理效果|动作效果)[^\n]*(?:人类|人工)[^\n]*(?:目视|观察)[^\n]*确认/.test(acceptance)) {
		errors.push("缺少真实物理效果由人类目视确认的验收边界");
	}
	if (errors.length > 0) throw new Error(`acceptance.md 缺少端到端必验项：${errors.join("；")}`);
}

function validateAcceptanceClaims(acceptance: string, options: readonly string[], entrypoint: string): void {
	const errors: string[] = [];
	const lines = acceptance.split(/\r?\n/);
	if (options.length > 0 && /无任何参数|无其他参数[^\n]*CLI|不(?:接受|支持)任何参数|动作本身不接受任何参数/.test(acceptance)) {
		errors.push(`声称动作无参数，但入口源码存在通用选项：${options.join(", ")}`);
	}
	if (/\btest_[a-zA-Z0-9_]+[^\n]{0,120}(?:通过|成功)/.test(acceptance)) {
		errors.push("验收场景不能在验证 Agent 执行测试前预写测试已通过");
	}
	if (lines.some((line) => line.includes("[actions]") && /自然语言|映射|触发/.test(line))) {
		errors.push("错把 plugin.toml 的 [actions] 当作自然语言或执行映射；映射应由 Skill 和入口源码契约证明");
	}
	if (lines.some((line) => /CLI\s*命令/.test(line) && /plugin\.toml/.test(line) && /定义|提供|声明/.test(line))) {
		errors.push("错把 plugin.toml 当作具体 CLI 动作命令的定义来源；manifest 只提供插件 id 与 entrypoint");
	}
	if (/非\s*root\s*可写|依赖系统级部署权限|文件权限为/.test(acceptance)) {
		errors.push("包含无法从配置和源码证明的文件权限结论");
	}
	if (/额外参数[^\n]*(?:解析失败|导致[^\n]*失败)/.test(acceptance) && /add_argument\(\s*["']args["'][^\n]*nargs\s*=\s*["']\*["']/.test(entrypoint)) {
		errors.push("声称额外位置参数会解析失败，但入口使用 nargs='*' 接收它们");
	}
	if (/未在[^\n]*(?:plugin\.toml|servo_ctrl\.py)[^\n]*(?:不构成有效触发|无效触发)/.test(acceptance)) {
		errors.push("根据 plugin 或 Python 源码臆断自然语言不是有效触发；自然语言边界应由 Skill 定义");
	}
	if (/未启用\s*shell[^\n]*plugin\.toml|plugin\.toml[^\n]*(?:未配置|未定义|没有)[^\n]*shell/.test(acceptance)) {
		errors.push("根据 plugin.toml 中不存在的 shell 字段推断执行安全性");
	}
	if (/无\s*shell\s*注入风险|无资源泄漏|确保[^\n]*无[^\n]*泄漏/.test(acceptance)) {
		errors.push("包含未被测试证明的绝对安全或资源泄漏结论");
	}
	if (errors.length > 0) throw new Error(`acceptance.md 契约声明不准确：${errors.join("；")}`);
}

async function validateSkillContract(
	workspaceRoot: string,
	skillDirectory: string,
	plan: Extract<DeliveryValidationPlan, { kind: "skill-contract" }>,
): Promise<void> {
	const source = workspacePath(workspaceRoot, plan.source);
	const skill = await readFile(join(source, "SKILL.md"), "utf8");
	const acceptance = await readFile(join(source, "acceptance.md"), "utf8");
	const manifest = await readFile(workspacePath(workspaceRoot, plan.manifest), "utf8");
	const entrypoint = await readFile(workspacePath(workspaceRoot, plan.entrypointSource), "utf8");
	validateSkillPackage(skill, plan.skillName);
	if (acceptance.trim() === "") throw new Error("acceptance.md 不能为空");
	const pluginId = manifestPluginId(manifest);
	const contract = pythonContract(entrypoint);
	validateCommands(skill, "SKILL.md", pluginId, contract.actions);
	validateCommands(acceptance, "acceptance.md", pluginId, contract.actions);
	validateAcceptanceClaims(acceptance, contract.options, entrypoint);

	const evidence = new Map<string, string>();
	for (const configuredPath of plan.evidenceFiles) {
		evidence.set(basename(configuredPath), await readFile(workspacePath(workspaceRoot, configuredPath), "utf8"));
	}
	validateEvidenceReferences(acceptance, evidence);
	validateRequiredServoAcceptance(acceptance, evidence);

	const baseline = await readFile(join(skillDirectory, plan.baselineSkillName, "SKILL.md"), "utf8");
	for (const command of normalizedPluginCommands(baseline, pluginId)) {
		if (!normalizedPluginCommands(skill, pluginId).has(command)) {
			throw new Error(`SKILL.md 丢失已安装 Skill 的既有命令：sophonctl ${command}`);
		}
	}
}

export async function validateDeliveryContract(
	workspaceRoot: string,
	skillDirectory: string,
	plan: DeliveryValidationPlan,
): Promise<void> {
	if (plan.kind === "skill-contract") await validateSkillContract(workspaceRoot, skillDirectory, plan);
}

export async function enforceDeliveryContract(
	result: AgentRunResult,
	workspaceRoot: string,
	skillDirectory: string,
	plan?: DeliveryValidationPlan,
): Promise<AgentRunResult> {
	if (!plan || result.outcome !== "completed") return result;
	try {
		await validateDeliveryContract(workspaceRoot, skillDirectory, plan);
		return result;
	} catch (error) {
		const feedback = error instanceof Error ? error.message : String(error);
		return {
			summary: `${result.summary}\n\n[确定性交付校验失败] ${feedback}`,
			outcome: "revision",
			feedback,
		};
	}
}
