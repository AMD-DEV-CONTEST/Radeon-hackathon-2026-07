import type { AgentProfile } from "../domain/agent-profile.ts";
import type { OrchestrationMode, RobotApplicationMode, RobotDevelopmentMode, TddLoopDefinition } from "../domain/orchestration-mode.ts";
import { DeliveryWorkflow, type WorkflowStage } from "../domain/workflow.ts";
import type { AgentExpectation, AgentRunResult, AgentRunner, Delivery } from "../shared/agent-runner.ts";
import type { HumanInLoop, HumanInputResponse } from "../shared/human-in-loop.ts";
import { defaultLocale, localeText, type Locale } from "../shared/locale.ts";
import type { WorkflowEvent } from "../shared/workflow-events.ts";

export interface RunOrchestrationInput {
	mode: OrchestrationMode;
	request: string;
	workspaceRoot: string;
	skillDirectory: string;
	humanInLoop: HumanInLoop;
	onEvent: (event: WorkflowEvent) => void;
}

export interface RunOrchestrationResult {
	modeId: string;
	stages: readonly WorkflowStage[];
	succeeded: boolean;
}

class HumanAbortedError extends Error {}

export class RunOrchestration {
	private readonly agentRunner: AgentRunner;
	private readonly profilesById: ReadonlyMap<string, AgentProfile>;
	private readonly locale: Locale;

	constructor(agentRunner: AgentRunner, profiles: readonly AgentProfile[], locale: Locale = defaultLocale) {
		this.agentRunner = agentRunner;
		this.profilesById = new Map(profiles.map((profile) => [profile.id, profile]));
		this.locale = locale;
	}

	async execute(input: RunOrchestrationInput): Promise<RunOrchestrationResult> {
		input.onEvent({ type: "workflow-started", request: input.request, modeId: input.mode.id, modeName: input.mode.name });
		return input.mode.type === "robot-development"
			? this.runDevelopment(input, input.mode)
			: this.runApplication(input, input.mode);
	}

	private async runDevelopment(input: RunOrchestrationInput, mode: RobotDevelopmentMode): Promise<RunOrchestrationResult> {
		const stageOrder = [
			...mode.loops.flatMap((loop) => [loop.id, ...(loop.deploymentAgentId ? [loop.deploymentAgentId] : [])]),
			...mode.deliveryAgentIds,
			...mode.acceptanceAgentIds,
		];
		const workflow = new DeliveryWorkflow(stageOrder);
		const deliveries: Delivery[] = [];

		for (const loop of mode.loops) {
			workflow.start(loop.id);
			input.onEvent({ type: "stage-status", stageId: loop.id, status: "running" });
			try {
				await this.runTddLoop(input, loop, deliveries);
				const detail = localeText(
					this.locale,
					`${loop.deliverable} 已通过 ${loop.name}`,
					`${loop.deliverable} passed ${loop.name}`,
				);
				workflow.succeed(loop.id, detail);
				input.onEvent({ type: "stage-status", stageId: loop.id, status: "succeeded", detail });
				deliveries.push({ stageId: loop.id, summary: detail });
			} catch (error) {
				const detail = error instanceof Error ? error.message : String(error);
				workflow.fail(loop.id, detail);
				input.onEvent({ type: "stage-status", stageId: loop.id, status: "failed", detail });
				input.onEvent({
					type: "workflow-finished",
					succeeded: false,
					detail: localeText(this.locale, `${loop.name} 中止：${detail}`, `${loop.name} stopped: ${detail}`),
				});
				return { modeId: mode.id, stages: workflow.snapshot(), succeeded: false };
			}
			if (loop.deploymentAgentId) {
				workflow.start(loop.deploymentAgentId);
				try {
					const deployment = await this.runAgent(input, loop.deploymentAgentId, "deployment", deliveries);
					workflow.succeed(loop.deploymentAgentId, deployment.summary);
					deliveries.push({ stageId: loop.deploymentAgentId, summary: deployment.summary });
				} catch (error) {
					const detail = error instanceof Error ? error.message : String(error);
					workflow.fail(loop.deploymentAgentId, detail);
					const agentName = this.profile(loop.deploymentAgentId).name;
					input.onEvent({
						type: "workflow-finished",
						succeeded: false,
						detail: localeText(this.locale, `${agentName} 中止：${detail}`, `${agentName} stopped: ${detail}`),
					});
					return { modeId: mode.id, stages: workflow.snapshot(), succeeded: false };
				}
			}
		}

		for (const deliveryAgentId of mode.deliveryAgentIds) {
			workflow.start(deliveryAgentId);
			try {
				const delivery = await this.runAgent(input, deliveryAgentId, "deployment", deliveries);
				workflow.succeed(deliveryAgentId, delivery.summary);
				deliveries.push({ stageId: deliveryAgentId, summary: delivery.summary });
			} catch (error) {
				const detail = error instanceof Error ? error.message : String(error);
				workflow.fail(deliveryAgentId, detail);
				const agentName = this.profile(deliveryAgentId).name;
				input.onEvent({
					type: "workflow-finished",
					succeeded: false,
					detail: localeText(this.locale, `${agentName} 中止：${detail}`, `${agentName} stopped: ${detail}`),
				});
				return { modeId: mode.id, stages: workflow.snapshot(), succeeded: false };
			}
		}

		for (const acceptanceAgentId of mode.acceptanceAgentIds) {
			workflow.start(acceptanceAgentId);
			try {
				const acceptance = await this.runAgent(input, acceptanceAgentId, "application", deliveries);
				workflow.succeed(acceptanceAgentId, acceptance.summary);
				deliveries.push({ stageId: acceptanceAgentId, summary: acceptance.summary });
			} catch (error) {
				const detail = error instanceof Error ? error.message : String(error);
				workflow.fail(acceptanceAgentId, detail);
				input.onEvent({
					type: "workflow-finished",
					succeeded: false,
					detail: localeText(this.locale, `真机验收中止：${detail}`, `Live-device acceptance stopped: ${detail}`),
				});
				return { modeId: mode.id, stages: workflow.snapshot(), succeeded: false };
			}
		}

		input.onEvent({
			type: "workflow-finished",
			succeeded: true,
			detail: localeText(
				this.locale,
				"动作包 TDD、release 构建、板端发布、开发机 Skill 安装与双重真机验收均已通过。",
				"Action-package TDD, release build, board deployment, development-host Skill installation, and both live-device acceptance stages all passed.",
			),
		});
		return { modeId: mode.id, stages: workflow.snapshot(), succeeded: true };
	}

	private async runTddLoop(input: RunOrchestrationInput, loop: TddLoopDefinition, deliveries: Delivery[]): Promise<void> {
		let iteration = 0;
		while (true) {
			iteration++;
			input.onEvent({ type: "loop-iteration", loopId: loop.id, loopName: loop.name, iteration, maxIterations: loop.maxIterations });

			const testResult = await this.runAgent(input, loop.testAgentId, "test", deliveries, iteration);
			deliveries.push({ stageId: loop.testAgentId, summary: testResult.summary });

			const codingResult = await this.runAgent(input, loop.codingAgentId, "coding", deliveries, iteration);
			deliveries.push({ stageId: loop.codingAgentId, summary: codingResult.summary });

			const verification = await this.runAgent(input, loop.verificationAgentId, "verification", deliveries, iteration);
			deliveries.push({ stageId: loop.verificationAgentId, summary: verification.summary });
			if (verification.outcome === "completed") return;

			if (iteration < loop.maxIterations) continue;

			const response = await this.requestHuman(
				input,
				loop.verificationAgentId,
				this.profile(loop.verificationAgentId).name,
				localeText(
					this.locale,
					`${loop.name} 已达到 ${loop.maxIterations} 次自动返工上限，请提供继续方向，或输入 /abort 终止。`,
					`${loop.name} reached the limit of ${loop.maxIterations} automatic revisions. Provide guidance to continue, or enter /abort to stop.`,
				),
				verification.feedback ?? verification.summary,
			);
			deliveries.push({ stageId: "human", summary: response.message });
			iteration = 0;
		}
	}

	private async runApplication(input: RunOrchestrationInput, mode: RobotApplicationMode): Promise<RunOrchestrationResult> {
		const workflow = new DeliveryWorkflow([mode.agentId]);
		const deliveries: Delivery[] = [];
		workflow.start(mode.agentId);
		try {
			const result = await this.runAgent(input, mode.agentId, "application", deliveries);
			workflow.succeed(mode.agentId, result.summary);
			input.onEvent({
				type: "workflow-finished",
				succeeded: true,
				detail: localeText(this.locale, "机器人应用效果测试完成。", "Robot application test completed."),
			});
			return { modeId: mode.id, stages: workflow.snapshot(), succeeded: true };
		} catch (error) {
			const detail = error instanceof Error ? error.message : String(error);
			workflow.fail(mode.agentId, detail);
			input.onEvent({
				type: "workflow-finished",
				succeeded: false,
				detail: localeText(this.locale, `机器人应用模式中止：${detail}`, `Robot application mode stopped: ${detail}`),
			});
			return { modeId: mode.id, stages: workflow.snapshot(), succeeded: false };
		}
	}

	private async runAgent(
		input: RunOrchestrationInput,
		agentId: string,
		expectation: AgentExpectation,
		deliveries: Delivery[],
		iteration?: number,
	): Promise<AgentRunResult> {
		const profile = this.profile(agentId);
		try {
			input.onEvent({ type: "stage-status", stageId: agentId, status: "running" });
			while (true) {
				let result: AgentRunResult;
				try {
					result = await this.agentRunner.run({
						profile,
						userRequest: input.request,
						workspaceRoot: input.workspaceRoot,
						skillDirectory: input.skillDirectory,
						expectation,
						iteration,
						previousDeliveries: deliveries,
						locale: this.locale,
						onEvent: (event) => {
							if (event.type === "text") input.onEvent({ type: "agent-event", stageId: agentId, text: event.text });
							else if (event.type === "status") {
								input.onEvent({
									type: "agent-event",
									stageId: agentId,
									text: localeText(this.locale, `\n[状态] ${event.message}\n`, `\n[Status] ${event.message}\n`),
								});
							}
							else if (event.type === "tool-start") {
								input.onEvent({
									type: "agent-event",
									stageId: agentId,
									text: localeText(
										this.locale,
										`\n[工具] ${event.toolName}${event.summary ? `：${event.summary}` : ""}\n`,
										`\n[Tool] ${event.toolName}${event.summary ? `: ${event.summary}` : ""}\n`,
									),
								});
							}
							else if (event.type === "tool-end") {
								const visibleResult = event.isError || event.toolName === "bash" || event.toolName === "deploy"
									? `\n${event.result.slice(-2_000)}\n`
									: "\n";
								input.onEvent({
									type: "agent-event",
									stageId: agentId,
									text: localeText(
										this.locale,
										`\n[工具完成] ${event.toolName}${event.isError ? "（失败）" : ""}${visibleResult}`,
										`\n[Tool completed] ${event.toolName}${event.isError ? " (failed)" : ""}${visibleResult}`,
									),
								});
							}
							else if (event.type === "skills-loaded") input.onEvent({ type: "skills-loaded", stageId: agentId, skills: event.skills });
							else input.onEvent({ type: "skill-selected", stageId: agentId, skill: event.skill });
						},
					});
				} catch (error) {
					const detail = error instanceof Error ? error.message : String(error);
					const response = await this.requestHuman(
						input,
						agentId,
						profile.name,
						localeText(
							this.locale,
							`${profile.name} 无法继续，请补充信息后重试，或输入 /abort 终止。`,
							`${profile.name} cannot continue. Provide more information and retry, or enter /abort to stop.`,
						),
						detail,
					);
					deliveries.push({ stageId: "human", summary: response.message });
					continue;
				}

				if (result.outcome === "needs-human") {
					const response = await this.requestHuman(
						input,
						agentId,
						profile.name,
						result.question ?? localeText(
							this.locale,
							`${profile.name} 需要人类补充信息，或输入 /abort 终止。`,
							`${profile.name} needs additional human input. Provide it, or enter /abort to stop.`,
						),
						result.summary,
					);
					deliveries.push({ stageId: "human", summary: response.message });
					continue;
				}
				if (result.outcome === "revision" && expectation !== "verification") {
					throw new Error(localeText(
						this.locale,
						`${profile.name} 在 ${expectation} 阶段返回了不支持的 revision 结果`,
						`${profile.name} returned an unsupported revision result during the ${expectation} stage`,
					));
				}

				input.onEvent({ type: "stage-status", stageId: agentId, status: result.outcome === "completed" ? "succeeded" : "failed", detail: result.feedback });
				return result;
			}
		} catch (error) {
			const detail = error instanceof Error ? error.message : String(error);
			input.onEvent({ type: "stage-status", stageId: agentId, status: "failed", detail });
			throw error;
		}
	}

	private async requestHuman(
		input: RunOrchestrationInput,
		stageId: string,
		agentName: string,
		question: string,
		context: string,
	): Promise<HumanInputResponse> {
		input.onEvent({ type: "human-input-required", stageId, question });
		const response = await input.humanInLoop.requestInput({ stageId, agentName, question, context });
		if (response.action === "abort") {
			throw new HumanAbortedError(localeText(this.locale, `人类终止了 ${agentName}`, `${agentName} was stopped by the user`));
		}
		input.onEvent({ type: "human-input-received", stageId, message: response.message });
		return response;
	}

	private profile(agentId: string): AgentProfile {
		const profile = this.profilesById.get(agentId);
		if (!profile) {
			throw new Error(localeText(this.locale, `Agent 配置不存在：${agentId}`, `Agent configuration does not exist: ${agentId}`));
		}
		return profile;
	}
}
