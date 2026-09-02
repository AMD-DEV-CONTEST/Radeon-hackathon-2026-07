"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  CANDIDATE_MUTATION_KEYS,
  CANDIDATE_QUERY_KEYS,
} from "@/features/candidate/constants/candidate-keys";
import { candidateService } from "@/features/candidate/services/candidate.service";
import type { UpdateCandidateRequest } from "@/features/candidate/types/candidate.types";
import { getCandidateErrorMessage } from "@/features/candidate/utils/candidate-errors";

interface UpdateCandidateVariables {
  id: string;
  payload: UpdateCandidateRequest;
}

export function useUpdateCandidate() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationKey: CANDIDATE_MUTATION_KEYS.update,
    retry: false,
    mutationFn: ({ id, payload }: UpdateCandidateVariables) =>
      candidateService.updateCandidate(id, payload),
    onSuccess: async (data, variables) => {
      queryClient.setQueryData(
        CANDIDATE_QUERY_KEYS.detail(variables.id),
        data
      );
      await queryClient.invalidateQueries({
        queryKey: CANDIDATE_QUERY_KEYS.detail(variables.id),
      });
    },
  });
}

export function getUpdateCandidateErrorMessage(error: unknown): string {
  return getCandidateErrorMessage(error);
}
