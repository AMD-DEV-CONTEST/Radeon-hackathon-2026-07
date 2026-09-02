import {
  STAGE_LABELS,
  STAGE_TO_AGENT,
  WORKFLOW_STAGE_ORDER,
} from "@/features/agents/constants/workflow";
import type {
  AgentRuntimeStatus,
  TimelineLane,
  WorkflowNode,
  WorkflowNodeId,
} from "@/features/agents/types/agents.types";
import type {
  LiveAgentRuntimeMap,
  OrchestrationStage,
  OrchestrationStageId,
  OrchestrationStageStatus,
  OrchestrationWorkflowStatus,
} from "@/features/agents/types/orchestration.types";

export function stageStatusToRuntime(
  status: OrchestrationStageStatus
): AgentRuntimeStatus {
  if (status === "completed") {
    return "completed";
  }
  if (status === "running") {
    return "running";
  }
  if (status === "failed") {
    return "error";
  }
  if (status === "cancelled") {
    return "idle";
  }
  return "waiting";
}

export function mapStagesToWorkflowNodes(
  stages: ReadonlyArray<OrchestrationStage>,
  activeStageId: OrchestrationStageId | null
): WorkflowNode[] {
  return stages
    .filter((stage) => stage.agentId !== null)
    .map((stage) => {
      const agentId = stage.agentId as WorkflowNodeId;
      const isActive = stage.id === activeStageId;
      return {
        id: agentId,
        label: stage.label.replace(/\s+Agent$/i, "").replace("Fact Checker", "Fact Check"),
        status: isActive && stage.status === "running"
          ? "running"
          : stageStatusToRuntime(stage.status),
      };
    });
}

export function mapStagesToTimeline(
  stages: ReadonlyArray<OrchestrationStage>
): TimelineLane[] {
  const total = Math.max(stages.length, 1);

  return stages.map((stage, index) => {
    const start = Math.round((index / total) * 100);
    const span = Math.round(100 / total);
    const end =
      stage.status === "completed"
        ? start + span
        : stage.status === "running"
          ? start + Math.max(Math.round(span * (stage.progress / 100)), 8)
          : start + 4;

    return {
      id: stage.id,
      label: stage.label,
      start,
      end: Math.min(end, 100),
      phase:
        stage.status === "completed"
          ? "done"
          : stage.status === "running"
            ? "active"
            : "waiting",
    };
  });
}

export function computeWorkflowProgress(
  stages: ReadonlyArray<OrchestrationStage>
): number {
  if (stages.length === 0) {
    return 0;
  }

  const weight = 100 / stages.length;
  const total = stages.reduce((sum, stage) => {
    if (stage.status === "completed" || stage.status === "skipped") {
      return sum + weight;
    }
    if (stage.status === "running") {
      return sum + weight * (stage.progress / 100);
    }
    return sum;
  }, 0);

  return Math.min(100, Math.round(total));
}

export function resolveWorkflowStatus(options: {
  stages: ReadonlyArray<OrchestrationStage>;
  cancelled: boolean;
}): OrchestrationWorkflowStatus {
  const { stages, cancelled } = options;

  if (cancelled) {
    return "cancelled";
  }

  const hasFailed = stages.some((stage) => stage.status === "failed");
  const allTerminal = stages.every(
    (stage) =>
      stage.status === "completed" ||
      stage.status === "skipped" ||
      stage.status === "failed" ||
      stage.status === "cancelled"
  );
  const allCompleted = stages.every(
    (stage) => stage.status === "completed" || stage.status === "skipped"
  );
  const hasRunning = stages.some((stage) => stage.status === "running");

  if (allCompleted) {
    return "completed";
  }
  if (hasFailed && allTerminal) {
    const completedCount = stages.filter(
      (stage) => stage.status === "completed"
    ).length;
    return completedCount > 0 ? "partial_success" : "failed";
  }
  if (hasRunning) {
    return "running";
  }
  if (stages.some((stage) => stage.status !== "pending")) {
    return "running";
  }
  return "idle";
}

export function applyLiveAgentRuntime(
  stages: ReadonlyArray<OrchestrationStage>,
  live: LiveAgentRuntimeMap
): OrchestrationStage[] {
  return stages.map((stage) => {
    const agentId = STAGE_TO_AGENT[stage.id];
    if (!agentId) {
      return stage;
    }

    const liveState = live[agentId];
    if (!liveState) {
      return stage;
    }

    if (stage.status === "completed" || stage.status === "failed") {
      return stage;
    }

    if (liveState.status === "completed") {
      return {
        ...stage,
        status: "completed",
        progress: 100,
        currentTask: liveState.currentTask || stage.currentTask,
        completedAt: stage.completedAt ?? new Date().toISOString(),
        error: null,
      };
    }

    if (
      liveState.status === "running" ||
      liveState.status === "busy" ||
      liveState.status === "waiting"
    ) {
      return {
        ...stage,
        status: "running",
        progress: Math.max(stage.progress, liveState.status === "waiting" ? 35 : 65),
        currentTask: liveState.currentTask || stage.currentTask,
        startedAt: stage.startedAt ?? new Date().toISOString(),
      };
    }

    if (liveState.status === "error") {
      return {
        ...stage,
        status: "failed",
        error: `${STAGE_LABELS[stage.id]} reported an error.`,
        retryable: true,
      };
    }

    return stage;
  });
}

export function nextPendingStageId(
  stages: ReadonlyArray<OrchestrationStage>
): OrchestrationStageId | null {
  for (const stageId of WORKFLOW_STAGE_ORDER) {
    const stage = stages.find((item) => item.id === stageId);
    if (!stage) {
      continue;
    }
    if (stage.status === "pending" || stage.status === "failed") {
      return stage.id;
    }
  }
  return null;
}

export function currentRunningStageId(
  stages: ReadonlyArray<OrchestrationStage>
): OrchestrationStageId | null {
  const running = stages.find((stage) => stage.status === "running");
  return running?.id ?? null;
}
