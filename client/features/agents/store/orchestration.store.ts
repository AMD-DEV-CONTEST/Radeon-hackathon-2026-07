"use client";

import { create } from "zustand";

import { createInitialStages } from "@/features/agents/constants/workflow";
import type { WorkflowNodeId } from "@/features/agents/types/agents.types";
import type {
  AiThought,
  LiveAgentRuntimeMap,
  OrchestrationContext,
  OrchestrationFinalResult,
  OrchestrationHistoryEntry,
  OrchestrationSnapshot,
  OrchestrationStage,
  OrchestrationStageId,
  OrchestrationStageStatus,
  OrchestrationWorkflowStatus,
} from "@/features/agents/types/orchestration.types";
import {
  applyLiveAgentRuntime,
  computeWorkflowProgress,
  currentRunningStageId,
  mapStagesToTimeline,
  mapStagesToWorkflowNodes,
  resolveWorkflowStatus,
} from "@/features/agents/utils/orchestration-mappers";

interface OrchestrationState extends OrchestrationSnapshot {
  cancelled: boolean;
  hydrateContext: (context: OrchestrationContext) => void;
  setWorkflowStatus: (status: OrchestrationWorkflowStatus) => void;
  beginStage: (stageId: OrchestrationStageId, task?: string) => void;
  updateStage: (
    stageId: OrchestrationStageId,
    patch: Partial<
      Pick<
        OrchestrationStage,
        "status" | "progress" | "currentTask" | "error" | "retryable"
      >
    >
  ) => void;
  completeStage: (stageId: OrchestrationStageId, task?: string) => void;
  failStage: (
    stageId: OrchestrationStageId,
    error: string,
    retryable?: boolean
  ) => void;
  appendHistory: (
    entry: Omit<OrchestrationHistoryEntry, "id" | "at"> & {
      id?: string;
      at?: string;
    }
  ) => void;
  appendThought: (
    thought: Omit<AiThought, "id" | "at"> & { id?: string; at?: string }
  ) => void;
  patchFinalResult: (patch: Partial<OrchestrationFinalResult>) => void;
  syncLiveAgents: (live: LiveAgentRuntimeMap) => void;
  setLastError: (message: string | null) => void;
  markCancelled: () => void;
  reset: () => void;
  getSnapshot: () => OrchestrationSnapshot;
}

function nowIso(): string {
  return new Date().toISOString();
}

function buildDerived(
  stages: ReadonlyArray<OrchestrationStage>,
  cancelled: boolean
): Pick<
  OrchestrationSnapshot,
  | "status"
  | "currentStageId"
  | "currentAgentId"
  | "progressPercent"
  | "timeline"
  | "workflowNodes"
> {
  const currentStageId = currentRunningStageId(stages);
  const currentStage = stages.find((stage) => stage.id === currentStageId);

  return {
    status: resolveWorkflowStatus({ stages, cancelled }),
    currentStageId,
    currentAgentId: (currentStage?.agentId ?? null) as WorkflowNodeId | null,
    progressPercent: computeWorkflowProgress(stages),
    timeline: mapStagesToTimeline(stages),
    workflowNodes: mapStagesToWorkflowNodes(stages, currentStageId),
  };
}

const emptyResult: OrchestrationFinalResult = {
  analysisId: null,
  planId: null,
  interviewId: null,
  reportId: null,
  recommendation: null,
  completedAt: null,
};

const initialState = {
  status: "idle" as OrchestrationWorkflowStatus,
  currentStageId: null as OrchestrationStageId | null,
  currentAgentId: null as WorkflowNodeId | null,
  progressPercent: 0,
  stages: createInitialStages(),
  history: [] as OrchestrationHistoryEntry[],
  thoughts: [] as AiThought[],
  timeline: mapStagesToTimeline(createInitialStages()),
  workflowNodes: mapStagesToWorkflowNodes(createInitialStages(), null),
  finalResult: emptyResult,
  context: null as OrchestrationContext | null,
  lastError: null as string | null,
  updatedAt: nowIso(),
  cancelled: false,
};

export const useOrchestrationStore = create<OrchestrationState>((set, get) => ({
  ...initialState,

  hydrateContext: (context) => {
    set({
      context,
      updatedAt: nowIso(),
    });
  },

  setWorkflowStatus: (status) => {
    set({
      status,
      updatedAt: nowIso(),
    });
  },

  beginStage: (stageId, task) => {
    set((state) => {
      const stages = state.stages.map((stage) =>
        stage.id === stageId
          ? {
              ...stage,
              status: "running" as OrchestrationStageStatus,
              progress: Math.max(stage.progress, 8),
              currentTask: task || stage.currentTask || "Running...",
              startedAt: stage.startedAt ?? nowIso(),
              error: null,
            }
          : stage
      );

      return {
        ...state,
        stages,
        cancelled: false,
        lastError: null,
        updatedAt: nowIso(),
        ...buildDerived(stages, false),
      };
    });
  },

  updateStage: (stageId, patch) => {
    set((state) => {
      const stages = state.stages.map((stage) =>
        stage.id === stageId
          ? {
              ...stage,
              ...patch,
            }
          : stage
      );

      return {
        ...state,
        stages,
        updatedAt: nowIso(),
        ...buildDerived(stages, state.cancelled),
      };
    });
  },

  completeStage: (stageId, task) => {
    set((state) => {
      const stages = state.stages.map((stage) =>
        stage.id === stageId
          ? {
              ...stage,
              status: "completed" as OrchestrationStageStatus,
              progress: 100,
              currentTask: task || "Completed",
              completedAt: nowIso(),
              error: null,
            }
          : stage
      );

      return {
        ...state,
        stages,
        updatedAt: nowIso(),
        ...buildDerived(stages, state.cancelled),
      };
    });
  },

  failStage: (stageId, error, retryable = true) => {
    set((state) => {
      const stages = state.stages.map((stage) =>
        stage.id === stageId
          ? {
              ...stage,
              status: "failed" as OrchestrationStageStatus,
              error,
              retryable,
              currentTask: "Failed",
            }
          : stage
      );

      return {
        ...state,
        stages,
        lastError: error,
        updatedAt: nowIso(),
        ...buildDerived(stages, state.cancelled),
      };
    });
  },

  appendHistory: (entry) => {
    set((state) => ({
      history: [
        ...state.history,
        {
          id: entry.id ?? `history-${state.history.length + 1}`,
          at: entry.at ?? nowIso(),
          stageId: entry.stageId,
          agentName: entry.agentName,
          action: entry.action,
          status: entry.status,
          detail: entry.detail,
        },
      ],
      updatedAt: nowIso(),
    }));
  },

  appendThought: (thought) => {
    set((state) => ({
      thoughts: [
        ...state.thoughts,
        {
          id: thought.id ?? `thought-${state.thoughts.length + 1}`,
          at: thought.at ?? nowIso(),
          agentId: thought.agentId,
          agentName: thought.agentName,
          thought: thought.thought,
        },
      ],
      updatedAt: nowIso(),
    }));
  },

  patchFinalResult: (patch) => {
    set((state) => ({
      finalResult: {
        ...state.finalResult,
        ...patch,
      },
      context: state.context
        ? {
            ...state.context,
            analysisId: patch.analysisId ?? state.context.analysisId,
            planId: patch.planId ?? state.context.planId,
            interviewId: patch.interviewId ?? state.context.interviewId,
            reportId: patch.reportId ?? state.context.reportId,
          }
        : state.context,
      updatedAt: nowIso(),
    }));
  },

  syncLiveAgents: (live) => {
    set((state) => {
      if (state.status === "idle" || state.status === "completed") {
        return state;
      }

      const stages = applyLiveAgentRuntime(state.stages, live);
      return {
        ...state,
        stages,
        updatedAt: nowIso(),
        ...buildDerived(stages, state.cancelled),
      };
    });
  },

  setLastError: (message) => {
    set({
      lastError: message,
      updatedAt: nowIso(),
    });
  },

  markCancelled: () => {
    set((state) => {
      const stages = state.stages.map((stage) =>
        stage.status === "pending" || stage.status === "running"
          ? {
              ...stage,
              status: "cancelled" as OrchestrationStageStatus,
              currentTask: "Cancelled",
              retryable: false,
            }
          : stage
      );

      return {
        ...state,
        stages,
        cancelled: true,
        updatedAt: nowIso(),
        ...buildDerived(stages, true),
      };
    });
  },

  reset: () => {
    const stages = createInitialStages();
    set({
      ...initialState,
      stages,
      timeline: mapStagesToTimeline(stages),
      workflowNodes: mapStagesToWorkflowNodes(stages, null),
      updatedAt: nowIso(),
    });
  },

  getSnapshot: () => {
    const state = get();
    return {
      status: state.status,
      currentStageId: state.currentStageId,
      currentAgentId: state.currentAgentId,
      progressPercent: state.progressPercent,
      stages: state.stages,
      history: state.history,
      thoughts: state.thoughts,
      timeline: state.timeline,
      workflowNodes: state.workflowNodes,
      finalResult: state.finalResult,
      context: state.context,
      lastError: state.lastError,
      updatedAt: state.updatedAt,
    };
  },
}));
