export interface TddLoopDefinition {
	id: string;
	name: string;
	deliverable: string;
	testAgentId: string;
	codingAgentId: string;
	verificationAgentId: string;
	maxIterations: number;
	deploymentAgentId?: string;
}

export interface RobotDevelopmentMode {
	id: string;
	name: string;
	type: "robot-development";
	loops: readonly TddLoopDefinition[];
	/** Deterministic delivery stages after all TDD loops and before live acceptance. */
	deliveryAgentIds: readonly string[];
	acceptanceAgentIds: readonly string[];
}

export interface RobotApplicationMode {
	id: string;
	name: string;
	type: "robot-application";
	agentId: string;
}

export type OrchestrationMode = RobotDevelopmentMode | RobotApplicationMode;

export function modeAgentIds(mode: OrchestrationMode): readonly string[] {
	if (mode.type === "robot-application") return [mode.agentId];
	return [
		...mode.loops.flatMap((loop) => [
			loop.testAgentId,
			loop.codingAgentId,
			loop.verificationAgentId,
			...(loop.deploymentAgentId ? [loop.deploymentAgentId] : []),
		]),
		...mode.deliveryAgentIds,
		...mode.acceptanceAgentIds,
	];
}
