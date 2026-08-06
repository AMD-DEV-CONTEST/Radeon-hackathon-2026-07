import { spawn } from "node:child_process";
import { access } from "node:fs/promises";
import { join } from "node:path";
import { Type } from "typebox";
import type { ToolDefinition } from "@earendil-works/pi-coding-agent";
import type { ActionPackageOperation, AgentProfile } from "../domain/agent-profile.ts";

type AnyToolDefinition = ToolDefinition<any, any, any>;

export interface ActionPackageToolOptions {
	freshExisting?: boolean;
}

export type ActionDirection = "left" | "right" | "both";

export interface ActionPackageScaffoldMetadata {
	actionId: string;
	description: string;
	start: "left" | "right" | "both" | "none";
	intentExamples: readonly string[];
}

const parameters = Type.Union([
	Type.Object({
		operation: Type.Literal("scaffold"),
		actionId: Type.String({ pattern: "^[a-z][a-z0-9-]*$" }),
		description: Type.String({ minLength: 1 }),
		start: Type.Union([Type.Literal("left"), Type.Literal("right"), Type.Literal("both"), Type.Literal("none")]),
		intentExamples: Type.Array(Type.String({ minLength: 1 }), { minItems: 1 }),
	}),
	Type.Object({ operation: Type.Literal("validate"), actionId: Type.String({ pattern: "^[a-z][a-z0-9-]*$" }) }),
	Type.Object({ operation: Type.Literal("build") }),
]);

function run(command: string, args: readonly string[], cwd: string, signal?: AbortSignal): Promise<{ stdout: string; stderr: string }> {
	return new Promise((resolve, reject) => {
		const child = spawn(command, args, { cwd, signal, stdio: ["ignore", "pipe", "pipe"] });
		let stdout = "";
		let stderr = "";
		child.stdout.setEncoding("utf8");
		child.stderr.setEncoding("utf8");
		child.stdout.on("data", (chunk: string) => { stdout += chunk; });
		child.stderr.on("data", (chunk: string) => { stderr += chunk; });
		child.once("error", reject);
		child.once("close", (code) => {
			if (code === 0) resolve({ stdout, stderr });
			else reject(new Error((stdout + stderr).trim() || `${command} 退出码 ${code}`));
		});
	});
}

function needsActionId(operation: ActionPackageOperation): boolean {
	return operation === "scaffold" || operation === "validate";
}

function stripNegatedDirections(value: string): string {
	return value
		.replace(
			/(?:不要|别|禁止|不能|不可|无需|不需要|避免|而非|不是)[^，。；,.!?！？\n]{0,16}?(?:左(?:手|臂|侧|边)?|右(?:手|臂|侧|边)?)/gu,
			" ",
		)
		.replace(
			/\b(?:do\s+not|don't|never|without|avoid|instead\s+of|not)\b[^,.!?;\n]{0,40}?\b(?:left|right)\b(?:[\s_-]+(?:hand|arm|side))?/giu,
			" ",
		);
}

function directionPresence(value: string, actionId = false): { left: boolean; right: boolean } {
	const normalized = stripNegatedDirections(value.normalize("NFKC").toLowerCase());
	const explicitBoth = /(?:左右|双手|双臂|双侧|两只手|两条手臂|两侧|两边)/u.test(normalized)
		|| /\b(?:both|two)[\s_-]+(?:hands?|arms?|sides?)\b/u.test(normalized)
		|| (actionId && /(?:^|[-_])(?:hands|arms)(?:$|[-_])/u.test(normalized));
	if (explicitBoth) return { left: true, right: true };
	return {
		left: /左/u.test(normalized) || /(?:^|[^a-z])left(?:[^a-z]|$)/u.test(normalized),
		right: /右/u.test(normalized) || /(?:^|[^a-z])right(?:[^a-z]|$)/u.test(normalized),
	};
}

function requestedReplacementDirection(value: string): Exclude<ActionDirection, "both"> | undefined {
	const normalized = value.normalize("NFKC").toLowerCase();
	if (/(?:把|将)[^\n]{0,80}?右[^\n]{0,40}?(?:改|换|变|调整)[^\n]{0,24}?左/u.test(normalized)
		|| /\b(?:change|replace|switch)\b[^\n]{0,80}?\bright\b[^\n]{0,40}?\b(?:to|with)\b[^\n]{0,24}?\bleft\b/u.test(normalized)) {
		return "left";
	}
	if (/(?:把|将)[^\n]{0,80}?左[^\n]{0,40}?(?:改|换|变|调整)[^\n]{0,24}?右/u.test(normalized)
		|| /\b(?:change|replace|switch)\b[^\n]{0,80}?\bleft\b[^\n]{0,40}?\b(?:to|with)\b[^\n]{0,24}?\bright\b/u.test(normalized)) {
		return "right";
	}
	return undefined;
}

/** Extracts only an explicit, unambiguous requested side. Ambiguous text deliberately remains unguarded. */
export function requestedActionDirection(userRequest: string): ActionDirection | undefined {
	const replacement = requestedReplacementDirection(userRequest);
	if (replacement) return replacement;
	const normalized = stripNegatedDirections(userRequest.normalize("NFKC").toLowerCase());
	const presence = directionPresence(normalized);
	const explicitBoth = /(?:左右|双手|双臂|双侧|两只手|两条手臂|两侧|两边)/u.test(normalized)
		|| /\b(?:both|two)[\s_-]+(?:hands?|arms?|sides?)\b/u.test(normalized)
		|| /(?:左(?:手|臂)?[^\n]{0,8}(?:和|与|及|、|跟|以及)[^\n]{0,8}右(?:手|臂)?|右(?:手|臂)?[^\n]{0,8}(?:和|与|及|、|跟|以及)[^\n]{0,8}左(?:手|臂)?)/u.test(normalized);
	if (explicitBoth) return "both";
	if (presence.left === presence.right) return undefined;
	return presence.left ? "left" : "right";
}

function detectedDirection(value: string, actionId = false): ActionDirection | undefined {
	const presence = directionPresence(value, actionId);
	if (presence.left && presence.right) return "both";
	if (presence.left) return "left";
	if (presence.right) return "right";
	return undefined;
}

function directionLabel(direction: ActionDirection | undefined): string {
	if (direction === "left") return "左";
	if (direction === "right") return "右";
	if (direction === "both") return "双侧";
	return "未标明方向";
}

function rejectDirection(field: string, expected: ActionDirection, actual: ActionDirection | undefined): never {
	throw new Error(
		`[ACTION-DIRECTION-001] 动作方向保护已拒绝：用户原始指令明确要求“${directionLabel(expected)}”，但 ${field} 为“${directionLabel(actual)}”；动作包尚未创建或覆盖`,
	);
}

function assertDirectionalText(field: string, value: string, expected: ActionDirection, actionId = false): void {
	const actual = detectedDirection(value, actionId);
	if (actual !== expected) rejectDirection(field, expected, actual);
}

/** Rejects scaffold metadata that loses or reverses an explicit direction from the original request. */
export function assertActionPackageDirectionConsistent(
	userRequest: string,
	metadata: ActionPackageScaffoldMetadata,
): void {
	const expected = requestedActionDirection(userRequest);
	if (!expected) return;
	assertDirectionalText("actionId", metadata.actionId, expected, true);
	if (metadata.start !== expected) rejectDirection("start", expected, metadata.start === "none" ? undefined : metadata.start);
	assertDirectionalText("description", metadata.description, expected);
	assertDirectionalText("intentExamples", metadata.intentExamples.join("\n"), expected);
}

export function assertActionIdDirectionConsistent(userRequest: string, actionId: string): void {
	const expected = requestedActionDirection(userRequest);
	if (!expected) return;
	assertDirectionalText("actionId", actionId, expected, true);
}

function actionPackagePath(workspacePath: string): { actionId: string; normalizedPath: string } | undefined {
	const normalizedPath = workspacePath.replaceAll("\\", "/");
	const segments = normalizedPath.split("/").filter(Boolean);
	const actionRoot = segments.indexOf("servo_actions");
	if (actionRoot < 0 || actionRoot + 1 >= segments.length) return undefined;
	return { actionId: segments[actionRoot + 1]!, normalizedPath };
}

/** Applies the action-id guard only to paths nested below a servo_actions/<actionId> directory. */
export function assertActionPackagePathDirectionConsistent(userRequest: string, workspacePath: string): void {
	const actionPath = actionPackagePath(workspacePath);
	if (actionPath) assertActionIdDirectionConsistent(userRequest, actionPath.actionId);
}

/** Rejects a rewritten registry that loses or reverses the direction authorized by the user. */
export function assertActionRegistryContentDirectionConsistent(
	userRequest: string,
	workspacePath: string,
	content: string,
): void {
	const expected = requestedActionDirection(userRequest);
	const actionPath = actionPackagePath(workspacePath);
	if (!expected || !actionPath || !actionPath.normalizedPath.endsWith("/registry.json")) return;
	let parsed: unknown;
	try {
		parsed = JSON.parse(content);
	} catch {
		// Registry syntax and schema errors are reported by the deterministic package validator.
		return;
	}
	if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return;
	const registry = parsed as Record<string, unknown>;
	const skill = typeof registry.skill === "object" && registry.skill !== null && !Array.isArray(registry.skill)
		? registry.skill as Record<string, unknown>
		: undefined;
	const intentExamples = Array.isArray(skill?.intentExamples)
		? skill.intentExamples.filter((value): value is string => typeof value === "string")
		: [];
	assertDirectionalText("registry.json.id", typeof registry.id === "string" ? registry.id : "", expected, true);
	const start = registry.start;
	if (start !== expected) {
		rejectDirection(
			"registry.json.start",
			expected,
			start === "left" || start === "right" || start === "both" ? start : undefined,
		);
	}
	assertDirectionalText(
		"registry.json.description",
		typeof registry.description === "string" ? registry.description : "",
		expected,
	);
	assertDirectionalText("registry.json.skill.intentExamples", intentExamples.join("\n"), expected);
}

function pythonCodeWithoutCommentsAndStrings(source: string): string {
	let code = "";
	let index = 0;
	while (index < source.length) {
		const character = source[index]!;
		if (character === "#") {
			while (index < source.length && source[index] !== "\n") {
				code += " ";
				index++;
			}
			continue;
		}
		if (character === "'" || character === '"') {
			const quote = character;
			const triple = source.slice(index, index + 3) === quote.repeat(3);
			const delimiterLength = triple ? 3 : 1;
			code += " ".repeat(delimiterLength);
			index += delimiterLength;
			while (index < source.length) {
				if (source[index] === "\n") {
					code += "\n";
					index++;
					if (!triple) break;
					continue;
				}
				if (source[index] === "\\") {
					code += " ";
					index++;
					if (index < source.length) {
						code += source[index] === "\n" ? "\n" : " ";
						index++;
					}
					continue;
				}
				if (triple ? source.slice(index, index + 3) === quote.repeat(3) : source[index] === quote) {
					code += " ".repeat(delimiterLength);
					index += delimiterLength;
					break;
				}
				code += " ";
				index++;
			}
			continue;
		}
		code += character;
		index++;
	}
	return code;
}

/** Rejects real opposite-side context bridge calls while ignoring comments and string literals. */
export function assertActionPythonContentDirectionConsistent(
	userRequest: string,
	workspacePath: string,
	content: string,
): void {
	const expected = requestedActionDirection(userRequest);
	if (expected !== "left" && expected !== "right") return;
	const actionPath = actionPackagePath(workspacePath);
	if (!actionPath || !actionPath.normalizedPath.endsWith(".py")) return;
	const opposite = expected === "left" ? "right" : "left";
	const code = pythonCodeWithoutCommentsAndStrings(content);
	const call = new RegExp(`(?<![A-Za-z0-9_.])context\\s*\\.\\s*([A-Za-z_][A-Za-z0-9_]*_${opposite})\\s*\\(`, "u").exec(code);
	if (call) rejectDirection(`Python bridge method context.${call[1]}()`, expected, opposite);
}

/** Runs only the repository-provided action-package automation; no arbitrary command is exposed. */
export function createActionPackageToolDefinition(
	workspaceRoot: string,
	profile: AgentProfile,
	userRequest: string,
	options: ActionPackageToolOptions = {},
): AnyToolDefinition {
	const plan = profile.actionPackage;
	if (!plan) throw new Error(`${profile.id} 未配置 actionPackage`);
	return {
		name: "action-package",
		label: "action-package",
		description: "Run the fixed parameterless-v1 servo action-package scaffold, validation, or release builder. It never accepts shell commands or paths.",
		promptSnippet: "Run the configured action-package automation",
		promptGuidelines: ["Use only an operation configured for this stage; report the returned JSON verbatim."],
		parameters,
		async execute(_toolCallId, args, signal) {
			const input = args as { operation: ActionPackageOperation; actionId?: string; description?: string; start?: "left" | "right" | "both" | "none"; intentExamples?: string[] };
			const operation = input.operation;
			if (!plan.operations.includes(operation)) throw new Error(`${profile.id} 不允许 action-package 操作：${operation}`);
			const actionId = input.actionId;
			if (needsActionId(operation) && !actionId) throw new Error(`${operation} 必须提供 actionId`);
			if (operation === "scaffold") {
				assertActionPackageDirectionConsistent(userRequest, {
					actionId: actionId!,
					description: input.description!,
					start: input.start!,
					intentExamples: input.intentExamples!,
				});
			} else if (operation === "validate") {
				assertActionIdDirectionConsistent(userRequest, actionId!);
			}
			const script = join(workspaceRoot, "tools", "servo_action.py");
			await access(script);
			const command = operation === "scaffold" ? "new" : operation;
			const metadata = operation === "scaffold"
				? [
					...(options.freshExisting ? ["--fresh"] : []),
					"--description",
					input.description!,
					"--start",
					input.start!,
					...input.intentExamples!.flatMap((intent) => ["--intent", intent]),
				]
				: [];
			const result = await run("python3", [script, command, ...(actionId ? [actionId] : []), ...metadata], workspaceRoot, signal);
			return { content: [{ type: "text", text: result.stdout.trim() || result.stderr.trim() }], details: undefined };
		},
	};
}
