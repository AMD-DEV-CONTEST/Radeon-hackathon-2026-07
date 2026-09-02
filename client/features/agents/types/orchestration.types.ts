import type {
  AgentRuntimeStatus,
  TimelineLane,
  WorkflowNode,
  WorkflowNodeId,
} from "@/features/agents/types/agents.types";
import type { InterviewConfiguration } from "@/features/interview/types/interview.types";

export type OrchestrationWorkflowStatus =
  | "idle"
  | "running"
  | "paused"
  | "completed"
  | "failed"
  | "cancelled"
  | "partial_success";

export type OrchestrationStageId =
  | "resumeUpload"
  | "resumeParsing"
  | "resume"
  | "planner"
  | "technical"
  | "behavior"
  | "factChecker"
  | "evaluation"
  | "hiring"
  | "report";

export type OrchestrationStageStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "skipped"
  | "cancelled";

export interface AiThought {
  id: string;
  agentId: OrchestrationStageId | WorkflowNodeId | string;
  agentName: string;
  thought: string;
  at: string;
}

export interface OrchestrationStage {
  id: OrchestrationStageId;
  agentId: WorkflowNodeId | null;
  label: string;
  description: string;
  status: OrchestrationStageStatus;
  progress: number;
  currentTask: string;
  startedAt: string | null;
  completedAt: string | null;
  error: string | null;
  retryable: boolean;
}

export interface OrchestrationHistoryEntry {
  id: string;
  stageId: OrchestrationStageId;
  agentName: string;
  action: string;
  status: OrchestrationStageStatus | "info";
  at: string;
  detail?: string;
}

export interface OrchestrationFinalResult {
  analysisId: string | null;
  planId: string | null;
  interviewId: string | null;
  reportId: string | null;
  recommendation: string | null;
  completedAt: string | null;
}

export interface OrchestrationRequest {
  candidateId: string;
  resumeId: string;
  configuration: InterviewConfiguration;
  interviewId?: string;
}

export interface OrchestrationContext {
  candidateId: string;
  resumeId: string;
  configuration: InterviewConfiguration;
  analysisId: string | null;
  planId: string | null;
  interviewId: string | null;
  reportId: string | null;
}

export interface OrchestrationSnapshot {
  status: OrchestrationWorkflowStatus;
  currentStageId: OrchestrationStageId | null;
  currentAgentId: WorkflowNodeId | null;
  progressPercent: number;
  stages: ReadonlyArray<OrchestrationStage>;
  history: ReadonlyArray<OrchestrationHistoryEntry>;
  thoughts: ReadonlyArray<AiThought>;
  timeline: ReadonlyArray<TimelineLane>;
  workflowNodes: ReadonlyArray<WorkflowNode>;
  finalResult: OrchestrationFinalResult;
  context: OrchestrationContext | null;
  lastError: string | null;
  updatedAt: string;
}

export interface AgentDefinition {
  id: WorkflowNodeId;
  stageId: OrchestrationStageId;
  name: string;
  description: string;
  defaultTask: string;
}

export type LiveAgentRuntimeMap = Partial<
  Record<
    WorkflowNodeId,
    {
      status: AgentRuntimeStatus;
      currentTask: string;
    }
  >
>;
