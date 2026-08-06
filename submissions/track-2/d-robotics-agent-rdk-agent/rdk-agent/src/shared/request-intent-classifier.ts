import type { DevelopmentCapability, RequestIntentDecision } from "../domain/development-intent.ts";
import type { Locale } from "./locale.ts";

export interface RequestIntentClassifierInput {
	request: string;
	modeName: string;
	developmentScope: string;
	capabilities: readonly DevelopmentCapability[];
	conversationContext: readonly string[];
	locale?: Locale;
}

/** A no-tool semantic router. It must not read or mutate the development workspace. */
export interface RequestIntentClassifier {
	classify(input: RequestIntentClassifierInput): Promise<RequestIntentDecision>;
}

export type RequestRoutingEvent =
	| { type: "intent-classification-started"; request: string }
	| { type: "intent-classified"; decision: RequestIntentDecision }
	| { type: "intent-classification-failed"; detail: string };
