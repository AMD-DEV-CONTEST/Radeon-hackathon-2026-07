import { defaultLocale, localeText, type Locale } from "../shared/locale.ts";

export type ConversationCategory = "greeting" | "thanks" | "informational" | "other";

export interface DevelopmentCapability {
	id: string;
	name: string;
	description: string;
}

export type RequestIntentDecision =
	| {
		kind: "development";
		confidence: number;
		normalizedRequest: string;
		reasonCode: string;
	}
	| {
		kind: "conversation";
		confidence: number;
		category: ConversationCategory;
		reasonCode: string;
	}
	| {
		kind: "clarification";
		confidence: number;
		question: string;
		reasonCode: string;
	}
	| {
		kind: "unsupported-development";
		confidence: number;
		reason: string;
		reasonCode: string;
	};

const greeting = /^(?:你好|您好|嗨|哈[喽啰]|hi|hello|hey)[\s!！。,.，]*$/i;
const thanks = /^(?:谢谢|感谢|多谢|辛苦了|再见|拜拜|thanks?|thank\s+you|thx|bye|goodbye|see\s+you)[\s!！。,.，]*$/i;
const chineseNewCapability = /(?:新增|添加|增加|新建|创建|开发|实现|做一个)[^。！？!?\n]{0,100}?(?:功能|能力|动作)/u;
const englishNewCapability = /\b(?:add|create|develop|implement|build|introduce)\b[^.!?\n]{0,140}\b(?:feature|capability|action)\b/iu;

/** High-precision creation signal used to enforce a red-first TDD baseline. */
export function isNewCapabilityRequest(request: string): boolean {
	const normalized = request.normalize("NFKC").trim();
	return chineseNewCapability.test(normalized) || englishNewCapability.test(normalized);
}

/** High-precision fast paths only; mixed or semantic requests go to the classifier Agent. */
export function obviousConversationIntent(request: string): RequestIntentDecision | undefined {
	const normalized = request.trim();
	if (greeting.test(normalized)) {
		return { kind: "conversation", confidence: 1, category: "greeting", reasonCode: "exact-greeting" };
	}
	if (thanks.test(normalized)) {
		return { kind: "conversation", confidence: 1, category: "thanks", reasonCode: "exact-thanks" };
	}
	return undefined;
}

export function conversationReply(category: ConversationCategory, locale: Locale = defaultLocale): string {
	if (category === "greeting") {
		return localeText(
			locale,
			"你好！当前处于机器人研发模式。请描述要新增、修改、修复或测试的机器人能力。",
			"Hello! You are currently in robot development mode. Describe the robot capability you want to add, change, fix, or test.",
		);
	}
	if (category === "thanks") {
		return localeText(
			locale,
			"不客气。研发流程未启动；需要继续时直接描述目标能力即可。",
			"You're welcome. No development workflow was started; describe the capability whenever you want to continue.",
		);
	}
	if (category === "informational") {
		return localeText(
			locale,
			"这条消息被识别为咨询信息，研发流程未启动。若要实际修改能力，请明确说明要新增或调整的行为。",
			"This was classified as an informational request, so no development workflow was started. To change the robot, explicitly describe the behavior to add or adjust.",
		);
	}
	return localeText(
		locale,
		"该用户指令没有明确要求研发，因此没有启动研发流程。",
		"The request did not explicitly authorize development, so no development workflow was started.",
	);
}
