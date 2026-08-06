import { access, mkdir, readFile, writeFile } from "node:fs/promises";
import { relative, resolve, sep } from "node:path";
import {
	createBashToolDefinition,
	createEditToolDefinition,
	createReadToolDefinition,
	createWriteToolDefinition,
	type ToolDefinition,
} from "@earendil-works/pi-coding-agent";
import { isReadOnlyApplicationRequest } from "../domain/application-intent.ts";
import { isNewCapabilityRequest } from "../domain/development-intent.ts";
import type { AgentProfile } from "../domain/agent-profile.ts";
import type { AgentExpectation } from "../shared/agent-runner.ts";
import { defaultLocale, localeText, type Locale } from "../shared/locale.ts";
import { createDeploymentToolDefinition } from "./deployment-agent-tool.ts";
import {
	assertActionPackagePathDirectionConsistent,
	assertActionPythonContentDirectionConsistent,
	assertActionRegistryContentDirectionConsistent,
	createActionPackageToolDefinition,
} from "./action-package-tool.ts";
import { createPodmanSandboxOperations } from "./podman-sandbox.ts";
import { isUnittestCommand } from "./verification-evidence.ts";

type AnyToolDefinition = ToolDefinition<any, any, any>;

export interface TestBaselineState {
	scaffoldSucceeded: boolean;
}

export interface ScopedAgentRunContext {
	expectation: AgentExpectation;
	userRequest: string;
	iteration?: number;
	locale?: Locale;
	testBaseline?: TestBaselineState;
}

/** Enforces the configured mutation boundary below the prompt layer. */
export class WorkspaceWritePolicy {
	private readonly root: string;
	private readonly patterns: readonly RegExp[];
	private readonly deniedPatterns: readonly RegExp[];
	private readonly directoryPrefixes: readonly string[];
	private readonly userRequest?: string;

	constructor(workspaceRoot: string, writePaths: readonly string[], userRequest?: string) {
		this.root = resolve(workspaceRoot);
		this.userRequest = userRequest;
		this.patterns = writePaths.filter((pattern) => !pattern.startsWith("!")).map((pattern) => this.glob(pattern));
		this.deniedPatterns = writePaths.filter((pattern) => pattern.startsWith("!")).map((pattern) => this.glob(pattern.slice(1)));
		this.directoryPrefixes = writePaths.filter((pattern) => !pattern.startsWith("!")).map((pattern) => {
			const wildcard = pattern.search(/[?*]/);
			const staticPart = wildcard < 0 ? pattern : pattern.slice(0, wildcard);
			return staticPart.slice(0, staticPart.lastIndexOf("/")).replace(/^\.\//, "");
		});
	}

	assertFileAllowed(path: string): void {
		const workspacePath = this.workspacePath(path);
		if (!this.patterns.some((pattern) => pattern.test(workspacePath)) || this.deniedPatterns.some((pattern) => pattern.test(workspacePath))) {
			throw new Error(`写入被拒绝：${workspacePath} 不在 Agent 的 writePaths 白名单中`);
		}
		this.assertRequestDirection(workspacePath);
	}

	assertDirectoryAllowed(path: string): void {
		const workspacePath = this.workspacePath(path).replace(/\/$/, "");
		if (!this.directoryPrefixes.some((prefix) => workspacePath.startsWith(prefix) || prefix.startsWith(workspacePath))) {
			throw new Error(`创建目录被拒绝：${workspacePath} 不在 Agent 的 writePaths 范围中`);
		}
		this.assertRequestDirection(workspacePath);
	}

	assertFileContentAllowed(path: string, content: string): void {
		this.assertFileAllowed(path);
		if (this.userRequest) {
			assertActionRegistryContentDirectionConsistent(this.userRequest, this.workspacePath(path), content);
			assertActionPythonContentDirectionConsistent(this.userRequest, this.workspacePath(path), content);
		}
	}

	private assertRequestDirection(workspacePath: string): void {
		if (this.userRequest) assertActionPackagePathDirectionConsistent(this.userRequest, workspacePath);
	}

	private workspacePath(path: string): string {
		const absolute = resolve(this.root, path);
		const workspacePath = relative(this.root, absolute);
		if (workspacePath === ".." || workspacePath.startsWith(`..${sep}`) || workspacePath === "") {
			throw new Error(`写入被拒绝：${absolute} 不在工作目录内`);
		}
		return workspacePath.split(sep).join("/");
	}

	private glob(pattern: string): RegExp {
		const normalized = pattern.replace(/^\.\//, "").replaceAll("\\", "/");
		let encoded = "";
		for (let index = 0; index < normalized.length; index++) {
			const character = normalized[index]!;
			if (character === "*" && normalized[index + 1] === "*") {
				encoded += ".*";
				index++;
			} else if (character === "*") encoded += "[^/]*";
			else if (character === "?") encoded += "[^/]";
			else encoded += character.replace(/[|\\{}()[\]^$+?.]/g, "\\$&");
		}
		return new RegExp(`^${encoded}$`);
	}
}

const forbiddenShell = [
	/[<>`]/,
	/\$\(/,
	/\b(rm|mv|cp|install|mkdir|touch|chmod|chown|ln|tee|truncate)\b/,
	/\bsed\s+[^\n]*-[^\n]*i\b/,
	/\b(perl|python\d*)\s+[^\n]*\s-i\b/,
	/\bgit\s+(add|apply|checkout|clean|commit|merge|rebase|reset|restore|switch)\b/,
	/\b(npm|pnpm|yarn|pip\d*|cargo)\s+(install|add|remove|update|fmt)\b/,
];

function withoutSafeNullRedirects(command: string): string {
	return command.replace(/(^|[\s;&|])(?:[12])?>\s*\/dev\/null(?=$|[\s;&|])/gu, "$1");
}

export function assertReadOnlyShell(command: string, locale: Locale = defaultLocale): void {
	const inspected = withoutSafeNullRedirects(command);
	const violation = forbiddenShell.find((pattern) => pattern.test(inspected));
	if (violation) {
		throw new Error(localeText(
			locale,
			`bash 仅允许测试与只读检查，命令被策略拒绝：${command}`,
			`Bash only permits tests and read-only checks; command rejected: ${command}`,
		));
	}
}

const sophonctl = String.raw`(?:[^\s;&|]*/)?sophonctl`;
const boardOption = String.raw`(?:\s+--board\s+[^\s;&|]+)?`;
const readOnlySophonctlCommands = [
	new RegExp(`^${sophonctl}\\s+(?:--help|--version)$`),
	new RegExp(`^${sophonctl}${boardOption}\\s+plugins\\s+list$`),
	new RegExp(`^${sophonctl}${boardOption}\\s+[a-z][a-z0-9-]*\\s+--help$`),
	/^(?:command\s+-v|which)\s+sophonctl$/,
];

export function assertApplicationShellAllowed(
	command: string,
	expectation: AgentExpectation,
	userRequest: string,
	locale: Locale = defaultLocale,
): void {
	if (expectation !== "application" || !isReadOnlyApplicationRequest(userRequest)) return;
	const normalized = command.trim().replace(/\s+/g, " ");
	if (readOnlySophonctlCommands.some((pattern) => pattern.test(normalized))) return;
	throw new Error(localeText(
		locale,
		`应用模式当前输入是只读查询，Bash 只允许 sophonctl 列表、帮助和版本检查，命令被拒绝：${normalized}`,
		`The current application-mode request is read-only. Bash only permits sophonctl list, help, and version checks; command rejected: ${normalized}`,
	));
}

export function assertNewCapabilityTestBaseline(command: string, context: ScopedAgentRunContext): void {
	if (context.expectation !== "test"
		|| (context.iteration ?? 1) !== 1
		|| !isNewCapabilityRequest(context.userRequest)
		|| context.testBaseline?.scaffoldSucceeded
		|| !isUnittestCommand(command)) {
		return;
	}
	throw new Error(localeText(
		context.locale ?? defaultLocale,
		"新增功能的第一轮目标测试已在启动前拒绝：当前 Session 尚未成功创建动作脚手架，工作区中的测试属于历史状态。请先调用一次 action-package scaffold；运行时会备份同名历史动作并创建干净的红测基线。",
		"The first target test for this new capability was rejected before launch because this Session has not created an action scaffold and the workspace test is historical state. Call action-package scaffold once; the runtime will archive any same-named historical action and create a clean red-test baseline.",
	));
}

function actionPackageStatus(result: unknown): string | undefined {
	if (typeof result !== "object" || result === null) return undefined;
	const content = (result as { content?: unknown }).content;
	if (!Array.isArray(content)) return undefined;
	for (const item of content) {
		if (typeof item !== "object" || item === null || (item as { type?: unknown }).type !== "text") continue;
		const value = (item as { text?: unknown }).text;
		if (typeof value !== "string") continue;
		try {
			const payload = JSON.parse(value) as { status?: unknown };
			if (typeof payload.status === "string") return payload.status;
		} catch {
			// The fixed action-package script normally returns JSON; leave unknown output untrusted.
		}
	}
	return undefined;
}

export function scopedAgentTools(
	workspaceRoot: string,
	skillDirectory: string,
	profile: AgentProfile,
	runContext?: ScopedAgentRunContext,
): AnyToolDefinition[] {
	if (profile.actionPackage && !runContext) {
		throw new Error(`${profile.id} 的 action-package 工具缺少原始用户指令上下文`);
	}
	const policy = new WorkspaceWritePolicy(workspaceRoot, profile.writePaths, runContext?.userRequest);
	const writeTool = createWriteToolDefinition(workspaceRoot, {
		operations: {
			mkdir: async (path) => {
				policy.assertDirectoryAllowed(path);
				await mkdir(path, { recursive: true });
			},
			writeFile: async (path, content) => {
				policy.assertFileContentAllowed(path, content);
				await writeFile(path, content);
			},
		},
	});
	const guardedWriteTool = {
		...writeTool,
		async execute(...executeArgs: Parameters<typeof writeTool.execute>) {
			const input = executeArgs[1];
			policy.assertFileContentAllowed(input.path, input.content);
			return writeTool.execute(...executeArgs);
		},
	} as AnyToolDefinition;
	const freshExisting = runContext !== undefined
		&& runContext.expectation === "test"
		&& (runContext.iteration ?? 1) === 1
		&& isNewCapabilityRequest(runContext.userRequest);
	const actionPackageTool = profile.actionPackage
		? createActionPackageToolDefinition(workspaceRoot, profile, runContext!.userRequest, { freshExisting })
		: undefined;
	const guardedActionPackageTool = actionPackageTool
		? {
			...actionPackageTool,
			async execute(...executeArgs: Parameters<typeof actionPackageTool.execute>) {
				const result = await actionPackageTool.execute(...executeArgs);
				const input = executeArgs[1] as { operation?: unknown };
				if (input.operation === "scaffold"
					&& actionPackageStatus(result) === "scaffolded"
					&& runContext?.testBaseline) {
					runContext.testBaseline.scaffoldSucceeded = true;
				}
				return result;
			},
		} as AnyToolDefinition
		: undefined;
	const definitions: Record<string, AnyToolDefinition | undefined> = {
		read: createReadToolDefinition(workspaceRoot),
		bash: createBashToolDefinition(workspaceRoot, {
			operations: profile.sandbox?.kind === "podman"
				? createPodmanSandboxOperations(workspaceRoot, profile.sandbox)
				: undefined,
			spawnHook: (spawnContext) => {
				assertReadOnlyShell(spawnContext.command, runContext?.locale);
				if (runContext) {
					assertNewCapabilityTestBaseline(spawnContext.command, runContext);
					assertApplicationShellAllowed(spawnContext.command, runContext.expectation, runContext.userRequest, runContext.locale);
				}
				return { ...spawnContext, env: { ...spawnContext.env, PYTHONDONTWRITEBYTECODE: "1" } };
			},
		}),
		edit: createEditToolDefinition(workspaceRoot, {
			operations: {
				readFile,
				access: async (path) => {
					policy.assertFileAllowed(path);
					await access(path);
				},
				writeFile: async (path, content) => {
					policy.assertFileContentAllowed(path, content);
					await writeFile(path, content);
				},
			},
		}),
		write: guardedWriteTool,
		deploy: profile.deployment
			? createDeploymentToolDefinition(workspaceRoot, skillDirectory, profile, runContext?.locale)
			: undefined,
		"action-package": guardedActionPackageTool,
	};
	return profile.tools.map((name) => {
		const definition = definitions[name];
		if (!definition) throw new Error(`不支持的 Agent 工具：${name}`);
		return definition;
	});
}
