"use client";

import { useMemo } from "react";

import { AGENT_DEFINITIONS } from "@/features/agents/constants/workflow";
import { useOrchestration } from "@/features/agents/hooks/use-orchestration";

export function useWorkflow(options?: {
  candidateId?: string;
  resumeId?: string;
}) {
  const orchestration = useOrchestration(options);

  const activeAgent = useMemo(() => {
    if (!orchestration.currentAgentId) {
      return null;
    }
    return (
      AGENT_DEFINITIONS.find(
        (agent) => agent.id === orchestration.currentAgentId
      ) ?? null
    );
  }, [orchestration.currentAgentId]);

  const completedAgents = useMemo(
    () =>
      orchestration.stages.filter(
        (stage) =>
          stage.agentId !== null &&
          (stage.status === "completed" || stage.status === "skipped")
      ),
    [orchestration.stages]
  );

  const failedStage = useMemo(
    () => orchestration.stages.find((stage) => stage.status === "failed") ?? null,
    [orchestration.stages]
  );

  return {
    ...orchestration,
    activeAgent,
    completedAgents,
    failedStage,
    workflowNodes: orchestration.workflowNodes,
    timeline: orchestration.timeline,
    thoughts: orchestration.thoughts,
  };
}
