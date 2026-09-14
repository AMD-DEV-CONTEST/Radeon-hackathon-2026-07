import { join, resolve } from "node:path";
import {
	createAgentSession,
	DefaultResourceLoader,
	getAgentDir,
	SessionManager,
	type Skill,
} from "@earendil-works/pi-coding-agent";
import type { AgentExpectation, AgentRunRequest, AgentRunResult, AgentRunner, AgentSkillInfo } from "../shared/agent-runner.ts";
import { defaultLocale, localeText, outputLanguageInstruction, type Locale } from "../shared/locale.ts";
import { AgentPromptBuilder } from "./agent-prompt-builder.ts";
import { scopedAgentTools } from "./scoped-agent-tools.ts";
import { enforceDeliveryContract } from "./delivery-contract-validator.ts";
import {
	enforceTestExecutionEvidence,
	enforceVerificationEvidence,
	needsTestExecutionEvidenceRetry,
	needsVerificationEvidenceRetry,
	testExecutionEvidenceRetryPromptForLocale,
	verificationEvidenceRetryPromptForLocale,
	type BashExecutionEvidence,
} from "./verification-evidence.ts";

export function createAgentResourceLoader(request: AgentRunRequest): DefaultResourceLoader {
	const locale = request.locale ?? defaultLocale;
	const skillPaths = request.profile.skills.map((name) => join(request.skillDirectory, name));
	const allowedSkillFiles = new Set(skillPaths.map((path) => resolve(path, "SKILL.md")));
	return new DefaultResourceLoader({
		cwd: request.workspaceRoot,
		agentDir: getAgentDir(),
		noSkills: true,
		additionalSkillPaths: skillPaths,
		skillsOverride: ({ skills, diagnostics }) => ({
			skills: skills.filter((skill) => allowedSkillFiles.has(resolve(skill.filePath))),
			diagnostics,
		}),
		appendSystemPromptOverride: (base) => [...base, request.profile.systemPrompt, outputLanguageInstruction(locale)],
	});
}

export function selectedSkillFromRead(
	toolName: string,
	args: unknown,
	workspaceRoot: string,
	loadedSkills: readonly Skill[],
): Skill | undefined {
	if (toolName !== "read" || typeof args !== "object" || args === null || !("path" in args)) return undefined;
	const path = (args as { path?: unknown }).path;
	if (typeof path !== "string") return undefined;
	const absolutePath = resolve(workspaceRoot, path);
	return loadedSkills.find((skill) => resolve(skill.filePath) === absolutePath);
}

function skillInfo(skill: Skill): AgentSkillInfo {
	return { name: skill.name, description: skill.description, filePath: skill.filePath };
}

export function toolCallSummary(toolName: string, args: unknown): string | undefined {
	if (typeof args !== "object" || args === null) return undefined;
	const values = args as Record<string, unknown>;
	if (toolName === "bash" && typeof values.command === "string") return values.command;
	if (["read", "edit", "write"].includes(toolName) && typeof values.path === "string") return values.path;
	if (toolName === "action-package" && typeof values.operation === "string") {
		const actionId = typeof values.actionId === "string" ? ` · ${values.actionId}` : "";
		const start = typeof values.start === "string" ? ` · start=${values.start}` : "";
		return `${values.operation}${actionId}${start}`;
	}
	return undefined;
}

function toolResultText(result: unknown): string {
	if (typeof result === "object" && result !== null && "content" in result && Array.isArray(result.content)) {
		return result.content
			.filter((item): item is { type: "text"; text: string } => typeof item === "object" && item !== null && item.type === "text" && typeof item.text === "string")
			.map((item) => item.text)
			.join("\n");
	}
	return String(result);
}

export function enforceApplicationSkillSelection(
	result: AgentRunResult,
	expectation: AgentExpectation,
	configuredSkillCount: number,
	selectedSkillCount: number,
	locale: Locale = defaultLocale,
): AgentRunResult {
	if (expectation !== "application" || result.outcome !== "completed" || configuredSkillCount === 0 || selectedSkillCount > 0) {
		return result;
	}
	return {
		summary: result.summary,
		outcome: "needs-human",
		question: localeText(
			locale,
			"机器人应用 Agent 未读取任何白名单 Skill，无法证明本次用户指令经过 Skill 选择与约束。请补充用户指令后重试，或输入 /abort 终止。",
			"The robot application Agent did not read an allowlisted Skill, so the runtime cannot prove that the request was selected and constrained by a Skill. Clarify the request and retry, or enter /abort to stop.",
		),
	};
}

export function needsConfiguredSkillSelectionRetry(
	result: AgentRunResult,
	configuredSkillCount: number,
	selectedSkillCount: number,
): boolean {
	return result.outcome === "completed" && configuredSkillCount > 0 && selectedSkillCount === 0;
}

export function configuredSkillSelectionRetryPrompt(
	skills: readonly Pick<Skill, "name" | "filePath">[],
	locale: Locale = defaultLocale,
): string {
	const files = skills.map((skill) => `- ${skill.name}: ${skill.filePath}`).join("\n");
	return localeText(locale, `运行时检测到你尚未通过 read 读取任何已配置 Skill，因此不能接受刚才的完成结论。
请立即从下列精确路径中选择与用户指令匹配的 Skill，用 read 完整读取对应 SKILL.md；不得在业务工作区猜路径：
${files}
读取后核对本阶段工作是否符合 Skill，再简洁复述交付结论，并重新输出本阶段要求的单行 RDK_AGENT_RESULT。不要重复已经完成的文件编辑或真实硬件动作。`, `The runtime cannot accept the previous completion because you have not read any configured Skill with the read tool.
Select the Skill that matches the user request from these exact paths and read its complete SKILL.md. Do not guess a path in the business workspace:
${files}
After reading it, verify that this stage complies with the Skill, briefly restate the delivery result, and emit the required single-line RDK_AGENT_RESULT again. Do not repeat completed file edits or real hardware actions.`);
}

export function exceedsToolCallLimit(toolCalls: number, maxToolCalls?: number): boolean {
	return maxToolCalls !== undefined && toolCalls > maxToolCalls;
}

/** Pi SDK adapter. It is the only layer that knows how an agent session is created. */
export class PiAgentRunner implements AgentRunner {
	private readonly promptBuilder = new AgentPromptBuilder();

	async run(request: AgentRunRequest): Promise<AgentRunResult> {
		const locale = request.locale ?? defaultLocale;
		const resourceLoader = createAgentResourceLoader(request);
		await resourceLoader.reload();
		const loadedSkills = resourceLoader.getSkills().skills;
		const loadedNames = new Set(loadedSkills.map((skill) => skill.name));
		const missingSkills = request.profile.skills.filter((name) => !loadedNames.has(name));
		if (missingSkills.length > 0) {
			throw new Error(localeText(
				locale,
				`配置的 Skill 加载失败：${missingSkills.join(", ")}`,
				`Failed to load configured Skill(s): ${missingSkills.join(", ")}`,
			));
		}
		request.onEvent({ type: "skills-loaded", skills: loadedSkills.map(skillInfo) });

		const testBaseline = { scaffoldSucceeded: false };
		const { session, modelFallbackMessage } = await createAgentSession({
			cwd: request.workspaceRoot,
			resourceLoader,
			sessionManager: SessionManager.inMemory(request.workspaceRoot),
			noTools: "builtin",
			tools: [...request.profile.tools],
			customTools: scopedAgentTools(request.workspaceRoot, request.skillDirectory, request.profile, {
				expectation: request.expectation,
				userRequest: request.userRequest,
				iteration: request.iteration,
				locale,
				testBaseline,
			}),
		});
		const text: string[] = [];
		let toolCalls = 0;
		const activeToolCalls = new Map<string, { toolName: string; args: unknown }>();
		const bashExecutions: BashExecutionEvidence[] = [];
		const selectedSkills = new Set<string>();
		let limitError: string | undefined;
		const abortForLimit = (message: string): void => {
			if (limitError) return;
			limitError = message;
			request.onEvent({ type: "status", message });
			void session.abort();
		};
		const unsubscribe = session.subscribe((event) => {
			if (event.type === "message_update" && event.assistantMessageEvent.type === "text_delta") {
				text.push(event.assistantMessageEvent.delta);
				request.onEvent({ type: "text", text: event.assistantMessageEvent.delta });
			}
			if (event.type === "tool_execution_start") {
				toolCalls++;
				activeToolCalls.set(event.toolCallId, { toolName: event.toolName, args: event.args });
				request.onEvent({ type: "tool-start", toolName: event.toolName, summary: toolCallSummary(event.toolName, event.args) });
				const selectedSkill = selectedSkillFromRead(event.toolName, event.args, request.workspaceRoot, loadedSkills);
				if (selectedSkill && !selectedSkills.has(selectedSkill.name)) {
					selectedSkills.add(selectedSkill.name);
					request.onEvent({ type: "skill-selected", skill: skillInfo(selectedSkill) });
				}
				if (exceedsToolCallLimit(toolCalls, request.profile.maxToolCalls)) {
					abortForLimit(localeText(
						locale,
						`${request.profile.name} 超过工具调用上限 ${request.profile.maxToolCalls}`,
						`${request.profile.name} exceeded the tool-call limit of ${request.profile.maxToolCalls}`,
					));
				}
			}
			if (event.type === "tool_execution_end") {
				const activeCall = activeToolCalls.get(event.toolCallId);
				const resultText = toolResultText(event.result);
				if (event.toolName === "bash" && activeCall?.toolName === "bash") {
					bashExecutions.push({
						command: toolCallSummary("bash", activeCall.args) ?? "",
						output: resultText,
						failed: event.isError,
					});
				}
				activeToolCalls.delete(event.toolCallId);
				request.onEvent({ type: "tool-end", toolName: event.toolName, result: resultText, isError: event.isError });
			}
		});

		const timer = setTimeout(
			() => abortForLimit(localeText(
				locale,
				`${request.profile.name} 超过阶段超时 ${request.profile.timeoutSeconds} 秒`,
				`${request.profile.name} exceeded the stage timeout of ${request.profile.timeoutSeconds} seconds`,
			)),
			request.profile.timeoutSeconds * 1_000,
		);
		try {
			const model = session.model
				? `${session.model.provider}/${session.model.id}`
				: localeText(locale, "未配置", "not configured");
			const environment = request.profile.sandbox?.kind === "podman"
				? localeText(
					locale,
					`Podman ${request.profile.sandbox.image}（离线、工作区只读）`,
					`Podman ${request.profile.sandbox.image} (offline, read-only workspace)`,
				)
				: localeText(locale, "宿主机", "host");
			const noValue = localeText(locale, "无", "none");
			request.onEvent({
				type: "status",
				message: localeText(
					locale,
					`已创建 Pi session；模型：${model}；推理级别：${session.thinkingLevel}；模型回退：${modelFallbackMessage ?? noValue}；工具：${request.profile.tools.join(", ")}；执行环境：${environment}；Skill 白名单：${loadedSkills.map((skill) => skill.name).join(", ") || noValue}`,
					`Created Pi session; model: ${model}; thinking level: ${session.thinkingLevel}; model fallback: ${modelFallbackMessage ?? noValue}; tools: ${request.profile.tools.join(", ")}; environment: ${environment}; Skill allowlist: ${loadedSkills.map((skill) => skill.name).join(", ") || noValue}`,
				),
			});
			try {
				await session.prompt(this.promptBuilder.build(request));
			} catch (error) {
				if (limitError) throw new Error(limitError);
				throw error;
			}
			if (limitError) throw new Error(limitError);
			let summary = text.join("").trim();
			if (!summary) throw new Error(localeText(locale, "Agent 未返回文本交付物", "The Agent returned no text deliverable"));
			let result = this.parseResult(summary, request.expectation, locale);
			if (needsConfiguredSkillSelectionRetry(result, request.profile.skills.length, selectedSkills.size)) {
				request.onEvent({
					type: "status",
					message: localeText(
						locale,
						"完成结论缺少 Skill 读取证据；在同一 Session 内给出精确路径并强制读取",
						"Completion lacks evidence that a Skill was read; supplying exact paths and requiring a read in the same Session",
					),
				});
				const retryStart = text.length;
				await session.prompt(configuredSkillSelectionRetryPrompt(loadedSkills, locale));
				if (limitError) throw new Error(limitError);
				summary = text.slice(retryStart).join("").trim();
				if (!summary) {
					throw new Error(localeText(locale, "Agent 未返回 Skill 读取后的补充结论", "The Agent returned no follow-up after reading the Skill"));
				}
				result = this.parseResult(summary, request.expectation, locale);
			}
			result = enforceApplicationSkillSelection(
				result,
				request.expectation,
				request.profile.skills.length,
				selectedSkills.size,
				locale,
			);
			const hasBashTool = request.profile.tools.includes("bash");
			const evidence = () => ({ bash: bashExecutions, scaffoldSucceeded: testBaseline.scaffoldSucceeded });
			if (needsTestExecutionEvidenceRetry(result, request.expectation, hasBashTool, evidence())) {
				request.onEvent({
					type: "status",
					message: localeText(
						locale,
						"测试完成结论缺少执行证据；在同一 Session 内强制运行本阶段测试",
						"Test completion lacks execution evidence; requiring this stage's test in the same Session",
					),
				});
				const retryStart = text.length;
				await session.prompt(testExecutionEvidenceRetryPromptForLocale(locale));
				if (limitError) throw new Error(limitError);
				summary = text.slice(retryStart).join("").trim();
				if (!summary) throw new Error(localeText(locale, "测试 Agent 未返回补充执行结论", "The test Agent returned no follow-up execution result"));
				result = this.parseResult(summary, request.expectation, locale);
			}
			if (needsVerificationEvidenceRetry(result, request.expectation, evidence())) {
				request.onEvent({
					type: "status",
					message: localeText(
						locale,
						"验证结论缺少命令证据；在同一 Session 内强制补跑一次安全测试",
						"Verification lacks command evidence; requiring one safe test in the same Session",
					),
				});
				const retryStart = text.length;
				await session.prompt(verificationEvidenceRetryPromptForLocale(locale));
				if (limitError) throw new Error(limitError);
				summary = text.slice(retryStart).join("").trim();
				if (!summary) throw new Error(localeText(locale, "验证 Agent 未返回补充测试结论", "The verification Agent returned no follow-up test result"));
				result = this.parseResult(summary, request.expectation, locale);
			}
			result = enforceTestExecutionEvidence(result, request.expectation, hasBashTool, evidence(), {
				locale,
				userRequest: request.userRequest,
				iteration: request.iteration,
			});
			result = enforceVerificationEvidence(result, request.expectation, evidence(), locale);
			const validated = await enforceDeliveryContract(
				result,
				request.workspaceRoot,
				request.skillDirectory,
				request.profile.validation,
			);
			if (validated.outcome === "revision" && result.outcome === "completed") {
				request.onEvent({
					type: "status",
					message: localeText(
						locale,
						`确定性交付校验要求返工：${validated.feedback}`,
						`Deterministic delivery validation requires revision: ${validated.feedback}`,
					),
				});
			}
			return validated;
		} finally {
			clearTimeout(timer);
			unsubscribe();
			session.dispose();
		}
	}

	private parseResult(text: string, expectation: AgentExpectation, locale: Locale = defaultLocale): AgentRunResult {
		const marker = "RDK_AGENT_RESULT:";
		const markerIndex = text.lastIndexOf(marker);
		if (markerIndex < 0) {
			return expectation === "verification"
				? {
					summary: text,
					outcome: "needs-human",
					question: localeText(
						locale,
						"验证 Agent 未返回结构化结论，请人工判断是否继续。",
						"The verification Agent did not return a structured result. Decide whether to continue.",
					),
				}
				: { summary: text, outcome: "completed" };
		}

		const summary = text.slice(0, markerIndex).trim();
		const encoded = text.slice(markerIndex + marker.length).trim();
		let value: unknown;
		try {
			value = JSON.parse(encoded);
		} catch {
			return {
				summary: summary || text,
				outcome: "needs-human",
				question: localeText(
					locale,
					"Agent 的结构化结果无法解析，请人工提供继续方向。",
					"The Agent's structured result could not be parsed. Provide guidance to continue.",
				),
			};
		}
		if (typeof value !== "object" || value === null || Array.isArray(value)) {
			return {
				summary: summary || text,
				outcome: "needs-human",
				question: localeText(
					locale,
					"Agent 的结构化结果格式不正确，请人工提供继续方向。",
					"The Agent's structured result has the wrong format. Provide guidance to continue.",
				),
			};
		}

		const result = value as Record<string, unknown>;
		const status = result.status;
		const feedback = typeof result.feedback === "string" ? result.feedback : undefined;
		const question = typeof result.question === "string" ? result.question : undefined;
		if (status === "needs-human") return { summary: summary || text, outcome: "needs-human", question };
		if (expectation === "verification" && status === "passed") {
			return { summary: summary || localeText(locale, "验证通过", "Verification passed"), outcome: "completed" };
		}
		if (expectation === "verification" && status === "revision") {
			return { summary: summary || feedback || localeText(locale, "验证要求返工", "Verification requires revision"), outcome: "revision", feedback };
		}
		if (expectation !== "verification" && status === "completed") {
			return { summary: summary || localeText(locale, "交付完成", "Delivery completed"), outcome: "completed" };
		}
		return {
			summary: summary || text,
			outcome: "needs-human",
			question: localeText(
				locale,
				"Agent 返回了不适用于当前阶段的状态，请人工判断。",
				"The Agent returned a status that is not valid for this stage. Decide how to proceed.",
			),
		};
	}
}
