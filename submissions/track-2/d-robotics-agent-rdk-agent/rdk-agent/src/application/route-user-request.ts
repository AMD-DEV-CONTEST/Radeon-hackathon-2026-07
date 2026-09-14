import {
	conversationReply,
	obviousConversationIntent,
	type DevelopmentCapability,
	type RequestIntentDecision,
} from "../domain/development-intent.ts";
import type { RobotDevelopmentMode } from "../domain/orchestration-mode.ts";
import type { RequestIntakeConfiguration } from "../shared/agent-configuration.ts";
import { defaultLocale, localeText, type Locale } from "../shared/locale.ts";
import type {
	RequestIntentClassifier,
	RequestRoutingEvent,
} from "../shared/request-intent-classifier.ts";

export interface RouteUserRequestInput {
	request: string;
	mode: RobotDevelopmentMode;
	conversationContext?: readonly string[];
	forceDevelopment?: boolean;
	onEvent?: (event: RequestRoutingEvent) => void;
}

export type RoutedUserRequest = RequestIntentDecision & { userMessage?: string };

export class RouteUserRequest {
	private readonly classifier: RequestIntentClassifier;
	private readonly configuration: RequestIntakeConfiguration;
	private readonly locale: Locale;

	constructor(
		classifier: RequestIntentClassifier,
		configuration: RequestIntakeConfiguration,
		locale: Locale = defaultLocale,
	) {
		this.classifier = classifier;
		this.configuration = configuration;
		this.locale = locale;
	}

	async execute(input: RouteUserRequestInput): Promise<RoutedUserRequest> {
		if (input.forceDevelopment) {
			const decision: RequestIntentDecision = {
				kind: "development",
				confidence: 1,
				normalizedRequest: input.request,
				reasonCode: "explicit-development-override",
			};
			input.onEvent?.({ type: "intent-classified", decision });
			return decision;
		}

		const obvious = obviousConversationIntent(input.request);
		if (obvious?.kind === "conversation") {
			input.onEvent?.({ type: "intent-classified", decision: obvious });
			return { ...obvious, userMessage: conversationReply(obvious.category, this.locale) };
		}

		input.onEvent?.({ type: "intent-classification-started", request: input.request });
		let decision: RequestIntentDecision;
		try {
			decision = await this.classifier.classify({
				request: input.request,
				modeName: input.mode.name,
				developmentScope: this.configuration.developmentScope,
				capabilities: capabilities(input.mode, this.locale),
				conversationContext: input.conversationContext ?? [],
				locale: this.locale,
			});
		} catch (error) {
			const detail = error instanceof Error ? error.message : String(error);
			input.onEvent?.({ type: "intent-classification-failed", detail });
			return {
				kind: "clarification",
				confidence: 0,
				question: localeText(
					this.locale,
					"暂时无法可靠判断该用户指令是否要求研发。你是要新增、修改或修复机器人动作能力吗？",
					"I couldn't reliably determine whether this request authorizes development. Do you want to add, change, or fix a robot action capability?",
				),
				reasonCode: "classifier-failed",
			};
		}

		if (decision.kind === "development" && decision.confidence < this.configuration.autoStartConfidence) {
			decision = {
				kind: "clarification",
				confidence: decision.confidence,
				question: localeText(
					this.locale,
					"该用户指令可能要求研发。请确认：是否要立即启动研发流程并修改机器人动作能力？",
					"This request may authorize development. Should I start the development workflow now and change the robot action capability?",
				),
				reasonCode: "development-confidence-below-threshold",
			};
		}
		input.onEvent?.({ type: "intent-classified", decision });
		if (decision.kind === "conversation") {
			return { ...decision, userMessage: conversationReply(decision.category, this.locale) };
		}
		return decision;
	}
}

function capabilities(mode: RobotDevelopmentMode, locale: Locale): readonly DevelopmentCapability[] {
	return mode.loops.map((loop) => ({
		id: loop.id,
		name: loop.name,
		description: localeText(
			locale,
			`交付物：${loop.deliverable}；执行测试设计、实现和独立验证，最多自动迭代 ${loop.maxIterations} 次。`,
			`Deliverable: ${loop.deliverable}; run test design, implementation, and independent verification for up to ${loop.maxIterations} automatic iterations.`,
		),
	}));
}
