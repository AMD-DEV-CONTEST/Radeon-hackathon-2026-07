import type { StageId } from "./agent-profile.ts";

export type { StageId } from "./agent-profile.ts";

export type StageStatus = "pending" | "running" | "succeeded" | "failed";

export interface WorkflowStage {
	id: StageId;
	status: StageStatus;
	detail?: string;
}

/** Enforces the hand-off order independently from the UI and LLM runtime. */
export class DeliveryWorkflow {
	private readonly stageOrder: readonly StageId[];
	private readonly stagesById: Map<StageId, WorkflowStage>;

	constructor(stageOrder: readonly StageId[]) {
		if (stageOrder.length === 0) throw new Error("workflow requires at least one stage");
		if (new Set(stageOrder).size !== stageOrder.length) throw new Error("workflow stage ids must be unique");
		this.stageOrder = [...stageOrder];
		this.stagesById = new Map(stageOrder.map((id) => [id, { id, status: "pending" }]));
	}

	start(stageId: StageId): void {
		const stage = this.stage(stageId);
		if (stage.status !== "pending") throw new Error(`${stageId} is not pending`);
		const index = this.stageOrder.indexOf(stageId);
		const predecessor = index === 0 ? undefined : this.stageOrder[index - 1];
		if (predecessor && this.stage(predecessor).status !== "succeeded") {
			throw new Error(`${stageId} requires ${predecessor} to succeed first`);
		}
		stage.status = "running";
	}

	succeed(stageId: StageId, detail: string): void {
		const stage = this.stage(stageId);
		if (stage.status !== "running") throw new Error(`${stageId} is not running`);
		stage.status = "succeeded";
		stage.detail = detail;
	}

	fail(stageId: StageId, detail: string): void {
		const stage = this.stage(stageId);
		if (stage.status !== "running") throw new Error(`${stageId} is not running`);
		stage.status = "failed";
		stage.detail = detail;
	}

	snapshot(): readonly WorkflowStage[] {
		return this.stageOrder.map((id) => ({ ...this.stage(id) }));
	}

	private stage(stageId: StageId): WorkflowStage {
		const stage = this.stagesById.get(stageId);
		if (!stage) throw new Error(`unknown stage: ${stageId}`);
		return stage;
	}
}
