import { RouteUserRequest } from "../../application/route-user-request.ts";
import { RunOrchestration } from "../../application/run-orchestration.ts";
import { PiAgentRunner } from "../../infra/pi-agent-runner.ts";
import { PiRequestIntentClassifier } from "../../infra/pi-request-intent-classifier.ts";
import type { ResolvedWorkspace } from "../../infra/managed-workspace.ts";
import { inspectDevelopmentWorkspace } from "../../infra/workspace-preflight.ts";
import type { AgentConfiguration } from "../../shared/agent-configuration.ts";
import type { AgentRunner } from "../../shared/agent-runner.ts";
import { defaultLocale, localeText, type Locale } from "../../shared/locale.ts";
import type { RequestIntentClassifier } from "../../shared/request-intent-classifier.ts";
import type { WorkflowEvent } from "../../shared/workflow-events.ts";

export interface HeadlessRunnerDependencies {
	agentRunner?: AgentRunner;
	intentClassifier?: RequestIntentClassifier;
	write?: (text: string) => void;
}

function printEvent(
	event: WorkflowEvent,
	write: (text: string) => void,
	showWorkflowProgress: boolean,
	locale: Locale = defaultLocale,
): void {
	if (event.type === "workflow-started") {
		write(locale === "en"
			? `RDK Agent · ${event.modeName}\nUser request: ${event.request}\n`
			: `RDK Agent · ${event.modeName}\n用户指令：${event.request}\n`);
	} else if (event.type === "loop-iteration") {
		write(localeText(
			locale,
			`\n[${event.loopName}] 第 ${event.iteration}/${event.maxIterations} 次迭代\n`,
			`\n[${event.loopName}] Iteration ${event.iteration}/${event.maxIterations}\n`,
		));
	} else if (event.type === "stage-status") {
		if (showWorkflowProgress) {
			write(`\n[${event.stageId}] ${event.status}${event.detail ? `${locale === "en" ? ": " : "："}${event.detail}` : ""}\n`);
		}
	} else if (event.type === "agent-event") {
		write(event.text);
	} else if (event.type === "skills-loaded") {
		write(locale === "en"
			? `\n[Skills loaded] ${event.skills.map((skill) => skill.name).join(", ") || "None"}\n`
			: `\n[Skill 已加载] ${event.skills.map((skill) => skill.name).join(", ") || "无"}\n`);
	} else if (event.type === "skill-selected") {
		write(localeText(locale, `\n[Skill 已选择] ${event.skill.name}\n`, `\n[Skill selected] ${event.skill.name}\n`));
	} else if (event.type === "workflow-finished") {
		write(locale === "en"
			? `\n${event.succeeded ? "Acceptance passed" : "Workflow stopped"}: ${event.detail}\n`
			: `\n${event.succeeded ? "验收通过" : "流程中止"}：${event.detail}\n`);
	}
}

export async function runHeadless(
	workspace: ResolvedWorkspace,
	configuration: AgentConfiguration,
	modeId: string,
	request: string,
	dependencies: HeadlessRunnerDependencies = {},
): Promise<boolean> {
	const locale = configuration.locale ?? defaultLocale;
	const mode = configuration.modes.find((candidate) => candidate.id === modeId);
	if (!mode) throw new Error(localeText(locale, `模式配置不存在：${modeId}`, `Mode configuration not found: ${modeId}`));
	const write = dependencies.write ?? ((text: string) => process.stdout.write(text));
	let workflowRequest = request;
	if (mode.type === "robot-development") {
		const forceDevelopment = request.startsWith("/develop ");
		const candidateRequest = forceDevelopment ? request.slice("/develop ".length).trim() : request;
		if (!candidateRequest) {
			throw new Error(localeText(locale, "/develop 需要明确的用户指令", "/develop requires an explicit user request"));
		}
		const classifier = dependencies.intentClassifier
			?? new PiRequestIntentClassifier(workspace.root, configuration.intake.timeoutSeconds, locale);
		const decision = await new RouteUserRequest(classifier, configuration.intake, locale).execute({
			request: candidateRequest,
			mode,
			forceDevelopment,
			onEvent(event) {
				if (event.type === "intent-classification-started") {
					write(localeText(
						locale,
						"[输入识别] 意图分类 Agent 正在判断……\n",
						"[Input classification] The intent-classification Agent is evaluating the request…\n",
					));
				}
				if (event.type === "intent-classification-failed") {
					write(localeText(locale, `[输入识别失败] ${event.detail}\n`, `[Input classification failed] ${event.detail}\n`));
				}
			},
		});
		if (decision.kind === "conversation") {
			write(locale === "en"
				? `[Input classification] Non-development conversation; the development workflow was not started.${decision.userMessage ? `\n${decision.userMessage}` : ""}\n`
				: `[输入识别] 非研发对话；研发流程未启动。${decision.userMessage ? `\n${decision.userMessage}` : ""}\n`);
			return true;
		}
		if (decision.kind === "clarification") {
			write(localeText(
				locale,
				`[需要确认研发意图] ${decision.question}\n研发流程未启动。\n`,
				`[Development intent confirmation required] ${decision.question}\nThe development workflow was not started.\n`,
			));
			return false;
		}
		if (decision.kind === "unsupported-development") {
			write(localeText(
				locale,
				`[输入识别] 当前研发流程不支持：${decision.reason}\n研发流程未启动。\n`,
				`[Input classification] Unsupported by the current development workflow: ${decision.reason}\nThe development workflow was not started.\n`,
			));
			return false;
		}
		// Classification grants or denies authority; it must never rewrite the user's authorized request.
		workflowRequest = candidateRequest;
		write(localeText(
			locale,
			`[输入识别] 已确认该用户指令需要启动研发流程 · 置信度 ${Math.round(decision.confidence * 100)}%\n`,
			`[Input classification] Confirmed that this user request requires the development workflow · confidence ${Math.round(decision.confidence * 100)}%\n`,
		));
		const problem = inspectDevelopmentWorkspace(workspace.root, configuration.workspace.requiredPaths);
		if (problem) {
			throw new Error(localeText(
				locale,
				`开发工作区校验失败：缺少 ${problem.missingPaths.join(", ")}`,
				`Development workspace validation failed: missing ${problem.missingPaths.join(", ")}`,
			));
		}
	}
	const result = await new RunOrchestration(dependencies.agentRunner ?? new PiAgentRunner(), configuration.profiles, locale).execute({
		mode,
		request: workflowRequest,
		workspaceRoot: workspace.root,
		skillDirectory: configuration.skillDirectory,
		humanInLoop: {
			async requestInput(humanRequest) {
				throw new Error(localeText(
					locale,
					`无交互运行禁止 Human-in-the-loop：${humanRequest.agentName}：${humanRequest.question}`,
					`Human-in-the-loop is unavailable in headless mode: ${humanRequest.agentName}: ${humanRequest.question}`,
				));
			},
		},
		onEvent: (event) => printEvent(event, write, mode.type === "robot-development", locale),
	});
	return result.succeeded;
}
