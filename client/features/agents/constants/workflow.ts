import type {
  AgentDefinition,
  OrchestrationStage,
  OrchestrationStageId,
} from "@/features/agents/types/orchestration.types";
import type { WorkflowNodeId } from "@/features/agents/types/agents.types";

export const AGENT_DEFINITIONS: ReadonlyArray<AgentDefinition> = [
  {
    id: "resume",
    stageId: "resume",
    name: "Resume Agent",
    description: "Parses resume content and extracts candidate signals.",
    defaultTask: "Analyzing resume structure and competencies",
  },
  {
    id: "planner",
    stageId: "planner",
    name: "Planner Agent",
    description: "Builds the interview plan and question strategy.",
    defaultTask: "Synthesizing interview plan",
  },
  {
    id: "technical",
    stageId: "technical",
    name: "Technical Agent",
    description: "Runs technical probes during the live interview.",
    defaultTask: "Preparing technical competency probes",
  },
  {
    id: "behavior",
    stageId: "behavior",
    name: "Behavioral Agent",
    description: "Evaluates behavioral and soft-skill responses.",
    defaultTask: "Warming behavioral rubric",
  },
  {
    id: "factChecker",
    stageId: "factChecker",
    name: "Fact Checker",
    description: "Validates claims against resume and transcript evidence.",
    defaultTask: "Awaiting claim verification inputs",
  },
  {
    id: "evaluation",
    stageId: "evaluation",
    name: "Evaluation Agent",
    description: "Aggregates live scoring and interview evaluation.",
    defaultTask: "Aggregating evaluation signals",
  },
  {
    id: "hiring",
    stageId: "hiring",
    name: "Hiring Agent",
    description: "Produces hiring recommendation and report output.",
    defaultTask: "Generating hiring recommendation",
  },
] as const;

export const WORKFLOW_STAGE_ORDER: ReadonlyArray<OrchestrationStageId> = [
  "resumeUpload",
  "resumeParsing",
  "resume",
  "planner",
  "technical",
  "behavior",
  "factChecker",
  "evaluation",
  "hiring",
  "report",
] as const;

export const STAGE_LABELS: Record<OrchestrationStageId, string> = {
  resumeUpload: "Resume Upload",
  resumeParsing: "Resume Parsing",
  resume: "Resume Agent",
  planner: "Planner Agent",
  technical: "Technical Agent",
  behavior: "Behavioral Agent",
  factChecker: "Fact Checker",
  evaluation: "Evaluation Agent",
  hiring: "Hiring Agent",
  report: "Interview Report",
};

export const STAGE_DESCRIPTIONS: Record<OrchestrationStageId, string> = {
  resumeUpload: "Confirm uploaded resume is available for analysis.",
  resumeParsing: "Parse resume document into structured candidate data.",
  resume: "Extract skills, experience, and interview focus areas.",
  planner: "Create interview plan and initialize the session.",
  technical: "Execute technical interview orchestration.",
  behavior: "Execute behavioral interview orchestration.",
  factChecker: "Cross-check candidate claims in real time.",
  evaluation: "Close the interview and finalize live evaluation.",
  hiring: "Generate hiring recommendation and report artifact.",
  report: "Publish the final interview report.",
};

export const STAGE_TO_AGENT: Partial<
  Record<OrchestrationStageId, WorkflowNodeId>
> = {
  resume: "resume",
  planner: "planner",
  technical: "technical",
  behavior: "behavior",
  factChecker: "factChecker",
  evaluation: "evaluation",
  hiring: "hiring",
};

export function createInitialStages(): OrchestrationStage[] {
  return WORKFLOW_STAGE_ORDER.map((id) => ({
    id,
    agentId: STAGE_TO_AGENT[id] ?? null,
    label: STAGE_LABELS[id],
    description: STAGE_DESCRIPTIONS[id],
    status: "pending",
    progress: 0,
    currentTask: "Waiting to start",
    startedAt: null,
    completedAt: null,
    error: null,
    retryable: true,
  }));
}

export function getAgentDefinition(
  agentId: WorkflowNodeId
): AgentDefinition | undefined {
  return AGENT_DEFINITIONS.find((agent) => agent.id === agentId);
}
