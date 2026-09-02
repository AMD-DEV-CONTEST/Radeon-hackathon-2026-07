"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  DEFAULT_INTERVIEW_CONFIGURATION,
  INTERVIEW_MUTATION_KEYS,
  INTERVIEW_QUERY_KEYS,
} from "@/features/interview/constants/interview-keys";
import { interviewService } from "@/features/interview/services/interview.service";
import type {
  CreateInterviewRequest,
  InterviewConfiguration,
  InterviewPlan,
  PlanInterviewRequest,
} from "@/features/interview/types/interview.types";
import {
  buildFallbackPlan,
  mapPlanningCandidate,
} from "@/features/interview/utils/planning-mappers";
import { useResumeStore } from "@/features/resume/store/resume.store";

export const interviewQueryKeys = INTERVIEW_QUERY_KEYS;

export function useInterviewPlanning(options?: {
  candidateId?: string;
  resumeId?: string;
}) {
  const queryClient = useQueryClient();
  const storedResume = useResumeStore((state) => state.currentResume);
  const hasAutoPlannedRef = useRef(false);

  const candidateId =
    options?.candidateId?.trim() || storedResume?.candidateId || "";
  const resumeIdHint = options?.resumeId?.trim() || storedResume?.id || "";

  const [configuration, setConfiguration] = useState<InterviewConfiguration>(
    DEFAULT_INTERVIEW_CONFIGURATION
  );
  const [plannedInterview, setPlannedInterview] = useState<InterviewPlan | null>(
    null
  );

  const candidateQuery = useQuery({
    queryKey: INTERVIEW_QUERY_KEYS.candidate(candidateId || "unknown"),
    queryFn: () => interviewService.getCandidate(candidateId),
    enabled: candidateId.length > 0,
    staleTime: 30_000,
    retry: 1,
  });

  const resumeId =
    resumeIdHint || candidateQuery.data?.profile.resumeId || "";

  const resumeQuery = useQuery({
    queryKey: INTERVIEW_QUERY_KEYS.resume(resumeId || "unknown"),
    queryFn: () => interviewService.getResume(resumeId),
    enabled: resumeId.length > 0,
    staleTime: 30_000,
    retry: 1,
  });

  useEffect(() => {
    if (!candidateQuery.data) {
      return;
    }

    setConfiguration((current) => {
      if (current.role.trim().length > 0) {
        return current;
      }
      return {
        ...current,
        role: candidateQuery.data.profile.targetRole || current.role,
      };
    });
  }, [candidateQuery.data]);

  const planningCandidate = useMemo(() => {
    if (!candidateQuery.data) {
      return null;
    }
    return mapPlanningCandidate(
      candidateQuery.data,
      resumeQuery.data ?? null,
      configuration.role
    );
  }, [candidateQuery.data, resumeQuery.data, configuration.role]);

  const planMutation = useMutation({
    mutationKey: INTERVIEW_MUTATION_KEYS.plan,
    retry: false,
    mutationFn: async (payload: Partial<PlanInterviewRequest> = {}) => {
      if (!candidateId) {
        throw new Error("Candidate missing.");
      }
      if (!resumeId) {
        throw new Error("Resume missing.");
      }
      if (!candidateQuery.data || !resumeQuery.data) {
        throw new Error("Candidate or resume data is not loaded.");
      }

      const request: PlanInterviewRequest = {
        candidateId: payload.candidateId ?? candidateId,
        resumeId: payload.resumeId ?? resumeId,
        configuration: payload.configuration ?? configuration,
      };

      return interviewService.planInterview(request, {
        dossier: candidateQuery.data,
        resume: resumeQuery.data,
      });
    },
    onSuccess: (result) => {
      setPlannedInterview(result.plan);
      queryClient.setQueryData(
        INTERVIEW_QUERY_KEYS.plan(candidateId, resumeId),
        result.plan
      );
    },
  });

  const createMutation = useMutation({
    mutationKey: INTERVIEW_MUTATION_KEYS.create,
    retry: false,
    mutationFn: async (payload: Partial<CreateInterviewRequest> = {}) => {
      if (!candidateId) {
        throw new Error("Candidate missing.");
      }
      if (!resumeId) {
        throw new Error("Resume missing.");
      }

      const request: CreateInterviewRequest = {
        candidateId: payload.candidateId ?? candidateId,
        resumeId: payload.resumeId ?? resumeId,
        configuration: payload.configuration ?? configuration,
      };

      return interviewService.createInterview(request);
    },
  });

  const planAsync = planMutation.mutateAsync;

  useEffect(() => {
    if (hasAutoPlannedRef.current) {
      return;
    }

    if (
      !candidateId ||
      !resumeId ||
      !candidateQuery.data ||
      !resumeQuery.data ||
      planMutation.isPending
    ) {
      return;
    }

    hasAutoPlannedRef.current = true;
    void planAsync({});
  }, [
    candidateId,
    resumeId,
    candidateQuery.data,
    resumeQuery.data,
    planMutation.isPending,
    planAsync,
  ]);

  const plan: InterviewPlan | undefined = useMemo(() => {
    if (!planningCandidate) {
      return undefined;
    }

    const base =
      plannedInterview ?? buildFallbackPlan(planningCandidate, configuration);

    return {
      ...base,
      configuration,
      candidate: {
        ...planningCandidate,
        selectedRole: configuration.role || planningCandidate.selectedRole,
        resumeScore:
          plannedInterview?.candidate.resumeScore ||
          planningCandidate.resumeScore,
        readinessScore:
          plannedInterview?.candidate.readinessScore ||
          planningCandidate.readinessScore,
      },
      summary: {
        ...base.summary,
        estimatedDurationMinutes: configuration.durationMinutes,
        expectedQuestionCount: configuration.questionCount,
        difficulty: configuration.difficulty,
      },
    };
  }, [planningCandidate, plannedInterview, configuration]);

  const isLoading =
    (candidateId.length > 0 && candidateQuery.isLoading) ||
    (resumeId.length > 0 && resumeQuery.isLoading);

  const isError = candidateQuery.isError || resumeQuery.isError;
  const error = candidateQuery.error ?? resumeQuery.error;

  return {
    candidateId,
    resumeId,
    configuration,
    setConfiguration,
    plan,
    candidateQuery,
    resumeQuery,
    planMutation,
    createMutation,
    isLoading,
    isError,
    error,
    refetch: async () => {
      hasAutoPlannedRef.current = false;
      await Promise.all([
        candidateQuery.refetch(),
        resumeId ? resumeQuery.refetch() : Promise.resolve(),
      ]);
      if (candidateId && resumeId) {
        hasAutoPlannedRef.current = true;
        await planMutation.mutateAsync({});
      }
    },
    regeneratePlan: async () => {
      hasAutoPlannedRef.current = true;
      return planMutation.mutateAsync({});
    },
  };
}
