import type { AgentProfile } from "../domain/agent-profile.ts";
import type { Locale } from "./locale.ts";

export interface Delivery {
	stageId: string;
	summary: string;
}

export type AgentExpectation = "test" | "coding" | "verification" | "deployment" | "application";
export type AgentOutcome = "completed" | "revision" | "needs-human";

export interface AgentSkillInfo {
	name: string;
	description: string;
	filePath: string;
}

export type AgentRuntimeEvent =
	| { type: "text"; text: string }
	| { type: "tool-start"; toolName: string; summary?: string }
	| { type: "tool-end"; toolName: string; result: string; isError: boolean }
	| { type: "skills-loaded"; skills: readonly AgentSkillInfo[] }
	| { type: "skill-selected"; skill: AgentSkillInfo }
	| { type: "status"; message: string };

export interface AgentRunRequest {
	profile: AgentProfile;
	userRequest: string;
	workspaceRoot: string;
	skillDirectory: string;
	expectation: AgentExpectation;
	iteration?: number;
	previousDeliveries: readonly Delivery[];
	locale?: Locale;
	onEvent: (event: AgentRuntimeEvent) => void;
}

export interface AgentRunResult {
	summary: string;
	outcome: AgentOutcome;
	feedback?: string;
	question?: string;
}

/** External LLM runtime port. Application code is independent of Pi's SDK. */
export interface AgentRunner {
	run(request: AgentRunRequest): Promise<AgentRunResult>;
}
