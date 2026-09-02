"use client";

import { useMutation } from "@tanstack/react-query";
import { useEffect, useMemo } from "react";

import { ORCHESTRATION_MUTATION_KEYS } from "@/features/agents/constants/orchestration-keys";
import { orchestrationService } from "@/features/agents/services/orchestration.service";
import { useOrchestrationStore } from "@/features/agents/store/orchestration.store";
import type {
  OrchestrationRequest,
  OrchestrationSnapshot,
} from "@/features/agents/types/orchestration.types";
import {
  getOrchestrationErrorMessage,
  isRetryableOrchestrationError,
} from "@/features/agents/utils/orchestration-errors";
import { DEFAULT_INTERVIEW_CONFIGURATION } from "@/features/interview/constants/interview-keys";

interface UseOrchestrationOptions {
  candidateId?: string;
  resumeId?: string;
  autoSync?: boolean;
}

export function useOrchestration(options: UseOrchestrationOptions = {}) {
  const autoSync = options.autoSync ?? true;

  const status = useOrchestrationStore((state) => state.status);
  const stages = useOrchestrationStore((state) => state.stages);
  const currentStageId = useOrchestrationStore((state) => state.currentStageId);
  const currentAgentId = useOrchestrationStore((state) => state.currentAgentId);
  const progressPercent = useOrchestrationStore(
    (state) => state.progressPercent
  );
  const history = useOrchestrationStore((state) => state.history);
  const thoughts = useOrchestrationStore((state) => state.thoughts);
  const timeline = useOrchestrationStore((state) => state.timeline);
  const workflowNodes = useOrchestrationStore((state) => state.workflowNodes);
  const finalResult = useOrchestrationStore((state) => state.finalResult);
  const lastError = useOrchestrationStore((state) => state.lastError);
  const context = useOrchestrationStore((state) => state.context);
  const updatedAt = useOrchestrationStore((state) => state.updatedAt);

  const startMutation = useMutation({
    mutationKey: ORCHESTRATION_MUTATION_KEYS.start,
    retry: false,
    mutationFn: (request: OrchestrationRequest) =>
      orchestrationService.startWorkflow(request),
  });

  const finalizeMutation = useMutation({
    mutationKey: ORCHESTRATION_MUTATION_KEYS.finalize,
    retry: false,
    mutationFn: () => orchestrationService.finalizeWorkflow(),
  });

  const retryMutation = useMutation({
    mutationKey: ORCHESTRATION_MUTATION_KEYS.retry,
    retry: false,
    mutationFn: () => orchestrationService.retryFailedStage(),
  });

  const cancelMutation = useMutation({
    mutationKey: ORCHESTRATION_MUTATION_KEYS.cancel,
    retry: false,
    mutationFn: async () => orchestrationService.cancelWorkflow(),
  });

  useEffect(() => {
    if (!autoSync) {
      return;
    }
    if (status !== "running") {
      return;
    }

    const timer = window.setInterval(() => {
      void orchestrationService.syncAgents().catch(() => undefined);
    }, 8_000);

    return () => {
      window.clearInterval(timer);
    };
  }, [autoSync, status]);

  const currentStage =
    stages.find((stage) => stage.id === currentStageId) ?? null;

  const snapshot = useMemo<OrchestrationSnapshot>(
    () => ({
      status,
      currentStageId,
      currentAgentId,
      progressPercent,
      stages,
      history,
      thoughts,
      timeline,
      workflowNodes,
      finalResult,
      context,
      lastError,
      updatedAt,
    }),
    [
      status,
      currentStageId,
      currentAgentId,
      progressPercent,
      stages,
      history,
      thoughts,
      timeline,
      workflowNodes,
      finalResult,
      context,
      lastError,
      updatedAt,
    ]
  );

  return {
    snapshot,
    status,
    stages,
    currentStage,
    currentStageId,
    currentAgentId,
    progressPercent,
    history,
    thoughts,
    timeline,
    workflowNodes,
    finalResult,
    lastError,
    context,
    isRunning:
      status === "running" ||
      startMutation.isPending ||
      finalizeMutation.isPending ||
      retryMutation.isPending,
    isFailed: status === "failed",
    isPartialSuccess: status === "partial_success",
    isCancelled: status === "cancelled",
    isCompleted: status === "completed",
    canRetry:
      (status === "failed" || status === "partial_success") &&
      stages.some((stage) => stage.status === "failed" && stage.retryable),
    start: async (request?: Partial<OrchestrationRequest>) => {
      const candidateId = request?.candidateId || options.candidateId || "";
      const resumeId = request?.resumeId || options.resumeId || "";
      if (!candidateId || !resumeId) {
        throw new Error(
          "candidateId and resumeId are required to start orchestration."
        );
      }

      return startMutation.mutateAsync({
        candidateId,
        resumeId,
        configuration: {
          ...DEFAULT_INTERVIEW_CONFIGURATION,
          role:
            request?.configuration?.role ||
            DEFAULT_INTERVIEW_CONFIGURATION.role ||
            "Software Engineer",
          difficulty: request?.configuration?.difficulty ?? "medium",
          durationMinutes: request?.configuration?.durationMinutes ?? 60,
          questionCount: request?.configuration?.questionCount ?? 12,
          interviewType: request?.configuration?.interviewType ?? "mixed",
        },
        interviewId: request?.interviewId,
      });
    },
    finalize: () => finalizeMutation.mutateAsync(),
    retry: () => retryMutation.mutateAsync(),
    cancel: () => cancelMutation.mutateAsync(),
    syncAgents: () => orchestrationService.syncAgents(),
    reset: () => useOrchestrationStore.getState().reset(),
    startMutation,
    finalizeMutation,
    retryMutation,
    cancelMutation,
    getErrorMessage: getOrchestrationErrorMessage,
    isRetryableError: isRetryableOrchestrationError,
  };
}
