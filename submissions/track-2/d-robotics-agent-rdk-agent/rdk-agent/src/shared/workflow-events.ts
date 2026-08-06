import type { StageId, StageStatus } from "../domain/workflow.ts";
import type { AgentSkillInfo } from "./agent-runner.ts";

export type WorkflowEvent =
	| { type: "workflow-started"; request: string; modeId: string; modeName: string }
	| { type: "loop-iteration"; loopId: string; loopName: string; iteration: number; maxIterations: number }
	| { type: "stage-status"; stageId: StageId; status: StageStatus; detail?: string }
	| { type: "agent-event"; stageId: StageId; text: string }
	| { type: "skills-loaded"; stageId: StageId; skills: readonly AgentSkillInfo[] }
	| { type: "skill-selected"; stageId: StageId; skill: AgentSkillInfo }
	| { type: "human-input-required"; stageId: StageId; question: string }
	| { type: "human-input-received"; stageId: StageId; message: string }
	| { type: "workflow-finished"; succeeded: boolean; detail: string };
