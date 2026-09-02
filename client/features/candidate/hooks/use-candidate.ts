"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  CANDIDATE_MUTATION_KEYS,
  CANDIDATE_QUERY_KEYS,
} from "@/features/candidate/constants/candidate-keys";
import { candidateService } from "@/features/candidate/services/candidate.service";
import type {
  AnalyzeResumeRequest,
  CandidateDossier,
} from "@/features/candidate/types/candidate.types";
import {
  getAnalyzeResumeErrorMessage,
  getCandidateErrorMessage,
  getResumeMissingMessage,
} from "@/features/candidate/utils/candidate-errors";
import { mergeAnalysisIntoDossier } from "@/features/candidate/utils/candidate-mappers";

export const candidateQueryKeys = CANDIDATE_QUERY_KEYS;

export function useCandidate(candidateId: string) {
  return useQuery({
    queryKey: CANDIDATE_QUERY_KEYS.detail(candidateId),
    queryFn: () => candidateService.getCandidate(candidateId),
    enabled: candidateId.length > 0,
    retry: 1,
    staleTime: 30_000,
  });
}

export function useResume(resumeId: string | undefined) {
  return useQuery({
    queryKey: CANDIDATE_QUERY_KEYS.resume(resumeId ?? "unknown"),
    queryFn: () => {
      if (!resumeId) {
        throw new Error("Resume id is required");
      }
      return candidateService.getResume(resumeId);
    },
    enabled: Boolean(resumeId),
    retry: 1,
    staleTime: 30_000,
  });
}

export function useAnalyzeResume() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationKey: CANDIDATE_MUTATION_KEYS.analyzeResume,
    retry: false,
    mutationFn: (payload: AnalyzeResumeRequest) =>
      candidateService.analyzeResume(payload),
    onSuccess: async (result, variables) => {
      if (result.candidateId) {
        queryClient.setQueryData<CandidateDossier>(
          CANDIDATE_QUERY_KEYS.detail(result.candidateId),
          (current) => {
            if (!current) {
              return current;
            }
            return mergeAnalysisIntoDossier(current, result);
          }
        );
        await queryClient.invalidateQueries({
          queryKey: CANDIDATE_QUERY_KEYS.detail(result.candidateId),
        });
      }

      await queryClient.invalidateQueries({
        queryKey: CANDIDATE_QUERY_KEYS.resume(variables.resumeId),
      });
    },
  });
}

export function getUseCandidateErrorMessage(error: unknown): string {
  return getCandidateErrorMessage(error);
}

export function getUseResumeErrorMessage(error: unknown): string {
  return getResumeMissingMessage(error);
}

export function getUseAnalyzeErrorMessage(error: unknown): string {
  return getAnalyzeResumeErrorMessage(error);
}
